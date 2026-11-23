"""Q-World auto re-entry.

Q-World farming maps run on a 30-minute timer. When it reaches 0 the game
warps the character to the Q-World lobby (with a short black screen in
between). Standing in the lobby's portal and pressing Up starts a new
30-minute run in the farming map.

A black screen can also mean a disconnect, so keys are only pressed after
the lobby has been positively recognised from its minimap. Anything else
that does not resolve to a known map raises the alarm instead.

Flow (on the notifier thread; the routine stays paused throughout)::

    trigger ──► pause ──► wait for the screen to settle ──┬─ farm map ──► recalibrate, resume routine
    (black screen,                                        ├─ lobby ─────► recalibrate, walk into the
     lobby minimap seen,                                  │               portal (pressing Up), wait again
     farm minimap missing)                                └─ still black / unknown after the timeout
                                                                       ──► Discord + siren, stay paused

The lobby is recognised by matching a saved picture of its minimap
(``assets/qworld_lobby_minimap.png`` by default; the Settings tab can replace
it with a fresh capture). The farm map is the minimap that was on screen
when the bot was last started with F8.

Keys go through ``vkeys`` like every command book, and ``vkeys.key_down`` /
``press`` only send anything while ``config.enabled`` is True. So the walk
into the portal parks the bot thread (it idles while :attr:`active`) and turns
``config.enabled`` on just for the walk.
"""

import ctypes
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager

import cv2
import numpy as np

from src.easymaple.common import config, utils
from src.easymaple.common.interfaces import Configurable
from src.easymaple.common.vkeys import key_down, key_up, press

log = logging.getLogger(__name__)


# Screen classes
BLACK = 'black'             # map transition / loading / possibly a disconnect
LOBBY = 'lobby'             # the Q-World lobby (its minimap matches the reference)
FARM = 'farm'               # the minimap that was on screen when the bot started
OTHER_MAP = 'other map'     # some minimap that is neither of the above
UNKNOWN = 'unknown'         # no minimap at all (login screen, dialogs, loading)

# Run outcomes
RESUMED = 'resumed'
FAILED = 'failed'
ABORTED = 'aborted'
BUSY = 'busy'

# Template-match scores (TM_CCOEFF_NORMED, grayscale). On the captured
# screenshots the right map scores ~1.0 and the wrong one ~0.3-0.4.
LOBBY_THRESHOLD = 0.75
FARM_THRESHOLD = 0.7
MINIMAP_TL_THRESHOLD = 0.9
MINIMAP_BR_THRESHOLD = 0.8

# The minimap always sits in the top-left corner: only search there.
SEARCH_HEIGHT = 400
SEARCH_WIDTH = 600

# A frame is "black" when nearly all of its centre is near-black. The centre
# crop leaves out the remote-desktop title bar, scrollbars and the HUD.
BLACK_PIXEL_LEVEL = 20
BLACK_FRACTION = 0.95

# How long the screen must stay black before the notifier hands over.
BLACK_HOLD_S = 0.3
# How often the notifier looks at the minimap while farming.
MAP_CHECK_INTERVAL_S = 1.0
# Consecutive map checks without the farm minimap before handing over.
FARM_MISS_LIMIT = 5

# Keys released after walking. Modifier keys are deliberately left alone: a
# stray key_up on the Interact key ('alt') can register as a press.
WALK_KEYS = ('left', 'right', 'up', 'down')

TL_TEMPLATE = utils.load_image('assets/minimap_tl_template.png', cv2.IMREAD_GRAYSCALE)
BR_TEMPLATE = utils.load_image('assets/minimap_br_template.png', cv2.IMREAD_GRAYSCALE)


#################################
#       Screen detection        #
#################################
def to_gray(image):
    """Grayscale copy of a BGR/BGRA image (gray images pass through)."""
    if image is None:
        return None
    if len(image.shape) == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def search_region(gray):
    """The top-left corner of the frame, where the minimap lives."""
    return gray[:SEARCH_HEIGHT, :SEARCH_WIDTH]


def is_black_screen(gray):
    """True when the centre of the frame is (almost) entirely black."""
    h, w = gray.shape[:2]
    centre = gray[int(h * 0.15):int(h * 0.85), int(w * 0.10):int(w * 0.90)]
    if centre.size == 0:
        return False
    return np.count_nonzero(centre < BLACK_PIXEL_LEVEL) / centre.size >= BLACK_FRACTION


def match(region, template):
    """Best TM_CCOEFF_NORMED score of TEMPLATE inside REGION (0.0 if it cannot match)."""
    if region is None or template is None:
        return 0.0
    if template.shape[0] > region.shape[0] or template.shape[1] > region.shape[1]:
        return 0.0
    try:
        score = float(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED).max())
    except cv2.error:
        return 0.0
    return 0.0 if np.isnan(score) else score


def minimap_present(region):
    """True when both minimap corner templates are clearly on screen."""
    return (match(region, TL_TEMPLATE) >= MINIMAP_TL_THRESHOLD
            and match(region, BR_TEMPLATE) >= MINIMAP_BR_THRESHOLD)


def classify(gray, lobby_ref, farm_ref):
    """Which screen GRAY shows. Returns (state, scores)."""
    if is_black_screen(gray):
        return BLACK, {}
    region = search_region(gray)
    lobby = match(region, lobby_ref)
    farm = match(region, farm_ref) if farm_ref is not None else None
    scores = {'lobby': lobby, 'farm': farm}
    if lobby >= LOBBY_THRESHOLD and (farm is None or lobby >= farm):
        return LOBBY, scores
    if farm is not None and farm >= FARM_THRESHOLD:
        return FARM, scores
    if minimap_present(region):
        return OTHER_MAP, scores
    return UNKNOWN, scores


#################################
#           Settings            #
#################################
class QWorldSettings(Configurable):
    DEFAULT_CONFIG = {
        'enabled': False,
        'portal x': 0.515,
        'portal y': 0.246,
        'tolerance': 0.01,
        'portal key': 'up',
        'lobby minimap': os.path.join('assets', 'qworld_lobby_minimap.png'),
    }

    def get(self, key):
        return self.config[key]

    def set(self, key, value):
        assert key in self.config
        self.config[key] = value


#################################
#         Re-entry logic        #
#################################
class QWorldReentry:
    """Watches for the Q-World kick and walks back through the lobby portal.

    The notifier calls :meth:`poll` every loop while the bot is enabled; when
    it sees a trigger it runs :meth:`run` synchronously on its own thread.
    """

    # Timings (class attributes so tests can shrink them)
    POLL_S = 0.25                   # screen polling period while handling
    PAUSE_SETTLE_S = 1.0            # let the bot's in-flight command finish
    PARK_TIMEOUT_S = 20             # the bot thread must be idle before we drive
    SCREEN_TIMEOUT_S = 60           # black/unknown this long => alarm
    STABLE_READS = 3                # lobby/farm must be seen this many polls in a row
    OTHER_MAP_STABLE_READS = 8      # an unrecognised minimap needs longer (fade-ins)
    CALIBRATE_TIMEOUT_S = 15
    AFTER_CALIBRATE_S = 0.5         # let Capture track the player on the new minimap
    FOCUS_WAIT_S = 0.5              # after bringing the game window to the front
    PORTAL_WAIT_S = 4               # after the walk, wait this long to leave the lobby
    MAX_PORTAL_ATTEMPTS = 4
    RESUME_SETTLE_S = 1.5           # let the farm map load before the routine restarts

    # Walking into the portal: the movement of the nightlord command book's
    # portal commands (FFP3_*_PORTAL / get_into_portal). Tap the arrow towards
    # the portal for a time proportional to the distance, press Up whenever
    # within range, stop once the lobby is gone.
    PORTAL_STEPS = 100
    PORTAL_PRESS_RANGE = 0.03       # press Up when this close (minimap units)
    PORTAL_CENTRED = 0.002          # close enough: stop walking, keep pressing Up
    MOVE_GAIN_S = 6                 # seconds of arrow per minimap unit of distance
    MOVE_GAIN_RIGHT = 1.8           # walking right is held this much longer
    MIN_MOVE_S = 0.03

    # The portal may be on another level than the spawn point (the lobby's
    # sits on a step above it). Like the command books' Adjust: line up on x
    # within 'tolerance', then the book's UpJump / Rope / DownJump.
    PORTAL_Y_RANGE = 0.015          # on the portal's level when |dy| is within this
    ROPE_HEIGHT = 0.1               # higher than this: Rope (if the book has one)
    LAND_S = 0.8                    # after a jump, let the character land
    MAX_LEVEL_CHANGES = 6           # then stop trusting 'portal y' and just press Up

    def __init__(self, notifier=None, settings=None):
        self.notifier = notifier
        self.settings = settings if settings is not None else QWorldSettings('qworld')
        self.farm_ref = None            # grayscale minimap of the farming map
        self.active = False             # True while run() is handling a kick
        self.status = 'idle'
        self.reentries = 0
        self._abort = threading.Event()
        self._run_lock = threading.Lock()
        self._lobby_cache = (None, None, None)     # (path, mtime, image)
        self._black_since = None
        self._last_map_check = 0.0
        self._farm_misses = 0
        self._not_lobby_reads = 0

    #############################
    #       Public helpers      #
    #############################
    def enabled(self):
        return bool(self.settings.get('enabled'))

    def lobby_reference(self):
        """The lobby minimap picture (grayscale), reloaded when the file changes."""
        path = self.settings.get('lobby minimap')
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        cached_path, cached_mtime, image = self._lobby_cache
        if cached_path != path or cached_mtime != mtime:
            image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            self._lobby_cache = (path, mtime, image)
        return image

    def classify_current(self):
        """Classify the latest captured frame. Returns (state, scores)."""
        frame = getattr(config.capture, 'frame', None)
        if frame is None:
            return UNKNOWN, {}
        return classify(to_gray(frame), self.lobby_reference(), self.farm_ref)

    def describe_screen(self):
        """One-line report of what the detector sees right now (for the GUI)."""
        state, scores = self.classify_current()
        parts = [f'Screen: {state.upper()}']
        if scores:
            parts.append(f"lobby {scores['lobby']:.2f}")
            farm = scores['farm']
            parts.append('farm —' if farm is None else f'farm {farm:.2f}')
        if self.lobby_reference() is None:
            parts.append('NO lobby picture')
        x, y = config.player_pos
        parts.append(f'player ({x:.3f}, {y:.3f})')
        return ', '.join(parts)

    def save_lobby_reference(self):
        """Save the currently calibrated minimap as the lobby picture.
        Returns (ok, message)."""
        capture = config.capture
        sample = getattr(capture, 'minimap_sample', None)
        if capture is None or not getattr(capture, 'calibrated', False) or sample is None:
            return False, 'Minimap not calibrated yet: stand in the lobby and press F6 first'
        gray = to_gray(sample)
        if self.farm_ref is not None and match(gray, self.farm_ref) >= FARM_THRESHOLD:
            return False, 'This is the farming map, not the lobby: go to the lobby and press F6'
        bgr = sample if len(sample.shape) == 2 or sample.shape[2] == 3 \
            else cv2.cvtColor(sample, cv2.COLOR_BGRA2BGR)
        path = self.settings.get('lobby minimap')
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if not cv2.imwrite(path, bgr):
            return False, f'Could not write {path}'
        h, w = gray.shape[:2]
        print(f'[~] Q-World: saved lobby minimap ({w}x{h}) to {path}')
        return True, f'Saved lobby minimap ({w}x{h}) to {path}'

    def on_bot_enabled(self):
        """Remember the farm minimap. Called by the F8 handler right after it
        recalibrated, just before the routine starts."""
        self._black_since = None
        self._farm_misses = 0
        self._last_map_check = 0.0
        sample = getattr(config.capture, 'minimap_sample', None)
        if sample is None:
            return
        gray = to_gray(sample)
        if match(gray, self.lobby_reference()) >= LOBBY_THRESHOLD:
            # Started in the lobby: keep the previous farm picture (if any);
            # poll() will see the lobby and walk to the portal.
            return
        self.farm_ref = gray.copy()

    def abort(self):
        """Stop an in-progress re-entry (F8). The bot stays paused."""
        self._abort.set()

    def status_text(self):
        if self.active:
            return f'Q-World: {self.status}'
        if not self.enabled():
            return 'Q-World: OFF'
        if self.reentries:
            return f'Q-World: ON ({self.reentries} re-entr{"y" if self.reentries == 1 else "ies"})'
        return 'Q-World: ON'

    #############################
    #        Notifier hook      #
    #############################
    def poll(self, gray):
        """Called by the notifier every loop while the bot is enabled. Runs a
        re-entry (blocking) and returns True when the frame showed a trigger."""
        if self.active or not self.enabled():
            return False
        now = time.time()

        if is_black_screen(gray):
            if self._black_since is None:
                self._black_since = now
            if now - self._black_since >= BLACK_HOLD_S:
                self._black_since = None
                self.run('black screen')
                return True
            return False
        self._black_since = None

        if now - self._last_map_check < MAP_CHECK_INTERVAL_S:
            return False
        self._last_map_check = now

        region = search_region(gray)
        if match(region, self.lobby_reference()) >= LOBBY_THRESHOLD:
            self.run('lobby minimap on screen')
            return True

        if self.farm_ref is None:
            self._adopt_current_minimap(region)
            return False
        if match(region, self.farm_ref) >= FARM_THRESHOLD:
            self._farm_misses = 0
            return False
        self._farm_misses += 1
        if self._farm_misses >= FARM_MISS_LIMIT:
            self._farm_misses = 0
            self.run('farm minimap missing')
            return True
        return False

    def _adopt_current_minimap(self, region):
        """No farm picture yet (Q-World was ticked after F8): take the
        calibrated minimap, if it really is what is on screen now."""
        sample = getattr(config.capture, 'minimap_sample', None)
        if sample is None or not getattr(config.capture, 'calibrated', False):
            return
        gray = to_gray(sample)
        if match(region, gray) >= FARM_THRESHOLD:
            self.farm_ref = gray.copy()

    #############################
    #        State machine      #
    #############################
    def run(self, reason, manual=False):
        """Handle a (suspected) kick: pause, recover, resume. Blocks until done.

        MANUAL (the GUI's test button): if the screen turns out to be the farm
        map without going through the portal, report it and leave the bot as
        it was instead of starting the routine.
        """
        if not self._run_lock.acquire(blocking=False):
            return BUSY
        self.active = True                      # parks the bot thread
        self._abort.clear()
        was_enabled = config.enabled
        config.enabled = False                  # stop the current routine command
        bot = getattr(config, 'bot', None)
        if bot is not None:
            bot.rune_active = False
        print(f'\n[~] Q-World: {reason} - routine paused, checking the screen')
        try:
            self._set_status('pausing')
            self._sleep(self.PAUSE_SETTLE_S)
            self._release_keys()
            outcome = self._recover(manual, was_enabled)
        except Exception as e:
            log.exception('Q-World re-entry crashed: %s', e)
            config.enabled = False
            self._release_keys()
            outcome = self._fail(f'程序出错（{e}）')
        finally:
            self._release_keys()
            self.active = False
            self.status = 'idle'
            self._black_since = None
            self._farm_misses = 0
            self._last_map_check = time.time()
            self._run_lock.release()
        if outcome == ABORTED:
            print('[!] Q-World: re-entry aborted - bot stays paused')
        return outcome

    def _recover(self, manual, was_enabled):
        attempts = 0
        entered = False
        while True:
            self._set_status('waiting for the screen')
            state = self._wait_for_settled_screen()
            if self._aborted():
                return ABORTED

            if state in (FARM, OTHER_MAP):
                return self._resume(state, entered, manual, was_enabled)

            if state == LOBBY:
                attempts += 1
                if attempts > self.MAX_PORTAL_ATTEMPTS:
                    return self._fail(f'试了 {self.MAX_PORTAL_ATTEMPTS} 次传送门还在大厅')
                if not self._wait_bot_parked():
                    return self._fail('机器人线程没有停下来，不能安全地走向传送门')
                if self._enter_portal(attempts):
                    entered = True
                if self._aborted():
                    return ABORTED
                continue

            if state == BLACK:
                return self._fail(f'黑屏超过 {self.SCREEN_TIMEOUT_S} 秒（可能掉线）')
            return self._fail('黑屏后没有识别到大厅或练级地图（可能掉线）')

    def _wait_for_settled_screen(self):
        """Poll until the screen shows the same known map for a few polls in a
        row. Returns that state, or the last state seen at the timeout."""
        deadline = time.time() + self.SCREEN_TIMEOUT_S
        last, streak = None, 0
        while time.time() < deadline:
            if self._aborted():
                return None
            state, _ = self.classify_current()
            streak = streak + 1 if state == last else 1
            last = state
            needed = self.OTHER_MAP_STABLE_READS if state == OTHER_MAP else self.STABLE_READS
            if state in (LOBBY, FARM, OTHER_MAP) and streak >= needed:
                return state
            time.sleep(self.POLL_S)
        return last

    def _enter_portal(self, attempt):
        """Walk into the lobby portal. True once the lobby is left."""
        self._set_status('walking to the portal')
        print(f'[~] Q-World: in the lobby - walking to the portal '
              f'(attempt {attempt}/{self.MAX_PORTAL_ATTEMPTS})')
        if not self._recalibrate():
            print('[!] Q-World: could not calibrate the lobby minimap')
            return False
        if not self._sleep(self.AFTER_CALIBRATE_S):
            return False
        self._focus_game()
        if self._aborted():
            return False

        target = (float(self.settings.get('portal x')), float(self.settings.get('portal y')))
        with self._driving():
            left = self._walk_into_portal(target)
        if left:
            print('[~] Q-World: left the lobby')
        elif not self._aborted():
            x, y = config.player_pos
            print(f'[!] Q-World: still in the lobby at ({x:.3f}, {y:.3f}); '
                  f'portal is at ({target[0]:.3f}, {target[1]:.3f})')
        return left

    def _walk_into_portal(self, target):
        """The nightlord command book's get_into_portal, ending when the lobby
        is gone instead of at the next portal's position. When the portal is
        on another level, line up under/over it and jump there first."""
        key = self.settings.get('portal key')
        x_tolerance = max(float(self.settings.get('tolerance')), self.PORTAL_CENTRED)
        level_changes = 0
        self._not_lobby_reads = 0
        for _ in range(self.PORTAL_STEPS):
            if self._aborted() or not config.enabled:
                return False
            if self._left_lobby():
                return True
            x, y = config.player_pos
            x_distance = x - target[0]
            y_distance = y - target[1]          # > 0: below the portal (minimap y grows down)
            off_level = (abs(y_distance) > self.PORTAL_Y_RANGE
                         and level_changes < self.MAX_LEVEL_CHANGES)
            if off_level and abs(x_distance) <= x_tolerance:
                level_changes += 1
                self._change_level(y, target[1])
                continue
            if not off_level and abs(x_distance) < self.PORTAL_PRESS_RANGE:
                press(key, 1, 0.05, 0.01)
            if abs(x_distance) < self.PORTAL_CENTRED:
                time.sleep(0.1)
                continue
            direction = 'right' if x_distance < 0 else 'left'
            press(direction, 1, self._move_time(direction, x_distance))
        return self._wait_until_left_lobby(self.PORTAL_WAIT_S)

    def _change_level(self, y, target_y):
        """Jump from minimap height Y towards TARGET_Y with the loaded command
        book's own movement commands (what its Adjust uses), or a plain
        Up+Jump / Down+Jump when the book has none."""
        book = getattr(getattr(config, 'bot', None), 'command_book', None) or {}
        jump = self._jump_key()
        if y > target_y:            # the portal is above (as in Adjust)
            if y - target_y > self.ROPE_HEIGHT and self._run_book(book, 'rope'):
                how = 'book Rope'
            elif self._run_book(book, 'upjump'):
                how = 'book UpJump'
            else:
                how = f'up + {jump} x2'
                key_down('up')
                press(jump, 1, 0.1, 0.1)
                press(jump, 1, 0.1, 0.01)
                key_up('up')
        else:                       # the portal is below
            if self._run_book(book, 'downjump'):
                how = 'book DownJump'
            else:
                how = f'down + {jump}'
                key_down('down')
                press(jump, 1, 0.1, 0.1)
                key_up('down')
        self._release_keys()
        print(f'[~] Q-World: portal is {"above" if y > target_y else "below"} '
              f'(y {y:.3f} -> {target_y:.3f}): {how}')
        self._sleep(self.LAND_S)

    @staticmethod
    def _run_book(book, name):
        """Run the command book's NAME command (no arguments). False if the
        book has none or it needs arguments."""
        command_class = book.get(name)
        if command_class is None:
            return False
        try:
            command = command_class()
        except (TypeError, ValueError):
            return False
        command.main()
        return True

    @staticmethod
    def _jump_key():
        """The loaded command book's jump key ('space' if it has none)."""
        name = getattr(getattr(config, 'bot', None), 'module_name', None)
        module = sys.modules.get(f'resources.command_books.{name}') if name else None
        return getattr(getattr(module, 'Key', None), 'JUMP', None) or 'space'

    def _move_time(self, direction, distance):
        base = max(abs(distance) * self.MOVE_GAIN_S, self.MIN_MOVE_S)
        return base * self.MOVE_GAIN_RIGHT if direction == 'right' else base

    def _left_lobby(self):
        """One look at the screen: black, or not the lobby twice in a row."""
        state, _ = self.classify_current()
        if state == BLACK:
            return True
        self._not_lobby_reads = self._not_lobby_reads + 1 if state != LOBBY else 0
        return self._not_lobby_reads >= 2

    def _wait_until_left_lobby(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._aborted():
                return False
            if self._left_lobby():
                return True
            time.sleep(self.POLL_S)
        return False

    def _resume(self, state, entered, manual, was_enabled):
        self._set_status('resuming')
        if not entered and manual:
            print(f'[~] Q-World: screen is the {state}, not the lobby - nothing to do')
            config.enabled = was_enabled
            return RESUMED
        if not self._recalibrate():
            return self._fail('回到练级地图后小地图校准失败')

        sample = getattr(config.capture, 'minimap_sample', None)
        if state == OTHER_MAP and self.farm_ref is not None and entered:
            msg = 'Q-World：传送后的地图和开始挂机时的不一样，已继续挂机，请检查'
            print(f'[!] {msg}')
            self._notify(msg)
        if sample is not None:
            gray = to_gray(sample)
            if match(gray, self.lobby_reference()) < LOBBY_THRESHOLD:
                self.farm_ref = gray.copy()

        if entered:
            routine = getattr(config, 'routine', None)
            if routine is not None:
                routine.index = 0           # start the routine over in the new run
        bot = getattr(config, 'bot', None)
        if bot is not None:
            bot.rune_active = False

        if not self._sleep(self.RESUME_SETTLE_S):
            return ABORTED
        if entered:
            self.reentries += 1
            print(f'[~] Q-World: back in the farming map (re-entry #{self.reentries}) - resuming routine')
        else:
            print(f'[~] Q-World: still in the farming map ({state}) - resuming routine')
        config.enabled = True
        return RESUMED

    def _fail(self, reason):
        """Give up: stay paused, tell Discord and sound the siren (blocks until F8)."""
        config.enabled = False
        self._set_status('FAILED')
        msg = f'Q-World 自动重进失败：{reason}，机器人已暂停，请手动处理'
        print(f'[!] {msg}')
        for _ in range(5):
            self._notify(msg)
        if self.notifier is not None:
            self.notifier._alert('siren')
        return FAILED

    #############################
    #          Helpers          #
    #############################
    @contextmanager
    def _driving(self):
        """Let keys through while walking into the portal.

        vkeys.key_down/press only act while config.enabled is True, so it is
        turned on here; the bot thread stays parked because :attr:`active` is
        set. F8 (listener) aborts and clears config.enabled, which stops the
        walk at its next step.
        """
        if not self._aborted():
            config.enabled = True
        try:
            yield
        finally:
            config.enabled = False
            self._release_keys()

    def _wait_bot_parked(self):
        """Wait until the bot thread is idling (it parks while we are active)."""
        bot = getattr(config, 'bot', None)
        if bot is None or not hasattr(bot, 'parked'):
            return True
        deadline = time.time() + self.PARK_TIMEOUT_S
        while not bot.parked:
            if self._aborted() or time.time() > deadline:
                return False
            time.sleep(0.05)
        return True

    def _focus_game(self):
        """Bring the game window to the front so it receives the keys (after
        the GUI's test button, the Auto Maple window has the focus)."""
        finder = getattr(config.capture, '_find_game_window', None)
        if finder is None:
            return
        try:
            window = finder()
            hwnd = getattr(window, '_hWnd', None)
            if window is None or hwnd is None:
                return
            user32 = ctypes.windll.user32
            if user32.GetForegroundWindow() == hwnd:
                return
            print('[~] Q-World: bringing the game window to the front')
            try:
                window.activate()
            except Exception:
                pass            # pygetwindow raises even on some successes
            self._sleep(self.FOCUS_WAIT_S)
            if user32.GetForegroundWindow() != hwnd:
                print('[!] Q-World: could not focus the game window - click it so it gets the keys')
        except Exception as e:
            log.warning('Q-World: focusing the game window failed: %s', e)

    def _set_status(self, status):
        self.status = status

    def _aborted(self):
        return self._abort.is_set()

    def _sleep(self, duration):
        """Sleep that wakes up early on abort. Returns False if aborted."""
        return not self._abort.wait(duration) if duration > 0 else not self._aborted()

    def _notify(self, message):
        if self.notifier is None:
            return
        user = os.environ.get('DISCORD_USER_ID', '')
        self.notifier._enqueue_notify(f'<@{user}> {message}' if user else message)

    def _recalibrate(self):
        """Re-find the minimap (like F6). False on timeout or abort."""
        capture = config.capture
        if capture is None:
            return False
        capture.calibrated = False
        deadline = time.time() + self.CALIBRATE_TIMEOUT_S
        while not capture.calibrated:
            if self._aborted() or time.time() > deadline:
                return False
            time.sleep(0.05)
        try:
            config.gui.edit.minimap.redraw()
        except Exception:
            pass
        return True

    @staticmethod
    def _release_keys():
        for key in WALK_KEYS:
            key_up(key)
