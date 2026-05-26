# Auto-buff Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-facing "Auto-buff" checkbox in the Settings tab that gates whether `self.buff.main()` runs each bot loop iteration. Default On (preserves today's behavior).

**Architecture:** Mirror the existing `Pets` panel pattern: a `LabelFrame` with a `tk.BooleanVar` checkbox, backed by a `Configurable` subclass that pickles to `.settings/buffs`. The bot thread reads `config.gui.settings.buffs.auto_buff.get()` each loop iteration and conditionally calls `self.buff.main()`.

**Tech Stack:** Python 3.10, Tkinter, `pickle` (via `Configurable` base in `src/easymaple/common/interfaces.py`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-25-auto-buff-toggle-design.md`

**Branch:** Create a feature branch `feat/auto-buff-toggle` off `mainline` before starting Task 1.

---

## File Structure

- **Create:** `src/easymaple/gui/settings/buffs.py` — `Buffs(LabelFrame)` widget + `BuffSettings(Configurable)` persistence (mirror of `pets.py`)
- **Modify:** `src/easymaple/gui/settings/main.py` — import `Buffs`, instantiate it in column 2, pack between `pets` and `advanced`
- **Modify:** `src/easymaple/modules/bot.py` — gate the `self.buff.main()` call (around line 137) behind the new toggle

The project has no test suite (`tests/` is empty per CLAUDE.md). Verification is manual via running `python main.py` and exercising the UI.

---

## Setup

- [ ] **Step 0a: Create and check out the feature branch**

Run from repo root:

```bash
git checkout -b feat/auto-buff-toggle
```

Expected: `Switched to a new branch 'feat/auto-buff-toggle'`.

- [ ] **Step 0b: Confirm clean working tree**

Run:

```bash
git status
```

Expected: `nothing to commit, working tree clean`. If files are dirty, stop and investigate — the plan assumes a clean start.

---

## Task 1: Add the `Buffs` settings panel

**Files:**
- Create: `src/easymaple/gui/settings/buffs.py`

This new module defines the GUI widget (a single labeled checkbox) and its persistence backing. It is self-contained — it does not import from `pets.py` or `bot.py`. The structure deliberately mirrors `src/easymaple/gui/settings/pets.py` so future contributors recognize the pattern.

- [ ] **Step 1: Create `src/easymaple/gui/settings/buffs.py` with the full contents below**

```python
import tkinter as tk
from src.easymaple.gui.interfaces import LabelFrame, Frame
from src.easymaple.common.interfaces import Configurable


class Buffs(LabelFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, 'Buffs', **kwargs)

        self.buff_settings = BuffSettings('buffs')
        self.auto_buff = tk.BooleanVar(value=self.buff_settings.get('Auto-buff'))

        row = Frame(self)
        row.pack(side=tk.TOP, fill='x', expand=True, pady=5, padx=5)
        check = tk.Checkbutton(
            row,
            variable=self.auto_buff,
            text='Auto-buff',
            command=self._on_change
        )
        check.pack()

    def _on_change(self):
        self.buff_settings.set('Auto-buff', self.auto_buff.get())
        self.buff_settings.save_config()


class BuffSettings(Configurable):
    DEFAULT_CONFIG = {
        'Auto-buff': True
    }

    def get(self, key):
        return self.config[key]

    def set(self, key, value):
        assert key in self.config
        self.config[key] = value
```

Notes for the implementer:
- `LabelFrame` is the project's `ttk.LabelFrame` wrapper from `src/easymaple/gui/interfaces.py`. Its constructor signature is `(parent, name, **kwargs)` — the name `'Buffs'` becomes the labeled title.
- `Configurable.__init__` takes a single `target` string and uses it as the filename under `.settings/`. Passing `'buffs'` means state will be pickled to `.settings/buffs`.
- `DEFAULT_CONFIG = {'Auto-buff': True}` is the source of truth for the default. Because `Configurable.load_config` merges saved pickles over the defaults, existing users without a `.settings/buffs` file will start with the checkbox ON.

- [ ] **Step 2: Sanity-check the import path by running the module in isolation**

Run from repo root:

```bash
python -c "from src.easymaple.gui.settings.buffs import Buffs, BuffSettings; print('OK')"
```

Expected output: `OK`. (Any `ImportError` means the file path or imports are wrong — fix before continuing.)

- [ ] **Step 3: Commit**

```bash
git add src/easymaple/gui/settings/buffs.py
git commit -m "feat(buff): add Buffs settings panel with persistence"
```

---

## Task 2: Wire the panel into the Settings tab

**Files:**
- Modify: `src/easymaple/gui/settings/main.py`

The settings tab is laid out as two columns of `LabelFrame`s. Column 2 currently reads top-to-bottom: `KeyBindings` → `Pets` → `Advanced`. We insert `Buffs` between `Pets` and `Advanced`.

- [ ] **Step 1: Add the `Buffs` import**

In `src/easymaple/gui/settings/main.py`, find the existing imports block (lines 4-7):

```python
from src.easymaple.gui.settings.advanced import Advanced
from src.easymaple.gui.settings.keybindings import KeyBindings
from src.easymaple.gui.settings.pets import Pets
from src.easymaple.gui.settings.rune import Rune
```

Add a new line for `Buffs` (alphabetical placement after `Advanced`):

```python
from src.easymaple.gui.settings.advanced import Advanced
from src.easymaple.gui.settings.buffs import Buffs
from src.easymaple.gui.settings.keybindings import KeyBindings
from src.easymaple.gui.settings.pets import Pets
from src.easymaple.gui.settings.rune import Rune
```

- [ ] **Step 2: Instantiate and pack `Buffs` between `pets` and `advanced`**

Find this block (lines 31-34 in the current file):

```python
        self.pets = Pets(column2)
        self.pets.pack(side=tk.TOP, fill='x', expand=True, pady=(10, 0))
        self.advanced = Advanced(column2)
        self.advanced.pack(side=tk.TOP, fill='x', expand=True, pady=(10, 0))
```

Replace it with:

```python
        self.pets = Pets(column2)
        self.pets.pack(side=tk.TOP, fill='x', expand=True, pady=(10, 0))
        self.buffs = Buffs(column2)
        self.buffs.pack(side=tk.TOP, fill='x', expand=True, pady=(10, 0))
        self.advanced = Advanced(column2)
        self.advanced.pack(side=tk.TOP, fill='x', expand=True, pady=(10, 0))
```

- [ ] **Step 3: Sanity-check by importing the settings module**

Run from repo root:

```bash
python -c "from src.easymaple.gui.settings.main import Settings; print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add src/easymaple/gui/settings/main.py
git commit -m "feat(buff): show Buffs panel in Settings tab"
```

---

## Task 3: Gate `self.buff.main()` behind the toggle

**Files:**
- Modify: `src/easymaple/modules/bot.py:137`

The bot loop currently calls `self.buff.main()` unconditionally once per iteration whenever `config.enabled` is true. We wrap it in an `if` reading the new BooleanVar.

- [ ] **Step 1: Wrap the buff call in a conditional**

Find this block in `src/easymaple/modules/bot.py` (currently around lines 135-144):

```python
            if config.enabled and len(config.routine) > 0:
                # Buff and feed pets
                self.buff.main()
                pet_settings = config.gui.settings.pets
                auto_feed = pet_settings.auto_feed.get()
                num_pets = pet_settings.num_pets.get()
                now = time.time()
                if auto_feed and now - last_fed > 600 / num_pets:
                    press(self.config['Feed pet'], 1)
                    last_fed = now
```

Change `self.buff.main()` to be guarded by the new toggle. The result:

```python
            if config.enabled and len(config.routine) > 0:
                # Buff and feed pets
                if config.gui.settings.buffs.auto_buff.get():
                    self.buff.main()
                pet_settings = config.gui.settings.pets
                auto_feed = pet_settings.auto_feed.get()
                num_pets = pet_settings.num_pets.get()
                now = time.time()
                if auto_feed and now - last_fed > 600 / num_pets:
                    press(self.config['Feed pet'], 1)
                    last_fed = now
```

Implementer notes:
- Do NOT cache `config.gui.settings.buffs.auto_buff.get()` into a local at the top of the loop — read it fresh each iteration so a user toggling the box mid-run takes effect on the very next loop pass. The `.get()` call is cheap (Tk BooleanVar lookup).
- The pet feeding logic is intentionally untouched — `Auto-feed` and `Auto-buff` are independent toggles.

- [ ] **Step 2: Sanity-check by importing the bot module**

Run from repo root:

```bash
python -c "from src.easymaple.modules.bot import Bot; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add src/easymaple/modules/bot.py
git commit -m "feat(buff): skip buff.main() when Auto-buff is off"
```

---

## Task 4: Manual verification

There is no automated test suite. The implementer must launch the app and walk through the checklist below before declaring the feature done.

**Files:**
- (none modified — verification only)

- [ ] **Step 1: Back up any existing buff settings**

Before the first launch, ensure there's no stale `.settings/buffs` lying around so you can verify the fresh-install default:

```bash
ls .settings/buffs 2>/dev/null && mv .settings/buffs .settings/buffs.bak || echo "no existing file"
```

Expected: either `no existing file`, or the file gets renamed to `.settings/buffs.bak`.

- [ ] **Step 2: Fresh-install default check**

Run:

```bash
python main.py
```

In the app:
1. Open the **Settings** tab.
2. Confirm a **Buffs** section appears in the right column between **Pets** and **Advanced**.
3. Confirm the **Auto-buff** checkbox is **checked** by default.

Close the app (do NOT toggle the checkbox yet — we want to test that defaults persist without user interaction).

- [ ] **Step 3: Default-persistence check**

Run:

```bash
ls .settings/buffs
```

Expected: the file now exists (created by `Configurable.load_config` on first run when no file was present).

- [ ] **Step 4: Bot-with-buffs-on smoke test**

Open the game, launch the app again with `python main.py`, load a routine + command book that has a real `Buff` implementation (e.g., `kanna.py`), and start the bot (F6). Confirm the character presses buff keys. Stop the bot (F6).

- [ ] **Step 5: Bot-with-buffs-off check**

In the Settings tab, uncheck **Auto-buff**. Start the bot again (F6). Confirm:
- The character does NOT press buff keys.
- The character DOES still move and execute the routine.
- Pet-feeding (if enabled) still works independently.

Stop the bot (F6).

- [ ] **Step 6: Mid-run toggle check**

Start the bot with **Auto-buff unchecked** (buffs off). After a few seconds, while the bot is still running, check the box. Confirm buff keys begin firing on the next loop iteration without needing a restart.

- [ ] **Step 7: Restart-persistence check**

Stop the bot, close the app. Re-launch `python main.py`. Confirm the checkbox state matches what it was when the app closed.

- [ ] **Step 8: Restore any backup**

```bash
[ -f .settings/buffs.bak ] && mv .settings/buffs.bak .settings/buffs || echo "no backup to restore"
```

If verification fails at any step, stop and diagnose before merging.

---

## Task 5: Open the pull request

Once Task 4 passes, push the branch and open a PR.

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/auto-buff-toggle
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat(buff): add Auto-buff toggle in Settings" --body "$(cat <<'EOF'
## Summary
- Adds a `Buffs` panel in the Settings tab with a single "Auto-buff" checkbox (default On).
- Bot loop now skips `self.buff.main()` when the toggle is off; other behaviour (movement, pet feeding, rune solving) is unchanged.
- Mirrors the existing `Pets` panel pattern; persisted to `.settings/buffs`.

Spec: `docs/superpowers/specs/2026-05-25-auto-buff-toggle-design.md`

## Test plan
- [ ] Fresh launch (no `.settings/buffs`): Auto-buff checkbox shows checked.
- [ ] With Auto-buff off, bot runs but no buff keys are pressed; pet feed still works.
- [ ] Toggling mid-run takes effect on the next loop iteration without restart.
- [ ] Checkbox state persists across app restarts.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: `gh` prints the PR URL. Report this URL back to the user.

---

## Self-review notes (for the plan author)

- **Spec coverage:** All three files in the spec's "Files touched" section have dedicated tasks (1, 2, 3). Default-On behavior is set in `DEFAULT_CONFIG` (Task 1). Toggle independence from pet-feeding is preserved (Task 3). Manual verification matches the spec's testing checklist (Task 4).
- **Placeholders:** None — every step shows the actual code or command.
- **Type/name consistency:** `Buffs`, `BuffSettings`, `auto_buff`, `'Auto-buff'`, `'buffs'` target string, and `config.gui.settings.buffs.auto_buff` are used consistently across Tasks 1, 2, and 3.
