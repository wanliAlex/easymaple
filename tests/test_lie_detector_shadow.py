"""Shadow-mode plumbing: the LieDetectorSession and the listener's takeover
hotkey (no keyboard needed — the static handlers are called directly)."""
import pytest

from src.easymaple.common import config
from src.easymaple.modules.lie_detector_player import LieDetectorSession, shadow_stats


class Settings:
    def __init__(self, shadow):
        self.cfg = {'shadow': shadow}

    def get(self, key):
        return self.cfg[key]


def test_session_takeover_by_hotkey_is_one_shot():
    s = LieDetectorSession(shadow=True, settings=Settings(True))
    assert not s.takeover_requested()
    assert s.request_takeover() is True       # first press hands over (caller beeps)
    assert s.request_takeover() is False      # repeats are no-ops
    assert s.takeover_requested()


def test_session_takeover_by_unticking_shadow_mid_game():
    settings = Settings(True)
    s = LieDetectorSession(shadow=True, settings=settings)
    assert not s.takeover_requested()
    settings.cfg['shadow'] = False            # user unticks "Shadow" in Settings
    assert s.takeover_requested()


def test_hotkey_outside_shadow_mode_does_not_report_a_takeover():
    s = LieDetectorSession(shadow=False)
    assert s.request_takeover() is False


def test_shadow_stats_compares_only_shadowed_tracking_frames():
    trace = {"state": ["ACQUIRE", "TRACK", "TRACK", "TRACK", "TRACK"],
             "bot": [(0, 0), (0, 0), (100, 0), (0, 0), (0, 0)],
             "user": [(500, 0), (10, 0), (0, 0), (5, 5), None],
             "driving": [False, False, False, False, True]}
    st = shadow_stats(trace)
    assert st["shadow_frames"] == 3 and abs(st["shadow_agreement"] - 2 / 3) < 1e-3


listener_mod = pytest.importorskip("src.easymaple.modules.listener")


class FakeNotifier:
    def __init__(self):
        self.stopped = 0

    def stop_alerts(self):
        self.stopped += 1


def test_listener_takeover_hotkey_signals_the_live_session_and_silences(monkeypatch):
    fake = FakeNotifier()
    monkeypatch.setattr(config, 'notifier', fake, raising=False)
    monkeypatch.setattr(config, 'lie_detector_session', None, raising=False)
    assert listener_mod.Listener.lie_detector_takeover() is False   # no game: no-op
    s = LieDetectorSession(shadow=True)
    monkeypatch.setattr(config, 'lie_detector_session', s, raising=False)
    assert listener_mod.Listener.lie_detector_takeover() is True
    assert s.takeover_requested()
    assert fake.stopped == 1, "taking over also silences the siren"


def test_f8_during_a_lie_detector_silences_siren_but_never_resumes(monkeypatch):
    fake = FakeNotifier()
    monkeypatch.setattr(config, 'notifier', fake, raising=False)
    monkeypatch.setattr(config, 'lie_detector_session', LieDetectorSession(shadow=True), raising=False)
    monkeypatch.setattr(config, 'enabled', False)
    monkeypatch.setattr(listener_mod.time, 'sleep', lambda s: None)
    listener_mod.Listener.toggle_enabled()
    assert config.enabled is False
    assert fake.stopped == 1


def test_success_banner_detector():
    import cv2
    import numpy as np
    from src.easymaple.modules.lie_detector_player import _success_banner
    box = (100, 100, 700, 440)
    frame = np.full((800, 1000, 3), (110, 170, 200), np.uint8)      # tan play-box
    assert not _success_banner(frame, box)
    cv2.putText(frame, "SUCCESS!", (220, 360), cv2.FONT_HERSHEY_SIMPLEX, 3.2,
                (60, 230, 255), 18)                                  # yellow (BGR)
    assert _success_banner(frame, box)
    assert not _success_banner(frame, None)
