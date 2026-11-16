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
    def __init__(self, auto, shadow=False):
        self._cfg = {'auto solve': auto, 'shadow': shadow}

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
