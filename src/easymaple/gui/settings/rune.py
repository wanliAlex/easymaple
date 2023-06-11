import tkinter as tk
from src.easymaple.gui.interfaces import LabelFrame, Frame
from src.easymaple.common.interfaces import Configurable


class Rune(LabelFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, 'Rune', **kwargs)

        self.rune_settings = RuneSettings('rune')
        self.solve_rune = tk.BooleanVar(value=self.rune_settings.get('solve rune'))

        feed_row = Frame(self)
        feed_row.pack(side=tk.TOP, fill='x', expand=True, pady=5, padx=5)
        check = tk.Checkbutton(
            feed_row,
            variable=self.solve_rune,
            text='Solve Rune',
            command=self._on_change
        )
        check.pack()

        num_row = Frame(self)
        num_row.pack(side=tk.TOP, fill='x', expand=True, pady=(0, 5), padx=5)

    def _on_change(self):
        self.rune_settings.set('solve rune', self.solve_rune.get())
        self.rune_settings.save_config()


class RuneSettings(Configurable):
    DEFAULT_CONFIG = {
        'solve rune' : False
    }

    def get(self, key):
        return self.config[key]

    def set(self, key, value):
        assert key in self.config
        self.config[key] = value
