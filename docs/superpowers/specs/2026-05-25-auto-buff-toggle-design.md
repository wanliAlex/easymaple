# Auto-buff Toggle in Settings

**Date:** 2026-05-25

## Problem

Auto-buffs run unconditionally whenever the bot is enabled. `bot.py:137` calls `self.buff.main()` on every main-loop iteration, and the active command book's `Buff` class decides which keys to press. There is no user-facing way to disable buffs without editing code or swapping command books.

Users may want to keep buffs off temporarily (e.g., during testing, when manually buffing, or for command books that don't yet implement `Buff`) while still using the bot for movement, attacks, and rune-solving.

## Goal

Add a single user-facing **Auto-buff** toggle to the Settings tab. When unchecked, the bot skips the buff call each loop iteration; everything else (movement, pet feeding, rune solving) continues unchanged.

## Non-goals

- Per-character or per-buff toggles
- Runtime hotkey to flip the toggle (the existing F6 already toggles the whole bot)
- A routine-level `$ Auto-buff` setting — the toggle is a global GUI preference

## Design

### Components

#### 1. New file: `src/easymaple/gui/settings/buffs.py`

Two classes, mirroring `gui/settings/pets.py`:

- **`Buffs(LabelFrame)`** — a "Buffs" labeled section containing one `tk.Checkbutton`.
  - `self.auto_buff = tk.BooleanVar(value=self.buff_settings.get('Auto-buff'))`
  - The checkbox text is "Auto-buff"; its `command` calls `self._on_change`, which writes the var back to `BuffSettings` and calls `save_config()`.
- **`BuffSettings(Configurable)`** — persistence class.
  - `DEFAULT_CONFIG = {'Auto-buff': True}` — preserves current behavior on fresh installs.
  - `get(key)` / `set(key, value)` mirror `PetSettings`.
  - Inherits load/save from `Configurable`, persisting to `.settings/buffs`.

#### 2. Edit `src/easymaple/gui/settings/main.py`

- Import `Buffs`.
- Instantiate `self.buffs = Buffs(column2)` and pack between `self.pets` and `self.advanced`. Column 2 will read top-to-bottom: KeyBindings → Pets → Buffs → Advanced.

#### 3. Edit `src/easymaple/modules/bot.py`

- Around line 137, gate the call:
  ```python
  if config.gui.settings.buffs.auto_buff.get():
      self.buff.main()
  ```
- Pet feeding stays untouched — the two toggles are independent.

### Data flow

```
User clicks checkbox
  → BooleanVar updated
  → Buffs._on_change writes to BuffSettings via set('Auto-buff', value)
  → BuffSettings.save_config() pickles to .settings/buffs

Bot thread, every loop iteration:
  → reads config.gui.settings.buffs.auto_buff.get()
  → calls self.buff.main() iff True
```

This matches exactly how the existing `Pets` panel works for `Auto-feed` (`bot.py:139` reads `config.gui.settings.pets.auto_feed.get()`).

### Persistence

Handled by the `Configurable` base class. The new file `.settings/buffs` will be created on first save; absence implies defaults (Auto-buff = True).

### Error handling

None needed beyond what `Configurable` already provides. The toggle has only two valid states; the var is a `BooleanVar`; there is no user-supplied free-form input.

### Testing

The project has no test suite (per CLAUDE.md `tests/` is empty). Manual verification:

1. Fresh install (no `.settings/buffs`): Settings tab shows Auto-buff checked. Bot presses buff keys.
2. Uncheck the box, start the bot: buff keys are NOT pressed; movement and pet feed still work.
3. Restart the app: checkbox state persists.
4. Re-check the box mid-run: buffs resume on the next loop iteration.

## Files touched

- **New:** `src/easymaple/gui/settings/buffs.py`
- **Edit:** `src/easymaple/gui/settings/main.py` (one import, one instantiation, one `.pack()` line)
- **Edit:** `src/easymaple/modules/bot.py` (wrap one call in an `if`)
