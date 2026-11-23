"""Tests for the notifier's Lie Detector handling policy.

The routing contract (user-specified):
* solver ENABLED  -> pause the bot, auto-solve, resume on success; on failure
  stay paused with a single non-blocking ping. Discord hears about a game only
  when it was not passed: a solved game (or a false alarm) is reported on the
  console, never pinged.
* solver DISABLED -> five Discord messages + the blocking `_alert` siren, like
  the white-room safeguard (mainline behavior).
* Either way a training clip is recorded. The blocking `_alert` siren loop is
  only used on the disabled path, never by the auto-solver.
"""
import pytest

from src.easymaple.common import config
from src.easymaple.modules import notifier


class FakeSettings:
    def __init__(self, auto, shadow=False, iframe=False):
        self._cfg = {'auto solve': auto, 'shadow': shadow, 'iframe': iframe}

    def get(self, key):
        return self._cfg[key]


class FakePlayer:
    result = {"outcome": "completed", "frames_moved": 500, "reached_track": True}
    last_kwargs = None
    session_seen = None

    def __init__(self, *a, **k):
        FakePlayer.last_kwargs = k

    def solve(self, *a, **k):
        FakePlayer.session_seen = config.lie_detector_session
        FakePlayer.fast_seen = config.capture_fast
        if isinstance(FakePlayer.result, Exception):
            raise FakePlayer.result
        return FakePlayer.result


traces, sirens, stops = [], [], []


@pytest.fixture
def env(monkeypatch):
    msgs, pings, alerts, clips = [], [], [], []
    for lst in (traces, sirens, stops):
        lst.clear()
    n = notifier.Notifier.__new__(notifier.Notifier)
    n._enqueue_notify = msgs.append
    n._ping = lambda name, volume=0.5: pings.append(name)
    n._alert = lambda name, volume=0.75: alerts.append(name)
    n._siren_on = lambda volume=0.75: sirens.append(1)
    n.stop_alerts = lambda: stops.append(1)
    monkeypatch.setattr(notifier.recorder, 'record_clip', lambda: clips.append(1))
    monkeypatch.setattr(notifier, 'LieDetectorPlayer', FakePlayer)
    monkeypatch.setattr(notifier, 'save_trace', lambda result: traces.append(result))
    monkeypatch.setattr(notifier, '_background', lambda fn, *args: fn(*args))
    monkeypatch.setattr(notifier, 'motion_solver', lambda retry=False: object())
    monkeypatch.setattr(config, 'enabled', True)
    monkeypatch.setattr(config, 'lie_detector_session', None, raising=False)
    monkeypatch.setattr(config, 'capture_fast', False, raising=False)
    monkeypatch.setattr(notifier, 'remember_box', lambda box: None)
    n._lie_detector_notice_at = None
    return n, msgs, pings, alerts, clips


def test_disabled_solver_five_pings_and_siren_bot_paused(env, monkeypatch):
    n, msgs, pings, alerts, clips = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(False), raising=False)
    n._handle_lie_detector("进行中")
    assert len(msgs) == 5, "five Discord messages when solver is off (mainline behavior)"
    assert alerts == ['siren'], "the blocking siren must fire when solver is off"
    assert not pings, "the non-blocking ping belongs to the auto-solve path only"
    assert config.enabled is False, "bot must not keep playing through the test"
    assert clips, "training clip must still be recorded"


def test_no_settings_panel_yet_behaves_as_disabled(env, monkeypatch):
    n, msgs, pings, alerts, _ = env
    monkeypatch.setattr(config, 'lie_detector', None, raising=False)
    n._handle_lie_detector("准备阶段")
    assert len(msgs) == 5 and alerts == ['siren'] and config.enabled is False


def test_enabled_solver_success_resumes_bot(env, monkeypatch):
    n, msgs, pings, alerts, clips = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    FakePlayer.result = {"outcome": "completed", "frames_moved": 500,
                         "reached_track": True}
    n._handle_lie_detector("准备阶段")
    assert config.enabled is True, "bot resumes after a solved game"
    assert msgs == [], "a passed game sends nothing to Discord"
    assert not pings
    assert not alerts, "the blocking siren loop must never fire on the auto-solve path"
    assert clips


def test_enabled_solver_failure_stays_paused_with_single_ping(env, monkeypatch):
    n, msgs, pings, alerts, _ = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    FakePlayer.result = {"outcome": "timeout", "frames_moved": 30,
                         "reached_track": False}
    n._handle_lie_detector("进行中")
    assert config.enabled is False, "unsure outcome -> keep the bot paused"
    assert pings == ['siren'], "one non-blocking ping, not the blocking loop"
    assert not alerts
    assert len(msgs) == 1, "only the result: no 'solving...' message up front"


def test_enabled_solver_jail_failure_stays_paused(env, monkeypatch):
    """outcome='failed' = the near-black punishment room was detected after
    the game: definitely lost. The bot must NOT resume (it would farm inside
    the jail) and the user is pinged once."""
    n, msgs, pings, alerts, _ = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    FakePlayer.result = {"outcome": "failed", "frames_moved": 400,
                         "reached_track": True}
    n._handle_lie_detector("进行中")
    assert config.enabled is False
    assert pings == ['siren']
    assert not alerts
    assert len(msgs) == 1 and "未通过" in msgs[0]


def test_enabled_solver_false_positive_resumes_quietly(env, monkeypatch):
    n, msgs, pings, alerts, _ = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    FakePlayer.result = {"outcome": "no_box", "frames_moved": 0,
                         "reached_track": False}
    n._handle_lie_detector("准备阶段")
    assert config.enabled is True, "no game ever appeared -> resume"
    assert not pings and not alerts
    assert msgs == [], "a false alarm is not a failed test"


def test_enabled_solver_crash_stays_paused(env, monkeypatch):
    n, msgs, pings, alerts, _ = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    FakePlayer.result = RuntimeError("boom")
    n._handle_lie_detector("进行中")
    FakePlayer.result = {"outcome": "completed", "frames_moved": 500,
                         "reached_track": True}
    assert config.enabled is False
    # The game may still be running: loud (five pings + looping siren) but
    # non-blocking, like shadow mode.
    assert sum("接管" in m for m in msgs) == 5
    assert sirens == [1]
    assert not alerts


# --- Shadow mode: the human plays, the solver follows and takes over on request ---
def test_shadow_mode_runs_player_in_shadow_with_a_live_session(env, monkeypatch, capsys):
    n, msgs, pings, alerts, clips = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True, shadow=True), raising=False)
    FakePlayer.result = {"outcome": "completed", "frames_moved": 0, "reached_track": True,
                         "took_over": False, "takeover_frame": None,
                         "shadow_agreement": 0.9, "shadow_end_agreement": 1.0, "shadow_frames": 250}
    n._handle_lie_detector("准备阶段")
    assert FakePlayer.last_kwargs["shadow"] is True
    session = FakePlayer.session_seen
    assert session is not None and session.shadow, "the takeover hotkey needs a live session"
    assert FakePlayer.last_kwargs["takeover"] == session.takeover_requested
    assert config.lie_detector_session is None, "session cleared after the game"
    assert len(msgs) == 5, "five pings like manual mode; a pass adds nothing"
    assert sirens == [1], "looping siren like manual mode..."
    assert not alerts, "...but never the blocking _alert loop (F9 must stay live)"
    assert stops == [1], "siren silenced when the game ends"
    assert not pings
    assert "90%" in capsys.readouterr().out, "console report: the solver agreed 90% with you"
    assert config.enabled is True, "a passed game resumes the routine"
    assert traces and clips, "shadow log saved and clip recorded"


def test_shadow_takeover_failure_keeps_bot_paused(env, monkeypatch):
    n, msgs, pings, alerts, _ = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True, shadow=True), raising=False)
    FakePlayer.result = {"outcome": "failed", "frames_moved": 120, "reached_track": True,
                         "took_over": True, "takeover_frame": 300,
                         "shadow_agreement": 0.8, "shadow_end_agreement": 0.5, "shadow_frames": 60}
    n._handle_lie_detector("进行中")
    assert config.enabled is False
    assert sirens == [1] and stops == [1]
    assert pings == ['siren'], "failure ping after the game"
    assert "接管" in msgs[-1]


def test_auto_mode_unchanged_by_shadow_support(env, monkeypatch):
    n, msgs, pings, alerts, _ = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True, shadow=False), raising=False)
    FakePlayer.result = {"outcome": "completed", "frames_moved": 500, "reached_track": True}
    n._handle_lie_detector("进行中")
    assert FakePlayer.last_kwargs["shadow"] is False
    assert not pings and not sirens
    assert traces, "every game logs its solver trace (post-mortems)"
    assert config.enabled is True


def test_shadow_human_pass_seen_by_banner_resumes_even_if_solver_never_tracked(env, monkeypatch, capsys):
    """In shadow mode the human can pass a game the solver never locked onto;
    the SUCCESS banner is proof enough to resume the routine."""
    n, msgs, pings, alerts, _ = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True, shadow=True), raising=False)
    FakePlayer.result = {"outcome": "completed", "frames_moved": 0, "reached_track": False,
                         "success_seen": True, "took_over": False, "takeover_frame": None,
                         "shadow_agreement": None, "shadow_end_agreement": None, "shadow_frames": 0}
    n._handle_lie_detector("进行中")
    assert config.enabled is True
    assert "SUCCESS" in capsys.readouterr().out
    assert len(msgs) == 5, "only the shadow-mode pings"



def test_fast_capture_and_prepositioning_during_the_game(env, monkeypatch):
    n, msgs, pings, alerts, _ = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    monkeypatch.setattr(notifier, 'expected_box', lambda: (1, 2, 3, 4))
    FakePlayer.result = {"outcome": "completed", "frames_moved": 500, "reached_track": True}
    n._handle_lie_detector("准备阶段")
    assert FakePlayer.fast_seen is True, "capture runs fast while the game is handled"
    assert config.capture_fast is False, "and back to normal afterwards"
    assert FakePlayer.last_kwargs["expected_box"] == (1, 2, 3, 4)


# --- The bottom-right prep notice: farm on, handle the game when it starts ---
@pytest.fixture
def screens(env, monkeypatch):
    """_check_lie_detector on labelled 'frames': 'notice' (the prep notice),
    'game' (the 'in progress' banner under the game window) or 'farm'.
    Returns (check, handled phases, clock)."""
    n = env[0]
    handled = []
    monkeypatch.setattr(n, '_handle_lie_detector', handled.append, raising=False)
    clock = [1000.0]
    monkeypatch.setattr(notifier.time, 'time', lambda: clock[0])

    def score(frame, template):
        if template is notifier.LIE_DETECTOR_PROGRESS_TEMPLATE:
            return 0.99 if frame == 'game' else 0.2
        return 0.99 if frame == 'notice' else 0.2
    monkeypatch.setattr(notifier.utils, 'match_score', score)

    def check(frame, dt=0.1):
        clock[0] += dt
        return n._check_lie_detector(frame)
    return check, handled, clock


def test_bot_keeps_farming_through_the_notice(screens, monkeypatch, capsys):
    """Regression (2026-11-23): handling the notice froze the player position
    (fast capture skips player matching) and the character walked off its
    route for ~10 s. The notice alone must not touch the bot at all."""
    check, handled, _ = screens
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    assert [check('notice') for _ in range(30)] == ['notice'] * 30
    assert handled == []
    assert config.enabled is True and config.capture_fast is False
    assert config.lie_detector_session is None
    assert capsys.readouterr().out.count('继续挂机') == 1, "one console line, not one per check"


def test_game_banner_after_the_notice_runs_the_game(screens, monkeypatch):
    check, handled, _ = screens
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    assert [check(f) for f in ['notice'] * 5 + ['game']] == ['notice'] * 5 + ['game']
    assert handled == ['进行中']


def test_notice_vanishing_runs_the_game(screens, monkeypatch):
    """The notice vanishes as the game window opens (all 30 live clips):
    the safety net if the banner is not matched on that frame."""
    check, handled, _ = screens
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    check('notice'); check('notice')
    assert check('farm') == 'game' and handled == ['开始']


def test_a_stale_notice_does_not_start_a_game(screens, monkeypatch):
    """Notice seen, then the bot was stopped (no checks) for a while."""
    check, handled, _ = screens
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    check('notice')
    assert check('farm', dt=30) is None and handled == []
    assert check('farm') is None and handled == []


def test_game_without_a_notice_is_still_handled(screens, monkeypatch):
    check, handled, _ = screens
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    assert check('game') == 'game' and handled == ['进行中']
    assert check('farm') is None


@pytest.mark.parametrize('settings', [FakeSettings(False), FakeSettings(True, shadow=True), None],
                         ids=['manual', 'shadow', 'no settings panel'])
def test_humans_are_alerted_at_the_notice(screens, monkeypatch, settings):
    """Somebody has to play: the ~10 s notice is their head start."""
    check, handled, _ = screens
    monkeypatch.setattr(config, 'lie_detector', settings, raising=False)
    assert check('notice') == 'game' and handled == ['准备阶段']


def test_no_solver_alerts_at_the_notice(screens, monkeypatch):
    check, handled, _ = screens
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    monkeypatch.setattr(notifier, 'motion_solver', lambda retry=False: None)
    assert check('notice') == 'game' and handled == ['准备阶段']


def test_motion_solver_unavailable_hands_over_like_manual(env, monkeypatch):
    """Never auto-solve with the old solver: five pings + the siren instead."""
    n, msgs, pings, alerts, _ = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    monkeypatch.setattr(notifier, 'motion_solver', lambda retry=False: None)
    FakePlayer.last_kwargs = None
    n._handle_lie_detector("准备阶段")
    assert FakePlayer.last_kwargs is None, "the player must not run"
    assert len(msgs) == 5 and alerts == ['siren'] and config.enabled is False


def test_box_only_remembered_from_a_played_game(env, monkeypatch):
    n, *_ = env
    boxes = []
    monkeypatch.setattr(notifier, 'remember_box', boxes.append)
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    FakePlayer.result = {"outcome": "timeout", "frames_moved": 5, "reached_track": False, "box": (1, 2, 3, 4)}
    n._handle_lie_detector("准备阶段")
    assert boxes == []
    FakePlayer.result = {"outcome": "completed", "frames_moved": 500, "reached_track": True, "box": (5, 6, 7, 8)}
    n._handle_lie_detector("准备阶段")
    assert boxes == [(5, 6, 7, 8)]


# --- i-frame guard (opt-in): the command book's LieDetectorGuard while solving ---
import threading
import time
from types import SimpleNamespace

from src.easymaple.common import vkeys


class RecordingKeyboard:
    """pynput Controller stand-in under the REAL vkeys functions: records
    every key that actually got through vkeys' enabled-gate."""

    def __init__(self):
        self.events = []        # (key name, config.enabled at the time)
        self._names = {v: k for k, v in vkeys.KEY_MAP.items()}

    def press(self, key):
        self.events.append((self._names.get(key, key), config.enabled))

    def release(self, key):
        pass


def _join_guard(timeout=5):
    for t in threading.enumerate():
        if t.name == 'lie-detector-guard':
            t.join(timeout)


class SlowPlayer(FakePlayer):
    """A solve that lasts until the guard has finished (a real game takes
    ~20-40 s, the guard 1.8 s)."""

    def solve(self, *a, **k):
        _join_guard()
        return super().solve(*a, **k)


@pytest.fixture
def guard_env(env, monkeypatch):
    from resources.command_books import erel_light
    keyboard = RecordingKeyboard()
    monkeypatch.setattr(vkeys, 'keyboard', keyboard)
    monkeypatch.setattr(notifier, 'LieDetectorPlayer', SlowPlayer)
    monkeypatch.setattr(config, 'bot', SimpleNamespace(
        module_name='erel_light',
        command_book={'liedetectorguard': erel_light.LieDetectorGuard}), raising=False)
    FakePlayer.result = {"outcome": "completed", "frames_moved": 500, "reached_track": True}
    return env, keyboard


def test_iframe_guard_presses_del_three_times_while_the_bot_is_paused(guard_env, monkeypatch):
    """Regression for the vkeys gate: the bot is paused during the game, and
    vkeys drops keys while config.enabled is False - the guard must still
    get through (and the routine must not)."""
    (n, msgs, pings, alerts, _), keyboard = guard_env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True, iframe=True), raising=False)
    t0 = time.time()
    n._handle_lie_detector("准备阶段")
    assert keyboard.events == [('delete', False)] * 3, "erel_light: Del x3, sent while paused"
    assert time.time() - t0 >= 3 * 0.6 - 0.1, "0.1 s down + 0.5 s up per press"
    assert config.enabled is True and not msgs and not alerts, "solve flow unchanged"


def test_iframe_cast_when_the_game_window_opens_not_at_the_notice(guard_env, monkeypatch):
    (n, *_), keyboard = guard_env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True, iframe=True), raising=False)
    monkeypatch.setattr(notifier.utils, 'match_score', lambda frame, template: 0.99 if (
        (frame == 'game') == (template is notifier.LIE_DETECTOR_PROGRESS_TEMPLATE)) else 0.2)
    for _ in range(5):
        assert n._check_lie_detector('notice') == 'notice'
    _join_guard()                       # a guard started at the notice would be done now
    assert keyboard.events == [], "no i-frame during the notice (the bot is still farming)"
    assert n._check_lie_detector('game') == 'game'
    assert keyboard.events == [('delete', False)] * 3, "cast once the game started, bot paused"


def test_iframe_guard_shadow_mode_too(guard_env, monkeypatch):
    (n, *_), keyboard = guard_env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True, shadow=True, iframe=True), raising=False)
    n._handle_lie_detector("准备阶段")
    assert [k for k, _ in keyboard.events] == ['delete'] * 3


def test_iframe_guard_is_opt_in(guard_env, monkeypatch):
    (n, *_), keyboard = guard_env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True, iframe=False), raising=False)
    n._handle_lie_detector("准备阶段")
    _join_guard()
    assert keyboard.events == []


def test_iframe_guard_not_used_when_a_human_takes_over(guard_env, monkeypatch):
    """Auto-solve off: the bot isn't solving, it hands over (siren)."""
    (n, msgs, pings, alerts, _), keyboard = guard_env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(False, iframe=True), raising=False)
    n._handle_lie_detector("准备阶段")
    _join_guard()
    assert keyboard.events == [] and alerts == ['siren']


def test_iframe_guard_skipped_when_the_book_has_none(guard_env, monkeypatch, capsys):
    (n, msgs, pings, alerts, _), keyboard = guard_env
    monkeypatch.setattr(config, 'bot', SimpleNamespace(module_name='hero', command_book={}), raising=False)
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True, iframe=True), raising=False)
    n._handle_lie_detector("准备阶段")
    assert keyboard.events == []
    assert 'LieDetectorGuard' in capsys.readouterr().out
    assert config.enabled is True, "the game is still solved"


def test_allow_keys_is_per_thread_and_only_while_inside(monkeypatch):
    keyboard = RecordingKeyboard()
    monkeypatch.setattr(vkeys, 'keyboard', keyboard)
    monkeypatch.setattr(config, 'enabled', False)
    vkeys.key_down('left')
    assert keyboard.events == [], 'paused: dropped as before'

    other = []
    inside = threading.Event()
    done = threading.Event()

    def routine_thread():
        inside.wait(2)
        vkeys.key_down('right')         # another thread while the guard is allowed
        other.append(1)
        done.set()

    threading.Thread(target=routine_thread, daemon=True).start()
    with vkeys.allow_keys():
        with vkeys.allow_keys():        # nesting is fine
            vkeys.press('delete', 1, 0, 0)
        inside.set()
        done.wait(2)
        vkeys.key_down('up')
    vkeys.key_down('down')
    assert other == [1]
    assert [k for k, _ in keyboard.events] == ['delete', 'up'], \
        "only this thread, only inside allow_keys()"
