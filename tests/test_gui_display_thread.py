"""The minimap display thread calls Tk from outside the main thread, which raises
if the main loop isn't running within ~1s. A raise kills the thread for good and
the minimap stays black, so a slow start-up must not reach it."""
import threading
import time
import tkinter as tk
from types import SimpleNamespace

from src.easymaple.common import cache
from src.easymaple.modules.gui import GUI


class FirstTkCall:
    """Stands in for the Minimap: one Tk call from the display thread, like the
    PhotoImage in display_minimap, then idles."""

    def __init__(self, root):
        self.root = root
        self.error = None
        self.finished = threading.Event()

    def display_minimap(self):
        if self.finished.is_set():
            return
        try:
            self.root.tk.call('info', 'patchlevel')
        except RuntimeError as e:
            self.error = e
        self.finished.set()


def test_display_thread_survives_a_late_main_loop(monkeypatch):
    monkeypatch.setattr(cache, 'auto_load_last_files', lambda: None)
    root = tk.Tk()
    root.withdraw()
    minimap = FirstTkCall(root)

    gui = GUI.__new__(GUI)
    gui.root = root
    gui.view = SimpleNamespace(minimap=minimap)
    gui._refresh_status_bar = lambda: None

    real_mainloop = root.mainloop

    def late_mainloop():
        time.sleep(1.5)     # Longer than tkinter waits for the main loop
        root.after(500, root.quit)
        real_mainloop()

    root.mainloop = late_mainloop
    gui.start()
    root.destroy()

    assert minimap.finished.is_set(), "the display thread never ran"
    assert minimap.error is None
