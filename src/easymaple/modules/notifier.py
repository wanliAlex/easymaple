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
from src.easymaple.modules.lie_detector_player import (
    LieDetectorPlayer, LieDetectorSession, expected_box, motion_solver,
    preload_motion_solver, remember_box, save_trace)

log = logging.getLogger(__name__)


def _background(fn, *args):
    """Run slow bookkeeping (the game log) off the notifier thread."""
    threading.Thread(target=fn, args=args, daemon=True).start()


def _save_trace_quietly(result):
    try:
        save_trace(result)
    except Exception as e:
        log.warning("Could not save the solver trace: %s", e)

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
# while the test runs. Detection hands the game to the auto-solver
# (LieDetectorPlayer) when it is enabled in Settings; otherwise it notifies
# Discord and sirens so the human can take over, like the white-room safeguard.
LIE_DETECTOR_PREP_TEMPLATE = utils.load_image('assets/lie_detector_prep.png', cv2.IMREAD_GRAYSCALE)
LIE_DETECTOR_PROGRESS_TEMPLATE = utils.load_image('assets/lie_detector_in_progress.png', cv2.IMREAD_GRAYSCALE)
LIE_DETECTOR_THRESHOLD = 0.9

RUNE_DETECT_FREQUENCY = 40

DEATH_DETECT_FREQUENCY = 400

# ~0.5s at 0.05s/loop; reliably catches the ~6s prep window.
LIE_DETECTOR_DETECT_FREQUENCY = 10

# After handling a Lie Detector (solved or handed over), ignore re-detections
# for this long: the banner lingers past the game, and the auto-solve itself
# ends well inside this window.
LIE_DETECTOR_COOLDOWN_S = 90

NOTIFIER_LOOP_SLEEP_S = 0.05


def _console(message):
    """Report on the console only: a Lie Detector game that went fine is not
    worth a Discord ping (Discord hears about it only when it was not passed)."""
    print(f'[~] {message}')
    log.info(message)


def _takeover_key():
    """The key bound to the Lie Detector takeover (Settings -> controls)."""
    listener = getattr(config, 'listener', None)
    try:
        return listener.config['Lie Detector takeover']
    except Exception:
        return 'f9'


def _solved_by(result):
    """Who drove the game, for the Discord report."""
    if 'took_over' not in result:
        return f"自动求解，跟踪了 {result['frames_moved']} 帧"
    if result['took_over']:
        return f"影子模式，机器人接管后驱动了 {result['frames_moved']} 帧"
    agree = result.get('shadow_agreement')
    if agree is None:
        return "你手动完成"
    return (f"你手动完成；影子跟踪与你一致 {agree:.0%}"
            f"（最后1秒 {result['shadow_end_agreement']:.0%}）")


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

        self.room_change_threshold = 0.90
        self.rune_alert_delay = 10

        self.rune_counter = 0
        self.death_counter = 0
        self.lie_detector_counter = 0

        self._discord_queue = queue.Queue()

    def start(self):
        """Starts this Notifier's thread."""

        print('\n[~] Started notifier')
        threading.Thread(target=self._discord_sender, daemon=True).start()
        # Load + warm the Lie Detector solver now, not when a test pops up.
        preload_motion_solver()
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

                    # Check for the Lie Detector mini-game: auto-solve if enabled
                    # in Settings (Discord only if it fails), otherwise siren +
                    # Discord for manual takeover.
                    if self.lie_detector_counter >= LIE_DETECTOR_DETECT_FREQUENCY or self.lie_detector_counter == 0:
                        self.lie_detector_counter = 1
                        prep_hit = utils.match_score(gray, LIE_DETECTOR_PREP_TEMPLATE) >= LIE_DETECTOR_THRESHOLD
                        prog_hit = utils.match_score(gray, LIE_DETECTOR_PROGRESS_TEMPLATE) >= LIE_DETECTOR_THRESHOLD
                        if prep_hit or prog_hit:
                            self._handle_lie_detector("准备阶段" if prep_hit else "进行中")
                            # Long cooldown so the lingering banner / the same
                            # test can't re-trigger the handler.
                            self.lie_detector_counter = -round(LIE_DETECTOR_COOLDOWN_S / NOTIFIER_LOOP_SLEEP_S)

                    self.rune_counter += 1
                    self.death_counter += 1
                    self.lie_detector_counter += 1
            except Exception as e:
                log.exception("Notifier loop iteration failed; continuing: %s", e)
            time.sleep(NOTIFIER_LOOP_SLEEP_S)

    def _handle_lie_detector(self, phase):
        """React to a detected Lie Detector mini-game.

        Auto-solve enabled (Settings -> Lie Detector): pause the routine, drive
        the mouse through the game with :class:`LieDetectorPlayer`, and resume
        on success. Discord stays quiet unless the game was not passed: the
        detection and a pass (or a false alarm) are only reported on the
        console. On an unsure/failed outcome the bot stays paused, Discord is
        told and a single non-blocking ping plays. Disabled: five Discord messages and the
        blocking siren, like the white-room safeguard. A training clip is
        recorded in every case (it is how the solver's corpus grows).

        Auto-solve + Shadow: the human plays while the solver follows along
        without moving the mouse. Alerts as for manual mode (five Discord
        messages + a looping siren) but non-blocking: F8, the takeover key or
        the end of the game silence it. The takeover hotkey or unticking
        Shadow hands the solver the mouse mid-game. The per-frame
        report says who finished and how closely the solver agreed. Every
        game's per-frame solver log is saved under
        ``training_data/lie_detector/solver_logs``.
        """
        recorder.record_clip()
        settings = getattr(config, 'lie_detector', None)
        unavailable = ""
        if settings is not None and settings.get('auto solve') and motion_solver(retry=True) is None:
            # Never auto-solve with the previous solver (0/23 live-like): hand
            # the game to the human exactly as with auto-solve off.
            unavailable = "（自动求解器加载失败）"
        if settings is None or not settings.get('auto solve') or unavailable:
            config.enabled = False      # don't bot through the test
            for _ in range(5):
                self._enqueue_notify(f"<@{DISCORD_USER_ID}> 测谎仪小游戏 ({phase}){unavailable}！快手动接管")
            self._alert('siren')
            return

        # Shadow mode: the human plays, the solver follows along without
        # touching the mouse and takes over on the hotkey (or when "Shadow"
        # is unticked mid-game). The human is expected to play, so alert like
        # manual mode — five pings + a looping siren — but without blocking:
        # the solver must keep shadowing and the takeover hotkey must stay
        # live. F8 / the takeover key / the end of the game silence it.
        shadow = bool(settings.get('shadow'))
        if shadow:
            key = _takeover_key().upper()
            for _ in range(5):
                self._enqueue_notify(f"<@{DISCORD_USER_ID}> 测谎仪小游戏（{phase}）！影子模式：快手动解，"
                                     f"按 {key}（或取消勾选“影子”）让机器人接管")
            self._siren_on()
        else:
            _console(f"测谎仪小游戏（{phase}）！自动求解中…")
        config.enabled = False          # pause the routine while we drive the mouse
        session = LieDetectorSession(shadow, settings)
        config.lie_detector_session = session
        config.capture_fast = True      # frames ~2x as often until the game is over
        try:
            result = LieDetectorPlayer(shadow=shadow, takeover=session.takeover_requested,
                                       expected_box=expected_box()).solve()
        except Exception as e:
            log.exception("Lie Detector auto-solve crashed: %s", e)
            result = {"outcome": "error", "frames_moved": 0, "reached_track": False}
        finally:
            config.lie_detector_session = None
            config.capture_fast = False
            if shadow:
                self.stop_alerts()
        if result.get("reached_track"):
            # Only a box the game was actually played in (a box glimpsed
            # during the countdown must not move the next pre-positioning).
            remember_box(result.get("box"))

        passed = result["outcome"] == "completed" and (
            result["reached_track"] or result.get("success_seen"))
        if passed:
            banner = "看到 SUCCESS" if result.get("success_seen") else "未见 SUCCESS 字样，但没有进小黑屋"
            _console(f"✅ 测谎仪通过（{banner}；{_solved_by(result)}），继续挂机")
            config.enabled = True
        elif result["outcome"] == "no_box":
            _console("测谎仪：未出现游戏窗口（可能误报），继续挂机")
            config.enabled = True
        elif result["outcome"] == "failed":
            self._enqueue_notify(f"<@{DISCORD_USER_ID}> ❌ 测谎仪未通过（检测到小黑屋；{_solved_by(result)}），"
                                 f"机器人保持暂停，请手动处理")
            self._ping('siren', volume=0.75)
        elif result["outcome"] == "error":
            # The solver gave up mid-game: the game may still be running.
            for _ in range(5):
                self._enqueue_notify(f"<@{DISCORD_USER_ID}> ⚠️ 测谎仪自动求解出错中断，可能仍在进行！"
                                     f"快手动接管（机器人保持暂停）")
            self._siren_on()
        else:
            self._enqueue_notify(f"<@{DISCORD_USER_ID}> ⚠️ 测谎仪自动求解结果不确定"
                                 f"（{result['outcome']}），机器人保持暂停，请手动检查")
            self._ping('siren', volume=0.75)
        # The game log is tens of MB: write it after acting on the outcome.
        _background(_save_trace_quietly, result)

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

    def _siren_on(self, volume=0.75):
        """Start the siren looping in the background (unlike :meth:`_alert`,
        nothing waits on it); :meth:`stop_alerts` ends it."""
        try:
            self.mixer.load(get_alert_path('siren'))
            self.mixer.set_volume(volume)
            self.mixer.play(-1)
        except Exception as e:
            log.warning('Failed to start the siren: %s', e)

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
