"""A module for detecting and notifying the user of dangerous in-game events."""

from src.easymaple.common import config, utils
import logging
import queue
import time
import os
import cv2
import pygame
import queue
import threading
import numpy as np
import keyboard as kb
import requests
from dotenv import load_dotenv, find_dotenv
from src.easymaple.routine.components import Point
from src.easymaple.modules import recorder

log = logging.getLogger(__name__)

print(find_dotenv())
load_dotenv()

# Discord webhook for notifications
WEB_HOOK = os.environ.get("DISCORD_WEBHOOK", "")
DISCORD_USER_ID = os.environ.get("DISCORD_USER_ID", "")

if not WEB_HOOK:
    log.warning("DISCORD_WEBHOOK is not set — Discord notifications will be disabled")

print(f"Successfully loaded WEB_HOOK = {WEB_HOOK}, DISCORD_USER_ID={DISCORD_USER_ID}")


# A rune's symbol on the minimap
RUNE_RANGES = (
    ((135, 50, 220), (200, 160, 255)),
)
rune_filtered = utils.filter_color(utils.load_image('assets/rune_template.png'), RUNE_RANGES)
RUNE_TEMPLATE = cv2.cvtColor(rune_filtered, cv2.COLOR_BGR2GRAY)

# Other players' symbols on the minimap
OTHER_RANGES = (
    ((0, 245, 215), (10, 255, 255)),
)
other_filtered = utils.filter_color(utils.load_image('assets/other_template.png'), OTHER_RANGES)
OTHER_TEMPLATE = cv2.cvtColor(other_filtered, cv2.COLOR_BGR2GRAY)

# The Elite Boss's warning sign
ELITE_TEMPLATE = utils.load_image('assets/elite_template.jpg', cv2.IMREAD_GRAYSCALE)

RUNE_COOLDOWN_TEMPLATE = utils.load_image('assets/rune_cd_template.jpg', cv2.IMREAD_GRAYSCALE)
RUNE_COOLDOWN_TEMPLATE_1 = utils.load_image('assets/rune_cd_template_1.jpg', cv2.IMREAD_GRAYSCALE)

DEATH_TEMPLATE = utils.load_image('assets/death_template.png', cv2.IMREAD_GRAYSCALE)

# The Lie Detector anti-bot mini-game. Two distinct full-screen banners: the
# "prep" countdown shown ~6s before the test, and the "in progress" banner shown
# while the test runs. The bot cannot solve it, so detection hands control back
# to the human via a siren, like the white-room safeguard.
LIE_DETECTOR_PREP_TEMPLATE = utils.load_image('assets/lie_detector_prep.png', cv2.IMREAD_GRAYSCALE)
LIE_DETECTOR_PROGRESS_TEMPLATE = utils.load_image('assets/lie_detector_in_progress.png', cv2.IMREAD_GRAYSCALE)
LIE_DETECTOR_THRESHOLD = 0.9

RUNE_DETECT_FREQUENCY = 40

DEATH_DETECT_FREQUENCY = 400

# ~0.5s at 0.05s/loop; reliably catches the ~6s prep window.
LIE_DETECTOR_DETECT_FREQUENCY = 10

NOTIFIER_LOOP_SLEEP_S = 0.05


def rune_detect_poll_count():
    """Resolve how often (in poll iterations) the notifier should run rune
    detection. Reads `rune_detect_interval_seconds` from advanced settings
    so changes take effect live; falls back to RUNE_DETECT_FREQUENCY when
    the panel isn't loaded yet (early startup, tests).
    """
    if config.advanced is None:
        return RUNE_DETECT_FREQUENCY
    interval = config.advanced.get('rune_detect_interval_seconds')
    return max(1, round(interval / NOTIFIER_LOOP_SLEEP_S))


def get_alert_path(name):
    return os.path.join(Notifier.ALERTS_DIR, f'{name}.mp3')


class Notifier:
    ALERTS_DIR = os.path.join('assets', 'alerts')

    def __init__(self):
        """Initializes this Notifier object's main thread."""

        config.notifier = self

        pygame.mixer.init()
        self.mixer = pygame.mixer.music

        self.ready = False
        self.thread = threading.Thread(target=self._main)
        self.thread.daemon = True

        self.room_change_threshold = 0.85
        self.rune_alert_delay = 10

        self.rune_counter = 0
        self.death_counter = 0
        self.lie_detector_counter = 0

        self._discord_queue = queue.Queue()

    def start(self):
        """Starts this Notifier's thread."""

        print('\n[~] Started notifier')
        threading.Thread(target=self._discord_sender, daemon=True).start()
        self.thread.start()

    def _main(self):
        self.ready = True
        while True:
            try:
                if config.enabled:
                    frame = config.capture.frame
                    height, width, _ = frame.shape
                    minimap = config.capture.minimap['minimap']

                    # Check for unexpected black screen
                    # white room
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    if np.count_nonzero(gray < 15) / height / width > self.room_change_threshold:
                        for _ in range(5):
                            self._enqueue_notify(f"<@{DISCORD_USER_ID}> 白屋了兄弟")
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

                    # Check for rune. Notifications for rune appearance are intentionally
                    # silent — the bot solves it automatically. The notifier only alerts
                    # via alert_rune_unsolvable() when the solver actually fails.
                    if self.rune_counter >= rune_detect_poll_count() or self.rune_counter == 0:
                        self.rune_counter = 1
                        filtered = utils.filter_color(minimap, RUNE_RANGES)
                        rune_threshold = (
                            config.advanced.get('rune_map_threshold')
                            if config.advanced is not None else 0.75
                        )
                        config.last_rune_map_score = (
                            utils.match_score(filtered, RUNE_TEMPLATE),
                            time.time(),
                        )
                        matches = utils.multi_match(filtered, RUNE_TEMPLATE, threshold=rune_threshold)
                        if matches:
                            # On first detection, record the rune's minimap position
                            if not config.bot.rune_active:
                                abs_rune_pos = (matches[0][0], matches[0][1])
                                config.bot.rune_pos = utils.convert_to_relative(abs_rune_pos, minimap)
                            config.bot.rune_active = True

                    if self.death_counter >= DEATH_DETECT_FREQUENCY or self.death_counter == 0:
                        self.death_counter = 1
                        matches = utils.multi_match(frame=gray, template=DEATH_TEMPLATE, threshold=0.60)
                        if matches:
                            self._ping("ding", volume=0.75)

                    # Check for the Lie Detector mini-game. The bot can't solve it,
                    # so notify and siren so the user can take over manually.
                    if self.lie_detector_counter >= LIE_DETECTOR_DETECT_FREQUENCY or self.lie_detector_counter == 0:
                        self.lie_detector_counter = 1
                        prep_hit = utils.match_score(gray, LIE_DETECTOR_PREP_TEMPLATE) >= LIE_DETECTOR_THRESHOLD
                        prog_hit = utils.match_score(gray, LIE_DETECTOR_PROGRESS_TEMPLATE) >= LIE_DETECTOR_THRESHOLD
                        if prep_hit or prog_hit:
                            phase = "准备阶段" if prep_hit else "进行中"
                            recorder.record_clip()
                            for _ in range(5):
                                self._enqueue_notify(f"<@{DISCORD_USER_ID}> 测谎仪小游戏 ({phase})！快手动接管")
                            self._alert('siren')

                    self.rune_counter += 1
                    self.death_counter += 1
                    self.lie_detector_counter += 1
            except Exception as e:
                log.exception("Notifier loop iteration failed; continuing: %s", e)
            time.sleep(NOTIFIER_LOOP_SLEEP_S)

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

    def _enqueue_notify(self, message):
        if WEB_HOOK:
            self._discord_queue.put(message)
        else:
            print('[!] DISCORD_WEBHOOK is not set — Discord notification skipped')

    def alert_rune_unsolvable(self, attempts):
        """Audio + Discord alert when the rune solver fails a batch of trials."""
        msg = (f"<@{DISCORD_USER_ID}> 符文已连续 {attempts} 次解不开，"
               f"可能是误报或模型识别失败，请手动检查")
        print(f'\n[!] {msg}')
        self._enqueue_notify(msg)
        self._ping("siren", volume=0.75)

    def alert_rune_giving_up(self, total_trials):
        """Final alert when the bot has disabled itself after too many failed batches."""
        msg = (f"<@{DISCORD_USER_ID}> 符文连续失败 {total_trials} 次，"
               f"机器人已自动停止，请手动处理")
        print(f'\n[!] {msg}')
        self._enqueue_notify(msg)
        self._ping("siren", volume=0.75)

    def stop_alerts(self):
        """Stop any alert audio currently playing. Called on F8 toggle so the
        siren doesn't keep ringing after the user takes over."""
        try:
            self.mixer.stop()
        except Exception as e:
            log.warning('Failed to stop mixer: %s', e)

    def _discord_sender(self):
        """Persistent worker that drains _discord_queue and posts to Discord."""
        while True:
            message = self._discord_queue.get()
            try:
                r = requests.post(WEB_HOOK, json={"content": message}, timeout=10)
                r.raise_for_status()
            except requests.RequestException as e:
                # Print as well as log — the user is more likely to be watching the
                # console than the logger output
                print(f'[!] Discord notification failed: {e}')
                log.warning("Discord notification failed: %s", e)
            finally:
                self._discord_queue.task_done()


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
