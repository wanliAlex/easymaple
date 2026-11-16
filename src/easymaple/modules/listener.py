"""A keyboard listener to track user inputs."""

import time
import threading
import winsound
import keyboard as kb
from src.easymaple.common.interfaces import Configurable
from src.easymaple.common import config, utils
from datetime import datetime


class Listener(Configurable):
    DEFAULT_CONFIG = {
        'Start/stop': 'f8',
        'Reload routine': 'f6',
        'Record position': 'f7',
        'Lie Detector takeover': 'f9',
    }
    BLOCK_DELAY = 1         # Delay after blocking restricted button press

    def __init__(self):
        """Initializes this Listener object's main thread."""

        super().__init__('controls')
        config.listener = self

        self.enabled = False
        self.ready = False
        self.block_time = 0
        self.thread = threading.Thread(target=self._main)
        self.thread.daemon = True

    def start(self):
        """
        Starts listening to user inputs.
        :return:    None
        """

        print('\n[~] Started keyboard listener')
        self.thread.start()

    def _main(self):
        """
        Constantly listens for user inputs and updates variables in config accordingly.
        :return:    None
        """

        self.ready = True
        while True:
            if self.enabled:
                if kb.is_pressed(self.config['Start/stop']):
                    Listener.toggle_enabled()
                elif kb.is_pressed(self.config['Reload routine']):
                    Listener.reload_routine()
                elif self.restricted_pressed('Record position'):
                    Listener.record_position()
                elif kb.is_pressed(self.config['Lie Detector takeover']):
                    if Listener.lie_detector_takeover():
                        winsound.Beep(988, 150)     # B5: the bot has the mouse
                    time.sleep(0.3)
            time.sleep(0.01)

    def restricted_pressed(self, action):
        """Returns whether the key bound to ACTION is pressed only if the bot is disabled."""

        if kb.is_pressed(self.config[action]):
            if not config.enabled:
                return True
            now = time.time()
            if now - self.block_time > Listener.BLOCK_DELAY:
                print(f"\n[!] Cannot use '{action}' while Auto Maple is enabled")
                self.block_time = now
        return False

    @staticmethod
    def lie_detector_takeover():
        """Hand a shadowed Lie Detector game to the solver. Returns True if a
        game in shadow mode was handed over (no-op otherwise)."""
        session = config.lie_detector_session
        if session is None:
            return False
        taken = session.request_takeover()
        if taken:
            print('\n[~] Lie Detector: solver takes over the mouse')
            Listener._silence()
        return taken

    @staticmethod
    def _silence():
        """Stop the (shadow-mode) siren."""
        if config.notifier is not None:
            config.notifier.stop_alerts()

    @staticmethod
    def toggle_enabled():
        """Resumes or pauses the current routine. Plays a sound to notify the user."""

        if not config.enabled and config.lie_detector_session is not None:
            # Never resume the routine in the middle of a Lie Detector game:
            # it would press skills while the test is being solved. F8 here
            # just acknowledges the (shadow-mode) siren, as in manual mode.
            Listener._silence()
            print('\n[!] Lie Detector in progress - siren off, routine stays paused')
            time.sleep(0.6)
            return

        config.bot.rune_active = False

        if not config.enabled:
            Listener.recalibrate_minimap()      # Recalibrate only when being enabled.

        config.enabled = not config.enabled
        utils.print_state()

        # If the user just took over (F8 toggled OFF), stop any rune-failure
        # siren that may still be playing so they can solve in peace
        if not config.enabled and config.notifier is not None:
            config.notifier.stop_alerts()

        if config.enabled:
            winsound.Beep(784, 333)     # G5
        else:
            winsound.Beep(523, 333)     # C5
        time.sleep(0.267)

    @staticmethod
    def reload_routine():
        Listener.recalibrate_minimap()

        config.routine.load(config.routine.path)

        winsound.Beep(523, 200)     # C5
        winsound.Beep(659, 200)     # E5
        winsound.Beep(784, 200)     # G5

    @staticmethod
    def recalibrate_minimap():
        config.capture.calibrated = False
        while not config.capture.calibrated:
            time.sleep(0.01)
        config.gui.edit.minimap.redraw()

    @staticmethod
    def record_position():
        pos = tuple('{:.3f}'.format(round(i, 3)) for i in config.player_pos)
        now = datetime.now().strftime('%I:%M:%S %p')
        config.gui.edit.record.add_entry(now, pos)
        print(f'\n[~] Recorded position ({pos[0]}, {pos[1]}) at {now}')
        time.sleep(0.6)
