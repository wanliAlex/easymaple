"""Interfaces that are used by various GUI pages."""

import tkinter as tk
from tkinter import ttk
from src.easymaple.gui.style import BG, SURFACE, SURFACE2, TEXT, TEXT_DIM, ACCENT, FONT


class Frame(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.parent = parent


class LabelFrame(ttk.LabelFrame):
    def __init__(self, parent, name, **kwargs):
        kwargs['text'] = name
        kwargs['labelanchor'] = tk.N
        super().__init__(parent, **kwargs)
        self.parent = parent


class Tab(Frame):
    def __init__(self, parent, name, **kwargs):
        kwargs.setdefault('background', BG)
        super().__init__(parent, **kwargs)
        parent.add(self, text=name)


class MenuBarItem(tk.Menu):
    def __init__(self, parent, label, **kwargs):
        kwargs.setdefault('background', SURFACE2)
        kwargs.setdefault('foreground', TEXT)
        kwargs.setdefault('activebackground', ACCENT)
        kwargs.setdefault('activeforeground', '#ffffff')
        kwargs.setdefault('borderwidth', 0)
        kwargs.setdefault('relief', 'flat')
        kwargs.setdefault('font', FONT)
        super().__init__(parent, **kwargs)
        parent.add_cascade(label=label, menu=self)
