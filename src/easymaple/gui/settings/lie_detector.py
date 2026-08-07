import tkinter as tk
from src.easymaple.gui.interfaces import LabelFrame, Frame
from src.easymaple.common.interfaces import Configurable
from src.easymaple.common import config


class LieDetector(LabelFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, 'Lie Detector', **kwargs)

        self.settings = LieDetectorSettings('lie_detector')
        config.lie_detector = self.settings
        self.auto_solve = tk.BooleanVar(value=self.settings.get('auto solve'))

        row = Frame(self)
        row.pack(side=tk.TOP, fill='x', expand=True, pady=5, padx=5)
        check = tk.Checkbutton(
            row,
            variable=self.auto_solve,
            text='Auto-solve Lie Detector',
            command=self._on_change
        )
        check.pack()
        hint = tk.Label(
            row,
            text='Off: siren + Discord pings, bot pauses for manual takeover',
            fg='gray'
        )
        hint.pack()

    def _on_change(self):
        self.settings.set('auto solve', self.auto_solve.get())
        self.settings.save_config()


class LieDetectorSettings(Configurable):
    DEFAULT_CONFIG = {
        'auto solve': True
    }

    def get(self, key):
        return self.config[key]

    def set(self, key, value):
        assert key in self.config
        self.config[key] = value
