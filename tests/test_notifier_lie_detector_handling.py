"""Tests for the notifier's Lie Detector handling policy.

The routing contract (user-specified):
* solver ENABLED  -> pause the bot, auto-solve, resume on success; on failure
  stay paused with a single non-blocking ping.
* solver DISABLED -> five Discord messages + the blocking `_alert` siren, like
  the white-room safeguard (mainline behavior).
* Either way a training clip is recorded. The blocking `_alert` siren loop is
  only used on the disabled path, never by the auto-solver.
"""
import pytest

from src.easymaple.common import config
from src.easymaple.modules import notifier


class FakeSettings:
    def __init__(self, auto):
        self._auto = auto

    def get(self, key):
        assert key == 'auto solve'
        return self._auto


class FakePlayer:
    result = {"outcome": "completed", "frames_moved": 500, "reached_track": True}

    def __init__(self, *a, **k):
        pass

    def solve(self, *a, **k):
        if isinstance(FakePlayer.result, Exception):
            raise FakePlayer.result
        return FakePlayer.result


@pytest.fixture
def env(monkeypatch):
    msgs, pings, alerts, clips = [], [], [], []
    n = notifier.Notifier.__new__(notifier.Notifier)
    n._enqueue_notify = msgs.append
    n._ping = lambda name, volume=0.5: pings.append(name)
    n._alert = lambda name, volume=0.75: alerts.append(name)
    monkeypatch.setattr(notifier.recorder, 'record_clip', lambda: clips.append(1))
    monkeypatch.setattr(notifier, 'LieDetectorPlayer', FakePlayer)
    monkeypatch.setattr(config, 'enabled', True)
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
    assert len(msgs) == 2, "detected + solved messages"
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
    assert len(msgs) == 2


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
    assert len(msgs) == 2


def test_enabled_solver_false_positive_resumes_quietly(env, monkeypatch):
    n, msgs, pings, alerts, _ = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    FakePlayer.result = {"outcome": "no_box", "frames_moved": 0,
                         "reached_track": False}
    n._handle_lie_detector("准备阶段")
    assert config.enabled is True, "no game ever appeared -> resume"
    assert not pings and not alerts


def test_enabled_solver_crash_stays_paused(env, monkeypatch):
    n, msgs, pings, alerts, _ = env
    monkeypatch.setattr(config, 'lie_detector', FakeSettings(True), raising=False)
    FakePlayer.result = RuntimeError("boom")
    n._handle_lie_detector("进行中")
    FakePlayer.result = {"outcome": "completed", "frames_moved": 500,
                         "reached_track": True}
    assert config.enabled is False
    assert pings == ['siren']
    assert not alerts
