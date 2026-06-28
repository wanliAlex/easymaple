# Lie Detector mini-game solver

Auto-solver for the Lie Detector anti-bot mini-game: keep the mouse cursor on a
shape that appears in a camouflage field and fades as it moves.

- Core algorithm: `src/easymaple/detection/lie_detector_solver.py`
- Runtime driver (moves the mouse): `src/easymaple/modules/lie_detector_player.py`
- Offline eval + demo renderer: `private_scripts/lie_detector/eval_solver.py`
- Tests (synthetic, no clips needed): `tests/test_lie_detector_solver.py`
- **Kalman tracker investigation**: `private_scripts/lie_detector/kalman/`
  (`findings.md`, `kalman_tracker.py`, `demo_velocity.py`) — why the drift was
  over-fast motion and how the velocity-bounded robust update fixes it.

## How the mini-game works (from the recorded clips)

| Phase | Time (in clips) | Behaviour |
|-------|-----------------|-----------|
| Countdown | ~6–8 s | Big circle + digits (5,4,3,2,1) in the box |
| **Stationary & opaque** | ~8–12 s | A bright shape (disc/triangle) sits **still** — trivially detectable |
| **Moving & fading** | ~12 s → SUCCESS | The shape moves on an irregular path while fading into the texture |

Dwell time of the cursor on the shape determines pass/fail. The in-game cursor
is a bright **green reticle** — in the recordings that is the human's cursor
(used here as ground truth); at runtime it is our own cursor.

## Algorithm

1. **Locate the play-box** by its tan colour, large size, and dense fill
   (rejects combat effects). The box is locked on first detection.
2. **Acquire** the shape during the stationary phase: the largest bright, round
   (`circularity ≥ 0.5`), shape-sized blob, confirmed stable for several frames
   (ignores the flickering countdown digits).
3. **Detect onset** when the shape moves or fades (confirmed over a few frames),
   and buffer frames from then on.
4. **Background plate**: a per-pixel **median** over the buffered moving-phase
   frames. The texture is static and the shape covers any pixel only briefly, so
   the median recovers the background; `current − plate` isolates the shape. The
   plate is rebuilt as more frames accumulate.
5. **Track** with a **constant-velocity Kalman filter** over a Bayesian
   motion-prior measurement: predict from velocity, search a Gaussian-prior
   window around the prediction for the shape's deviation blob, and correct with
   that measurement (noise scaled by detection confidence). When the shape
   carries no signal (deep fade / edges) there is no measurement and the filter
   **coasts on velocity** — far better for a smooth track than holding position.
   Green is always masked so the cursor is never tracked.

### Why this shape

- Frame-differencing fails — the background shimmers globally.
- Global per-frame detection fails — the faded shape is the global maximum only
  ~15 % of the time (texture distractors win).
- But **locally** the shape is the dominant feature ~99 % of the time, so local
  tracking with a motion prior is the right tool.
- The motion is irregular, so pure trajectory extrapolation does not work.

## Offline results (validation vs the green-cursor ground truth)

Mean error is **not** used — tracking well early then losing the shape still
scores a fine mean. What matters for passing (accumulating dwell) is staying
locked, so we report **continuous coverage** over the moving/fading phase: the
fraction of frames within tolerance and the longest unbroken locked run.

| Clip | coverage <60px | coverage <80px | longest locked run |
|------|---------------|----------------|--------------------|
| 23-30-28 | ~30 % | ~33 % | ~2.1 s |
| 23-54-16 | ~36 % | ~40 % | ~1.3 s |

**Honest characterisation:** the solver **acquires and tracks the shape tightly
while it carries signal** (acquisition + the first ~1–2 s of the fade, errors
~10–45 px), then **loses it in the deep-fade stretch** and partially re-locks
when the shape regains contrast. It follows the motion pattern at the start but
does **not** sustain a continuous lock for the whole puzzle.

### Why it cannot (yet) track the whole puzzle — the ceiling is the signal
Measured directly from the clips:
- The shape spends ~40–67 % of the puzzle **hugging an edge** of the box.
- Where it sits, the per-frame deviation signal is present only ~37 % of the
  time at edges (vs ~58–94 % mid-field) — at edges the faded shape is
  effectively invisible in any single frame.
- The motion is smooth but **turns** during these invisible stretches, so even
  a Kalman coasting on velocity drifts.
- With an *ideal* (full-clip) background plate and best-tuned Kalman, the
  longest continuous lock is still only ~1.3–2 s. The limit is the signal in
  these two ~30 fps clips, not the tracker.

### Path to a full-duration solver
- **Higher-quality capture** — the live game likely renders at 60 fps with less
  compression than these re-encoded clips; smaller per-frame motion and stronger
  faint-shape contrast would help continuous tracking the most.
- **A learned detector** trained on frames with the cursor path as free labels
  (the project already has CUDA torch; the recorder feature can gather clips).
- **Motion-coherent temporal integration** along the tracked trajectory.

## Running

```bash
# Offline evaluation + demo video/montage (needs clips in training_data/lie_detector/)
python private_scripts/lie_detector/eval_solver.py
# -> writes *_demo.mp4 and *_montage.png under training_data/lie_detector/demo/

# Tests (no clips required)
uv run --with pytest pytest tests/test_lie_detector_solver.py -v
```

## Runtime integration (untested live)

`LieDetectorPlayer.solve()` pulls frames from the capture thread, runs the
solver, and moves the mouse via `win32api.SetCursorPos`. It is the entry point
to validate in-game. It is **not** wired into the notifier's detection path —
today the notifier still sirens + stops on detection. To auto-play, call
`LieDetectorPlayer().solve()` when the Lie Detector is detected, in place of (or
alongside) the siren, after validating it live.
