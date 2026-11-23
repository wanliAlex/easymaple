"""Tests for Q-World auto re-entry (modules/qworld.py).

Detection runs on real minimap crops from the game (tests/fixtures/qworld_*),
pasted into synthetic full-size frames. The state machine runs against a fake
world through the REAL vkeys functions (only pynput's keyboard underneath is
faked), so vkeys' run_if_enabled gate applies exactly as in the game: a first
version paused the bot with config.enabled = False and every key it sent was
silently dropped.

Contract (user-specified):
* kicked to the lobby -> walk into the portal (0.515, 0.246) pressing Up,
  resume farming once the farm map is back;
* a black screen can also be a disconnect: never press keys unless the lobby
  was recognised; anything unresolved -> Discord + siren, bot stays paused.
"""
import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from pynput.keyboard import Key

from src.easymaple.common import config, vkeys
from src.easymaple.common.vkeys import key_down, key_up, press
from src.easymaple.modules import qworld
from src.easymaple.routine.components import Command
from src.easymaple.modules.qworld import (
    BLACK, FARM, LOBBY, OTHER_MAP, UNKNOWN, RESUMED, FAILED, ABORTED, QWorldReentry)

H, W = 822, 1047                    # the remote-desktop window the screenshots came from
FIXTURE_TOP = 40                    # fixtures were cropped from frame rows 40..150
FARM_CROP = (slice(23, 97), slice(7, 227))      # calibrated minimap inside the fixture
LOBBY_CROP = (slice(23, 86), slice(7, 174))
PORTAL_X, SPAWN_X, SPAWN_Y = 0.515, 0.407, 0.281
PORTAL_HALF_WIDTH = 0.015
# The lobby: the spawn is on the floor (y 0.281), the portal (F7: 0.515,
# 0.246) on a step above it that needs an up-jump.
LOWER_Y, UPPER_Y = SPAWN_Y, 0.246
STEP = (0.48, 0.56)


def _background(seed=0):
    rng = np.random.default_rng(seed)
    noise = rng.integers(40, 200, size=(H // 8, W // 8, 3), dtype=np.uint8)
    frame = cv2.resize(noise, (W, H), interpolation=cv2.INTER_LINEAR)
    frame[:38] = 240                # title bar
    frame[:, -18:] = 230            # scrollbar
    return frame


def _with_topleft(path):
    frame = _background()
    tile = cv2.imread(path)
    frame[FIXTURE_TOP:FIXTURE_TOP + tile.shape[0], :tile.shape[1]] = tile
    return frame


def _black():
    frame = np.zeros((H, W, 3), np.uint8)
    frame[:38] = 240
    frame[:, -18:] = 230
    return frame


FRAMES = {
    'farm': _with_topleft('tests/fixtures/qworld_farm_topleft.png'),
    'lobby': _with_topleft('tests/fixtures/qworld_lobby_topleft.png'),
    'black': _black(),
    'login': _background(seed=7),   # no minimap at all
}
FARM_MM = cv2.imread('tests/fixtures/qworld_farm_topleft.png')[FARM_CROP]
LOBBY_MM = cv2.imread('tests/fixtures/qworld_lobby_topleft.png')[LOBBY_CROP]
FARM_REF = cv2.cvtColor(FARM_MM, cv2.COLOR_BGR2GRAY)
# Tests use the fixture's own lobby crop; the asset is user-replaceable
# ("Save lobby minimap") and is checked separately below.
LOBBY_REF = cv2.cvtColor(LOBBY_MM, cv2.COLOR_BGR2GRAY)


def gray(name):
    return cv2.cvtColor(FRAMES[name], cv2.COLOR_BGR2GRAY)


#################################
#           Detection           #
#################################
def test_classifies_the_real_screens():
    assert qworld.classify(gray('lobby'), LOBBY_REF, FARM_REF)[0] == LOBBY
    assert qworld.classify(gray('farm'), LOBBY_REF, FARM_REF)[0] == FARM
    assert qworld.classify(gray('black'), LOBBY_REF, FARM_REF)[0] == BLACK
    assert qworld.classify(gray('login'), LOBBY_REF, FARM_REF)[0] == UNKNOWN
    # No farm picture yet: a minimap that is not the lobby is "some map".
    assert qworld.classify(gray('farm'), LOBBY_REF, None)[0] == OTHER_MAP


def test_bgra_frames_from_mss_work():
    bgra = cv2.cvtColor(FRAMES['lobby'], cv2.COLOR_BGR2BGRA)
    assert qworld.classify(qworld.to_gray(bgra), LOBBY_REF, FARM_REF)[0] == LOBBY


def test_scores_are_well_separated():
    _, lobby_scores = qworld.classify(gray('lobby'), LOBBY_REF, FARM_REF)
    _, farm_scores = qworld.classify(gray('farm'), LOBBY_REF, FARM_REF)
    assert lobby_scores['lobby'] > 0.95 and lobby_scores['farm'] < 0.5
    assert farm_scores['farm'] > 0.95 and farm_scores['lobby'] < 0.5


def test_saved_lobby_picture_recognises_the_lobby_screenshot():
    """The asset (shipped, or re-saved live from the game) vs the screenshot:
    a live capture with other players elsewhere scored 0.90 here."""
    asset = cv2.imread('assets/qworld_lobby_minimap.png', cv2.IMREAD_GRAYSCALE)
    state, scores = qworld.classify(gray('lobby'), asset, FARM_REF)
    assert state == LOBBY and scores['lobby'] >= 0.85, scores
    state, scores = qworld.classify(gray('farm'), asset, FARM_REF)
    assert state == FARM and scores['lobby'] < 0.5, scores


@pytest.mark.parametrize('seed', range(5))
def test_lobby_still_recognised_with_other_players_moving(seed):
    """Other players' dots come and go on the lobby minimap."""
    rng = np.random.default_rng(seed)
    frame = FRAMES['lobby'].copy()
    top, left = FIXTURE_TOP + 23, 7
    for _ in range(10):
        x = int(rng.integers(left + 5, left + 160))
        y = int(rng.integers(top + 30, top + 58))
        colour = tuple(int(c) for c in rng.integers(0, 256, 3))
        cv2.circle(frame, (x, y), 4, colour, -1)
    state, scores = qworld.classify(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), LOBBY_REF, FARM_REF)
    assert state == LOBBY, scores


def test_black_screen_needs_the_centre_dark_not_just_most_pixels():
    assert qworld.is_black_screen(gray('black'))
    assert not qworld.is_black_screen(gray('farm'))
    dimmed = (FRAMES['farm'] * 0.5).astype(np.uint8)        # e.g. an elite-boss darkening
    assert not qworld.is_black_screen(cv2.cvtColor(dimmed, cv2.COLOR_BGR2GRAY))


#################################
#          Fake world           #
#################################
class FakeSettings:
    def __init__(self, **overrides):
        self.config = dict(qworld.QWorldSettings.DEFAULT_CONFIG)
        self.config.update(overrides)

    def get(self, key):
        return self.config[key]

    def set(self, key, value):
        self.config[key] = value

    def save_config(self):
        pass


KEY_NAMES = {v: k for k, v in vkeys.KEY_MAP.items()}


class FakeWorld:
    """The game behind the keyboard: screens over time, plus a player whose
    minimap position a fake capture thread keeps writing to config.player_pos
    while arrow keys are held (like Capture does from the real minimap).

    Two levels: the floor (LOWER_Y) and a raised platform (UPPER_Y) over
    PLATFORM. Space with Up held climbs onto the platform from below it,
    Space with Down held drops off it, walking off its edge falls. The portal
    only works on its own level (PORTAL_Y)."""

    SPEED = 0.08                    # minimap widths per second while an arrow is held

    def __init__(self, sequence, portal_works=True, can_walk=True,
                 platform=STEP, start_y=LOWER_Y, portal_y=UPPER_Y):
        self.lock = threading.Lock()
        self.x, self.y = SPAWN_X, start_y
        self.platform, self.portal_y = platform, portal_y
        self.held = set()
        self.presses = []           # every key pressed down, by vkeys name
        self.jumps = []             # 'up' / 'down' level changes that happened
        self.entered = False
        self.portal_works = portal_works
        self.can_walk = can_walk
        self.set_sequence(sequence)
        self._stop = threading.Event()
        self._t_last = time.time()
        config.player_pos = (self.x, self.y)
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(1)

    def set_sequence(self, sequence):
        """[(seconds, screen), ..., (None, screen)]: the last screen stays."""
        self.sequence, self.t0 = sequence, time.time()

    def screen(self):
        elapsed = time.time() - self.t0
        for duration, name in self.sequence:
            if duration is None or elapsed < duration:
                return name
            elapsed -= duration
        return self.sequence[-1][1]

    @property
    def frame(self):
        return FRAMES[self.screen()]

    def _capture_loop(self):
        while not self._stop.is_set():
            with self.lock:
                now = time.time()
                if self.can_walk and self.screen() == 'lobby':
                    step = self.SPEED * (now - self._t_last)
                    if 'right' in self.held and 'left' not in self.held:
                        self.x += step
                    elif 'left' in self.held and 'right' not in self.held:
                        self.x -= step
                    if self.y == UPPER_Y and not self._over_platform():
                        self.y = LOWER_Y            # walked off the edge
                self._t_last = now
                if self.screen() == 'lobby':
                    config.player_pos = (self.x, self.y)
            time.sleep(0.005)

    def _over_platform(self):
        return self.platform is not None and self.platform[0] <= self.x <= self.platform[1]

    # pynput Controller stand-in (vkeys.keyboard)
    def press(self, key):
        name = KEY_NAMES.get(key, key)
        with self.lock:
            self.presses.append(name)
            self.held.add(name)
            if name == 'space':
                if 'up' in self.held and self.y == LOWER_Y and self._over_platform():
                    self.y = UPPER_Y
                    self.jumps.append('up')
                elif 'down' in self.held and self.y == UPPER_Y:
                    self.y = LOWER_Y
                    self.jumps.append('down')
            if name == 'up' and self.screen() == 'lobby' and self.portal_works \
                    and abs(self.x - PORTAL_X) <= PORTAL_HALF_WIDTH and self.y == self.portal_y:
                self.entered = True
                self.set_sequence([(0.2, 'black'), (None, 'farm')])

    def release(self, key):
        with self.lock:
            self.held.discard(KEY_NAMES.get(key, key))


class _CaptureProxy:
    """config.capture stand-in whose .frame comes from the fake world."""

    def __init__(self, world, ns):
        object.__setattr__(self, '_world', world)
        object.__setattr__(self, '_ns', ns)

    @property
    def frame(self):
        return self._world.frame

    def __getattr__(self, name):
        return getattr(self._ns, name)

    def __setattr__(self, name, value):
        setattr(self._ns, name, value)


@pytest.fixture
def world_env(monkeypatch):
    msgs, alerts, worlds = [], [], []
    monkeypatch.setattr(config, 'player_pos', (0, 0))

    def make(sequence, parked=True, command_book=None, **world_kwargs):
        world = FakeWorld(sequence, **world_kwargs)
        worlds.append(world)
        capture = SimpleNamespace(calibrated=True, minimap_sample=None, minimap={}, minimap_ratio=1.0)
        monkeypatch.setattr(config, 'capture', _CaptureProxy(world, capture))
        monkeypatch.setattr(config, 'bot', SimpleNamespace(
            rune_active=True, module_name=None, parked=parked, command_book=command_book or {}))
        monkeypatch.setattr(config, 'routine', SimpleNamespace(index=5))
        monkeypatch.setattr(config, 'gui', None)
        monkeypatch.setattr(config, 'enabled', True)        # the bot was farming
        monkeypatch.setattr(vkeys, 'keyboard', world)       # real vkeys, fake keyboard

        notifier = SimpleNamespace(_enqueue_notify=msgs.append,
                                   _alert=lambda name, volume=0.75: alerts.append(name))
        h = QWorldReentry(notifier, settings=FakeSettings(enabled=True))
        h.farm_ref = FARM_REF
        h.POLL_S = 0.01
        h.PAUSE_SETTLE_S = 0
        h.PARK_TIMEOUT_S = 0.3
        h.SCREEN_TIMEOUT_S = 1.0
        h.AFTER_CALIBRATE_S = 0
        h.PORTAL_WAIT_S = 0.3
        h.RESUME_SETTLE_S = 0
        h.LAND_S = 0.05

        def recalibrate():
            name = world.screen()
            config.capture.minimap_sample = {'farm': FARM_MM, 'lobby': LOBBY_MM}.get(name)
            return name in ('farm', 'lobby')
        h._recalibrate = recalibrate
        return h, world

    yield make, msgs, alerts
    for world in worlds:
        world.stop()


#################################
#         State machine         #
#################################
def test_kicked_to_lobby_walks_into_portal_and_resumes(world_env):
    """Regression: the keys must reach the keyboard although the routine is
    paused (vkeys drops key_down/press while config.enabled is False)."""
    make, msgs, alerts = world_env
    h, world = make([(0.3, 'black'), (None, 'lobby')])
    assert h.run('black screen') == RESUMED
    assert 'right' in world.presses, 'must walk towards the portal'
    assert world.jumps == ['up'], 'the portal is on the step above the spawn'
    assert world.entered, 'must press Up inside the portal, on its level'
    assert not world.held, 'no key left held'
    assert config.enabled is True, 'routine resumes in the farm map'
    assert config.routine.index == 0, 'a new run starts the routine over'
    assert config.bot.rune_active is False
    assert h.reentries == 1 and not h.active
    assert not alerts and not msgs


def test_walks_left_when_spawned_past_the_portal(world_env):
    make, msgs, alerts = world_env
    h, world = make([(None, 'lobby')])
    world.x = 0.62
    assert h.run('lobby minimap on screen') == RESUMED
    assert 'left' in world.presses and world.entered and h.reentries == 1


class BookUpJump(Command):
    """A command book's UpJump (erel_light style), through the real vkeys."""
    calls = 0

    def __init__(self, wait: float = 0):
        super().__init__(locals())
        self.wait = float(wait)

    def main(self):
        BookUpJump.calls += 1
        key_down('up')
        press('space', 1, 0.05, 0.05)
        press('space', 1, 0.05, 0.01)
        key_up('up')


def test_uses_the_command_books_upjump(world_env):
    """Same move the book's Adjust makes when the target is above."""
    make, msgs, alerts = world_env
    BookUpJump.calls = 0
    h, world = make([(None, 'lobby')], command_book={'upjump': BookUpJump})
    assert h.run('lobby minimap on screen') == RESUMED
    assert BookUpJump.calls == 1 and world.jumps == ['up'] and world.entered


def test_down_jumps_when_the_portal_is_below(world_env):
    make, msgs, alerts = world_env
    h, world = make([(None, 'lobby')], platform=(0.38, 0.60), start_y=UPPER_Y, portal_y=LOWER_Y)
    h.settings.set('portal y', LOWER_Y)
    assert h.run('lobby minimap on screen') == RESUMED
    assert world.jumps == ['down'] and world.entered


def test_portal_on_the_same_level_needs_no_jump(world_env):
    make, msgs, alerts = world_env
    h, world = make([(None, 'lobby')], platform=None, portal_y=LOWER_Y)
    h.settings.set('portal y', LOWER_Y)
    assert h.run('lobby minimap on screen') == RESUMED
    assert 'space' not in world.presses and world.entered


def test_wrong_portal_y_stops_jumping_and_presses_up_anyway(world_env):
    """A mis-measured 'portal y' must not make it jump forever."""
    make, msgs, alerts = world_env
    h, world = make([(None, 'lobby')], platform=None, portal_y=LOWER_Y)   # settings say 0.246
    h.MAX_LEVEL_CHANGES = 2
    assert h.run('lobby minimap on screen') == RESUMED
    assert world.presses.count('space') == 2 * 2, 'two Up+Jump x2 tries, then just Up'
    assert world.entered


def test_disconnect_never_presses_keys_and_raises_the_alarm(world_env):
    make, msgs, alerts = world_env
    h, world = make([(0.3, 'black'), (None, 'login')])
    assert h.run('black screen') == FAILED
    assert not world.presses, 'no keys unless the lobby was recognised'
    assert alerts == ['siren'] and len(msgs) == 5
    assert config.enabled is False


def test_endless_black_screen_raises_the_alarm(world_env):
    make, msgs, alerts = world_env
    h, world = make([(None, 'black')])
    assert h.run('black screen') == FAILED
    assert not world.presses
    assert alerts == ['siren'] and '黑屏' in msgs[0]
    assert config.enabled is False


def test_false_alarm_resumes_without_moving(world_env):
    make, msgs, alerts = world_env
    h, world = make([(0.2, 'black'), (None, 'farm')])
    assert h.run('black screen') == RESUMED
    assert not world.presses
    assert config.enabled is True
    assert config.routine.index == 5, 'still the same run: keep the routine position'
    assert h.reentries == 0 and not alerts


def test_portal_that_does_not_work_gives_up_with_alarm(world_env):
    make, msgs, alerts = world_env
    h, world = make([(None, 'lobby')], portal_works=False)
    h.MAX_PORTAL_ATTEMPTS = 2
    h.PORTAL_STEPS = 15
    assert h.run('lobby minimap on screen') == FAILED
    assert world.presses.count('up') >= 2
    assert alerts == ['siren'] and config.enabled is False


def test_never_drives_while_the_bot_thread_is_still_running(world_env):
    make, msgs, alerts = world_env
    h, world = make([(None, 'lobby')], parked=False)
    assert h.run('lobby minimap on screen') == FAILED
    assert not world.presses, 'the routine and the walk must never press keys together'
    assert alerts == ['siren'] and config.enabled is False


def test_f8_abort_while_walking_leaves_bot_paused(world_env):
    make, msgs, alerts = world_env
    h, world = make([(None, 'lobby')], can_walk=False)

    def f8():               # what Listener.toggle_enabled does during a re-entry
        h.abort()
        config.enabled = False
    threading.Timer(0.5, f8).start()
    t0 = time.time()
    assert h.run('lobby minimap on screen') == ABORTED
    assert time.time() - t0 < 3, 'abort must be prompt'
    assert config.enabled is False and not world.held
    assert not alerts and not msgs


def test_manual_test_in_farm_map_does_not_start_the_bot(world_env, monkeypatch):
    make, msgs, alerts = world_env
    h, world = make([(None, 'farm')])
    monkeypatch.setattr(config, 'enabled', False)
    assert h.run('manual test', manual=True) == RESUMED
    assert config.enabled is False and not world.presses


def test_move_time_follows_the_nightlord_portal_walk():
    h = QWorldReentry(None, settings=FakeSettings())
    assert h._move_time('left', 0.1) == pytest.approx(0.6)
    assert h._move_time('right', -0.1) == pytest.approx(1.08)
    assert h._move_time('left', 0.001) == pytest.approx(0.03)


#################################
#          Notifier hook        #
#################################
def test_poll_triggers(world_env, monkeypatch):
    make, msgs, alerts = world_env
    h, world = make([(None, 'farm')])
    runs = []
    h.run = lambda reason, manual=False: runs.append(reason)
    monkeypatch.setattr(qworld, 'MAP_CHECK_INTERVAL_S', 0)

    assert not h.poll(gray('farm'))
    assert not h.poll(gray('black')), 'a single black frame is not enough'
    time.sleep(qworld.BLACK_HOLD_S + 0.05)
    assert h.poll(gray('black')) and runs == ['black screen']

    assert h.poll(gray('lobby')) and runs[-1] == 'lobby minimap on screen'

    for _ in range(qworld.FARM_MISS_LIMIT - 1):
        assert not h.poll(gray('login'))
    assert h.poll(gray('login')) and runs[-1] == 'farm minimap missing'

    h.settings.set('enabled', False)
    assert not h.poll(gray('lobby')), 'off means off'


def test_poll_adopts_farm_minimap_when_none_yet(world_env, monkeypatch):
    make, msgs, alerts = world_env
    h, world = make([(None, 'farm')])
    monkeypatch.setattr(qworld, 'MAP_CHECK_INTERVAL_S', 0)
    h.farm_ref = None
    config.capture.minimap_sample = FARM_MM
    assert not h.poll(gray('farm'))
    assert h.farm_ref is not None


def test_on_bot_enabled_remembers_farm_not_lobby(world_env):
    make, msgs, alerts = world_env
    h, world = make([(None, 'farm')])
    h.farm_ref = None
    config.capture.minimap_sample = cv2.cvtColor(LOBBY_MM, cv2.COLOR_BGR2BGRA)
    h.on_bot_enabled()
    assert h.farm_ref is None, 'started in the lobby: the lobby is not the farm map'
    config.capture.minimap_sample = cv2.cvtColor(FARM_MM, cv2.COLOR_BGR2BGRA)
    h.on_bot_enabled()
    assert h.farm_ref is not None and h.farm_ref.shape == FARM_REF.shape


def test_save_lobby_reference(world_env, tmp_path):
    make, msgs, alerts = world_env
    h, world = make([(None, 'lobby')])
    path = tmp_path / 'lobby.png'
    h.settings.set('lobby minimap', str(path))
    config.capture.minimap_sample = cv2.cvtColor(FARM_MM, cv2.COLOR_BGR2BGRA)
    ok, _ = h.save_lobby_reference()
    assert not ok and not path.exists(), 'refuses to save the farm map as the lobby'
    config.capture.minimap_sample = cv2.cvtColor(LOBBY_MM, cv2.COLOR_BGR2BGRA)
    ok, _ = h.save_lobby_reference()
    assert ok and h.lobby_reference().shape == LOBBY_REF.shape


def test_notifier_routes_black_screen_to_qworld_when_enabled(monkeypatch):
    from src.easymaple.modules import notifier
    n = notifier.Notifier.__new__(notifier.Notifier)
    n.room_change_threshold = 0.90
    alerts, polls = [], []
    n._alert = lambda name, volume=0.75: alerts.append(name)
    n._enqueue_notify = lambda msg: None
    n.qworld = SimpleNamespace(active=False, enabled=lambda: True, poll=lambda g: polls.append(1) or True)
    assert n._check_map_change(gray('black')) is True
    assert polls and not alerts, 'Q-World handles it, no white-room siren'

    # A GUI test re-entry is walking (toggle off): its portal black screen
    # must not trip the white-room alarm either.
    polls.clear()
    n.qworld = SimpleNamespace(active=True, enabled=lambda: False, poll=lambda g: polls.append(1) or False)
    assert n._check_map_change(gray('black')) is False
    assert polls and not alerts

    n.qworld = SimpleNamespace(active=False, enabled=lambda: False, poll=lambda g: polls.append(1))
    polls.clear()
    assert n._check_map_change(gray('black')) is True
    assert alerts == ['siren'] and not polls, 'off: original white-room alarm'
    assert n._check_map_change(gray('farm')) is False


def test_f8_during_reentry_aborts_instead_of_starting_the_bot(monkeypatch):
    from src.easymaple.modules import listener
    aborted = []
    monkeypatch.setattr(config, 'lie_detector_session', None, raising=False)
    monkeypatch.setattr(config, 'qworld', SimpleNamespace(active=True, abort=lambda: aborted.append(1)))
    monkeypatch.setattr(config, 'enabled', False)
    monkeypatch.setattr(listener.winsound, 'Beep', lambda *a: None)
    monkeypatch.setattr(listener.time, 'sleep', lambda s: None)
    listener.Listener.toggle_enabled()
    assert aborted and config.enabled is False
