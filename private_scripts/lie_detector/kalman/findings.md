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

## 7. Evaluated on 18 clips, the Kalman still lost the *end*

The chromatic Kalman above was validated on two clips. Run over all 18 recordings
and scored on what actually passes the game — **being locked on the shape at the
end**, not the average — it kept the finish on only ~12/18 clips (~59% mean
end-lock @80px). Averages hid it: one clip averaged 80% coverage yet was locked
for **3%** of its final second. The failure mode was always the same: near the
finish the shape fades to near the texture while some texture blob is momentarily
the *stronger* global peak, and a greedy filter cannot tell "the far strong peak
is the shape, still moving" from "it is a distractor". Every greedy variant we
tried (ratio snap, reachability gate, established-lock, sustained-velocity coast)
just moved which clips it guessed wrong on — because the information to decide is
not in the current frame.

## 8. The real fix: a fixed-lag trajectory smoother

Detection was never the problem (the shape is a ~20-σ, 93–100%-global signal);
**association** was. So we stopped deciding per frame. The tracker now keeps the
top-K deviation peaks over a short window and runs a tiny DP for the smoothest
strong path through them, emitting the position a few frames back — informed by
that many **future** frames. A one-frame distractor never lies on a smooth path;
a genuinely moving shape is followed because the path continues to it. It is the
causal analog of the offline optimal-trajectory search (which reaches ~96%).

| metric (18 clips, end-focused) | chromatic **Kalman** | **fixed-lag smoother** |
|--------------------------------|----------------------|------------------------|
| **locked at end** (of 18) | ~12 | **16** |
| mean end-lock @80px | ~59% | **81%** |
| mean longest continuous lock | ~3.4 s | 3.0 s |
| mean coverage @60 / @80 | 77% / 81% | 77% / 82% |

The lesson mirrors §6: the earlier plateau was not a signal limit but an
*algorithm* limit — there the wrong *channel*, here the wrong *decision horizon*.
The few-frame output lag (~0.13 s, a few px on the slow shape) is well inside the
pass tolerance.

## 9. The cursor is the deliverable: score (and smooth) the mouse, not the target

Watching the demos exposed the last gap: the *tracker output* teleports — a
smoother path-switch or re-acquisition legitimately re-decides history and steps
the target by up to ~330 px in one frame. No human hand moves like that, and the
game grades a *cursor*, so both the runtime and the evaluation now drive a
`CursorPilot`: a PD chase with the target's velocity fed forward, hard-capped at
45 px/frame speed and 6 px/frame² acceleration, parked at the box centre during
the countdown (the shape always spawns in the middle). Feed-forward makes
constant-velocity chase essentially lag-free, so the physical smoothing is free:

| metric (19 clips, scored on what the game sees) | raw target | **piloted cursor** |
|--------------------------------------------------|-----------|--------------------|
| locked at end | 17/19 | **17/19** |
| max step anywhere | ~330 px/frame | **45 px/frame** |

The pilot's inertia even glides through the one-frame end flicker that costs the
raw target `23-17-58`. The one cursor-only miss (`22-31-07`) is the tracker
wandering onto a sustained distractor for ~1.5 s just before the finish; the raw
point snaps back instantly (a lucky "locked"), while any physical cursor pays a
few frames of catch-up — the remaining failure is the tracker's, not the
pilot's.

## 10. First live failure: a variant that fades to zero, and a tracker that tracked itself

The first live run (clip `2026-07-10_14-34-09`, white diamond on a crumpled-
paper texture) ended in the punishment room. The recording — where the green
reticle is **our own** cursor — exposed two things no human-played clip could:

1. **The reticle's own halo is a trap.** The green mask removes the reticle's
   core, but a ring 12–25 px outside it still carries **~5× the texture floor**
   in cool (B−R) deviation — the reticle's anti-aliased white/blue glow. In
   every prior clip this never mattered: the shape's ~20-σ signal always
   out-shone it (and the human's cursor rode *on* the shape). Here, the moment
   the shape faded below z≈8, the strongest stable blob in the box became the
   halo around wherever our cursor already was — the tracker locked onto
   itself and the cursor froze mid-box from ~15 s to the end.
2. **This variant fades the shape to *nothing*.** Unlike all 19 human-played
   clips (shape detectable at z≈20 to the finish), the deviation peak here
   sinks below the noise floor at 14.6 s — with half the game left. This was
   verified exhaustively: cursor-excluded argmax timeline (z≈5–6, random
   locations), luminance / desaturation channels, and velocity-integrated
   track-before-detect over ±20-frame windows (best hypothesis ≈ zero velocity
   at z≈5, i.e. static noise self-aligning). **The information is not in the
   pixels.** A human passes this variant by extrapolating the remembered
   motion and hovering — not by seeing.

What shipped, and what the corpus killed:

- **`CURSOR_MASK_R` (shipped)** — the player tells the solver where it just
  put the cursor (`process(frame, cursor_xy=...)`), and a disc around it is
  masked from every search. A tracker must never be able to track itself.
  *This is the fix for the live death-spiral.*
- **The jail is now a signal (shipped)** — the near-black "Time Remaining"
  room right after the box vanishes means the test was *failed*: the player
  reports `outcome="failed"` and the notifier keeps the bot paused instead of
  resuming (previously it would have counted the vanished box as success).
- **Border ring (killed by data)** — combat-effect colour does bleed over the
  box border, but real shapes also *end* hugging the wall: a 24 px ring cost
  `11-52-25` its end-lock and even 10 px cut `23-11-27` from 83 % to 53 %.
  The DP's smoothness already refuses transient border blobs; the ring was
  removed.
- **Blind-phase coasting (killed by data, twice)** — design 1 coasted when
  the best peak's *per-frame z* fell below ~7 and broke half the corpus
  (17/19 → 11/19): several clips end with the shape at z ≈ 5–7, beneath any
  single-frame confidence yet perfectly trackable, because weak peaks chain
  into a smooth path and the DP accumulates that evidence — per-frame
  confidence gates away this tracker's entire advantage. Design 2 gated on
  *path quality* (mean net path score: "noise cannot chain") and its premise
  died on real data too: real texture noise is **not** i.i.d. — static
  plate-residual blobs chain as smoothly as a real path (a truly blind
  phase still scores ≈ +5, median, on the failed clip), while genuinely
  trackable flickering endgames (`23-11-27`) dip *below* any workable
  threshold. There is no signal that separates "blind" from "weak shape"
  here, and in real blind phases the plain DP already does the sane thing —
  it hovers on a static residual, which is as good as any dead reckoning
  when the pixels contain nothing. Removed entirely; the masks carry the
  catastrophic modes.

No offline metric exists for this clip (its green cursor is the bot, not
ground truth), and passing the fade-to-zero variant cannot be guaranteed by
any tracker — the masks prevent it from being *lost to our own cursor*, which
is what actually happened. The 19 human-played clips are the regression suite
for these changes, and the final design scores identically to the pre-fix
baseline on them (17/19 locked at end) while closing the live failure modes.

## 11. The invisible shape was learnable all along: the shape net

After a second live failure on the fade-to-zero variant (punishment escalated
1 h → 3 h), the user played it manually — and **passed, visibly tracking the
"invisible" shape** through the whole blind phase (three recordings, three
passes, three texture variants). So the signal survives the RDP capture; it
just isn't any statistic we hand-crafted. Supervised patch analysis at the
human's cursor confirmed it: every classical feature (two-sided |dev|, B−R,
gradient deficit, temporal std, optical flow) sits at 47–67 % percentile vs
background — barely above chance, far below usable. The signal is a faint
spatio-temporal *pattern*, not a patch statistic.

So it is learned now (`lie_detector_net.py`): a 328k-param CNN takes 8 frames
(stride 2, ~0.5 s of motion context) as 16 channels (gray + B−R each) and
outputs a shape heatmap. Labels: the human's reticle across 22 recordings
(19 easy + 3 hard; the two bot-failure clips are excluded — their reticle is
the failing bot). Two label-leakage traps were closed before training:

1. the reticle must be erased from inputs (it IS the label), and
2. the erasure itself must be invisible — an inpaint smudge or a too-static
   fill at the label position would be learned, and at runtime the net would
   lock onto *our own* cursor's fill artifact (the self-tracking death spiral,
   ML edition). Fills are therefore plate + shimmer-matched noise, with decoy
   fills at random positions during training.

Held-out validation (clips never seen in training):

| held-out clip | variant | median err | within 60 px |
|---|---|---|---|
| `2026-07-09_15-09-28` | easy | 11 px | ~90 % |
| `2026-07-11_01-16-11` | **fade-to-zero** | **12 px** | **82 %** |

Twelve-pixel localization on the variant where seven hand-built detectors
measured pure noise. Runtime: 12 ms/frame on the local GPU (33 ms budget);
the net's peaks enter the existing fixed-lag smoother as extra candidates on
the same reward scale — association, the cursor pilot, jail detection and the
notifier flow are unchanged, and everything degrades to classical tracking if
the model is unavailable.

The §6 lesson completes itself: "the information is in the data" was true a
third time — first the wrong channel, then the wrong decision horizon, now
the wrong *feature class*. Hand-crafted statistics exhausted is not the same
as the data exhausted.

## Files
- `../../../src/easymaple/detection/lie_detector_solver.py` — the tracker
  (`ShapeTracker`, a fixed-lag smoother with blind-phase coasting), the
  `CursorPilot`, and the full solver
- `demo_velocity.py` — renders the velocity-vector demo (solver vs truth)
- `../eval_solver.py` — end-to-end evaluation + demo renderer
