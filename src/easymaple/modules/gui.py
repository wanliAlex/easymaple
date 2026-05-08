"""User friendly GUI to interact with Auto Maple."""

import os
import time
import threading
import tkinter as tk
from tkinter import ttk
from src.easymaple.common import config, settings, cache
from src.easymaple.gui import Menu, View, Edit, Settings


class GUI:
    DISPLAY_FRAME_RATE = 30
    RESOLUTIONS = {
        'DEFAULT': '800x800',
        'Edit': '1400x800'
    }

    def __init__(self):
        config.gui = self

        self.root = tk.Tk()
        self.root.title('Auto Maple')
        icon = tk.PhotoImage(file='assets/icon.png')
        self.root.iconphoto(False, icon)
        self.root.geometry(GUI.RESOLUTIONS['DEFAULT'])
        self.root.resizable(False, False)

        # Initialize GUI variables
        self.routine_var = tk.StringVar()

        # Build the GUI
        self.menu = Menu(self.root)
        self.root.config(menu=self.menu)

        self.navigation = ttk.Notebook(self.root)

        self.view = View(self.navigation)
        self.edit = Edit(self.navigation)
        self.settings = Settings(self.navigation)

        self.navigation.pack(expand=True, fill='both')
        self.navigation.bind('<<NotebookTabChanged>>', self._resize_window)

        # Status bar — pack AFTER notebook so it sits at the bottom of the window
        self._build_status_bar()

        self.root.focus()

    def _build_status_bar(self):
        bar = tk.Frame(self.root, relief=tk.SUNKEN, borderwidth=1)
        bar.pack(side=tk.BOTTOM, fill=tk.X)

        self._book_label = tk.Label(bar, text='Book: —', anchor='w')
        self._book_label.pack(side=tk.LEFT, padx=(6, 6))

        tk.Label(bar, text='|').pack(side=tk.LEFT)

        self._routine_label = tk.Label(bar, text='Routine: —', anchor='w')
        self._routine_label.pack(side=tk.LEFT, padx=(6, 6))

        tk.Label(bar, text='|').pack(side=tk.LEFT)

        self._bot_label = tk.Label(bar, text='Bot: —', anchor='w', fg='gray')
        self._bot_label.pack(side=tk.LEFT, padx=(6, 6))

        tk.Label(bar, text='|').pack(side=tk.LEFT)

        self._fps_label = tk.Label(bar, text='FPS: —', anchor='w')
        self._fps_label.pack(side=tk.LEFT, padx=(6, 6))

    def _refresh_status_bar(self):
        # Book
        book = getattr(config.bot, 'module_name', None) if config.bot else None
        self._book_label.configure(text=f"Book: {book or '—'}")

        # Routine + dirty
        routine = config.routine
        if routine and routine.path:
            name = os.path.basename(routine.path)
            suffix = '*' if routine.dirty else ''
            self._routine_label.configure(text=f"Routine: {name}{suffix}")
        else:
            self._routine_label.configure(text='Routine: —')

        # Bot enabled state
        if config.enabled:
            self._bot_label.configure(text='Bot: ENABLED', fg='green')
        else:
            self._bot_label.configure(text='Bot: DISABLED', fg='gray')

        # FPS
        fps = getattr(config.capture, 'fps', 0.0) if config.capture else 0.0
        self._fps_label.configure(text=f"FPS: {fps:.1f}" if fps else 'FPS: —')

        self.root.after(500, self._refresh_status_bar)

    def update_title(self):
        """Rebuilds the window title string from current routine state."""
        routine = config.routine
        if routine and routine.path:
            name = os.path.basename(routine.path)
            suffix = ' *' if routine.dirty else ''
            self.root.title(f"Auto Maple — {name}{suffix}")
        else:
            self.root.title('Auto Maple')

    def set_routine(self, arr):
        self.routine_var.set(arr)

    def clear_routine_info(self):
        """
        Clears information in various GUI elements regarding the current routine.
        Does not clear Listboxes containing routine Components, as that is handled by Routine.
        """

        self.view.details.clear_info()
        self.view.status.set_routine('')

        self.edit.minimap.redraw()
        self.edit.routine.commands.clear_contents()
        self.edit.routine.commands.update_display()
        self.edit.editor.reset()

    def _resize_window(self, e):
        """Callback to resize entire Tkinter window every time a new Page is selected."""

        nav = e.widget
        curr_id = nav.select()
        nav.nametowidget(curr_id).focus()      # Focus the current Tab
        page = nav.tab(curr_id, 'text')
        if self.root.state() != 'zoomed':
            if page in GUI.RESOLUTIONS:
                self.root.geometry(GUI.RESOLUTIONS[page])
            else:
                self.root.geometry(GUI.RESOLUTIONS['DEFAULT'])

    def start(self):
        """Starts the GUI as well as any scheduled functions."""

        display_thread = threading.Thread(target=self._display_minimap)
        display_thread.daemon = True
        display_thread.start()

        layout_thread = threading.Thread(target=self._save_layout)
        layout_thread.daemon = True
        layout_thread.start()

        # Auto-load last used files from cache after GUI is fully initialized
        self.root.after(100, cache.auto_load_last_files)

        # Status bar refresh loop
        self.root.after(500, self._refresh_status_bar)

        self.root.mainloop()

    def _display_minimap(self):
        delay = 1 / GUI.DISPLAY_FRAME_RATE
        while True:
            self.view.minimap.display_minimap()
            time.sleep(delay)

    def _save_layout(self):
        """Periodically saves the current Layout object."""

        while True:
            if config.layout is not None and settings.record_layout:
                config.layout.save()
            time.sleep(5)


if __name__ == '__main__':
    gui = GUI()
    gui.start()
