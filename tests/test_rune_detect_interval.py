"""Tests for the rune-detect interval setting and its poll-count resolver."""
from src.easymaple.common import config
from src.easymaple.modules import notifier


class _FakeAdvanced:
    def __init__(self, interval):
        self._interval = interval

    def get(self, key):
        assert key == 'rune_detect_interval_seconds'
        return self._interval


def test_falls_back_to_constant_when_advanced_missing(monkeypatch):
    """Early startup / tests don't have an Advanced panel — must keep working."""
    monkeypatch.setattr(config, 'advanced', None, raising=False)
    assert notifier.rune_detect_poll_count() == notifier.RUNE_DETECT_FREQUENCY


def test_default_interval_matches_legacy_frequency(monkeypatch):
    """Default of 2.0s must produce the same poll count as the old constant
    (40 polls × 0.05s) — i.e. zero behavior change for users who don't tune."""
    monkeypatch.setattr(config, 'advanced', _FakeAdvanced(2.0), raising=False)
    assert notifier.rune_detect_poll_count() == notifier.RUNE_DETECT_FREQUENCY


def test_converts_seconds_to_polls(monkeypatch):
    monkeypatch.setattr(config, 'advanced', _FakeAdvanced(0.5), raising=False)
    assert notifier.rune_detect_poll_count() == 10
    monkeypatch.setattr(config, 'advanced', _FakeAdvanced(5.0), raising=False)
    assert notifier.rune_detect_poll_count() == 100


def test_clamps_below_one_poll(monkeypatch):
    """A 0s interval would be a divide-by-zero waiting to happen if anyone
    routed it through the loop — must stay at minimum 1 poll."""
    monkeypatch.setattr(config, 'advanced', _FakeAdvanced(0.0), raising=False)
    assert notifier.rune_detect_poll_count() == 1
