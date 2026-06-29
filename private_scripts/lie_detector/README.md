# Lie Detector mini-game solver

Auto-solver for the Lie Detector anti-bot mini-game: keep the mouse cursor on a
shape that appears in a camouflage field and fades as it moves.

- Core algorithm: `src/easymaple/detection/lie_detector_solver.py`
- Runtime driver (moves the mouse): `src/easymaple/modules/lie_detector_player.py`
- Offline eval + demo renderer: `private_scripts/lie_detector/eval_solver.py`
- Tests (synthetic, no clips needed): `tests/test_lie_detector_solver.py`
- **Tracker investigation** (how we got here): `private_scripts/lie_detector/kalman/`
  (`findings.md`) — the velocity/drift work and the chromatic breakthrough.

## How the mini-game works (from the recorded clips)

| Phase | Time (in clips) | Behaviour |
|-------|-----------------|-----------|
| Countdown | ~6–8 s | Big circle + digits (5,4,3,2,1) in the box |
| **Stationary & opaque** | ~8–12 s | A bright shape (disc/triangle) sits **still** — trivially detectable |
| **Moving & fading** | ~12 s → SUCCESS | The shape moves on an irregular path while fading into the texture |

Dwell time of the cursor on the shape determines pass/fail. The in-game cursor
is a bright **green reticle** — in the recordings that is the human's cursor
(used here as ground truth); at runtime it is our own cursor.

## The key insight: track colour, not brightness

This is what makes a full-duration solve possible. The shape is a bright
**cool/white** disc; the camouflage is **warm/tan**. While opaque it is trivially
bright, but as it moves it fades toward the texture's own brightness, and the
texture's strong per-frame **luminance shimmer** (~17 grey-levels/frame, partly
the camouflage animating, partly video compression) then buries it. Measured on
the clips, luminance detection of the faded shape collapses to ~40% by
mid-puzzle, and the shape's leave-region-out brightness contrast falls from ~2.5×
the background early to ~1.1× late — effectively invisible in any single frame.

But the texture's **hue** barely shimmers. The shape stays measurably *cooler*
than its surroundings the whole way down. Working in the **B − R** (blue minus
red) "coolness" channel instead of luminance:

| signal | faded-shape detection (late frames) |
|--------|-------------------------------------|
| luminance | ~40 % |
| **B − R (coolness)** | **~87–99 %** (local) / **81–96 %** (global) |

Everything else in the solver is in service of exploiting this chromatic signal.

## Algorithm

1. **Locate the play-box** by its tan colour, large size, and dense fill
   (rejects combat effects). Locked on first detection.
2. **Acquire** the opaque shape by **brightness** while it sits still: the
   largest bright, round, shape-sized blob, confirmed stable for several frames
   (ignores the flickering countdown digits).
3. **Background plate** in the **B − R channel**: the texture is static, so a
   per-pixel **median** over a rolling buffer of moving-phase frames recovers the
   background; `current − plate` isolates the shape's cool halo. Rebuilt as more
   frames accumulate (more frames → cleaner median).
4. **Seed at the shape's *current* position** when tracking starts: the
   acquisition seed (last bright-blob position) goes stale the moment the shape
   fades, so we re-seed at the strongest cool-deviation blob (start-spot
   excluded — it carries a fading plate artifact).
5. **Track** with a robust constant-velocity **Kalman filter** on the
   B − R deviation: *motion-compensated* (recent frames shifted by the velocity
   estimate and averaged, so the moving shape reinforces while residual shimmer
   cancels) and *z-gated* (accept a measurement only when it rises a robust
   z-score above the local floor, else coast on velocity). When lost for several
   frames, **globally re-acquire** — the chromatic signal is clean enough that
   the box-wide strongest cool blob is the shape ~81–96 % of the time.
   Green is always masked so our own cursor is never tracked.

## Offline results (validation vs the green-cursor ground truth)

Mean error is **not** used — tracking well early then losing the shape still
scores a fine mean. What matters for passing (accumulating dwell) is staying on
the shape, so we report **continuous coverage** over the moving/fading phase: the
fraction of frames within tolerance and the longest unbroken locked run.

| Clip | coverage <60px | coverage <80px | longest lock | locked at end |
|------|---------------|----------------|--------------|---------------|
| 23-30-28 (disc) | **64 %** | 69 % | 2.6 s (5.5 s @80px) | no |
| 23-54-16 (triangle) | **75 %** | 78 % | 3.8 s | yes |

The solver acquires, tracks the moving/fading shape for most of the puzzle, and
re-acquires after the brief stretches where it slips. This is a ~2–3× improvement
over the luminance-only tracker that preceded it (~30–36 % coverage).

## How we got here (and why colour)

The first solver worked entirely in **luminance** and hit a hard ceiling:
- The faded shape is the *global* brightest deviation only ~25 % of frames
  (texture distractors win); even with an oracle position prior it is the local
  max only ~50 %.
- The shape *turns while invisible*, so a Kalman coasting on velocity cannot
  bridge the longest (~2 s) blind gaps (measured drift 155–260 px). Even the
  human loses it in those gaps and re-acquires.
- Motion-compensated integration and a velocity-bounded robust update helped at
  the margins but could not manufacture signal that was not there.

The unlock was realising the lost signal was **chromatic, not luminous**: the
shape never stops being cooler than the warm texture, even when its brightness
matches. Switching the plate/deviation/tracking to the B − R channel turned
~40 % late detection into ~90 %, and the existing Kalman + a global
re-acquisition step (now reliable, because the global cool-max *is* the shape)
carried it to full-duration coverage — all from the **same 30 fps clips**, no
higher-rate capture needed.

## Remaining limits
- Brief deep-fade stretches near the box edges (e.g. clip 1 around 15 s and the
  final 19–21 s as the shape stops) where even the chromatic contrast thins and
  the cursor slips for ~1 s before re-acquiring.
- Tuned and validated on **two** clips. More recordings (the `recorder` feature
  gathers them) would harden the colour thresholds and the box/acquisition gates
  against shape/texture variants.

## Running

```bash
# Offline evaluation + demo video/montage (needs clips in training_data/lie_detector/)
python private_scripts/lie_detector/eval_solver.py
# -> writes *_demo.mp4 and *_montage.png under training_data/lie_detector/demo/

# Velocity-vector demo (solver vs ground-truth motion)
python private_scripts/lie_detector/kalman/demo_velocity.py

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
