"""A menu for loading routines and command books."""

import tkinter as tk
from easymaple.gui.menu.file import File
from easymaple.gui.menu.update import Update


class Menu(tk.Menu):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        self.file = File(self, tearoff=0)
        self.update = Update(self, tearoff=0)
