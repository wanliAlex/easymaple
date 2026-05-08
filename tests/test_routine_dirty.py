"""Tests that Routine.dirty triggers GUI.update_title via property setter."""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.easymaple.common import config


class FakeGUI:
    def __init__(self):
        self.title_calls = 0

    def update_title(self):
        self.title_calls += 1


def test_dirty_setter_pings_gui_only_on_change():
    from src.easymaple.routine.routine import Routine
    fake = FakeGUI()
    config.gui = fake

    r = Routine()
    # Initial state was set in __init__ — count is whatever happened then
    baseline = fake.title_calls

    r.dirty = True
    assert fake.title_calls == baseline + 1, "True after False should ping"

    r.dirty = True
    assert fake.title_calls == baseline + 1, "True after True should NOT ping again"

    r.dirty = False
    assert fake.title_calls == baseline + 2, "False after True should ping"


def test_dirty_setter_safe_when_gui_unset():
    from src.easymaple.routine.routine import Routine
    config.gui = None
    r = Routine()
    r.dirty = True  # must not raise
    assert r.dirty is True
