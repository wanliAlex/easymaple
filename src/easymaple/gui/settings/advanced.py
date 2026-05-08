import time
import tkinter as tk

from src.easymaple.common import config
from src.easymaple.common.interfaces import Configurable
from src.easymaple.gui.interfaces import LabelFrame, Frame


SCORE_FRESHNESS_S = 2.0


class Advanced(LabelFrame):
    """Settings panel for low-level detection thresholds with live match-score readouts."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, 'Advanced', **kwargs)

        self.settings = AdvancedSettings('advanced')
        config.advanced = self.settings

        self._map_value_label = None
        self._map_score_label = None
        self._buff_value_label = None
        self._buff_score_label = None

        self._build_threshold_row(
            label_text='Rune map detection threshold',
            key='rune_map_threshold',
            score_attr='last_rune_map_score',
            value_label_attr='_map_value_label',
            score_label_attr='_map_score_label',
        )
        self._build_threshold_row(
            label_text='Rune buff detection threshold',
            key='rune_buff_threshold',
            score_attr='last_rune_buff_score',
            value_label_attr='_buff_value_label',
            score_label_attr='_buff_score_label',
        )

        self._refresh_scores()

    def _build_threshold_row(self, label_text, key, score_attr, value_label_attr, score_label_attr):
        row = Frame(self)
        row.pack(side=tk.TOP, fill='x', expand=True, pady=(5, 0), padx=5)

        tk.Label(row, text=label_text).pack(side=tk.TOP, anchor='w')

        slider_row = Frame(row)
        slider_row.pack(side=tk.TOP, fill='x', expand=True)

        current = self.settings.get(key)

        def on_change(val):
            value = float(val)
            self.settings.set(key, value)
            self.settings.save_config()
            value_label.configure(text=f"{value:.2f}")

        scale = tk.Scale(
            slider_row,
            from_=0.5, to=0.99,
            resolution=0.01,
            orient=tk.HORIZONTAL,
            showvalue=False,
            command=on_change,
        )
        scale.set(current)
        scale.pack(side=tk.LEFT, fill='x', expand=True)

        value_label = tk.Label(slider_row, text=f"{current:.2f}", width=5)
        value_label.pack(side=tk.LEFT, padx=(5, 5))
        setattr(self, value_label_attr, value_label)

        def on_reset():
            default = AdvancedSettings.DEFAULT_CONFIG[key]
            scale.set(default)
            self.settings.set(key, default)
            self.settings.save_config()
            value_label.configure(text=f"{default:.2f}")

        tk.Button(slider_row, text='Reset', command=on_reset).pack(side=tk.LEFT)

        score_label = tk.Label(row, text='Current match: —', anchor='w', fg='gray')
        score_label.pack(side=tk.TOP, anchor='w')
        setattr(self, score_label_attr, score_label)
        score_label._attr = score_attr  # remember which config slot to read

    def _refresh_scores(self):
        for label in (self._map_score_label, self._buff_score_label):
            if label is None:
                continue
            score, ts = getattr(config, label._attr, (0.0, 0.0))
            if ts and time.time() - ts <= SCORE_FRESHNESS_S:
                label.configure(text=f"Current match: {score:.2f}", fg='black')
            else:
                label.configure(text='Current match: —', fg='gray')
        # Schedule next refresh on the Tk main loop
        self.after(200, self._refresh_scores)


class AdvancedSettings(Configurable):
    DEFAULT_CONFIG = {
        'rune_map_threshold': 0.75,
        'rune_buff_threshold': 0.9,
    }

    def get(self, key):
        return self.config[key]

    def set(self, key, value):
        assert key in self.config
        self.config[key] = value
