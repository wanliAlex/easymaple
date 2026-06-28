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
velocity). Coverage and longest-lock are essentially unchanged: bounding the
speed removes the *catastrophic* drift but does not, on its own, break the
underlying signal ceiling (the shape is invisible for long edge-hugging
stretches and turns while invisible). Sustaining a full-duration lock still needs
a stronger per-frame signal — higher-fps capture or a learned detector.

## Files
- `kalman_tracker.py` — the tracker (mirrored in `src/.../lie_detector_solver.py`)
- `demo_velocity.py` — renders the velocity-vector demo
- `../eval_solver.py` — end-to-end evaluation
