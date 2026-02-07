"""A module for detecting and notifying the user of dangerous in-game events."""

from src.easymaple.common import config, utils
import time
import os
import cv2
import pygame
import threading
import numpy as np
import keyboard as kb
from src.easymaple.routine.components import Point


# A rune's symbol on the minimap
RUNE_RANGES = (
    ((135, 50, 220), (200, 160, 255)),
)
rune_filtered = utils.filter_color(cv2.imread('assets/rune_template.png'), RUNE_RANGES)
RUNE_TEMPLATE = cv2.cvtColor(rune_filtered, cv2.COLOR_BGR2GRAY)

# Other players' symbols on the minimap
OTHER_RANGES = (
    ((0, 245, 215), (10, 255, 255)),
)
other_filtered = utils.filter_color(cv2.imread('assets/other_template.png'), OTHER_RANGES)
OTHER_TEMPLATE = cv2.cvtColor(other_filtered, cv2.COLOR_BGR2GRAY)

# The Elite Boss's warning sign
ELITE_TEMPLATE = cv2.imread('assets/elite_template.jpg', 0)

RUNE_COOLDOWN_TEMPLATE = cv2.imread('assets/rune_cd_template.jpg', 0)
RUNE_COOLDOWN_TEMPLATE_1 = cv2.imread('assets/rune_cd_template_1.jpg', 0)

DEATH_TEMPLATE = cv2.imread('assets/death_template.png', 0)

RUNE_DETECT_FREQUENCY = 40

DEATH_DETECT_FREQUENCY = 400

def get_alert_path(name):
    return os.path.join(Notifier.ALERTS_DIR, f'{name}.mp3')


class Notifier:
    ALERTS_DIR = os.path.join('assets', 'alerts')

    def __init__(self):
        """Initializes this Notifier object's main thread."""

        pygame.mixer.init()
        self.mixer = pygame.mixer.music

        self.ready = False
        self.thread = threading.Thread(target=self._main)
        self.thread.daemon = True

        self.room_change_threshold = 0.85
        self.rune_alert_delay = 10

        self.rune_counter = 0
        self.rune_warning_thread = None

        self.death_counter = 0

    def start(self):
        """Starts this Notifier's thread."""

        print('\n[~] Started notifier')
        self.thread.start()

    def _main(self):
        self.ready = True
        report_time = 0
        while True:
            if config.enabled:
                frame = config.capture.frame
                height, width, _ = frame.shape
                minimap = config.capture.minimap['minimap']

                # Check for unexpected black screen
                # white room
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if np.count_nonzero(gray < 15) / height / width > self.room_change_threshold:
                    self._alert('siren')

                # Check for elite warning
                #elite_frame = frame[height // 4:3 * height // 4, width // 4:3 * width // 4]
                #elite = utils.multi_match(elite_frame, ELITE_TEMPLATE, threshold=0.9)
                #if len(elite) > 0:
                #    self._alert('siren')

                # Disable check for players
                # Check for other players entering the map
                # filtered = utils.filter_color(minimap, OTHER_RANGES)
                # others = len(utils.multi_match(filtered, OTHER_TEMPLATE, threshold=0.5))
                # config.stage_fright = others > 0
                # if others != prev_others:
                #     if others > prev_others:
                #         self._ping('ding')
                #     prev_others = others

                # Check for rune
                if self.rune_counter >= RUNE_DETECT_FREQUENCY or self.rune_counter == 0:
                    self.rune_counter = 1
                    filtered = utils.filter_color(minimap, RUNE_RANGES)
                    matches = utils.multi_match(filtered, RUNE_TEMPLATE, threshold=0.75)
                    if matches:
                        config.bot.rune_active=True
                        if time.time() - report_time > 10 or report_time == 0:
                            self._ping("rune_appeared", volume=0.75)
                            report_time = time.time()

                if self.death_counter >= DEATH_DETECT_FREQUENCY or self.death_counter == 0:
                    self.death_counter = 1
                    matches = utils.multi_match(frame=gray, template=DEATH_TEMPLATE, threshold=0.60)
                    if matches:
                        self._ping("ding", volume=0.75)

                self.rune_counter += 1
                self.death_counter +=1
            time.sleep(0.05)

    def _alert(self, name, volume=0.75):
        """
        Plays an alert to notify user of a dangerous event. Stops the alert
        once the key bound to 'Start/stop' is pressed.
        """

        config.enabled = False
        config.listener.enabled = False
        self.mixer.load(get_alert_path(name))
        self.mixer.set_volume(volume)
        self.mixer.play(-1)
        while not kb.is_pressed(config.listener.config['Start/stop']):
            time.sleep(0.1)
        self.mixer.stop()
        time.sleep(2)
        config.listener.enabled = True

    def _ping(self, name, volume=0.5):
        """A quick notification for non-dangerous events."""

        self.mixer.load(get_alert_path(name))
        self.mixer.set_volume(volume)
        self.mixer.play()


#################################
#       Helper Functions        #
#################################
def distance_to_rune(point):
    """
    Calculates the distance from POINT to the rune.
    :param point:   The position to check.
    :return:        The distance from POINT to the rune, infinity if it is not a Point object.
    """

    if isinstance(point, Point):
        return utils.distance(config.bot.rune_pos, point.location)
    return float('inf')
