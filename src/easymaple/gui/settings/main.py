"""Displays Auto Maple's current settings and allows the user to edit them."""

import tkinter as tk
from src.easymaple.gui.settings.keybindings import KeyBindings
from src.easymaple.gui.settings.pets import Pets
from src.easymaple.gui.settings.rune import Rune
from src.easymaple.gui.interfaces import Tab, Frame
from src.easymaple.common import config


class Settings(Tab):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, 'Settings', **kwargs)

        self.columnconfigure(0, weight=1)
        self.columnconfigure(3, weight=1)

        column1 = Frame(self)
        column1.grid(row=0, column=1, sticky=tk.N, padx=10, pady=10)
        self.controls = KeyBindings(column1, 'Auto Maple Controls', config.listener)
        self.controls.pack(side=tk.TOP, fill='x', expand=True)

        self.rune = Rune(column1)
        self.rune.pack(side=tk.TOP, fill='x', expand=True, pady=(10, 0))

        column2 = Frame(self)
        column2.grid(row=0, column=2, sticky=tk.N, padx=10, pady=10)
        self.key_bindings = KeyBindings(column2, 'In-game Keybindings', config.bot)
        self.key_bindings.pack(side=tk.TOP, fill='x', expand=True)
        self.pets = Pets(column2)
        self.pets.pack(side=tk.TOP, fill='x', expand=True, pady=(10, 0))
