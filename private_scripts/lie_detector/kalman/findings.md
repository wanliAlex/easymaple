# Kalman tracker — findings

Investigation prompted by the observation that the tracker *"moves the cursor
very fast sometimes and drifts"* — and the hypothesis that prediction should
follow a smooth, bounded velocity.

## 1. The ground truth moves slowly and smoothly

Frame-to-frame speed of the in-game cursor (the real shape motion):

| clip | median | mean | p95 | p99 | **max** |
|------|--------|------|-----|-----|---------|
| 23-30-28 | 2.3 | 3.6 | 13.2 | 15.5 | **17.3** |
| 23-54-16 | 3.0 | 3.7 | 10.1 | 14.7 | **22.7** |

The shape **never moves faster than ~23 px/frame**, and >25 px/frame happens
0% of the time. Any estimate that moves faster than that is physically
impossible — it is a drift.

## 2. The drift *is* over-fast motion (hypothesis confirmed)

Running the earlier (un-capped) tracker:

- estimate step reached **43 px/frame** (≈2× the shape's max);
- in the 10 frames *after* any >25 px jump, the error averaged **160–280 px**
  vs ~65–94 px overall.

So the fast jumps — the deviation centroid latching onto a texture distractor —
directly cause the drift.

## 3. A hard gate makes it worse

Rejecting any measurement farther than G from the prediction *lowered* coverage
(37% → 22%). Once the prediction drifts, the gate also rejects the *corrective*
real measurement (now far from the bad prediction) and **locks the drift in**.

## 4. A robust soft update works

Use every measurement, but inflate its noise with both low confidence and
innovation distance:

```
R = (R_max − (R_max − R_min)·confidence) · (1 + (innovation / S)²)
```

A lone fast jump is heavily down-weighted (the filter coasts on its smooth
velocity), yet a *run* of consistent far measurements still pulls it back, so it
recovers. Plus a constant-velocity model with low velocity process-noise, a hard
velocity cap at 24 px/frame, and a soft edge-bounce (reflect + damp the outward
velocity at walls).

**Tuned params:** `PRIOR_SIGMA=40, KF_Q_VEL=5, INNOV_SCALE=18, R∈[40,600],
MAX_SPEED=24, EDGE_BOUNCE=0.6`.

## 5. Result

| metric | before | after |
|--------|--------|-------|
| estimate step, max | 43 px/f | **~24 px/f** (≈ GT max) |
| estimate step, p95 | ~19 px/f | **~14–16 px/f** |
| coverage <60px (cached, ideal plate) | 37% | **39%** |
| longest continuous lock | ~2.0 s | ~2.0 s |

The motion now obeys the shape's real dynamics — the jumpy fast drift is gone and
the velocity is smooth (see `demo_velocity.py`, which draws solver vs truth
velocity). But coverage and longest-lock were essentially unchanged: bounding the
speed removed the *catastrophic* drift without breaking the apparent signal
ceiling. At this point the luminance solver plateaued at ~30–36 % coverage.

## 6. The real fix was chromatic, not kinematic

The "signal ceiling" was a property of **luminance**, not of the clips. The shape
is a cool/white disc on a warm/tan texture. As it fades its *brightness* drops
into the texture's (and the ~17 grey-level/frame luminance shimmer buries it),
but its *hue* does not: it stays measurably cooler than its surroundings the
whole way down. Measured on the clips:

| signal | faded-shape detection (late frames) |
|--------|-------------------------------------|
| luminance | ~40 % |
| **B − R (blue − red)** | **~87–99 %** (local) / **81–96 %** (global) |

Switching the plate, deviation and tracking from grayscale to the **B − R
channel** — keeping the same robust Kalman, motion-compensation and z-gating —
plus seeding at the shape's current position (the acquisition seed goes stale
once the shape fades) and a **global re-acquisition** step (now reliable, because
the global cool-max *is* the shape), took it to a full-duration solve:

| metric | luminance | **chromatic (B − R)** |
|--------|-----------|----------------------|
| coverage <60px (clip 1 / clip 2) | 35 % / 36 % | **64 % / 75 %** |
| coverage <80px | 35 % / 37 % | **69 % / 78 %** |
| longest lock | ~2.0 s | **2.6–5.5 s** |

All from the **same 30 fps clips** — no higher-rate capture, no learned detector.
The earlier "needs a stronger per-frame signal" conclusion was right that the
luminance signal was exhausted, and wrong that the answer was more pixels: the
answer was a *different channel* of the pixels we already had.

## Files
- `../../../src/easymaple/detection/lie_detector_solver.py` — the tracker
  (`ShapeTracker`) and full solver
- `demo_velocity.py` — renders the velocity-vector demo (solver vs truth)
- `../eval_solver.py` — end-to-end evaluation + demo renderer
