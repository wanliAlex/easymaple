import os
import tkinter as tk
from src.easymaple.common import config, utils, cache
from src.easymaple.gui.interfaces import MenuBarItem
from tkinter.filedialog import askopenfilename, asksaveasfilename
from tkinter.messagebox import askyesno, showerror


class File(MenuBarItem):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, 'File', **kwargs)

        self.add_command(
            label='New Routine',
            command=utils.async_callback(self, File._new_routine),
            state=tk.DISABLED
        )
        self.add_command(
            label='Save Routine',
            command=utils.async_callback(self, File._save_routine),
            state=tk.DISABLED
        )
        self.add_separator()
        self.add_command(label='Load Command Book', command=utils.async_callback(self, File._load_commands))
        self.add_command(
            label='Load Routine',
            command=utils.async_callback(self, File._load_routine),
            state=tk.DISABLED
        )

        # Open Recent ► [Command Books ►, Routines ►]
        self._recent_menu = tk.Menu(self, tearoff=0)
        self._recent_books_menu = tk.Menu(self._recent_menu, tearoff=0,
                                          postcommand=self._rebuild_recent_books)
        self._recent_routines_menu = tk.Menu(self._recent_menu, tearoff=0,
                                             postcommand=self._rebuild_recent_routines)
        self._recent_menu.add_cascade(label='Command Books', menu=self._recent_books_menu)
        self._recent_menu.add_cascade(label='Routines', menu=self._recent_routines_menu)
        self.add_cascade(label='Open Recent', menu=self._recent_menu)

    def enable_routine_state(self):
        self.entryconfig('New Routine', state=tk.NORMAL)
        self.entryconfig('Save Routine', state=tk.NORMAL)
        self.entryconfig('Load Routine', state=tk.NORMAL)

    def _rebuild_recent_books(self):
        self._recent_books_menu.delete(0, tk.END)
        paths = cache.get_recent_command_books()
        if not paths:
            self._recent_books_menu.add_command(label='(empty)', state=tk.DISABLED)
            return
        for p in paths:
            self._recent_books_menu.add_command(
                label=os.path.basename(p),
                command=utils.async_callback(self, lambda path=p: File._open_recent_book(path)),
            )

    def _rebuild_recent_routines(self):
        self._recent_routines_menu.delete(0, tk.END)
        paths = cache.get_recent_routines()
        if not paths:
            self._recent_routines_menu.add_command(label='(empty)', state=tk.DISABLED)
            return
        for p in paths:
            self._recent_routines_menu.add_command(
                label=os.path.basename(p),
                command=utils.async_callback(self, lambda path=p: File._open_recent_routine(path)),
            )

    @staticmethod
    @utils.run_if_disabled('\n[!] Cannot create a new routine while Auto Maple is enabled')
    def _new_routine():
        if config.routine.dirty:
            if not askyesno(title='New Routine',
                            message='The current routine has unsaved changes. '
                                    'Would you like to proceed anyways?',
                            icon='warning'):
                return
        config.routine.clear()

    @staticmethod
    @utils.run_if_disabled('\n[!] Cannot save routines while Auto Maple is enabled')
    def _save_routine():
        file_path = asksaveasfilename(initialdir=get_routines_dir(),
                                      title='Save routine',
                                      filetypes=[('*.csv', '*.csv')],
                                      defaultextension='*.csv')
        if file_path:
            config.routine.save(file_path)
            cache.add_recent_routine(file_path)

    @staticmethod
    @utils.run_if_disabled('\n[!] Cannot load routines while Auto Maple is enabled')
    def _load_routine():
        if config.routine.dirty:
            if not askyesno(title='Load Routine',
                            message='The current routine has unsaved changes. '
                                    'Would you like to proceed anyways?',
                            icon='warning'):
                return
        file_path = askopenfilename(initialdir=get_routines_dir(),
                                    title='Select a routine',
                                    filetypes=[('*.csv', '*.csv')])
        if file_path:
            config.routine.load(file_path)
            cache.set_last_routine(file_path)
            cache.add_recent_routine(file_path)

    @staticmethod
    @utils.run_if_disabled('\n[!] Cannot load command books while Auto Maple is enabled')
    def _load_commands():
        if config.routine.dirty:
            if not askyesno(title='Load Command Book',
                            message='Loading a new command book will discard the current routine, '
                                    'which has unsaved changes. Would you like to proceed anyways?',
                            icon='warning'):
                return
        file_path = askopenfilename(initialdir=os.path.join(config.RESOURCES_DIR, 'command_books'),
                                    title='Select a command book',
                                    filetypes=[('*.py', '*.py')])
        if file_path:
            config.bot.load_commands(file_path)
            cache.set_last_command_book(file_path)
            cache.add_recent_command_book(file_path)

    @staticmethod
    @utils.run_if_disabled('\n[!] Cannot load command books while Auto Maple is enabled')
    def _open_recent_book(file_path):
        if not os.path.exists(file_path):
            showerror('Open Recent', f'File not found:\n{file_path}\n\nIt will be hidden from this list.')
            # The next get_recent_command_books() will already filter it out — no action needed.
            return
        if config.routine.dirty:
            if not askyesno(title='Load Command Book',
                            message='Loading a new command book will discard the current routine, '
                                    'which has unsaved changes. Would you like to proceed anyways?',
                            icon='warning'):
                return
        config.bot.load_commands(file_path)
        cache.set_last_command_book(file_path)
        cache.add_recent_command_book(file_path)

    @staticmethod
    @utils.run_if_disabled('\n[!] Cannot load routines while Auto Maple is enabled')
    def _open_recent_routine(file_path):
        if not os.path.exists(file_path):
            showerror('Open Recent', f'File not found:\n{file_path}\n\nIt will be hidden from this list.')
            # The next get_recent_routines() will already filter it out — no action needed.
            return
        if config.routine.dirty:
            if not askyesno(title='Load Routine',
                            message='The current routine has unsaved changes. '
                                    'Would you like to proceed anyways?',
                            icon='warning'):
                return
        config.routine.load(file_path)
        cache.set_last_routine(file_path)
        cache.add_recent_routine(file_path)


def get_routines_dir():
    target = os.path.join(config.RESOURCES_DIR, 'routines', config.bot.module_name)
    if not os.path.exists(target):
        os.makedirs(target)
    return target
