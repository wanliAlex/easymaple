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
        self.shadow = tk.BooleanVar(value=self.settings.get('shadow'))
        self.iframe = tk.BooleanVar(value=self.settings.get('iframe'))

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

        # Shadow: you play, the solver follows along without touching the
        # mouse; the takeover hotkey (or unticking this mid-game) hands it over.
        self.shadow_check = tk.Checkbutton(
            row,
            variable=self.shadow,
            text='Shadow my manual solve',
            command=self._on_change
        )
        self.shadow_check.pack()
        key = self._takeover_key().upper()
        tk.Label(
            row,
            text=f'Solver follows without moving the mouse;\n'
                 f'press {key} or untick to let it take over',
            fg='gray'
        ).pack()

        # i-frame: the command book's LieDetectorGuard (an invincibility
        # skill) runs once while the game is being solved.
        self.iframe_check = tk.Checkbutton(
            row,
            variable=self.iframe,
            text='Cast i-frame while solving',
            command=self._on_change
        )
        self.iframe_check.pack()
        tk.Label(
            row,
            text="Runs the command book's LieDetectorGuard\n(erel_light: Del x3)",
            fg='gray'
        ).pack()
        self._sync_state()

    @staticmethod
    def _takeover_key():
        listener = getattr(config, 'listener', None)
        try:
            return listener.config['Lie Detector takeover']
        except Exception:
            return 'f9'

    def _sync_state(self):
        state = tk.NORMAL if self.auto_solve.get() else tk.DISABLED
        self.shadow_check.config(state=state)
        self.iframe_check.config(state=state)

    def _on_change(self):
        self.settings.set('auto solve', self.auto_solve.get())
        self.settings.set('shadow', self.shadow.get())
        self.settings.set('iframe', self.iframe.get())
        self.settings.save_config()
        self._sync_state()


class LieDetectorSettings(Configurable):
    DEFAULT_CONFIG = {
        'auto solve': True,
        'shadow': False,
        'iframe': False,        # opt-in: command book's LieDetectorGuard while solving
    }

    def get(self, key):
        return self.config[key]

    def set(self, key, value):
        assert key in self.config
        self.config[key] = value
