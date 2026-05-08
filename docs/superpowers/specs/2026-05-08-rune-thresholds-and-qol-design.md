# Adjustable Rune Thresholds + UI QoL — Design

**Date:** 2026-05-08
**Status:** Approved (pending implementation plan)

## Problem

Three independent issues are bundled into a single PR:

1. **Cache file is tracked in git.** `resources/.cache.json` stores absolute Windows paths (`last_command_book`, `last_routine`) and is unique per machine. A recent commit attempted to ignore it via `./resources/.cache.json` in `.gitignore`, but the leading `./` makes the pattern invalid — the file is still tracked.
2. **Detection thresholds are hardcoded.** Rune appearance on the minimap (`modules/notifier.py:130`, `0.75`) and rune buff icon after solving (`modules/bot.py:151`, `0.9`) are constants. Tuning requires a code edit and restart.
3. **UI lacks several quality-of-life affordances** — there's no visibility into bot state from non-View tabs, no recent-files shortcut, no unsaved-edit indicator, and no way to empirically tune detection.

## Goals

- Stop tracking `resources/.cache.json` without affecting other tracked content.
- Surface the two rune detection thresholds as live-adjustable sliders in the Settings tab.
- Add four QoL improvements: bottom status bar, recent-files menu, dirty-state title indicator, and live match-score readout.

## Non-Goals

- Untracking `__pycache__` directories or other already-tracked content beyond `.cache.json`.
- Untracking command book `.py` files or routine `.csv` files.
- Exposing additional thresholds (`jump_threshold`, `room_change_threshold`, death detection) — out of scope for this PR.
- Resizable main window or persisted window geometry.
- Adding a test harness — none exists today and tests won't meaningfully cover Tk wiring or template-matching tuning.

## Design

### Feature 1 — Cache untracking

- Edit `.gitignore`: replace `./resources/.cache.json` with `resources/.cache.json`.
- `git rm --cached resources/.cache.json` so the file stops being tracked. The on-disk file is retained.
- No code changes — `common/cache.py::save_cache` already creates the file on demand, so a fresh clone will generate its own.

### Feature 2 — Adjustable rune thresholds

#### Persistence layer

New `Configurable` subclass in `src/easymaple/gui/settings/advanced.py`, mirroring the existing `RuneSettings` pattern (`gui/settings/rune.py`):

```python
class AdvancedSettings(Configurable):
    DEFAULT_CONFIG = {
        'rune_map_threshold': 0.75,
        'rune_buff_threshold': 0.9,
    }

    def get(self, key): return self.config[key]

    def set(self, key, value):
        assert key in self.config
        self.config[key] = value
```

Persisted to `.settings/advanced` (pickle, same convention as the rest). Instantiated once in the `Advanced` LabelFrame's `__init__` and exposed on `config.advanced` so worker threads can read it without holding a Tk reference.

#### Wiring threshold reads

- `modules/notifier.py:130` — replace `threshold=0.75` with `threshold=config.advanced.get('rune_map_threshold')`.
- `modules/bot.py:151` — replace `threshold=0.9` with `threshold=config.advanced.get('rune_buff_threshold')`.

Both reads happen inside their respective detection loops, so slider changes take effect on the next iteration without restart.

#### Live match-score preview

`utils.multi_match` returns only the locations that exceed the threshold; it doesn't expose the underlying max score. We add a helper:

```python
def match_score(frame, template) -> float:
    """Return the maximum normalized match score (0.0–1.0) for TEMPLATE in FRAME."""
    result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
    return float(result.max())
```

In the notifier loop, alongside the existing `multi_match` call, also compute and stash:

```python
config.last_rune_map_score = (utils.match_score(filtered, RUNE_TEMPLATE), time.time())
```

In the bot's rune-solve block, do the same for the buff template. The tuple is `(score, timestamp)`; the GUI shows "—" if the timestamp is older than 2 seconds (especially relevant for the buff score, which is only computed during active solves).

#### UI

A new `Advanced` LabelFrame placed in column 2 of the Settings tab (`gui/settings/main.py`), below `Pets`. Contents per threshold:

```
Rune map detection threshold
[=========|==] 0.75    [Reset]
Current match: 0.62

Rune buff detection threshold
[============|=] 0.90  [Reset]
Current match: —
```

- `tk.Scale(from_=0.5, to=0.99, resolution=0.01, orient=tk.HORIZONTAL)` for each threshold.
- `tk.Label` next to each slider showing the current value to 2 decimals.
- "Reset" button restores the default for that single threshold.
- `tk.Label` showing `Current match: <score>` updated every 200 ms via `root.after(200, refresh)`. Reads `config.last_rune_*_score`; shows `—` if stale (>2 s) or unset.

Slider `command=` callback writes to `AdvancedSettings` and calls `save_config()`.

### Feature 3a — Status bar (QoL b)

A `tk.Frame` packed at the bottom of `self.root` *before* the notebook (`modules/gui.py`), so it's visible on every tab.

Layout: single sunken row, four labels separated by ` | `:

```
Book: shadower.py | Routine: GentleSummer5.csv* | Bot: ENABLED  | FPS: 28.4
```

Sources:

- **Book:** basename of the currently loaded command book. `Bot.load_commands()` already records the path; we add a `config.command_book_path` slot it writes to (alongside the existing cache write). `—` when unset.
- **Routine:** basename of the loaded routine path; `*` suffix when `config.routine.dirty` is True (ties into Feature 3c).
- **Bot:** `ENABLED` (green text) when `config.enabled`, `DISABLED` (gray) otherwise.
- **FPS:** rolling average over the last 30 frames captured by `modules/capture.py`. Implementation: capture thread maintains a small `collections.deque(maxlen=30)` of frame timestamps; `Capture.fps` is a property returning `30 / (latest - oldest)` or `0.0` when underfilled.

Refresh: `root.after(500, refresh_status_bar)`. 2 Hz is plenty given that only FPS moves quickly (and it's already smoothed).

If `config.bot` / `config.capture` aren't yet initialized at first refresh, labels show `—`. No exceptions surface to the user.

### Feature 3b — Recent files menu (QoL c)

#### Cache extension

Add to `common/cache.py`:

```python
RECENT_LIMIT = 5

def get_recent_command_books() -> list[str]: ...
def add_recent_command_book(file_path: str): ...   # dedupes, prepends, trims to 5
def get_recent_routines() -> list[str]: ...
def add_recent_routine(file_path: str): ...
```

Stored in the existing `.cache.json` under new keys `recent_command_books` and `recent_routines` (lists, most-recent-first). Read-time filtering drops paths that no longer exist on disk.

Hook points: existing call sites of `set_last_command_book` / `set_last_routine` also call the corresponding `add_recent_*`.

#### Menu wiring

In `gui/menu/file.py`, add an "Open Recent ►" cascade with two sub-cascades:

```
Open Recent ►
├── Command Books ►
│     ├── shadower.py
│     ├── nightlord.py
│     └── (Clear)
└── Routines ►
      ├── GentleSummer5.csv
      ├── BurningRoyalLibrarySection6.csv
      └── (Clear)
```

Each sub-cascade is rebuilt on open via `tkinter.Menu`'s `postcommand` parameter — guarantees fresh state without a manual refresh path. Empty lists show a disabled `(empty)` entry.

Click action: invoke the same loader the existing "Load Command Book" / "Load Routine" entries use. On failure (file gone, parse error), show `messagebox.showerror` and remove the entry from the cache.

### Feature 3c — Dirty-state title indicator (QoL d)

#### Source of truth

`Routine` (`routine/routine.py`) gains a `dirty: bool` flag plus `mark_dirty()` helper:

```python
def mark_dirty(self):
    if not self.dirty:
        self.dirty = True
        if config.gui:
            config.gui.update_title()
```

`load()` and `save()` set `self.dirty = False` and call `update_title()`.

#### Title format

- No routine loaded: `Auto Maple`
- Loaded, clean: `Auto Maple — GentleSummer5.csv`
- Loaded, dirty: `Auto Maple — GentleSummer5.csv *`

`GUI.update_title()` is a new method on `modules/gui.py::GUI` that rebuilds the string and calls `self.root.title(...)`.

#### Hook points

Every Edit-tab mutation calls `config.routine.mark_dirty()`. The mutations live in:

- `gui/edit/components.py` — Component add/delete/move/edit
- `gui/edit/routine.py` — top-level routine list mutations
- `gui/edit/commands.py` — Command argument edits

Each mutation path gets a single line added. Coverage is best-effort: false negatives (treating dirty as clean) are acceptable — the user notices when they re-open. False positives (marking clean as dirty) are also acceptable — worst case is a redundant save. Exhaustive coverage is not required.

## Architecture / data flow

```
Tk main thread                        Worker threads
─────────────                          ──────────────
[Advanced sliders]                     [notifier.py loop]
   │                                       │ reads
   │ writes                                ▼
   ▼                                  config.advanced.get(...)
config.advanced ◄─────────────────── (used as threshold)
                                          │
[Status bar refresh]                      │ writes
   │ reads                                ▼
   ▼                                  config.last_rune_map_score
config.last_rune_*_score ◄────────── (timestamped tuple)
config.capture.fps
config.routine.dirty
```

Threading: dict reads/writes on `config.advanced.config` and the `config.last_*_score` slots are atomic under CPython's GIL; no locks needed for these single-key operations.

## Out-of-scope risks left untouched

- Other `__pycache__` files are tracked in git (visible in `git status` output). Not addressed here per user direction.
- The threshold defaults stay at 0.75 / 0.9, matching today's behavior — anyone whose detection works fine sees no change.

## Files touched

| File | Type | Purpose |
|------|------|---------|
| `.gitignore` | edit | Fix cache pattern |
| `resources/.cache.json` | git rm --cached | Untrack |
| `src/easymaple/gui/settings/advanced.py` | new | Advanced LabelFrame + `AdvancedSettings` |
| `src/easymaple/gui/settings/main.py` | edit | Wire Advanced into column 2 |
| `src/easymaple/common/config.py` | edit | `advanced`, `last_rune_*_score` slots |
| `src/easymaple/common/utils.py` | edit | `match_score()` helper |
| `src/easymaple/common/cache.py` | edit | `add_recent_*` / `get_recent_*` helpers |
| `src/easymaple/modules/notifier.py` | edit | Read threshold from config; stash map score |
| `src/easymaple/modules/bot.py` | edit | Read threshold from config; stash buff score |
| `src/easymaple/modules/capture.py` | edit | Expose rolling-avg `fps` property |
| `src/easymaple/modules/gui.py` | edit | Status bar, `update_title()`, recent-files cache hook |
| `src/easymaple/gui/menu/file.py` | edit | Open Recent submenu with `postcommand` |
| `src/easymaple/routine/routine.py` | edit | `dirty` flag + `mark_dirty()` |
| `src/easymaple/gui/edit/components.py` | edit | Call `mark_dirty()` on mutations |
| `src/easymaple/gui/edit/routine.py` | edit | Call `mark_dirty()` on mutations |
| `src/easymaple/gui/edit/commands.py` | edit | Call `mark_dirty()` on mutations |

## Verification

No automated test suite exists. Manual smoke after implementation:

1. `git status` — `resources/.cache.json` should not appear as tracked or modified.
2. Launch GUI; Settings tab shows Advanced LabelFrame with two sliders at default values.
3. With the GUI showing the game window's current scene, the live "Current match" label updates within 1 second and shows a value in `[0, 1]`.
4. Drop the rune-map slider to 0.4 → on the next bot run, rune detection fires more eagerly than at default (manual: confirm via console output of the rune-detected branch).
5. Reset button restores 0.75 / 0.9.
6. Status bar visible on every tab; FPS updates ~2 Hz; Bot label flips on F6.
7. Load a routine, edit it → title gains `*`; save → `*` clears.
8. File → Open Recent ► populated after one or more loads; clicking an entry reloads it.
