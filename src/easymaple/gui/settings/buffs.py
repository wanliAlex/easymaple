import tkinter as tk
from src.easymaple.gui.interfaces import LabelFrame, Frame
from src.easymaple.common.interfaces import Configurable


class Buffs(LabelFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, 'Buffs', **kwargs)

        self.buff_settings = BuffSettings('buffs')
        self.auto_buff = tk.BooleanVar(value=self.buff_settings.get('Auto-buff'))

        row = Frame(self)
        row.pack(side=tk.TOP, fill='x', expand=True, pady=5, padx=5)
        check = tk.Checkbutton(
            row,
            variable=self.auto_buff,
            text='Auto-buff',
            command=self._on_change
        )
        check.pack()

    def _on_change(self):
        self.buff_settings.set('Auto-buff', self.auto_buff.get())
        self.buff_settings.save_config()


class BuffSettings(Configurable):
    DEFAULT_CONFIG = {
        'Auto-buff': True
    }

    def get(self, key):
        return self.config[key]

    def set(self, key, value):
        assert key in self.config
        self.config[key] = value
