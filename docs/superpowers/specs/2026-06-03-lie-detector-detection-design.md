# Lie Detector Detection — Design

**Date:** 2026-06-03
**Branch:** `feat/lie-detector-detection`

## Problem

MapleStory's "Lie Detector" mini-game is an anti-bot mechanic the bot cannot
solve: the player must follow a fading on-screen figure with the mouse cursor.
If the bot keeps farming through it, the account fails the test. We need to
detect it and hand control back to the human, exactly like the existing
white-room safeguard.

The game shows two distinct full-screen banners:

- **Prep** (`assets/lie_detector_prep.png`) — "The Lie Detector Mini-game will
  start in N sec. Go to a safe place." Shown for ~6 seconds before the test.
- **In progress** (`assets/lie_detector_in_progress.png`) — "Use the mouse to
  follow the fading figure." Shown while the test is running.

## Approach

Mirror the white-room / death detection already in `modules/notifier.py`. The
notifier loop already grabs the frame and computes a grayscale copy each
iteration; we add a throttled template-match check that reuses that `gray`
frame.

Template matching was validated against real screenshots at the live game
resolution (824×1045):

| | prep screenshot | in-progress screenshot |
|---|---|---|
| prep template | 0.999 | 0.260 |
| in-progress template | 0.315 | 1.000 |

A threshold of `0.9` cleanly separates true matches from cross-matches.

## Behavior (per user decisions)

Both banners trigger the **same** response:

1. Send a Discord notification (`@user`), enqueued 5× like the white-room handler.
2. Fire `_alert('siren')` — disables the bot and rings the siren until the user
   presses the Start/stop key.

The Discord message names which phase was detected (准备阶段 / 进行中) for context.

## Implementation

In `modules/notifier.py`:

- Module-level grayscale templates + constants:
  ```python
  LIE_DETECTOR_PREP_TEMPLATE     = utils.load_image('assets/lie_detector_prep.png', cv2.IMREAD_GRAYSCALE)
  LIE_DETECTOR_PROGRESS_TEMPLATE = utils.load_image('assets/lie_detector_in_progress.png', cv2.IMREAD_GRAYSCALE)
  LIE_DETECTOR_THRESHOLD = 0.9
  LIE_DETECTOR_DETECT_FREQUENCY = 10   # ~0.5s at 0.05s/loop; reliably catches the ~6s prep window
  ```
- `self.lie_detector_counter = 0` in `__init__`.
- A throttled block in `_main` (counter pattern like rune/death) that matches
  both templates against `gray`, and on a hit enqueues the Discord message and
  calls `_alert('siren')`.

## Testing

Add the repo's first pytest. Commit the two validation screenshots as fixtures
under `tests/fixtures/` and assert:

- prep template matches the prep screenshot ≥ 0.9 and the in-progress
  screenshot < 0.5.
- in-progress template matches the in-progress screenshot ≥ 0.9 and the prep
  screenshot < 0.5.

This guards the templates and threshold against regressions.

## Out of scope

- Solving the mini-game automatically (it is intentionally unsolvable by bots).
- Resolution-independent detection (templates assume the standard game window
  size, same constraint as the existing rune/elite/death templates).
