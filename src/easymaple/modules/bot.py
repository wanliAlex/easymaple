"""An interpreter that reads and executes user-created routines."""

import os
import threading
import time
import cv2
import inspect
import importlib
import traceback
from os.path import splitext, basename
from src.easymaple.common import config, utils
from src.easymaple.detection import detection
from src.easymaple.routine import components
from src.easymaple.routine.routine import Routine
from src.easymaple.routine.components import Point
from src.easymaple.common.vkeys import press, click
from src.easymaple.common.interfaces import Configurable
from src.easymaple.common.vkeys import press, key_down, key_up


# The rune's buff icon — two visual variants both indicate a solved rune.
RUNE_BUFF_TEMPLATES = [
    utils.load_image('assets/rune_buff_template.jpg', cv2.IMREAD_GRAYSCALE),
    utils.load_image('assets/rune_buff_template_2.jpg', cv2.IMREAD_GRAYSCALE),
]


class Bot(Configurable):
    """A class that interprets and executes user-defined routines."""

    DEFAULT_CONFIG = {
        'Interact': 'alt',
        'Feed pet': '9'
    }

    # Number of consecutive failed rune solves before alerting the user
    RUNE_FAIL_THRESHOLD = 3

    # After a full solve attempt (with all internal retries) fails, ignore
    # rune detections for this many seconds so the bot keeps farming instead
    # of looping into another doomed solve.
    RUNE_COOLDOWN_AFTER_FAIL = 60

    # Hard wall-clock timeout for the inference loop. The in-game rune UI
    # closes after ~10s, so 11s gives a small safety margin. On timeout the
    # outer retry loop sleeps 3s, re-presses Interact, and tries again.
    RUNE_INFERENCE_TIMEOUT = 11

    # After this many consecutive failed _solve_rune batches (each batch is
    # RUNE_FAIL_THRESHOLD trials), give up entirely and disable the bot so
    # the user can solve manually. 3 batches × 3 trials = 9 trials.
    RUNE_BATCH_FAIL_LIMIT = 3

    def __init__(self):
        """Loads a user-defined routine on start up and initializes this Bot's main thread."""

        super().__init__('keybindings')
        config.bot = self

        self.rune_active = False
        self.rune_pos = (0, 0)
        self.rune_closest_pos = (0, 0)      # Location of the Point closest to rune
        self.rune_solve_failures = 0
        self.rune_solve_cooldown_until = 0
        self.rune_consecutive_batch_failures = 0
        self.submodules = []
        self.module_name = None
        self.buff = components.Buff()
        self.model = None
        self._model_load_thread = None

        self.command_book = {}
        for c in (components.Wait, components.Walk, components.Fall,
                  components.Move, components.Adjust, components.Buff):
            self.command_book[c.__name__.lower()] = c

        config.routine = Routine()

        self.ready = False
        self.thread = threading.Thread(target=self._main)
        self.thread.daemon = True

    def start(self):
        """
        Starts this Bot object's thread.
        :return:    None
        """

        #self.update_submodules()
        print('\n[~] Started main bot loop')
        self.thread.start(  )

    def _main(self):
        """
        The main body of Bot that executes the user's routine.
        :return:    None
        """

        # rune_settings = config.gui.settings.rune
        # solve_rune = rune_settings.solve_rune.get()
        # if solve_rune is True:
        #     print('\n[~] Initializing detection algorithm:\n')
        #     model = detection.load_model()
        #     print('\n[~] Initialized detection algorithm')
        # else:
        #     print('\n[~] Skip model detection as `solve_rune = False`')

        self.ready = True
        config.listener.enabled = True
        last_fed = time.time()
        key_up("left"); key_up("right")
        while True:
            if config.enabled:
                solve_rune = config.gui.settings.rune.solve_rune.get()

                # Warm up the rune model in the background as soon as the toggle
                # is on, so the first rune doesn't pay the multi-second load cost
                if solve_rune and self.model is None and self._model_load_thread is None:
                    self._kick_off_model_load()

                if self.rune_active:
                    if not solve_rune:
                        self.rune_active = False
                    elif time.time() < self.rune_solve_cooldown_until:
                        # We just exhausted our retries; ignore this rune for a
                        # while so the bot keeps farming instead of re-triggering
                        # a guaranteed-to-fail solve every ~2s.
                        self.rune_active = False
                    else:
                        if self.model is None and self._model_load_thread is not None:
                            print('[~] Rune appeared but detection model is still loading — waiting...')
                            self._model_load_thread.join()
                        if self.model is not None:
                            self._solve_rune(self.model)

            if config.enabled and len(config.routine) > 0:
                # Buff and feed pets
                self.buff.main()
                pet_settings = config.gui.settings.pets
                auto_feed = pet_settings.auto_feed.get()
                num_pets = pet_settings.num_pets.get()
                now = time.time()
                if auto_feed and now - last_fed > 600 / num_pets:
                    press(self.config['Feed pet'], 1)
                    last_fed = now

                # Highlight the current Point
                config.gui.view.routine.select(config.routine.index)
                config.gui.view.details.display_info(config.routine.index)

                # Execute next Point in the routine
                element = config.routine[config.routine.index]
                element.execute()

                # Only advance if the command finished naturally. If it broke
                # early because a rune appeared, leave the index in place so
                # we re-enter the same point after the rune is solved on the
                # next loop iteration.
                if not self.rune_active:
                    config.routine.step()
            else:
                time.sleep(0.01)

    @staticmethod
    def _interruptible_sleep(duration):
        """Sleeps in 0.05s slices and returns False as soon as config.enabled is cleared."""
        end = time.time() + duration
        while time.time() < end:
            if not config.enabled:
                return False
            time.sleep(0.05)
        return config.enabled

    @utils.run_if_enabled
    def _solve_rune(self, model):
        """
        Moves to the rune, then tries up to RUNE_FAIL_THRESHOLD times to solve
        it (3s sleep between retries). Re-navigates before each retry since
        failed solves often leave the player drifted away. Always clears
        `rune_active` on exit. Bails early whenever config.enabled is cleared.
        """

        print(f'[~] Rune detected at {self.rune_pos}; moving to solve')

        # Loosen adjust tolerance for the rune approach — exact alignment
        # to the rune-pos minimap pixel isn't necessary, and tighter
        # tolerances cause the bot to thrash trying to reach a sub-pixel
        # target. Restored on every exit path below.
        from src.easymaple.common import settings
        original_adjust_tolerance = settings.adjust_tolerance
        settings.adjust_tolerance = max(original_adjust_tolerance, 0.02)

        def _navigate_to_rune():
            move = self.command_book['move']
            print('[~] Moving to rune')
            move(*self.rune_pos).execute()
            adjust = self.command_book['adjust']
            print(f'[~] Adjusting to rune (tolerance {settings.adjust_tolerance})')
            adjust(*self.rune_pos).execute()
            return move, adjust

        try:
            move, adjust = _navigate_to_rune()
        except Exception as e:
            print(f'[!] Failed to navigate to rune: {e}')
            settings.adjust_tolerance = original_adjust_tolerance
            self.rune_active = False
            self._record_solve_failure()
            return

        # Move/Adjust press arrows + jump (space) during navigation; release
        # everything we know about so nothing bleeds into the rune-solve presses
        self._release_solver_keys()
        # Stand still for 1s so the player settles before pressing Interact.
        print('[~] Standing still 1s before Interact')
        if not self._interruptible_sleep(1.0):
            settings.adjust_tolerance = original_adjust_tolerance
            self.rune_active = False
            return

        solved = False
        for attempt in range(1, self.RUNE_FAIL_THRESHOLD + 1):
            if not config.enabled:
                break
            if attempt > 1:
                print(f'[~] Retrying rune solve in 3s (attempt {attempt}/{self.RUNE_FAIL_THRESHOLD})...')
                if not self._interruptible_sleep(3):
                    break

                # Failed solves often involve drift; re-navigate before retry.
                try:
                    print('[~] Re-navigating to rune')
                    move(*self.rune_pos).execute()
                    print(f'[~] Re-adjusting to rune (tolerance {settings.adjust_tolerance})')
                    adjust(*self.rune_pos).execute()
                except Exception as e:
                    print(f'[!] Failed to re-navigate to rune: {e}')
                    break
                self._release_solver_keys()
                print('[~] Standing still 1s before Interact')
                if not self._interruptible_sleep(1.0):
                    break

            print(f'[~] Pressing Interact (attempt {attempt}/{self.RUNE_FAIL_THRESHOLD}); waiting 3s for rune UI')
            press(self.config['Interact'], 1, down_time=0.2)
            # 3s gives the rune UI time to fully render. We then wait a
            # bit more inside _attempt_solve_once for the band to settle
            # — damage numbers from in-flight attacks animate for a
            # couple of seconds and obscure the arrows.
            if not self._interruptible_sleep(3.0):
                break

            if self._attempt_solve_once(model):
                solved = True
                print(f'[~] Rune solve SUCCESS (attempt {attempt}/{self.RUNE_FAIL_THRESHOLD})')
                break
            print(f'[!] Rune solve attempt {attempt}/{self.RUNE_FAIL_THRESHOLD} did not confirm a buff')

        # Restore the global adjust_tolerance we widened at the start so it
        # doesn't bleed into subsequent routine commands.
        settings.adjust_tolerance = original_adjust_tolerance

        self.rune_active = False
        if not config.enabled:
            print('[~] Rune solver interrupted by F8')
            return
        if solved:
            if self.rune_solve_failures > 0:
                print(f'[~] Rune solved after {self.rune_solve_failures + 1} prior failures')
            self.rune_solve_failures = 0
            self.rune_consecutive_batch_failures = 0
            return

        print(f'[!] Rune solve FAILED — all {self.RUNE_FAIL_THRESHOLD} attempts exhausted')
        self.rune_solve_failures = self.RUNE_FAIL_THRESHOLD
        self.rune_consecutive_batch_failures += 1
        self._record_solve_failure()

        if self.rune_consecutive_batch_failures >= self.RUNE_BATCH_FAIL_LIMIT:
            total_trials = self.rune_consecutive_batch_failures * self.RUNE_FAIL_THRESHOLD
            print(f'[!] {self.rune_consecutive_batch_failures} batches failed '
                  f'({total_trials} trials); disabling bot for manual intervention')
            notifier = getattr(config, 'notifier', None)
            if notifier is not None and hasattr(notifier, 'alert_rune_giving_up'):
                notifier.alert_rune_giving_up(total_trials)
            config.enabled = False
            self.rune_consecutive_batch_failures = 0
            self.rune_solve_cooldown_until = 0   # cooldown is moot; bot is off
        else:
            self.rune_solve_cooldown_until = time.time() + self.RUNE_COOLDOWN_AFTER_FAIL
            print(f'[!] Rune solve batch failed; suppressing further attempts for {self.RUNE_COOLDOWN_AFTER_FAIL}s')

    def _wait_for_stable_band(self, timeout=3.0, diff_threshold=5.0, sample_interval=0.2):
        """Block until the rune-band crop is visually stable frame-to-frame,
        or until ``timeout`` seconds elapse. 'Stable' = mean absolute pixel
        diff between two consecutive band crops below ``diff_threshold``.
        Returns True if stability was reached, False on timeout."""
        from src.easymaple.detection.detection import _crop_rune_band
        deadline = time.time() + timeout
        prev = None
        while time.time() < deadline:
            if not config.enabled:
                return False
            frame = config.capture.frame
            if frame is None:
                time.sleep(0.05)
                continue
            curr = _crop_rune_band(frame)
            if prev is not None and curr.shape == prev.shape:
                diff = float(cv2.absdiff(prev, curr).mean())
                if diff < diff_threshold:
                    print(f'[~] Rune band stable (frame-diff {diff:.2f}); starting inference')
                    return True
            prev = curr
            time.sleep(sample_interval)
        print(f'[!] Rune band did not stabilize within {timeout}s; running inference anyway')
        return False

    def _release_solver_keys(self):
        """Release every key the rune solver or command book might be holding."""
        keys = ['left', 'right', 'up', 'down', 'space', 'shift', 'ctrl', 'alt']
        interact = self.config.get('Interact')
        if interact and interact not in keys:
            keys.append(interact)
        for k in keys:
            key_up(k)

    def _attempt_solve_once(self, model):
        """One end-to-end solve attempt. Returns True iff the rune buff was confirmed."""
        print('\nSolving rune:')

        # Damage numbers from in-flight attacks animate over the rune band
        # for a couple of seconds after Interact and confuse both panel
        # detection and arrow classification. Wait for the band to settle.
        self._wait_for_stable_band(timeout=3.0)

        # Take the first inference that returns a complete 4-arrow solution.
        # If we get nothing for several consecutive iterations the rune likely
        # contains an arrow style the model can't classify (e.g. magenta) and
        # no amount of additional inferences will help — bail early so the
        # bot can keep farming while the user retrains the model.
        solution = None
        deadline = time.time() + self.RUNE_INFERENCE_TIMEOUT
        empty_iters = 0
        for _ in range(15):
            if not config.enabled:
                return False
            if time.time() >= deadline:
                print('[!] Inference timed out with no 4-arrow solution')
                return False

            frame = config.capture.frame
            candidate = detection.merge_detection(model, frame)
            if candidate and len(candidate) == 4:
                solution = candidate
                break

            empty_iters += 1
            if empty_iters >= 5:
                print('[!] No 4-arrow detection in 5 inferences; bailing')
                return False

        if not solution:
            return False

        print(f'[~] Entering solution: {", ".join(solution)}')

        def _buff_positions():
            f = config.capture.frame
            if f is None:
                return []
            top = f[:f.shape[0] // 8, :]
            matches = []
            for template in RUNE_BUFF_TEMPLATES:
                matches.extend(utils.multi_match(top, template, threshold=0.9) or [])
            return matches

        # 5px tolerance buckets — the buff bar shifts a few pixels as
        # neighboring buffs tick down, but a fresh icon lands in a
        # noticeably different slot.
        def _bucketed(matches):
            return {(p[0] // 5, p[1] // 5) for p in matches}

        pre_matches = _buff_positions()
        pre_buckets = _bucketed(pre_matches)
        print(f'[debug] pre  matches={pre_matches} buckets={sorted(pre_buckets)}')

        self._release_solver_keys()
        if not self._interruptible_sleep(0.1):
            return False
        for arrow in solution:
            if not config.enabled:
                return False
            press(arrow, 1, down_time=0.15, up_time=0.15)
        if not self._interruptible_sleep(1):
            return False

        for poll in range(1, 4):
            if not self._interruptible_sleep(0.3):
                return False
            rune_buff = _buff_positions()
            post_buckets = _bucketed(rune_buff)
            print(f'[debug] post{poll} matches={rune_buff} buckets={sorted(post_buckets)} '
                  f'fresh={sorted(post_buckets - pre_buckets)}')
            if not rune_buff:
                continue
            # New or repositioned buff icon ⇒ a rune was just applied.
            # Identical sets ⇒ leftover from a prior solve, not a fresh
            # success.
            if post_buckets <= pre_buckets:
                continue

            rune_buff_pos = min(rune_buff, key=lambda p: p[0])
            target = (
                round(rune_buff_pos[0] + config.capture.window['left']),
                round(rune_buff_pos[1] + config.capture.window['top'])
            )
            click(target, button='right')
            return True

        return False

    def _kick_off_model_load(self):
        """Loads the rune detection model in a background daemon thread, then
        runs a warmup inference so the first real solve doesn't pay
        torch/CUDA JIT cost."""
        def loader():
            try:
                print('\n[~] Loading rune detection model...')
                self.model = detection.load_model()

                # Warmup: one forward pass through the classifier so the
                # first real solve doesn't pay CUDA/cuDNN tuning cost.
                # Bypass detect_panel (it'd return "no_image" on a blank
                # frame and skip the model entirely).
                import torch
                dummy = torch.zeros(4, 3, 224, 224, device=self.model.device)
                with torch.no_grad():
                    self.model.model(dummy)

                print('[~] Rune detection model ready')
            except Exception as e:
                print(f'[!] Failed to pre-load rune detection model: {e}')
                self._model_load_thread = None  # Allow another attempt later

        self._model_load_thread = threading.Thread(target=loader, daemon=True)
        self._model_load_thread.start()

    def _record_solve_failure(self):
        self.rune_solve_failures += 1
        print(f'[!] Rune solve attempt {self.rune_solve_failures} failed')
        if self.rune_solve_failures >= self.RUNE_FAIL_THRESHOLD:
            notifier = getattr(config, 'notifier', None)
            if notifier is not None:
                notifier.alert_rune_unsolvable(self.rune_solve_failures)
            self.rune_solve_failures = 0

    def load_commands(self, file):
        """Prompts the user to select a command module to import. Updates config's command book."""

        utils.print_separator()
        print(f"[~] Loading command book '{basename(file)}':")

        ext = splitext(file)[1]
        if ext != '.py':
            print(f" !  '{ext}' is not a supported file extension.")
            return False

        new_step = components.step
        new_cb = {}
        for c in (components.Wait, components.Walk, components.Fall):
            new_cb[c.__name__.lower()] = c

        # Import the desired command book file
        module_name = splitext(basename(file))[0]
        target = '.'.join(['resources', 'command_books', module_name])
        try:
            module = importlib.import_module(target)
            module = importlib.reload(module)
        except ImportError:     # Display errors in the target Command Book
            print(' !  Errors during compilation:\n')
            for line in traceback.format_exc().split('\n'):
                line = line.rstrip()
                if line:
                    print(' ' * 4 + line)
            print(f"\n !  Command book '{module_name}' was not loaded")
            return

        # Check if the 'step' function has been implemented
        step_found = False
        for name, func in inspect.getmembers(module, inspect.isfunction):
            if name.lower() == 'step':
                step_found = True
                new_step = func

        # Populate the new command book
        for name, command in inspect.getmembers(module, inspect.isclass):
            new_cb[name.lower()] = command

        # Check if required commands have been implemented and overridden
        required_found = True
        for command in [components.Buff]:
            name = command.__name__.lower()
            if name not in new_cb:
                required_found = False
                new_cb[name] = command
                print(f" !  Error: Must implement required command '{name}'.")

        # Look for overridden movement commands
        movement_found = True
        for command in (components.Move, components.Adjust):
            name = command.__name__.lower()
            if name not in new_cb:
                movement_found = False
                new_cb[name] = command

        if not step_found and not movement_found:
            print(f" !  Error: Must either implement both 'Move' and 'Adjust' commands, "
                  f"or the function 'step'")
        if required_found and (step_found or movement_found):
            self.module_name = module_name
            self.command_book = new_cb
            self.buff = new_cb['buff']()
            components.step = new_step
            config.gui.menu.file.enable_routine_state()
            config.gui.view.status.set_cb(basename(file))
            config.routine.clear()
            print(f" ~  Successfully loaded command book '{module_name}'")
        else:
            print(f" !  Command book '{module_name}' was not loaded")