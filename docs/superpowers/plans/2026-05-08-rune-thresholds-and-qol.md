# Adjustable Rune Thresholds + UI QoL — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Untrack `resources/.cache.json`, expose two rune detection thresholds via a new Settings → Advanced panel with a live match-score readout, and add four UI QoL features (status bar, recent files, dirty title, live preview).

**Architecture:** Threshold values live in a new `AdvancedSettings(Configurable)` exposed at `config.advanced`; worker threads read them per detection cycle for live tuning. Live match scores are stashed on `config` slots `last_rune_map_score`/`last_rune_buff_score` as `(score, timestamp)` tuples, polled by Tk via `root.after`. Status bar is a fourth widget on the root window beneath the notebook. Recent files extend the existing `cache.py` with two list keys. Dirty-title piggybacks on the existing `Routine.dirty` flag by promoting it to a property that pings `GUI.update_title()`.

**Tech Stack:** Python 3.10, Tkinter, OpenCV (cv2), MSS, NumPy, pickle (existing `Configurable` pattern), JSON cache.

**Working branch:** `feat/rune-thresholds-and-qol` (already created; the design spec is committed at `68fcd1a`).

**Testing approach:** The repo has no existing test suite. For pure logic added by this PR (recent-files dedup, `match_score` helper, dirty-property setter side-effects), small standalone pytest files are added under `tests/` — they're runnable on demand via `pytest tests/` without any new harness. Tk wiring and OpenCV threshold tuning are verified manually per the spec's verification steps.

---

## File Map

**New:**
- `src/easymaple/gui/settings/advanced.py` — `Advanced` LabelFrame + `AdvancedSettings(Configurable)` + live preview refresh
- `tests/test_cache_recent.py` — pytest for recent-files cache helpers
- `tests/test_utils_match_score.py` — pytest for `match_score`
- `tests/test_routine_dirty.py` — pytest for dirty-property setter calls `update_title`

**Modified:**
- `.gitignore` — fix cache pattern
- `src/easymaple/common/config.py` — add `advanced`, `last_rune_map_score`, `last_rune_buff_score`
- `src/easymaple/common/utils.py` — add `match_score()`
- `src/easymaple/common/cache.py` — add recent-files helpers
- `src/easymaple/modules/notifier.py` — read threshold from `config.advanced`; stash map score
- `src/easymaple/modules/bot.py` — read threshold from `config.advanced`; stash buff score
- `src/easymaple/modules/capture.py` — expose rolling-avg `fps`
- `src/easymaple/modules/gui.py` — status bar, `update_title()`, status refresh loop
- `src/easymaple/gui/menu/file.py` — Open Recent submenu; recent-files cache hook on load
- `src/easymaple/gui/settings/main.py` — wire Advanced into column 2
- `src/easymaple/routine/routine.py` — `dirty` becomes a property triggering `GUI.update_title`

**Untracked (git rm --cached):**
- `resources/.cache.json`

---

## Task 1: Untrack `resources/.cache.json` and fix `.gitignore`

**Files:**
- Modify: `.gitignore` line 5
- Untrack: `resources/.cache.json`

- [ ] **Step 1: Edit `.gitignore` — replace the broken cache pattern**

The existing line 5 is `./resources/.cache.json` (leading `./` makes it invalid). Replace with `resources/.cache.json`.

After edit, `.gitignore` should look like:

```
assets/models
.settings/
.env
CLAUDE.md
resources/.cache.json
```

- [ ] **Step 2: Verify the pattern works**

Run:

```bash
git -C D:/easymaple check-ignore -v resources/.cache.json
```

Expected output (line number may differ but pattern must show):

```
.gitignore:5:resources/.cache.json	resources/.cache.json
```

If the command prints nothing, the pattern is still broken — fix before continuing.

- [ ] **Step 3: Untrack the file (keep it on disk)**

```bash
git -C D:/easymaple rm --cached resources/.cache.json
```

Expected output:

```
rm 'resources/.cache.json'
```

Then verify the file still exists on disk:

```bash
ls D:/easymaple/resources/.cache.json
```

It should still print the file (we're only stopping git from tracking it, not deleting it).

- [ ] **Step 4: Verify status**

```bash
git -C D:/easymaple status
```

Expected: `deleted: resources/.cache.json` under "Changes to be committed", and `.gitignore` modified. The cache file should NOT appear under "Untracked files" because it now matches an ignore pattern.

- [ ] **Step 5: Commit**

```bash
git -C D:/easymaple add .gitignore
git -C D:/easymaple commit -m "chore: untrack resources/.cache.json

The previous gitignore line './resources/.cache.json' had an invalid
leading './' so the file was still tracked. Fix the pattern and untrack
the file. Each user keeps their own local cache from now on.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add `match_score` helper to `utils.py`

**Files:**
- Modify: `src/easymaple/common/utils.py` (add a function after `multi_match` near line 146)
- Create: `tests/test_utils_match_score.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_utils_match_score.py`:

```python
"""Tests for utils.match_score."""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import numpy as np
from src.easymaple.common import utils


def test_match_score_returns_one_for_self_match():
    """A grayscale frame matched against itself should score very close to 1.0."""
    frame = np.array([[10, 20, 30, 40], [50, 60, 70, 80]], dtype=np.uint8)
    template = frame.copy()
    score = utils.match_score(frame, template)
    assert 0.99 <= score <= 1.0001


def test_match_score_returns_float_in_range():
    """Score against a different patch must be a finite float in [-1, 1] (TM_CCOEFF_NORMED range)."""
    rng = np.random.default_rng(seed=0)
    frame = rng.integers(0, 256, size=(40, 40), dtype=np.uint8)
    template = rng.integers(0, 256, size=(8, 8), dtype=np.uint8)
    score = utils.match_score(frame, template)
    assert isinstance(score, float)
    assert -1.0 <= score <= 1.0
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd D:/easymaple
pytest tests/test_utils_match_score.py -v
```

Expected: both tests FAIL with `AttributeError: module 'src.easymaple.common.utils' has no attribute 'match_score'`.

- [ ] **Step 3: Add `match_score` to `utils.py`**

In `src/easymaple/common/utils.py`, immediately after the `multi_match` function (after line 146), add:

```python
def match_score(frame, template):
    """
    Returns the maximum normalized template-match score for TEMPLATE in FRAME.
    Useful for live-tuning detection thresholds: shows how close the best match is
    regardless of whether it exceeds any threshold.

    :param frame:       The image in which to search.
    :param template:    The template to match with.
    :return:            A float in [-1.0, 1.0]. Higher = better match.
    """

    if len(frame.shape) != 2:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame

    try:
        result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    except cv2.error:
        return 0.0
    return float(result.max())
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_utils_match_score.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git -C D:/easymaple add src/easymaple/common/utils.py tests/test_utils_match_score.py
git -C D:/easymaple commit -m "feat(utils): add match_score helper for live threshold preview

Returns the maximum normalized template-match score regardless of
threshold, enabling a live readout in the upcoming Advanced settings UI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Add `advanced`, `last_rune_map_score`, `last_rune_buff_score` slots to `config.py`

**Files:**
- Modify: `src/easymaple/common/config.py` (after line 45)

- [ ] **Step 1: Add the slots**

At the end of `src/easymaple/common/config.py` (after `gui = None`), add:

```python


# AdvancedSettings instance — populated by the GUI on init. Worker threads read
# detection thresholds from here. Stays None until GUI initializes it.
advanced = None

# Live match scores for the rune templates: (score, timestamp). Updated by the
# notifier (map score) and bot (buff score) loops; read by the Advanced UI for
# live preview. Stale (>2s) values display as "—".
last_rune_map_score = (0.0, 0.0)
last_rune_buff_score = (0.0, 0.0)
```

- [ ] **Step 2: Verify imports still work**

```bash
cd D:/easymaple
python -c "from src.easymaple.common import config; print(config.advanced, config.last_rune_map_score)"
```

Expected output:

```
None (0.0, 0.0)
```

- [ ] **Step 3: Commit**

```bash
git -C D:/easymaple add src/easymaple/common/config.py
git -C D:/easymaple commit -m "feat(config): add advanced and last_rune_*_score slots

Slots that the new Settings > Advanced panel and worker threads will
share: 'advanced' for the AdvancedSettings instance, last_rune_*_score
for the live match-score readout.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Create `AdvancedSettings` + `Advanced` LabelFrame

**Files:**
- Create: `src/easymaple/gui/settings/advanced.py`

- [ ] **Step 1: Create the file**

Write `src/easymaple/gui/settings/advanced.py`:

```python
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
```

- [ ] **Step 2: Smoke-import**

```bash
cd D:/easymaple
python -c "from src.easymaple.gui.settings.advanced import Advanced, AdvancedSettings; print('ok')"
```

Expected: `ok` (no traceback).

- [ ] **Step 3: Commit**

```bash
git -C D:/easymaple add src/easymaple/gui/settings/advanced.py
git -C D:/easymaple commit -m "feat(gui): add Advanced settings panel for rune thresholds

New LabelFrame with sliders + numeric readouts + Reset buttons for
rune-map and rune-buff detection thresholds, plus a live 'Current
match' label that polls config.last_rune_*_score every 200ms.

The panel is not yet wired into the Settings tab — that comes next.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Wire `Advanced` into the Settings tab

**Files:**
- Modify: `src/easymaple/gui/settings/main.py`

- [ ] **Step 1: Update `main.py`**

Replace the contents of `src/easymaple/gui/settings/main.py` with:

```python
"""Displays Auto Maple's current settings and allows the user to edit them."""

import tkinter as tk
from src.easymaple.gui.settings.advanced import Advanced
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
        self.advanced = Advanced(column2)
        self.advanced.pack(side=tk.TOP, fill='x', expand=True, pady=(10, 0))
```

- [ ] **Step 2: Smoke-launch the GUI**

Run the bot and click the Settings tab:

```bash
cd D:/easymaple
python main.py
```

Expected: Settings tab shows a third LabelFrame "Advanced" in column 2 below "Pets", with two threshold sliders defaulted to 0.75 and 0.90 and "Current match: —" labels. Move sliders — values update; click Reset — defaults restore. Close the window when satisfied.

- [ ] **Step 3: Commit**

```bash
git -C D:/easymaple add src/easymaple/gui/settings/main.py
git -C D:/easymaple commit -m "feat(gui): wire Advanced panel into Settings tab

Adds the new Advanced LabelFrame to column 2 below Pets so the rune
threshold sliders are accessible from the Settings tab.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Read thresholds + stash live scores in `notifier.py` and `bot.py`

**Files:**
- Modify: `src/easymaple/modules/notifier.py:127-130`
- Modify: `src/easymaple/modules/bot.py:148-151`

- [ ] **Step 1: Update `notifier.py`**

Locate the rune-detection block (around line 126–137):

```python
                # Check for rune
                if self.rune_counter >= RUNE_DETECT_FREQUENCY or self.rune_counter == 0:
                    self.rune_counter = 1
                    filtered = utils.filter_color(minimap, RUNE_RANGES)
                    matches = utils.multi_match(filtered, RUNE_TEMPLATE, threshold=0.75)
                    if matches:
```

Replace with:

```python
                # Check for rune
                if self.rune_counter >= RUNE_DETECT_FREQUENCY or self.rune_counter == 0:
                    self.rune_counter = 1
                    filtered = utils.filter_color(minimap, RUNE_RANGES)
                    rune_threshold = (
                        config.advanced.get('rune_map_threshold')
                        if config.advanced is not None else 0.75
                    )
                    config.last_rune_map_score = (
                        utils.match_score(filtered, RUNE_TEMPLATE),
                        time.time(),
                    )
                    matches = utils.multi_match(filtered, RUNE_TEMPLATE, threshold=rune_threshold)
                    if matches:
```

- [ ] **Step 2: Update `bot.py`**

Locate the rune-buff detection block (around line 146–151):

```python
                    for _ in range(3):
                        time.sleep(0.3)
                        frame = config.capture.frame
                        rune_buff = utils.multi_match(frame[:frame.shape[0] // 8, :],
                                                      RUNE_BUFF_TEMPLATE,
                                                      threshold=0.9)
                        if rune_buff:
```

Replace with:

```python
                    for _ in range(3):
                        time.sleep(0.3)
                        frame = config.capture.frame
                        buff_frame = frame[:frame.shape[0] // 8, :]
                        buff_threshold = (
                            config.advanced.get('rune_buff_threshold')
                            if config.advanced is not None else 0.9
                        )
                        config.last_rune_buff_score = (
                            utils.match_score(buff_frame, RUNE_BUFF_TEMPLATE),
                            time.time(),
                        )
                        rune_buff = utils.multi_match(buff_frame,
                                                      RUNE_BUFF_TEMPLATE,
                                                      threshold=buff_threshold)
                        if rune_buff:
```

- [ ] **Step 3: Smoke-launch and verify live preview**

```bash
python main.py
```

Wait for the bot to detect the game window (the View tab will start showing the minimap). On the Settings tab, the Advanced panel's "Current match" label for the rune-map threshold should update within ~1 second to a real numeric value (e.g. `0.62`). Drop the slider to 0.4 — the slider value updates instantly, and on subsequent runs detection fires more eagerly.

The buff-score label may stay as "—" because it only updates during an active rune solve; that's expected.

- [ ] **Step 4: Commit**

```bash
git -C D:/easymaple add src/easymaple/modules/notifier.py src/easymaple/modules/bot.py
git -C D:/easymaple commit -m "feat(detection): read rune thresholds from AdvancedSettings live

Replace hardcoded 0.75 and 0.9 thresholds with values pulled from
config.advanced each detection cycle (falling back to defaults if the
GUI hasn't initialized AdvancedSettings yet). Stash max match scores
on config.last_rune_*_score for the live UI preview.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Expose rolling-average `fps` on `Capture`

**Files:**
- Modify: `src/easymaple/modules/capture.py`

- [ ] **Step 1: Add a frame-timestamp deque and `fps` property**

In `src/easymaple/modules/capture.py`, near the top alongside the other imports, add:

```python
from collections import deque
```

In `Capture.__init__`, after `self.window = {...}` (around line 64), add:

```python
        self._frame_times = deque(maxlen=30)
```

Add this method on `Capture` immediately after `__init__` (before `start`):

```python
    @property
    def fps(self):
        """Rolling average frames-per-second over the last 30 captured frames."""
        if len(self._frame_times) < 2:
            return 0.0
        span = self._frame_times[-1] - self._frame_times[0]
        if span <= 0:
            return 0.0
        return (len(self._frame_times) - 1) / span
```

In the inner capture loop (around line 145, right after `self.frame = self.screenshot()` and the `if self.frame is None: continue` check), add:

```python
                    self._frame_times.append(time.time())
```

The full block becomes:

```python
                    # Take screenshot
                    self.frame = self.screenshot()
                    if self.frame is None:
                        continue
                    self._frame_times.append(time.time())
```

- [ ] **Step 2: Smoke-test**

```bash
python main.py
```

After the game window is detected, drop into a Python REPL or just confirm the bot window shows minimap updates. Then in code (you can add a temporary print or use the next task's status bar) verify `config.capture.fps` is a positive float around 25–30.

Or run this one-liner from a separate terminal (only meaningful while the bot is running):

```bash
python -c "from src.easymaple.common import config; import time; time.sleep(2); print(config.capture.fps if config.capture else 'capture not started')"
```

(This requires the running bot's process; skip if too fiddly — the status bar in Task 8 will reveal it.)

- [ ] **Step 3: Commit**

```bash
git -C D:/easymaple add src/easymaple/modules/capture.py
git -C D:/easymaple commit -m "feat(capture): expose rolling-average fps property

Ring buffer of the last 30 capture timestamps powers a Capture.fps
property used by the upcoming status bar.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Add the bottom status bar + `update_title()` to `GUI`

**Files:**
- Modify: `src/easymaple/modules/gui.py`

- [ ] **Step 1: Replace `gui.py` with the extended version**

Add a status bar widget, a refresh loop, and an `update_title()` helper. Replace `src/easymaple/modules/gui.py` with:

```python
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
```

- [ ] **Step 2: Smoke-launch and verify**

```bash
python main.py
```

Expected: a sunken row at the bottom of the window shows `Book: — | Routine: — | Bot: DISABLED | FPS: —`. After the game window is detected and the cache auto-loads the last book + routine, those labels populate. Press F6 to enable — `Bot: ENABLED` (green). FPS shows ~25–30. Switch tabs — bar stays visible.

- [ ] **Step 3: Commit**

```bash
git -C D:/easymaple add src/easymaple/modules/gui.py
git -C D:/easymaple commit -m "feat(gui): add bottom status bar + update_title helper

Persistent four-field status bar (book/routine/bot/fps) visible from
every tab, refreshed at 2Hz. Adds GUI.update_title() that the routine
will invoke when dirty/load/save state changes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Promote `Routine.dirty` to a property that pings `update_title`

**Files:**
- Modify: `src/easymaple/routine/routine.py`
- Create: `tests/test_routine_dirty.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_routine_dirty.py`:

```python
"""Tests that Routine.dirty triggers GUI.update_title via property setter."""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.easymaple.common import config


class FakeGUI:
    def __init__(self):
        self.title_calls = 0

    def update_title(self):
        self.title_calls += 1


def test_dirty_setter_pings_gui_only_on_change():
    from src.easymaple.routine.routine import Routine
    fake = FakeGUI()
    config.gui = fake

    r = Routine()
    # Initial state was set in __init__ — count is whatever happened then
    baseline = fake.title_calls

    r.dirty = True
    assert fake.title_calls == baseline + 1, "True after False should ping"

    r.dirty = True
    assert fake.title_calls == baseline + 1, "True after True should NOT ping again"

    r.dirty = False
    assert fake.title_calls == baseline + 2, "False after True should ping"


def test_dirty_setter_safe_when_gui_unset():
    from src.easymaple.routine.routine import Routine
    config.gui = None
    r = Routine()
    r.dirty = True  # must not raise
    assert r.dirty is True
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_routine_dirty.py -v
```

Expected: tests FAIL — likely because `dirty` is a plain attribute today, so the title_calls counter stays at baseline and the first assertion trips.

- [ ] **Step 3: Promote `dirty` to a property**

In `src/easymaple/routine/routine.py`, modify the `Routine` class. Replace `__init__`'s `self.dirty = False` line with `self._dirty = False`, and add the property below the `dirty` decorator definition. The relevant changes:

1. The module-level `def dirty(func)` decorator at line 24 is currently named the same as the soon-to-be property. **Rename the decorator** to avoid the shadowing. Find this block (around lines 24-31):

```python
def dirty(func):
    """Decorator function that sets the dirty bit for mutative Routine operations."""

    def f(self, *args, **kwargs):
        result = func(self, *args, **kwargs)
        self.dirty = True
        return result
    return f
```

Rename to `_mark_dirty`:

```python
def _mark_dirty(func):
    """Decorator: sets the dirty bit on the wrapped Routine method's instance."""

    def f(self, *args, **kwargs):
        result = func(self, *args, **kwargs)
        self.dirty = True
        return result
    return f
```

2. Throughout the file, replace every `@dirty` decorator usage (there are 9 of them: `set`, `append_component`, `append_command`, `move_component_up`, `move_component_down`, `move_command_up`, `move_command_down`, `delete_component`, `delete_command`) with `@_mark_dirty`.

3. In `Routine.__init__`, change `self.dirty = False` to `self._dirty = False`.

4. Add the property right after `__init__` (before `set`):

```python
    @property
    def dirty(self):
        return self._dirty

    @dirty.setter
    def dirty(self, value):
        if self._dirty != bool(value):
            self._dirty = bool(value)
            if config.gui is not None:
                config.gui.update_title()
```

The decorators continue to assign `self.dirty = True` — which now goes through the setter. Same for `update_component`, `update_command`, `save`, `clear`, `load` which all do `self.dirty = True/False` directly.

- [ ] **Step 4: Run the test again**

```bash
pytest tests/test_routine_dirty.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Run all tests to make sure nothing else broke**

```bash
pytest tests/ -v
```

Expected: all tests pass (3 tests so far: 2 from match_score + 2 from dirty… 4 total).

- [ ] **Step 6: Smoke-launch**

```bash
python main.py
```

Load a routine, verify title shows `Auto Maple — <routine>.csv`. Edit a component (drag in Edit tab, or change a coordinate) — title updates to `Auto Maple — <routine>.csv *`. Save — `*` clears.

- [ ] **Step 7: Commit**

```bash
git -C D:/easymaple add src/easymaple/routine/routine.py tests/test_routine_dirty.py
git -C D:/easymaple commit -m "feat(routine): wire dirty flag to window-title indicator

Promote Routine.dirty to a property whose setter calls
GUI.update_title() on transitions, so the title bar shows '*' for
unsaved edits without each mutation site needing a manual hook.

Renames the @dirty decorator to @_mark_dirty to avoid shadowing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Add recent-files helpers to `cache.py`

**Files:**
- Modify: `src/easymaple/common/cache.py`
- Create: `tests/test_cache_recent.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cache_recent.py`:

```python
"""Tests for recent-files cache helpers."""
import os, sys, json, tempfile, importlib
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _reload_cache_with_tmpdir(tmpdir):
    """Reloads cache module pointing at a temp resources dir."""
    from src.easymaple.common import config
    config.RESOURCES_DIR = tmpdir
    from src.easymaple.common import cache
    importlib.reload(cache)
    return cache


def test_add_recent_dedupes_and_trims_to_limit(tmp_path, monkeypatch):
    cache = _reload_cache_with_tmpdir(str(tmp_path))

    # Create 7 fake routine files on disk so the existence filter doesn't drop them
    paths = []
    for i in range(7):
        p = tmp_path / f"r{i}.csv"
        p.write_text("# fake")
        paths.append(str(p))

    for p in paths:
        cache.add_recent_routine(p)

    recent = cache.get_recent_routines()
    assert len(recent) == cache.RECENT_LIMIT == 5
    # most-recent-first
    assert recent[0] == paths[-1]
    assert recent[-1] == paths[-cache.RECENT_LIMIT]


def test_add_recent_dedupes_existing_entry(tmp_path):
    cache = _reload_cache_with_tmpdir(str(tmp_path))

    a = tmp_path / "a.py"; a.write_text("# fake")
    b = tmp_path / "b.py"; b.write_text("# fake")

    cache.add_recent_command_book(str(a))
    cache.add_recent_command_book(str(b))
    cache.add_recent_command_book(str(a))  # re-touch a

    recent = cache.get_recent_command_books()
    assert recent == [str(a), str(b)]


def test_get_recent_filters_missing_files(tmp_path):
    cache = _reload_cache_with_tmpdir(str(tmp_path))

    a = tmp_path / "a.py"; a.write_text("# fake")
    cache.add_recent_command_book(str(a))
    cache.add_recent_command_book(str(tmp_path / "missing.py"))  # never created

    recent = cache.get_recent_command_books()
    assert recent == [str(a)]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_cache_recent.py -v
```

Expected: tests FAIL with `AttributeError: module ... has no attribute 'add_recent_routine'`.

- [ ] **Step 3: Extend `cache.py`**

Append to `src/easymaple/common/cache.py` (after line 89):

```python


RECENT_LIMIT = 5


def _add_recent(key, file_path):
    cache_data = load_cache()
    items = list(cache_data.get(key, []))
    if file_path in items:
        items.remove(file_path)
    items.insert(0, file_path)
    cache_data[key] = items[:RECENT_LIMIT]
    save_cache(cache_data)


def _get_recent(key):
    cache_data = load_cache()
    items = cache_data.get(key, [])
    return [p for p in items if isinstance(p, str) and os.path.exists(p)]


def get_recent_command_books():
    return _get_recent('recent_command_books')


def add_recent_command_book(file_path):
    _add_recent('recent_command_books', file_path)


def get_recent_routines():
    return _get_recent('recent_routines')


def add_recent_routine(file_path):
    _add_recent('recent_routines', file_path)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_cache_recent.py -v
```

Expected: all three tests PASS.

- [ ] **Step 5: Commit**

```bash
git -C D:/easymaple add src/easymaple/common/cache.py tests/test_cache_recent.py
git -C D:/easymaple commit -m "feat(cache): add recent-files helpers (max 5, deduped, missing filtered)

Adds add_recent_command_book/get_recent_command_books and the routine
equivalents. Stored under 'recent_command_books' / 'recent_routines'
keys in .cache.json. Most-recent-first; max 5 entries; missing paths
filtered at read time.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Add "Open Recent" submenu to File menu

**Files:**
- Modify: `src/easymaple/gui/menu/file.py`

- [ ] **Step 1: Replace `file.py` with the extended version**

Replace `src/easymaple/gui/menu/file.py` with:

```python
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
            showerror('Open Recent', f'File not found:\n{file_path}\n\nRemoved from recent list.')
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
            showerror('Open Recent', f'File not found:\n{file_path}\n\nRemoved from recent list.')
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
```

- [ ] **Step 2: Smoke-launch and verify**

```bash
python main.py
```

Open `File → Open Recent`:
- After cache auto-loads at startup, both submenus should show the most-recent items.
- Click an entry — it should load the file.
- Load a different command book via `File → Load Command Book` — re-open `Open Recent → Command Books` — the new entry appears at the top.
- The "(empty)" disabled entry shows when a category has no entries.

- [ ] **Step 3: Commit**

```bash
git -C D:/easymaple add src/easymaple/gui/menu/file.py
git -C D:/easymaple commit -m "feat(menu): add File > Open Recent submenu

Two cascades (Command Books, Routines) populated from the recent-files
cache and rebuilt via postcommand on each open. Loading any file from
the Load/Save dialogs also pushes it onto the recent list.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Final end-to-end smoke + push + open PR

- [ ] **Step 1: Run all tests one more time**

```bash
cd D:/easymaple
pytest tests/ -v
```

Expected: all tests pass. (Total: ~7 tests across 3 files.)

- [ ] **Step 2: Run the full app and verify the spec's manual checks**

```bash
python main.py
```

Verify each item from the spec's "Verification" section:

1. `git status` — `resources/.cache.json` is neither tracked nor modified.
2. Settings tab → Advanced LabelFrame visible with two sliders at 0.75 / 0.90.
3. Game window detected → Advanced "Current match" (rune map) updates to a real number within ~1s.
4. Drop rune-map slider → on next bot run, detection fires more eagerly (console output).
5. Reset buttons restore 0.75 / 0.90.
6. Status bar visible on every tab; FPS ~25–30; Bot label flips on F6.
7. Edit routine → title gains `*`; save → `*` clears.
8. File → Open Recent populated; clicking an entry reloads the file.

If any check fails, drop into the relevant task to fix before proceeding.

- [ ] **Step 3: Push the branch and open the PR**

```bash
git -C D:/easymaple push -u origin feat/rune-thresholds-and-qol
```

Then:

```bash
gh pr create --title "Adjustable rune thresholds + UI QoL" --body "$(cat <<'EOF'
## Summary

- **Untrack `resources/.cache.json`** — fix broken gitignore pattern and `git rm --cached` the file so each user keeps their own local cache (commit history, last book/routine, recent files all stay local).
- **Adjustable rune thresholds** — new `Settings → Advanced` panel with sliders for the rune-map detection threshold (`notifier.py`, default 0.75) and the rune-buff detection threshold (`bot.py`, default 0.90). Each slider has a live "Current match" readout so you can tune empirically against the live game frame.
- **UI QoL**:
  - Bottom status bar showing book / routine (with `*` when dirty) / bot enabled / FPS — visible from any tab.
  - `File → Open Recent ►` submenus for Command Books and Routines (max 5 each, deduped, missing files filtered).
  - Window title shows `*` when the routine has unsaved edits.

Spec: `docs/superpowers/specs/2026-05-08-rune-thresholds-and-qol-design.md`
Plan: `docs/superpowers/plans/2026-05-08-rune-thresholds-and-qol.md`

## Test plan

- [ ] `pytest tests/` — all green
- [ ] `git check-ignore -v resources/.cache.json` shows pattern matches; file is no longer tracked
- [ ] Launch app: Advanced sliders move and persist; "Current match" populates
- [ ] Drop rune-map slider to 0.4 → rune detection fires more eagerly on next run
- [ ] Status bar visible on every tab; FPS displays a reasonable number
- [ ] Edit a routine → title gains `*`; save → `*` clears
- [ ] `File → Open Recent` populated after loads; entries reload correctly

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

The PR URL is printed on success.

---

## Self-review

**1. Spec coverage:**
- Cache untracking → Task 1.
- AdvancedSettings + Advanced LabelFrame → Tasks 3, 4.
- Wire into Settings tab → Task 5.
- Threshold reads in notifier/bot → Task 6.
- Live match-score stash + readout → Tasks 2, 4, 6.
- Status bar → Task 8.
- Rolling FPS → Task 7.
- Recent files cache + menu → Tasks 10, 11.
- Dirty-title indicator → Tasks 8 (`update_title`), 9 (property setter).
- Final verification → Task 12.

All spec sections covered.

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code; commands have expected output.

**3. Type consistency:** `config.advanced.get(key)` used consistently; `config.last_rune_*_score` always a `(score, timestamp)` tuple; `Routine.dirty` becomes a property but its public boolean type is preserved; `Capture.fps` returns a float in all paths.

**4. One concern flagged:** Task 9 renames the module-level `dirty` decorator to `_mark_dirty`. There are 9 use-sites within `routine.py` to rewrite — the task explicitly enumerates them, so the executor has the full list. No external file uses the decorator (verified during exploration).
