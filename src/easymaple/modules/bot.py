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
        'Interact': 'y',
        'Feed pet': '9'
    }

    # Number of consecutive failed rune solves before alerting the user
    RUNE_FAIL_THRESHOLD = 3

    def __init__(self):
        """Loads a user-defined routine on start up and initializes this Bot's main thread."""

        super().__init__('keybindings')
        config.bot = self

        self.rune_active = False
        self.rune_pos = (0, 0)
        self.rune_closest_pos = (0, 0)      # Location of the Point closest to rune
        self.rune_solve_failures = 0
        self.submodules = []
        self.module_name = None
        self.buff = components.Buff()
        self.model = None

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
                if self.rune_active:
                    if solve_rune:
                        if self.model is None:
                            print('\n[~] Loading rune detection model...')
                            self.model = detection.load_model()
                            print('[~] Rune detection model loaded')
                        self._solve_rune(self.model)
                    else:
                        self.rune_active = False

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
                config.routine.step()
            else:
                time.sleep(0.01)

    @utils.run_if_enabled
    def _solve_rune(self, model):
        """
        Moves to the position of the rune and solves the arrow-key puzzle. Always
        clears `rune_active` on exit so the notifier re-detects on the next scan
        instead of busy-looping. After `RUNE_FAIL_THRESHOLD` consecutive failures
        (no consensus solution, or buff icon never appeared), alerts the user.
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

        time.sleep(1)
        press(self.config['Interact'], 1, down_time=0.2)        # Inherited from Configurable

        print('\nSolving rune:')
        inferences = []
        buff_confirmed = False
        for _ in range(15):
            frame = config.capture.frame
            solution = detection.merge_detection(model, frame)
            if solution:
                print(', '.join(solution))
                if solution in inferences:
                    print('Solution found, entering result')
                    for arrow in solution:
                        press(arrow, 1, down_time=0.1)
                    time.sleep(1)
                    for _ in range(3):
                        time.sleep(0.3)
                        frame = config.capture.frame
                        rune_buff = utils.multi_match(frame[:frame.shape[0] // 8, :],
                                                      RUNE_BUFF_TEMPLATE,
                                                      threshold=0.9)
                        if rune_buff:
                            buff_confirmed = True
                            rune_buff_pos = min(rune_buff, key=lambda p: p[0])
                            target = (
                                round(rune_buff_pos[0] + config.capture.window['left']),
                                round(rune_buff_pos[1] + config.capture.window['top'])
                            )
                            click(target, button='right')
                            break
                    break
                elif len(solution) == 4:
                    inferences.append(solution)

        # Always clear so we don't busy-loop; the notifier re-sets it if the rune
        # is still on the minimap (real failure) or stays clear if it was a false alarm.
        self.rune_active = False
        if buff_confirmed:
            if self.rune_solve_failures > 0:
                print(f'[~] Rune solved after {self.rune_solve_failures + 1} attempt(s)')
            self.rune_solve_failures = 0
        else:
            self._record_solve_failure()

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