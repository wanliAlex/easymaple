"""Settings panel for Q-World auto re-entry (see modules/qworld.py)."""

import threading
import tkinter as tk

from src.easymaple.common import config
from src.easymaple.gui.interfaces import LabelFrame, Frame


class QWorld(LabelFrame):
    FIELDS = (('Portal x', 'portal x'), ('y', 'portal y'), ('tol', 'tolerance'))

    def __init__(self, parent, **kwargs):
        super().__init__(parent, 'Q-World Re-entry', **kwargs)

        self.handler = getattr(config, 'qworld', None)
        if self.handler is None:
            tk.Label(self, text='Unavailable (notifier not running)', fg='gray').pack(pady=5)
            return
        self.settings = self.handler.settings

        self.enabled = tk.BooleanVar(value=self.settings.get('enabled'))
        tk.Checkbutton(
            self,
            variable=self.enabled,
            text='Auto re-enter when kicked to the lobby',
            command=self._on_toggle
        ).pack(side=tk.TOP, padx=5, pady=(5, 0))

        fields = Frame(self)
        fields.pack(side=tk.TOP, padx=5, pady=(2, 0))
        self.vars = {}
        for label, key in self.FIELDS:
            tk.Label(fields, text=label).pack(side=tk.LEFT)
            var = tk.StringVar(value=f'{self.settings.get(key):.3f}')
            entry = tk.Entry(fields, textvariable=var, width=6)
            entry.pack(side=tk.LEFT, padx=(2, 6))
            entry.bind('<FocusOut>', lambda _e, k=key: self._on_field(k))
            entry.bind('<Return>', lambda _e, k=key: self._on_field(k))
            self.vars[key] = var

        buttons = Frame(self)
        buttons.pack(side=tk.TOP, padx=5, pady=(4, 0))
        tk.Button(buttons, text='Save lobby minimap', command=self._save_lobby).pack(side=tk.LEFT)
        tk.Button(buttons, text='Check screen', command=self._check).pack(side=tk.LEFT, padx=4)
        tk.Button(buttons, text='Test re-entry', command=self._test).pack(side=tk.LEFT)

        self.info = tk.Label(self, text=self._reference_text(), fg='gray',
                             wraplength=280, justify=tk.CENTER)
        self.info.pack(side=tk.TOP, padx=5, pady=(2, 5))

    def _reference_text(self):
        ref = self.handler.lobby_reference()
        if ref is None:
            return ('No lobby minimap saved: stand in the lobby, press F6, '
                    'then Save lobby minimap')
        h, w = ref.shape[:2]
        return f'Lobby minimap {w}x{h}. Portal: F7 in the lobby. F8 stops a re-entry.'

    def _on_toggle(self):
        self.settings.set('enabled', self.enabled.get())
        self.settings.save_config()
        print(f"[~] Q-World auto re-entry {'ON' if self.enabled.get() else 'OFF'}")

    def _on_field(self, key):
        var = self.vars[key]
        try:
            value = float(var.get())
            if not 0 <= value <= 1:
                raise ValueError
        except ValueError:
            var.set(f'{self.settings.get(key):.3f}')
            return
        self.settings.set(key, value)
        self.settings.save_config()

    def _save_lobby(self):
        _, message = self.handler.save_lobby_reference()
        self.info.configure(text=message)

    def _check(self):
        report = self.handler.describe_screen()
        print(f'[~] Q-World: {report}')
        self.info.configure(text=report)

    def _test(self):
        if self.handler.active:
            self.info.configure(text='A re-entry is already running (F8 stops it)')
            return
        self.info.configure(text='Test running: brings the game to the front, walks into '
                                 'the portal and starts the routine. F8 stops it.')
        threading.Thread(target=self.handler.run, args=('manual test',),
                         kwargs={'manual': True}, daemon=True).start()
