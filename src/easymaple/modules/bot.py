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

            print(f'[~] Pressing Interact (attempt {attempt}/{self.RUNE_FAIL_THRESHOLD}); waiting 1s for rune UI')
            press(self.config['Interact'], 1, down_time=0.2)
            # 1s gives the rune UI time to fully render. We then wait a
            # bit more inside _attempt_solve_once for the band to settle
            # — damage numbers from in-flight attacks animate for a
            # couple of seconds and obscure the arrows.
            if not self._interruptible_sleep(1.0):
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

    def _release_solver_keys(self):
        """Release every key the rune solver or command book might be
        holding, except the Interact key. A key_up on Interact has been
        observed to register as a brief press in some keyboard-hook
        setups, which closes the puzzle UI and destroys the rune.
        """
        keys = ['left', 'right', 'up', 'down', 'space', 'shift', 'ctrl', 'alt']
        interact = self.config.get('Interact')
        if interact and interact in keys:
            keys.remove(interact)
        for k in keys:
            key_up(k)

    def _attempt_solve_once(self, model):
        """One end-to-end solve attempt. Returns True iff the rune buff was confirmed."""
        print('\nSolving rune:')

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

        def _buff_positions(label=''):
            """Match both rune-buff templates against the top-right quadrant.
            Logs the best correlation score for each template so we can see
            why a match did or didn't fire, then returns positions that
            cleared the 0.9 threshold (shifted to full-frame coords).
            """
            f = config.capture.frame
            if f is None:
                return []
            # Top-right quadrant of the screen: top 1/3 vertically and
            # right 1/2 horizontally. The buff icons sometimes land outside
            # the old narrow top-1/8 strip, especially when several buffs
            # are already active and the bar wraps onto a second row.
            h, w = f.shape[:2]
            top_right = f[:h // 3, w // 2:]
            x_offset = w // 2

            gray = cv2.cvtColor(top_right, cv2.COLOR_BGR2GRAY) if len(top_right.shape) == 3 else top_right
            threshold = 0.9
            matches = []
            scores = []
            for idx, template in enumerate(RUNE_BUFF_TEMPLATES):
                try:
                    result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
                    best_score = float(result.max())
                except cv2.error as e:
                    best_score = 0.0
                    print(f'[!] template {idx} match failed: {e}')
                    scores.append(best_score)
                    continue
                scores.append(best_score)

                hits = utils.multi_match(top_right, template, threshold=threshold) or []
                matches.extend([(x + x_offset, y) for (x, y) in hits])

            score_str = ', '.join(f'tpl{i}={s:.3f}' for i, s in enumerate(scores))
            verdict = 'FOUND' if matches else 'NO MATCH'
            print(f'[~] Rune buff {label}: {verdict} (threshold={threshold}; scores: {score_str})')
            return matches

        self._release_solver_keys()
        if not self._interruptible_sleep(0.1):
            return False
        # Human-ish cadence: vary the hold and gap times per arrow, and
        # occasionally pause as if hesitating. Keeps inputs from looking
        # mechanically uniform while still landing inside the rune timer.
        for i, arrow in enumerate(solution):
            if not config.enabled:
                return False
            down_time = utils.rand_float(0.08, 0.18)
            up_time = utils.rand_float(0.15, 0.40)
            # ~15% chance to "hesitate" before the next arrow.
            if i < len(solution) - 1 and utils.bernoulli(0.15):
                up_time += utils.rand_float(0.30, 0.60)
            press(arrow, 1, down_time=down_time, up_time=up_time)
        # Initial wait shortened from 1.0s -> 0.5s so the first poll catches
        # the buff right as it appears (it usually renders within ~500ms).
        if not self._interruptible_sleep(0.5):
            return False

        # 5 polls at 0.3s intervals: gives the buff icon multiple chances
        # to match through its fade-in animation. Rune cooldown (10 min)
        # is longer than the buff duration (5 min), so there can never be
        # a leftover buff from a prior solve — any match here is fresh.
        for poll in range(1, 6):
            if not self._interruptible_sleep(0.3):
                return False
            rune_buff = _buff_positions(label=f'post{poll}')
            if not rune_buff:
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