"""An interpreter that reads and executes user-created routines."""

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


# The rune's buff icon
RUNE_BUFF_TEMPLATE = utils.load_image('assets/rune_buff_template.jpg', cv2.IMREAD_GRAYSCALE)


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
    # closes after ~10s, so if we haven't found a 4-arrow solution by this
    # point there's no point continuing. Bumped slightly above 10s to leave
    # room for the very first cold-start inference.
    RUNE_INFERENCE_TIMEOUT = 15

    def __init__(self):
        """Loads a user-defined routine on start up and initializes this Bot's main thread."""

        super().__init__('keybindings')
        config.bot = self

        self.rune_active = False
        self.rune_pos = (0, 0)
        self.rune_closest_pos = (0, 0)      # Location of the Point closest to rune
        self.rune_solve_failures = 0
        self.rune_solve_cooldown_until = 0
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
        Moves to the rune, then tries up to RUNE_FAIL_THRESHOLD times to solve it
        in-place (3s sleep between retries). Always clears `rune_active` on exit
        so we don't busy-loop. Alerts the user if all retries fail. Bails early
        whenever config.enabled is cleared (F8).
        """

        try:
            move = self.command_book['move']
            move(*self.rune_pos).execute()
            adjust = self.command_book['adjust']
            adjust(*self.rune_pos).execute()
        except Exception as e:
            print(f'[!] Failed to navigate to rune: {e}')
            self.rune_active = False
            self._record_solve_failure()
            return

        # Move/Adjust press arrows + jump (space) during navigation; release
        # everything we know about so nothing bleeds into the rune-solve presses
        self._release_solver_keys(reason='post-navigation cleanup')
        if not self._interruptible_sleep(0.5):
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

            interact_key = self.config['Interact']
            print(f"[rune-key] press Interact='{interact_key}' (open rune UI, attempt {attempt})")
            press(interact_key, 1, down_time=0.2)
            if not self._interruptible_sleep(0.5):
                break

            if self._attempt_solve_once(model):
                solved = True
                break

        self.rune_active = False
        if not config.enabled:
            print('[~] Rune solver interrupted by F8')
            return
        if solved:
            if self.rune_solve_failures > 0:
                print(f'[~] Rune solved after {self.rune_solve_failures + 1} prior failures')
            self.rune_solve_failures = 0
        else:
            self.rune_solve_failures = self.RUNE_FAIL_THRESHOLD
            self.rune_solve_cooldown_until = time.time() + self.RUNE_COOLDOWN_AFTER_FAIL
            print(f'[!] Rune solve failed; suppressing further attempts for {self.RUNE_COOLDOWN_AFTER_FAIL}s')
            self._record_solve_failure()

    def _release_solver_keys(self, reason=''):
        """Release every key the rune solver or command book might be holding."""
        keys = ['left', 'right', 'up', 'down', 'space', 'shift', 'ctrl', 'alt']
        interact = self.config.get('Interact')
        if interact and interact not in keys:
            keys.append(interact)
        if reason:
            print(f"[rune-key] release {keys} ({reason})")
        else:
            print(f"[rune-key] release {keys}")
        for k in keys:
            key_up(k)

    def _attempt_solve_once(self, model):
        """One end-to-end solve attempt. Returns True iff the rune buff was confirmed."""
        print('\nSolving rune:')

        # Take the first inference that returns a complete 4-arrow solution.
        # The 15-iteration loop only exists to wait for the rune UI to render —
        # we don't require two matching inferences before pressing.
        solution = None
        loop_start = time.time()
        deadline = loop_start + self.RUNE_INFERENCE_TIMEOUT
        for i in range(15):
            if not config.enabled:
                return False
            if time.time() >= deadline:
                elapsed = time.time() - loop_start
                print(f'[!] Inference timed out after {elapsed:.1f}s with no 4-arrow solution')
                return False

            iter_start = time.time()
            frame = config.capture.frame
            candidate = detection.merge_detection(model, frame)
            iter_dt = time.time() - iter_start

            if candidate:
                print(f'  iter {i+1} ({iter_dt:.2f}s): {", ".join(candidate)}')
                if len(candidate) == 4:
                    solution = candidate
                    break
            else:
                print(f'  iter {i+1} ({iter_dt:.2f}s): no detection')

        if not solution:
            return False

        print(f'[~] Entering solution: {", ".join(solution)}')
        self._release_solver_keys(reason='pre-solution-press')
        if not self._interruptible_sleep(0.1):
            return False
        for arrow in solution:
            if not config.enabled:
                return False
            print(f'[rune-key] press {arrow}')
            press(arrow, 1, down_time=0.15, up_time=0.15)
        if not self._interruptible_sleep(1):
            return False
        for _ in range(3):
            if not self._interruptible_sleep(0.3):
                return False
            frame = config.capture.frame
            rune_buff = utils.multi_match(frame[:frame.shape[0] // 8, :],
                                          RUNE_BUFF_TEMPLATE,
                                          threshold=0.9)
            if rune_buff:
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
        runs warmup inferences for each input shape merge_detection uses so
        the first real solve doesn't pay TF JIT cost. Also warns the user
        when per-inference cost exceeds the in-game rune UI lifetime."""
        def loader():
            try:
                print('\n[~] Pre-loading rune detection model in background...')
                t0 = time.time()
                self.model = detection.load_model()
                print(f'[~] Model loaded in {time.time()-t0:.1f}s, warming up...')

                import numpy as np
                warmup_start = time.time()

                # Wait briefly for capture to expose a real frame so we warm
                # up with the user's actual game-window dimensions
                frame = None
                for _ in range(50):
                    if config.capture is not None and getattr(config.capture, 'frame', None) is not None:
                        frame = config.capture.frame
                        break
                    time.sleep(0.1)
                if frame is None:
                    frame = np.zeros((768, 1366, 3), dtype=np.uint8)

                # Inference 1: get_boxes on the cannied frame (shape varies with window)
                h, w = frame.shape[:2]
                cropped = frame[120:h//2, w//4:3*w//4]
                if cropped.shape[2] == 4:    # mss returns BGRA; filter_color expects 3 chans
                    cropped = cv2.cvtColor(cropped, cv2.COLOR_BGRA2BGR)
                filtered = detection.filter_color(cropped)
                cannied = detection.canny(filtered)
                t_inf = time.time()
                detection.get_boxes(self.model, cannied)
                get_boxes_dt = time.time() - t_inf
                print(f'[~]   warmup get_boxes ({cannied.shape[1]}x{cannied.shape[0]}): {get_boxes_dt:.2f}s')

                # Inferences 2 & 3: fixed shapes used after a successful box detection
                t_inf = time.time()
                detection.sort_by_confidence(self.model, np.zeros((384, 455, 3), dtype=np.uint8))
                print(f'[~]   warmup classify (455x384): {time.time()-t_inf:.2f}s')
                t_inf = time.time()
                detection.sort_by_confidence(self.model, np.zeros((455, 384, 3), dtype=np.uint8))
                print(f'[~]   warmup classify (384x455 rotated): {time.time()-t_inf:.2f}s')

                print(f'[~] Rune detection model ready (total warmup {time.time()-warmup_start:.1f}s)')

                # The rune UI is only on screen for ~10s. If a single get_boxes
                # call alone exceeds that, the solver cannot keep up no matter
                # how we tune retries. Surface this loudly with a fix path.
                if get_boxes_dt > 5.0:
                    print(f'[!] WARNING: per-inference cost is {get_boxes_dt:.1f}s; the rune UI '
                          f'closes after ~10s, so the solver may not keep up on this device.')
                    print(f'[!] TensorFlow on native Windows is CPU-only since TF 2.11. To get GPU '
                          f'acceleration, either run under WSL2 or install the DirectML plugin: '
                          f'`uv pip install tensorflow-directml-plugin`.')
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