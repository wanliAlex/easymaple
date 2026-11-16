# Lie Detector — the motion solver (Oct 2026)

The previous solver (B−R plate + fixed-lag smoother + shape net, see
`../kalman/findings.md`) scored 20/22 offline but kept failing live. This
investigation re-derived the problem from all **293** recordings and found
why — and a solver that works on the invisible shape.

## 1. What the recordings actually contain

* **293 clips**: 278 passes (SUCCESS banner), 15 failures (jail). 13 of the 15
  failures have no cursor in the box at all — nobody was playing; 2 are the
  July bot runs. The passes are human-played (the cursor sits 5–150 px off
  the opaque shape's centroid during the countdown; the bot parks exactly on
  it), so their cursor tracks are genuine ground truth — 278 of them, not 22.
* The game's own rule (prep dialog): *"The time the cursor stays above the
  shape determines if you pass or fail."*

## 2. The camouflage pans; the distractors move together

From START on, the whole camouflage field **translates**: 4–8 px/frame, the
direction rotating smoothly (phase correlation response 0.5–0.85; a 6-frame
local displacement field is uniform to ±0.7 px). The earlier work read this
as "luminance shimmer". The distractor outlines/discs (copies of the shape's
motif) ride along with it — *the distractors all move in the same direction*,
exactly as hypothesised. The relief layer drifts slightly relative to the
outlines (a second layer), which leaves residue after alignment.

## 3. The real shape is invisible in any single frame

The shape is opaque until START and fades out within about a second. After
that, measured **leak-free** (annulus 28–55 px around the human's cursor,
outside the reticle and its halo; 24 clips, ~1300 frames): no brightness,
coolness (B−R) or edge excess — median z ≈ 0 from 10% of the game to the end.
Cursor-centred averages show nothing either. There is no static signal left.

## 4. …but it is visible in motion

Align reference frames to the field's motion so everything that moves with
the distractors cancels; what remains is whatever moves on its own. The
motion-compensated residual around the human's cursor sits at the
**88–99th percentile** of the box for the *whole* game, last second included
(median z 3–7). The human sees the shape the same way — as a patch of texture
that does not move with the camouflage.

## 5. Why the previous solver failed live: it tracked the human's cursor

Every recording has the human's reticle sitting on the target. The old B−R
tracker masked the green pixels, but the reticle's cool halo survives — and
the cool halo *is* what it followed. Run under runtime conditions (the
reticle masked like the live player masks its own cursor):

| previous solver, 23 clips | as validated | reticle masked (= live) |
|---|---|---|
| locked at end | 22/23 | **0/23** |
| coverage @60 px | 76% | **23%** |

Offline it was scoring the human. Live, with only its own (masked) cursor in
the frame, there was nothing to follow.

## 6. The motion solver

1. **Box + acquisition** as before; START is detected as the moment the
   field starts to pan (not from the shape).
2. **Align** 4 reference frames to the current one by the field motion
   (phase correlation, integer shifts, half resolution). Inputs: current
   frame + 4 aligned differences.
3. **MotionNet**: a 7×7-receptive-field fully-convolutional scorer (52k
   params) trained on the 232 training clips to say "this pixel is near the
   shape". Labels: a ring around the human's cursor vs anything ≥120 px away.
4. **Leak-proof by construction**: every cursor (and its warped copies in the
   reference frames) is blanked with a 30 px disc, and only pixels whose
   receptive field cannot reach a blanked disc are ever supervised or
   scored. Tested: randomising everything inside the discs changes the
   output at usable pixels by exactly 0; scoring against the cursor from 3 s
   later collapses to chance.
5. **Track-before-detect**: a grid Bayes filter accumulates the pooled
   evidence along smooth paths (weak, flickering evidence that a per-frame
   detector gets wrong adds up on the shape's path), seeded where the opaque
   shape was at START.
6. **CursorPilot** unchanged (human speed/acceleration caps).

## 7. Results

**46 held-out recordings** (every 6th clip, never seen in training), scored
START → SUCCESS on the piloted cursor against the human's cursor. "Live
conditions" = every cursor in the frame blanked/masked, our own included —
for the motion solver that is the full runtime class replayed on the raw
recordings (`replay.py`), box detection and START detection included.

| solver | conditions | locked at end @60 px | @80 px | coverage @60 | @80 | longest lock |
|---|---|---|---|---|---|---|
| previous solver | as validated (it can see the reticle) | 43/46 | 44/46 | 77% | 83% | 3.4 s |
| previous solver | **live conditions** | **0/46** | 0/46 | **22%** | 26% | 1.4 s |
| hand-crafted motion residual + grid HMM | live (23-clip sample) | 12/23 | — | 41% | — | 1.9 s |
| **motion solver** | **live conditions** | **42/46** | **45/46** | **86%** | **92%** | **4.3 s** |

* The hard fade-to-invisible clip `2026-07-11_01-16-11` (held out): 86%
  coverage, locked at the end (previous solver live: 14%, lost).
* Leak tests (`leak_test.py`): randomising everything inside the blanked
  cursor discs changes the output at usable pixels by **0.0**; scoring
  against the cursor from 3 s later drops localisation to chance
  (median percentile 0.57, wins 4% vs 0.99 / 52% for the true cursor).
* Latency per frame while tracking: median 18–26 ms, p95 ≤ 36 ms on the
  laptop RTX 4060; CPU-only median 33 ms / p95 38 ms — real time either way.
* Bigger is not better here: a 6-reference, width-64 variant (trained on the
  5070 Ti box) scored 42/46 · 45/46 · 87% · 93% — the same four end misses,
  +1 point of coverage, ~20% more compute. The shipped model is the 4-reference,
  width-48 one (`assets/models/lie_detector_motion.pt`, 52k params).
* The causal design (reference frames −7, −5, −3, −1) means estimates are
  for the *current* frame: no latency to extrapolate over. A model that also
  looked 2–4 frames ahead was no more accurate per frame and lost ~4 points
  of coverage to the lag.

**Remaining misses.** 4/46 clips lose the final second at 60 px (1/46 at
80 px). In the ones inspected the tracker is on the evidence blob but
60–80 px from where the human held the cursor — typically the shape hugging
a wall at the end, where the pooled evidence is clipped by the border. The
human only has to be *somewhere* on the shape, so part of this is the
metric; part is real. Not yet run live — watch the first real Lie Detector.

## 8. First live games (2026-10-11): one pass, one fail — and a cadence bug

Two live games ran on the motion solver (auto mode): 19:08 passed, 19:30 failed
(24 h jail). Post-mortem from the recording of the failed one:

* **The live player ran at ~15 Hz, not 30.** It slept a fixed 1/30 s *after*
  each frame's processing (~47% of the recorded frames show no cursor motion
  vs ~12% in human play). The solver picked its reference frames *by count*,
  so live they sat at twice the time gap it was trained on (1/30–7/30 s), and
  the CursorPilot, stepping once per processed frame, moved at half its
  real-time speed. The offline replay processed every frame, so it never saw
  this. Simulating exactly that live setup on the 46 held-out clips:

  | | locked at end @60 | coverage @60 / @80 |
  |---|---|---|
  | live setup (15 Hz, refs by count, pilot per frame) | 40/46 | 77% / 85% |
  | fixed (refs by capture time, pilot per elapsed time), 15 Hz | 44/46 | 86% / 92% |

* **Late onto the shape at the start:** the play-box opened only 0.7 s before
  the shape started moving and the cursor began ~350 px away; the half-speed
  pilot reached the shape ~0.4 s after it started moving.
* On the failed recording the fixed solver (offline) follows a different path
  from the live bot after ~10 s (median 128 px apart), along a strong evidence
  trail; there is no ground truth for that clip, so whether it would have
  passed cannot be proven.

Runtime changes: references chosen by **capture time**; the player processes
every new frame (no fixed sleep) and steps the pilot by elapsed time; the
solver scores at most every 1/30 s (the tracker's tuned rate) while extra
frames refresh the extrapolated target; while a Lie Detector is handled the
capture thread skips its minimap work and runs at ~60 Hz; on the prep banner
the cursor pre-positions at where the box opened last game; the model is
loaded and warmed at startup; **every game saves a log** (live Hz, ms/frame,
raw half-res frames, solver path) to `training_data/lie_detector/solver_logs/`.
Per-frame cost on an idle laptop: ~13 ms (inference itself was never the
bottleneck).

Follow-ups: the elapsed-time pilot rounded each frame's step count on its own,
so at 60 Hz capture every frame got a full 1/30 s step (double speed); it now
carries the remainder (`_pilot_steps`). The pilot was made faster — speed cap
45 → 60 px/step, accel 6 → 9, spring 0.14 → 0.18: a 350 px trip settles in
0.53 s instead of 0.67 s, and the closed-loop replay is unchanged (42/46 ·
45/46 · 86% · 92%). Pilot speed was never what limited the results — the
cursor already sits ~5 px from the solver's target; misses are the target
being off. Stiffer settings chase tracker jitter (one borderline clip,
`2026-09-14_19-58-37`, flips either way with small pilot changes).
`replay.py --pilot speed=..,accel=..,kp=..` evaluates alternatives.

## 9. Systematic review (2026-10-12): live-only failure modes

Five parallel reviews (timing, train/serve skew, coordinates, game flow,
solver internals), each finding verified before fixing. Found and fixed:

* **OpenCV `phaseCorrelate` quirks** (4.9): +0.5 px shift on any axis padded
  to an *odd* FFT size (half-res height 217–225 → 225: identical frames read
  (0, 0.5)), and in-place windowing of its inputs when no padding is needed
  (216×360). Live repeats were never flagged as duplicates; a 30 fps RDP
  stream captured at 60 Hz then starved START (5 of 8 moving frames needed,
  at most 4 possible): the cursor would have stayed on the faded blob all
  game. Now: pre-windowed, unpadded, even-sized copies (`pc_size`), speed
  measured against the last distinct frame, duplicates never scored.
  (`build_cache.py` has the same bug: 18–31% of training clips were aligned
  with the bias; the runtime is now *more* accurate than training.)
* **Clock**: the recordings are ~24.6 fps (the recorder slept 1/30 s after
  each write), not 30 — `FRAME_DT = 30/738`. The recorder now saves each
  clip's frame times (`*_t.npy`); the capture thread stamps every frame
  (`frame_stamped`) and the player passes that time; `perf_counter`, not
  `monotonic` (15.6 ms ticks on Windows); 1 ms timer resolution during a game.
* **False box before the game** (3/295 clips): combat effects passed the box
  gates for a frame, the solver locked it, lost it, and the player declared
  the game over 1.5 s later — before the real one opened (unplayed → jail).
  Now: gates tightened to the trained range (690–770 × 410–480), a box must
  be detected consistently for 0.15 s, before START it keeps re-detecting and
  re-locks to a better stable box, box loss is time-based (0.5 s), and the
  game can only end after TRACK.
* **The play-box was clipped**: `detect_play_box` only searches the central
  region, cutting the field's bottom ~48 px and left ~13 px — where the
  shape is in 8% of final-second frames, unseen and unreachable (and unseen
  by the cache's ground truth, so offline numbers hid it). `refine_box` grows
  the box to the field's real edges.
* **Outcome handling**: a capture stall no longer reads as a pass (game over
  needs ≥10 new frames without the box); a missed game ending in the jail is
  `failed`, not `no_box`; per-frame exceptions are caught (30 in a row →
  `error`, alerted like manual mode); a failed model load is retried and,
  if still unavailable, the game is handed to the human instead of the old
  solver; `remember_box` only after a played game; the game log is written
  after acting on the outcome (no more ~25 s compressed save before the
  alert), keeps the last ~10 s of raw frames, and only the newest 10 logs.
* **Solver robustness**: a frozen stream no longer crashes TRACK (KeyError
  after 48 frames); extrapolation is bounded and clipped to the box.

Live-like replays of the 46 held-out clips (`replay.py` now stamps frames at
the clips' real rate and steps the pilot exactly like the player):

| | before | after |
|---|---|---|
| recorded rate | 42/46 · 45/46 · 86% · 92% | 43/46 · 45/46 · 86% · 93% |
| per-clip real timing | 41/46 · 44/46 · 86% · 92% | 42/46 · 43/46 · 86% · 93% |
| 60 Hz capture of a 30 fps stream (live) | **30/46** · 33/46 · 68% · 74% | **41/46** · 43/46 · 85% · 92% |

(locked at end @60 · @80 px · coverage @60 · @80; box refinement not yet
included in these rows.)

Box refinement, scored against the human reticle found anywhere in the real
field (the cache's ground truth stops at the clipped crop): clipped box
43/46 · 45/46 · 87.2% · 94.1%, longest 4.57 s → refined 43/46 · 45/46 ·
88.1% · 94.5%, longest 4.92 s. Four clips flip (2 each way): the shape-at-the-
bottom clip `2026-09-03_21-18-49` goes from lost (75%) to locked (96%);
`2026-06-29_20-37-58`, already borderline, loses its end. Refined box in the
60 Hz live simulation (cache GT, which undervalues it): 40/46 · 43/46 · 86% ·
93%.

Known, not yet addressed: the RDP round trip (~67 ms between moving the
mouse and the reticle moving in the stream) is not compensated (replay with
100 ms lag: −1 clip, −1.4 points of coverage) — measure it from the new game
logs first; a box lost mid-game cannot re-enter TRACK (never seen in the
recordings); the cache's onset lags the runtime START, so the START hand-off
is not in the offline numbers; a retrain should use the full field, recomputed
onsets, the fixed phase correlation, per-frame timestamps, and exclude
bot-played clips.

## 10. Live 2026-10-13: 9/10 passed; post-mortem of the failure

Ten auto games (30 Hz processing, ~31 ms/frame, 0 errors): nine passed, the
11:35 one failed. The player showed the cursor losing the shape at 0:14 and
finding it at 0:16 — the clip plays at its 30 fps container rate but was
recorded at 24.9 fps, so that is 16.9–19.3 s real time, ~2.4 s of a 10.5 s
game (the field pans from 10.0 s, during the countdown; the START banner is at
11.9 s). The solver log and the clip align to within a frame.

What happened (raw MotionNet logits replayed with the logged cursor; the shape
shows as a ring of high logits around its moving outline):

1. 14.7–16.0 s the shape stayed near the **bottom wall**. There the usable
   part of the evidence disc around the estimate fell to 4–10% (`DEN_MIN` is
   8%): half the disc is outside the field, the pan was bringing new texture in
   from the bottom (the −7/−5 references do not cover a ~14 half-res px strip
   there), and our own cursor's exclusion disc takes most of the rest
   (mid-field the same fraction is ~40%).
2. ~16.0–16.5 s the logits go quiet almost everywhere — the shape nearly
   vanishes from the motion signal — and it moves up-right; the tracker stays
   at the wall and then drifts up-left on clutter.
3. From ~17.0 s the ring is clearly visible again 100–150 px away
   ((675, 444) at 17.4 s, (690, 395) at 18.2 s, the right wall at 18.7 s), but
   the tracker only jumps there at 18.8 s (live); the cursor arrives at 19.3 s.

Raising the tracker's teleport floor (1e-7 → 1e-3) changes nothing: a far
cell only needs ~4–8 frames of evidence ≈1 to win. The stale spot keeps
winning because the pooled evidence there is a *mean over very few pixels* —
noisy, so often high.

Is it the walls? Not in general. The 46 held-out clips replayed live-like
(refined box, pilot in the loop, scored against the human reticle anywhere in
the field): cursor on the shape 88% when the human is < 20 px from a wall,
91% at 20–60 px, 91% beyond 130 px; off-shape frames are not concentrated at
walls (10% of them vs 13% of all frames); the target is pulled only ~8–10 px
toward a wall. Half of all off-shape time is losses > 0.5 s, but only one loss
in 46 clips exceeds 2 s: a 2.4 s loss is rare, and it is re-acquisition after
the shape fades that costs it.

**Fix: borrow reference coverage at the walls.** A reference that does not
cover a pixel (texture that entered at the wall in the last few frames) now
takes the diff of the nearest newer reference that does, and a pixel is usable
if any reference covers it (before: only if all four did). Leak-proofing is
unchanged — diffs are borrowed at the same current-frame pixel and every
reference's cursor disc is blanked there (`test_borrowed_diffs_never_carry_a_cursor`).
No retrain. 46 held-out clips, live-like, full-field GT:

| | locked at end @60 | coverage @60 | worst clip | losses > 2 s |
|---|---|---|---|---|
| before | 43/46 | 88.1% | 66% | 1 |
| borrowed coverage | 44/46 | 88.9% | 75% | 0 |
| shrink few-pixel means (k=0.3) | 42/46 | 86.6% | 61% | 2 |
| both | 44/46 | 87.5% | 59% | 2 |
| *with the header trim (box logic as shipped):* | | | | |
| **no borrowing (shipped)** | **43/46** | **88.3%** | 69% | 1 |
| borrowing (reverted, see below) | 43/46 | 88.5% | 69% | 1 |

**Caution — the closed loop is chaotic.** The header trim moves 22 of the 46
boxes by ~1 px, and that alone flips clips both ways (`2026-10-03_22-45-12`
77% locked → 69% lost). Like for like, borrowing gains +0.16 ± 0.48 points of
coverage per clip (5 clips better, 7 worse by > 2 points): **no measurable
effect**; the first comparison's +1 clip was noise of the same kind. (Jittering
the pilot's start by ±4 px is *not* a usable noise probe — it washes out and
gives identical runs.) It also did not rescue the 11:35 clip in replay, and
it was **reverted**: on the live logs the net reads the borrowed strip as
shape — away from our cursor, pooled evidence within ~30 px of the bottom wall
(where the texture entered in these games) is +0.06–0.11 with borrowing vs
+0.04–0.05 without, the interior ~0. `build_input_fast` keeps its rewrite
(differences written straight into the output): 3.0 ms/frame vs ~6.5 ms
(live processing is ~31 ms of a 33 ms frame). Shrinking means over few usable
pixels toward 0 hurts and was dropped.

**Human ground truth for the failed game** (`label_clip.py`, the user
following the shape at half speed; `compare_gt.py`): the bot's cursor was
within 60 px of the user's 63% of the game; during the countdown (opaque
shape) they agree to 5–10 px, afterwards the typical gap is 40–70 px (both on
a ~120 px shape, different parts — so 60 px understates on-shape time). One
real loss: 16.2–19.0 s. The labels confirm the reconstruction and correct it:
the shape did not vanish and reappear — it **moved steadily away** from the
bottom wall from 16.0 s (584, 556) → (695, 394) at 18.0 s → (793, 385) at
19.0 s, while the tracker stayed at the wall and drifted left. Before that,
15.0–16.0 s, the estimate sat 35–50 px *below* the user's cursor, nearer the
wall. Throughout the loss the pooled evidence at the user's position ranks in
the top 2–17% of the map; the stale spot near the wall was higher at
16.35–16.75 s (1.1–1.3 vs 0.5–0.8), lower from ~17.0 s, and the tracker
needed until ~18.3 s (replay) to climb back.

Tracker changes scored against these labels (replay with the live box and
cursor, target within 60 px of the user's cursor, 12–22.3 s): current 73%;
*fading memory* (prior raised to γ each step, γ = 0.95 … 0.7) 61% … 50% —
worse, clutter grabs it more often than recovery speeds up; the teleport
floor (1e-7 → 1e-3) changes nothing. A self-leak from our own rendered
cursor (RDP artifacts past the blanked disc) was tested on all ten live logs:
around our cursor *in transit* (> 80 px behind the target, > 400 px/s — a
position the evidence did not choose) the logit profile is flat (~0.6), not
peaked at the disc edge as a leak would be; reticle detection misses no
in-game frame. No leak found (n = 19 transit frames: weak).

So the tracker is not the lever: the shape is visible to the net the whole
time but only a little above wall-adjacent clutter. The fix is a more
discriminative detector — retrain on the full field (the training crops were
the detector's clipped box, so the net never saw the bottom ~48 px next to
the wall), with the fixed pipeline, and with **live games labelled by the
user** (our own cursor drawn, live RDP rendering), holding some labelled live
games out as the test that decides whether a model ships.

Any change must be judged over perturbed runs (e.g. ±1 px box offsets), not
one replay.

Also found:
* **The live box included the dialog header.** While the dialog opens
  (~0.17 s) `detect_play_box` returns a box starting at the dark
  "LIE DETECTOR" header, 19 px above the field; the box locked inside that
  window and the field started panning before a re-lock was allowed — every
  live box on 2026-10-13 started at y=126–130 instead of 145 (the training
  crops never contain the header). `refine_box` now also trims edges that are
  not field.
* **Failure logs were rotated away** (keep-10: the day's passes deleted the
  2026-10-11 failures). Log names now carry the outcome; only completed games
  rotate.

## 11. Retrain on the full field — and the alignment was following the shape

Rebuilding the cache for the retrain (`build_cache.py` now crops the refined
box like the runtime, aligns like the runtime, and skips bot-played clips)
exposed a runtime bug. **The field alignment was Hanning-windowed**, and the
window weights the field's centre — exactly where the opaque shape sits still
right after START (and where the invisible shape's own motion counts most
later). Phase correlation then follows the shape instead of the panning
field: on frames right after START it reads ~(0, 0) while the field moves
3 px/frame, and the differences show the whole field as residue and the shape
as "no change" — the opposite of what the net needs.

Measured as the share of reference pairs (offset −7) whose rounded shift is
> 2 px from the best whole-pixel alignment (brute-force minimum of the mean
absolute difference):

| | windowed (shipped) | unwindowed |
|---|---|---|
| 10 live games 2026-10-13, TRACK frames | 8–29% | 0–2% |
| the failed 11:35 game, ~12–14 s (first 2 s of its frame log) | 67% | — |
| 8 recorded clips, offsets −1…−7, rounded shift has a clearly higher residual than the best | 20–41% | 4–9% |

Unwindowed correlation of the `pc_size` crop (no padding, so no +0.5 px bias)
is correct on all of these. The old cache had the same problem (OpenCV's
internal window + odd padding), so the shipped net was trained on
misaligned references as well — part of the "clutter" it has to beat was
our own alignment residue. The unwindowed pan onset is also often seconds
earlier: the windowed speed stayed low while the still shape dominated, so
the cache's onset sat in the countdown's late part (one clip: 3.8 s late).
Fixed in `LM.pc_crop` (runtime) and `build_cache.py`;
`test_alignment_follows_the_field_not_a_still_shape_at_its_centre`.

Bot-played clips (from 2026-10-11 19:00; the reticle is our own cursor) are
no longer cached — the old cache had picked up two. The 46 held-out clips are
frozen in `val_clips.txt`.

**The retrain did not beat the shipped model.** Same recipe as the shipped
net (4 references, width 48, 14 epochs), two seeds, on the new cache
(`motion_cache_full`: full field, unwindowed alignment, 232 training clips,
64k frames). Leak tests pass (0.0 change; time-shifted labels 5% wins).
Closed-loop replays of the 46 held-out clips, 5 runs each (box shifted
0/±1 px), scored from the first cache's onsets against the full-field
reticle:

| | coverage @60 | locked @60 | coverage @80 | locked @80 | worst clip | labelled live game @60 / @80 |
|---|---|---|---|---|---|---|
| **shipped net, windowed (live today)** | **87.0%** | **94.8%** | **93.3%** | 97.0% | 66% | **59% / 73%** |
| shipped net, unwindowed | 86.4% | 96.5% | 93.3% | 97.0% | 63% | 57% / 68% |
| new net seed 1 | 85.0% | 94.3% | 92.6% | 98.7% | 58% | 52% / 60% |
| new net seed 2 | 85.1% | 94.8% | 92.5% | 97.8% | 56% | 52% / 61% |

(The labelled live game column is the failed 11:35 game. A second labelled
game, the passed 10:53 one: the live bot was within 60 px of the user's
cursor 91% of the time, median 23 px — the labels are precise — and the
replays agree: shipped net 90% @60 / 94% @80, new nets 88–89% / 94%. Third,
the passed 10:35 game: live bot 91%, median 25 px; replays shipped 91% / 96%,
new 91% / 98%. Fourth, the passed 06:19 game (picked by `rank_unlabelled.py`:
the two nets disagreed most there): live bot only 63% (slips of 2.3, 0.7 and
1.5 s); replays shipped 68% / 79%, new 59–61% / 75–77%. The easy games tie;
on both hard ones the new net loses by 7–9 points. Fifth, 10-12 21:32 (no
solver log; scored with the rendered reticle blanked only): shipped 76% / 82%,
new 76–77% / 87%.)

**Ship rule (agreed with the user):** every game the current bot played has
passed, so it is the baseline and nothing may regress. A candidate model or
solver change ships only if, against the current one, it is no worse beyond
noise on the 46 held-out clips (5 perturbed runs each, `ev.py heldout`) *and*
no worse on any user-labelled live game (`ev.py live`, 5 runs each).
`rank_unlabelled.py` picks the next games worth labelling (where two models
disagree) into `label_queue.txt`, which `label_clip.py` serves first.

New − shipped: −1.9 ± 0.6 points of coverage per clip (18 clips worse by
> 2 points, 4 better); the two seeds agree to 0.1 points. The new net is
behind at every tolerance (within 40 px of the human's cursor 64% vs 70%,
120 px 96.6% vs 97.3%) and spends more time lost (> 120 px for > 0.5 s:
1.3% vs 0.8%) — not a metric artefact.

Yet per frame, on identical inputs (the new cache, 2105 held-out frames), the
new net is *better*: the human's cursor beats every spot > 50 px away in 51%
of frames vs 48% (first quarter of the game 63% vs 56%, last fifth 45% vs
41%, middle equal; near walls equal, 44% vs 45%). Explanations tested and
rejected:
* *Evidence scale.* The new net's evidence is ~1.6× larger (logit std 0.96
  vs 0.75), so `beta` = 2 trusts single frames more. `beta` 1.0 / 1.25 / 1.5
  (clip scaled to match): −2.3 / −1.9 / −1.9 points — no recovery.
* *Countdown labels.* The earlier onsets add 2.3% of training frames, and in
  them the cursor is on the opaque shape (median 8 half-res px).
* *Our own cursor's hole* removing body-centred evidence. Without blanking our
  cursor both nets lose ~2 points and the gap stays (−2.0).

So per-frame localisation does not predict closed-loop tracking here; what
the tracker needs (temporally consistent evidence, little persistent
clutter) is not what the per-frame win rate measures. Not shipped. **Each
net now aligns the way it was trained** (`pc_window` in the checkpoint;
absent = windowed): with the shipped net the live solver is bit-identical to
before (replays reproduce exactly). `train.py` writes `pc_window: False`.

Also found: the cache's ground truth takes the largest green blob, and the
START banner's glow wins for some frames (e.g. `2026-09-10_18-18-00` around
frame 352: "cursor" on the text) — mislabelled training frames and mis-scored
frames in both caches. `train.py`'s OneCycle step count was one short per
epoch (partial last batch): torch 2.11 raises on the final step.

Next candidates (not done): ablate which change hurts (full field vs
alignment, one retrain each, ~35 min on the box); fix the START-glow labels;
pick checkpoints by a closed-loop score rather than the per-frame win rate;
more user-labelled live games — the one labelled game is the closest thing
to the real target, and it agrees with the held-out replays.

## 12. Overnight 2026-10-14: clutter that stays put in the box

**Shipped: two evidence fixes in the runtime solver, same net.** A
`ClutterBackground` (τ = 0.5 s, k = 0.5) removes evidence that stays put in
the box (the shape's start-position imprint). `DEN_FLOOR` = 0.4 stops
few-pixel means at the walls from spiking. On the 8 user-labelled live games,
coverage rises from 79.6% to 93.3% @60 px (86.9% → 97.0% @80), every game
better (the failed 11:35 one least: +1.6 / +5.1). On the 46 held-out clips:
+2.4 ± 0.9 points @60, locked at end @60 0.948 → 0.978, @80 0.970 → 1.000.
Off-shape time on the labelled games falls from 12.2% to 2.5%. Cost:
0.02 ms/frame.

### The live replay was unfair to any candidate, and scored past the game

* `ev.py live` blanked the **live bot's logged cursor**, not the candidate's
  own. Wherever a candidate left the shipped bot's path, its view had a hole
  where the shipped bot was (on the shape, when the candidate was lost) and
  none where its own cursor would be. Now `--own` simulates and blanks the
  candidate's own cursor (the live bot's rendered reticle is still blanked by
  detection) and scores the **piloted cursor** — what the game counts.
* The labels run 1–2.7 s past the game: the user presses Q on seeing SUCCESS,
  at half speed. Scoring now stops at the SUCCESS banner, or for the failed
  11:35 game when the field stops moving (22.08 s) (`live_end.json`).
* Three more games labelled (10-13 01:09, 01:54, 02:38): 8 games.

### Diagnosis: a fixed hotspot at the shape's start position

In the hard games the tracker leaves the shape for a spot **fixed to the
box**. Time-averaged evidence away from the user's label (> 100 px) peaks at
the same box position — about (340, 260) px into the box, its centre, where
the opaque shape waits during the countdown — in 7 of the 8 labelled games
and in **all 46 held-out clips** (mean evidence 0.5–0.65 there, ~0.01
elsewhere). The temporal std of the raw frames shows a faint, shape-sized
static imprint there. To the net it looks exactly like the shape: texture
that does not move with the field. Both nets see it. The new net's evidence
is ~1.6× larger, so in 06:19 at 18.0 s its tracker teleports onto it after
~8 frames (clutter +1.4–2.0 vs +0.45–0.85 at the label). The shipped net's
margin is about half that, so it holds, which is why the new net lost 06:19.
11:35's loss (16.3–18.1 s): the estimate slid onto clutter at the bottom wall
(x ≈ 400 px), then onto the same centre spot.

### Fix: subtract what has stayed put

`ClutterBackground` keeps an exponential average (time constant τ, by capture
time) of each grid position's evidence and subtracts k × its positive part
before the tracker sees it. The shape keeps moving (it stays within 60 px of
a spot for 0.68 s median, 1.2 s p90, in the labels), so the average is mostly
clutter. Cost 0.02 ms/frame. Live replays (`--own`, 5 runs each,
coverage @60 / @80):

| game | shipped | + clutter (0.5 s, 0.5) |
|---|---|---|
| 10-12 21:32 | 0.776 / 0.861 | 0.808 / 0.952 |
| 10-13 01:09 | 0.692 / 0.757 | 0.775 / 0.833 |
| 10-13 01:54 | 0.750 / 0.858 | 0.866 / 0.968 |
| 10-13 02:38 | 0.936 / 0.949 | 0.951 / 0.963 |
| 10-13 06:19 | 0.723 / 0.834 | 0.947 / 0.995 |
| 10-13 10:35 | 0.904 / 0.964 | 0.962 / 0.998 |
| 10-13 10:53 | 0.967 / 1.000 | 0.970 / 1.000 |
| 10-13 11:35 (failed live) | 0.618 / 0.728 | 0.664 / 0.766 |
| **mean** | **0.796 / 0.869** | **0.868 / 0.934** |

τ 0.4–0.6 s at k = 0.5 is a plateau (mean 0.859–0.871 @60, every game no
worse). Longer memory or a stronger weight gains more on the hard games but
starts eating slow-moving shapes: τ = 1 s costs 21:32 5 points, τ = 0.5 s at
k = 0.75 gives a 0.892 mean but −2.1 ± 0.7 points on the held-out clips. On the
final second (end60, 25 frames) the mean rises 0.64 → 0.74. 21:32 and 11:35
read 6–7 points lower there, but the trajectories are the same to a few px,
crossing the 60 px line (e.g. 67 vs 73 px).

Tried and dropped:
* A rolling minimum over 1.5–4 s instead of the average: +1–2 points only
  (the imprint's evidence flickers, so its minimum is low).
* Not updating the background near the estimate: −20 to −45 points. The
  shape's leading edge is learned before the tracker reaches it, then frozen.
* Not suppressing near the estimate.
* The shipped net + new net ensemble (evidence averaged): still −7 on 06:19.
* The new nets + clutter: mean 0.848–0.855, worse than the shipped net +
  clutter.

### Walls: means over few pixels (`DEN_FLOOR` = 0.4)

With the centre imprint handled, where was the target when off the shape
(> 80 px from the label, share of all frames)?

| | off-shape | box centre | within 50 px of a wall | elsewhere |
|---|---|---|---|---|
| shipped | 12.2% | 2.6% | 6.3% | 3.4% |
| + clutter | 5.9% | 0.2% | 3.6% | 2.1% |
| + clutter + floor 0.4 | **2.5%** | 0.2% | 0.2% | 2.1% |

The pooled evidence is a mean over the disc's usable pixels. Mid-field a disc
is fully usable (median 1.00), but within 10 half-res px of a wall it is 0.44
(p10 0.19): half the disc lies outside the field, and texture the pan just
brought in has no reference. A mean over so few pixels is noisy, and its
spikes pull the tracker (§10 saw this in 11:35). `evidence_grid` now divides
by max(den, `DEN_FLOOR`), so a disc with fewer usable pixels counts the
missing ones as 0. §10's shrinkage, num / (den + 0.3), scaled every position,
mid-field included, and hurt; the floor leaves full discs alone. At the
tracker's own position the cursor hole leaves den ≈ 0.54 (p10 0.43), so
floors above ~0.5 start shrinking the tracked shape itself. On top of clutter
0.5 / 0.5:

| floor | held-out coverage @60 (vs shipped) | locked @60 (clips) | locked @80 | live mean @60 / @80 | worst live game @60 |
|---|---|---|---|---|---|
| — (clutter only) | +0.07 ± 0.51 | −1.8 | 0.978 | 0.868 / 0.934 | +0.3 |
| 0.3 | +3.12 ± 0.78 | −0.6 | 1.000 | 0.910 / 0.955 | +1.4 |
| **0.4** | **+2.42 ± 0.93** | **+1.4** | **1.000** | **0.933 / 0.970** | **+0.9** |
| 0.5 | +0.44 ± 1.05 | +1.4 | — | 0.939 / 0.971 | +0.8 |
| 0.7 | — | — | — | 0.942 / 0.970 | +0.8 |
| 1.0 | — | — | — | 0.926 / 0.956 | −1.8 |
| 0.3, no clutter | — | — | — | 0.844 / 0.907 | −3.2 |

The floor needs the clutter background: alone it costs 11:35. At 0.4 the
held-out clips gain on both coverage and end-lock **at zero lag**: locked
@60 0.948 → 0.978, @80 0.970 → 1.000, longest lock 4.13 → 4.38 s, worst clip
0.66 → 0.66. With lag allowed (82–246 ms): +4.1 to +7.9 points, +2.8 to +4.2
clips. Live, per game, vs shipped (@60 / @80 / end60, points):

| 21:32 | 01:09 | 01:54 | 02:38 | 06:19 | 10:35 | 10:53 | 11:35 |
|---|---|---|---|---|---|---|---|
| +20 / +14 / +10 | +31 / +24 / +94 | +16 / +12 / +42 | +6 / +5 / 0 | +25 / +17 / +1 | +10 / +4 / +24 | +1 / 0 / 0 | +2 / +5 / +5 |

How strong should the clutter weight be with the floor in? 46 held-out clips
(zero lag / with 123 ms of human lag allowed) and the labelled live games:

| clutter k (τ 0.5 s, floor 0.4) | held-out @60 vs shipped | locked @60 (clips) | live mean @60 / @80 | 11:35 @60 |
|---|---|---|---|---|
| **0.5 (shipped)** | **+2.43 ± 0.93 / +5.03** | **+1.4 / +3.0** | **0.933 / 0.970** | **0.634** |
| 0.6 | +1.79 ± 0.95 / +4.95 | +0.6 / +2.8 | 0.942 / 0.976 | 0.702 |
| 0.75 | −0.21 ± 1.08 / +3.41 | −0.6 / +2.0 | 0.959 / 0.988 | 0.862 |

A stronger weight rescues the failed 11:35 game (its motion signal is weak
for ~3 s, and the tracker sits on a semi-persistent spot that only k = 0.75
clears). But it is worse on the held-out clips at **every** lag allowance,
not just at zero (−2.6 points vs k = 0.5 at 0 ms, −0.8 at 246 ms), and wins
live mainly on 11:35. So k = 0.5, which is best on the broader set and better
than before on every game, ships. k = 0.6 is the safe next step if 11:35-type
games keep failing (`CLUTTER_K`). Retrained nets under the new runtime tie the
shipped one (`fw`: held-out −0.36 ± 0.17, live 0.937 vs 0.933), so the net
stays.

### Held-out human clips: lag, not loss

(Clutter-only stage. With the floor added, the held-out gain holds at zero
lag; see above. The lag finding matters for judging any future change.)

46 clips × 5 perturbed runs: coverage @60 0.870 → 0.870 (+0.07 ± 0.51 per
clip), @80 0.933 → 0.938, locked @80 0.970 → 0.978, locked @60 0.948 → 0.909
(−1.8 clips). The human players' cursor **trails the shape**. The shipped
solver's cursor is already 8 px ahead of the human along their direction of
motion (the human track fits best 3 frames later), and the clutter background
moves it a further ~8 px forward. Against the user's half-speed labels the
shipped target trails by 200 ms (17 px); with clutter 0.5/0.5 by 20 ms, so
the change removes lag rather than adding error. Re-scored with the human
track advanced to allow for reaction time:

| human lag allowed | 0 | 82 ms | 123 ms | 164 ms | 246 ms |
|---|---|---|---|---|---|
| coverage @60, change (points) | +0.07 ± 0.51 | +1.16 ± 0.56 | +1.85 ± 0.57 | +2.49 ± 0.59 | +3.70 ± 0.67 |
| locked @60, change (clips) | −1.8 | +0.2 | +0.4 | +1.0 | +1.4 |

The shipped solver's own locked @60 falls from 0.948 to 0.917 with just 82 ms
allowed: it matches the human's timing. For scale, a retrain of the shipped
recipe (below) also reads −1.4 clips locked @60 at equal coverage.

### Ablation: what hurt the full-field retrain

`rep` (the shipped recipe retrained on the first cache, current `train.py`,
pc_window True) reproduces the shipped net: held-out +0.07 ± 0.25 points of
coverage, live mean 0.812 vs 0.796 (worst game −0.3). So the cache change cost
the §11 retrain its closed-loop points, not the training code. Which part:

| retrain (seed 1, 14 epochs) | field | alignment | held-out coverage vs shipped | live mean @60 (shipped 0.796) |
|---|---|---|---|---|
| `rep` | clipped | windowed | +0.07 ± 0.25 | 0.812 |
| `fw` | full | windowed | +0.40 ± 0.29 | 0.813 |
| `cu` | clipped | unwindowed | −1.52 ± 0.52 | 0.782 |
| §11 s1 / s2 | full | unwindowed | −1.9 ± 0.6 | 0.786 / 0.79 |

**Training on the unwindowed (correct) alignment is what hurt**; the full
field is neutral to slightly positive. The centre imprint explains it: the
Hanning window weights the box centre, so the windowed alignment partly
follows the static imprint and cancels it in the differences. Correctly
aligned, the imprint stands out, and the unwindowed nets' centre hotspot is
~1.7× stronger (mean evidence 0.99 vs 0.57). With the clutter background the
models tie (live mean 0.868 shipped, 0.870 `fw`, 0.879 `rep`; held-out
+0.08 / −0.05 / −0.23 vs shipped without it), so the shipped net stays.

### Robustness checks (runtime defaults: clutter 0.5 s / 0.5, floor 0.4)

* The runtime reproduces the prototype (`ens.py --bg --den-floor`) to the
  digit, and `ev.py --legacy` reproduces the old solver. The laptop
  reproduces the box's replays to the digit except 11:35 (0.588 vs 0.585 @60:
  GPU numerics, amplified in a chaotic game).
* Updates span at most 0.12 s (`CLUTTER_MAX_DT`), so after a stalled stream
  the background is not rebuilt from one frame (that frame contains the
  shape). This changes no replay (−0.02 ± 0.02 points held-out, live
  identical). Test: `test_clutter_background_is_not_rebuilt_from_one_frame_after_a_stall`.
* 60 Hz capture (every frame fed twice, `--feed60`): live mean
  0.799 → 0.932 @60 (0.868 → 0.968 @80), every game better (worst
  +1.3 / +0.0 / +0.0 with end60).
* A slower player (20 Hz, `--hz 20`): live mean 0.775 → 0.917 @60
  (0.851 → 0.957 @80; worst game +2.6 @60, −0.1 @80). Held-out +1.17 ± 0.95
  points, locked @60 +0.6 clips, @80 0.957 → 0.978.
* With clutter only (no floor), 20 Hz: held-out +0.19 ± 0.53, locked @60
  −2.0 clips — the floor fixes that too.

### Tooling (all in this folder; results in `training_data/lie_detector/eval/`)

* `ev.py` — the ship rule's evaluator. `heldout` / `live` modes, one run per
  box perturbation; `--own` (live: our own cursor, the piloted-cursor score
  `c60/c80/end60`, game-end windows from `game_end.py`); the runtime's
  defaults unless `--legacy` (the old solver), `--clutter TAU,K` or
  `--den-floor X`; `--feed60`, `--hz`, `--pos`. Prototypes in `ens.py` (`--bg`, `--tta`,
  comma-separated `--model` for ensembles).
* `evcmp.py heldout|live|lag` — paired comparisons. `lag` re-scores held-out
  runs (`--pos`) with the human track advanced for reaction lag.
* `game_end.py` — SUCCESS / game-over time per labelled game.
* `rank_unlabelled.py` takes `PATH[@TAU,K]`. The label queue now ranks the
  17 unlabelled bot games by clutter-off vs clutter-on disagreement (top:
  10-11 19:30, 10-12 22:00, 10-12 23:54).
* `train.py --pc-window --seed --init`; `build_cache.py` with
  `LD_PC_WINDOW=1` builds a windowed cache.
* Tests: `test_clutter_background_*`, `test_evidence_over_few_usable_pixels_is_not_inflated`.

## 13. 2026-10-28: the second live failure, and a stronger clutter background

About 360 bot games were played on the §12 solver from 10-14 to 10-28. Two
were reported as failed.

### 10-26 04:52 was a pass, misread as the jail

`success_seen` was True, but the outcome was `failed`. SUCCESS! showed at
24.9–25.5 s. At 27 s an event darkened the map ("Powerful monsters … have
appeared"), and the dark aftermath read as the punishment room. The banner now
overrules the darkness (`LieDetectorPlayer`, with a test).

The check is safe. Over 90 recent games, gameplay never exceeded 1,725 yellow
pixels before the banner, against the 3,000 threshold. The banner itself
measured 3,025–9,329. `success_seen` was True on all 10 passed logs and False
on both real failures.

### 10-28 12:16: a real failure, the 11:35 mechanism

The recording was destroyed by a scratch script that wrote over it. The
user's labels and the solver log survived. The log's 300 half-res box frames
cover 10.7–22.2 s, which is what the solver consumes. `halfreplay.py` replays
them closed-loop, seeded on the labels, and reproduces the live loss at
14.1 s (live: 13.9 s).

Live, the cursor was within 60 px of the labels for 55% of the game. The
shape faded to almost nothing at 14.5–16 s: raw evidence at the shape was
0.2–0.4, against 1.5–4 while visible. The tracker slid onto clutter about
100 px from the centre, then teleported between the box centre and the shape
until 20.4 s.

The clutter is the shape's outline from the countdown. The mean evidence away
from the labels forms a ring 50–70 px from the centre (out to ~100 px) in
11:35, 06:19 and 21:32 alike. The §12 background (τ 0.5 s, k 0.5) removes
only part of it.

### Stronger, longer-memory clutter background

Results vs the §12 solver:
* **Tier 1:** the user's 15 labelled live games, `ev.py live --own`, 5 runs.
* **Held-out:** the 46 clips, 5 runs.
* **12:16:** `halfreplay.py`, 5 starts.

| clutter τ / k (floor) | held-out @60 | labelled mean @60 | worst labelled game | 11:35 | 12:16 |
|---|---|---|---|---|---|
| 0.5 s / 0.5 (§12) | — | 0.945 | — | 0.635 | 0.44 |
| 2 s / 1.0 | −2.98 ± 0.69 | 0.959 (9 games) | −4.4 | +27 | 0.85 |
| 1 s / 1.0 | −6.92 ± 0.86 | — | — | — | 0.84 |
| 2 s / 0.75 | −0.26 ± 0.28 | 0.961 | −2.8 (00:30) | +25 | 0.79 |
| 2 s / 0.65 | +0.58 ± 0.23 | 0.963 | −1.2 (21:32) | +23 | 0.74 |
| **2 s / 0.65, wall floor 0.5 (20 px)** | **+0.80 ± 0.21** | **0.965** | **−0.6 (00:30)** | **+23.5** | **0.74** |

Full strength (k 1) rescues both failures but eats the real shape. In the
held-out clips that lose most, the shape sits still at the box centre at the
start (2 s at speed 0 in 07-20 21:46), or crosses it late (10:53, 19.4 s).

At k 0.65–0.75 the cost moves to **wall spikes**. With the mid-field
evidence lowered, a brief spike along a wall becomes the strongest thing in
the box: 00:30 at 17.5 s on the top wall, 21:32 at 21.2 s on the bottom wall.

A higher floor everywhere fixes the walls but costs held-out coverage
(0.5: −1.63 ± 0.28). The floor also shrinks the tracked shape mid-field,
where the cursor hole leaves only ~0.5 of its disc usable (§12). So the
higher floor applies only along the walls: `WALL_FLOOR` 0.5 within
`WALL_BAND` = 20 half-res px of the field edge. `DEN_FLOOR` stays 0.4
mid-field.

The remaining 00:30 dip is −0.6 points against the first label and −0.1
against the user's second label. The two labels agree to a median of 9 px,
and switching between them moves the old solver's score by 0.8 points. What
remains is a 4-frame top-wall jump, plus an 80 ms later re-acquisition at
23.8 s, where both solvers had lost the shape.

**Tier 2, the 361 passed games since 10-14 (`tier2.py`).** The bot's
recorded green reticle is a path that passed. The §12 solver's replay stays
within 80 px of it almost always (median 0% of a game, p99 8%, max 13%). The
new solver is the same: mean 0.91% vs 0.90%, no game worse by 5 points or
more, largest departure 3.7%.

**Dropped:**
* *Adaptive blend toward the strong background while peak evidence is low*
  (−1.9 held-out). The shape is faint most of the game by design, so "faint"
  does not mark trouble.
* *Central strong suppression, gated on the shape having left the centre*
  (held-out −0.4). It loses 10:53, where the shape crosses the centre late.
  Freezing that map: −2.2. Excluding the estimate's neighbourhood loses
  12:16 again.
* *Constant-velocity prediction in GridTracker:* overshoots at the turns
  (12:16: 0.85 → 0.50–0.74; labelled games −14).
* *Readout hysteresis, β 1.5, evidence cap 1.5–2* (`clip`): no gain, or
  the losses move to other games.

### Tooling

* `halfreplay.py` replays a failure from its solver log when the clip is
  gone.
* `tier2.py` is the passed-games check (`--compare A B` summarises two runs).
* `ev.py --prev` gives the §12 solver (τ 0.5 / k 0.5, no wall floor);
  `--wall-floor X` overrides the wall floor. `rank_unlabelled.py` takes
  `PATH@TAU,K,FLOOR,WALL`.
* On the box, `run_cfg2.sh` / `evq2.sh` run `ev.py` under env-selected
  prototypes (`evp.py` + `trk_patch.py`, scratch only).
* Tests: `test_wall_floor_damps_few_pixel_means_at_the_walls_only`, and the
  player's `test_a_dark_screen_after_success_is_still_a_pass`.

## Shadow mode (live validation without risk)

Settings → Lie Detector → **Auto-solve** + **Shadow my manual solve**:

1. A Lie Detector is detected → the routine pauses, a clip is recorded, and
   you are alerted exactly as with auto-solve off — five Discord pings and the
   looping siren — except the siren does not block anything: **F8** silences
   it (and still never resumes the routine mid-game), as do F9 and the end of
   the game. You play it.
2. The solver runs on every frame with a *virtual* cursor and never touches
   the mouse (your reticle is blanked like any cursor — it cannot follow you).
3. Press **F9** (Settings → Auto Maple Controls → "Lie Detector takeover"), or
   untick Shadow, at any moment: the bot takes the mouse from where your
   cursor is — already tracking — and plays to the end. F8 cannot resume the
   routine while a game is running.
4. Game over: the yellow **SUCCESS!** banner (100% on the recordings) or a box
   closing without the jail room → the routine resumes automatically; the jail
   → stays paused + siren. Discord reports who finished and, for games you
   finished, how often the solver agreed with your cursor (within 60 px; and
   over the final second).
5. Per-frame log (solver target, solver cursor, your cursor, who drove) in
   `training_data/lie_detector/shadow_logs/` next to the recorded clip.

(If torch/the motion weights are missing the player falls back to the previous
solver, whose shadow agreement is meaningless — it can see your reticle.)

## Running / retraining

Every Lie Detector (bot or human) records a 30 s clip into
`training_data/lie_detector/`; human-played passes are new training data.

```bash
S=private_scripts/lie_detector/motion
# a retrain must align windowed, like the shipped net (FINDINGS §12): full field + windowed = `fw`
LD_PC_WINDOW=1 LD_CACHE=training_data/lie_detector/motion_cache_fw python $S/build_cache.py
LD_REFS=-7,-5,-3,-1 LD_CACHE=training_data/lie_detector/motion_cache_fw python $S/train.py --epochs 14 --pc-window --out NEW.pt
python $S/leak_test.py assets/models/lie_detector_motion.pt      # must print PASS twice
python $S/replay.py                            # runtime solver on the held-out clips
python $S/demo.py 2026-07-11_01-16-11          # -> training_data/lie_detector/demo/*_motion_demo.mp4
uv run --with pytest pytest tests/test_lie_detector_motion.py
```

The ship rule (§11, §13) has three tiers. A candidate must be no worse on
every labelled live game (tier 1, the truth), must not stray from the bot's
path in passed games (tier 2, `tier2.py`), and must be no worse on the 46
held-out clips (secondary). Tiers 1 and 3 use 5 perturbed runs each:

```bash
for j in 0,0 1,0 -1,0 0,1 0,-1; do                # (on the GPU box: ~10x faster, run in parallel)
  python $S/ev.py heldout training_data/lie_detector/eval/NEW_$j.jsonl --model NEW.pt --jit=$j
  python $S/ev.py live training_data/lie_detector/eval/live_NEW.jsonl --model NEW.pt --own --jit=$j
done
python $S/evcmp.py heldout final NEW               # final / live_final = the runtime of 2026-10-28
python $S/evcmp.py live final NEW                  # (rt28 / live_L_rt = 2026-10-14, ev.py --prev; d_old = --legacy)
python $S/game_end.py                              # after labelling a new game (label_clip.py)
# tier 2: the bot's passed games (list of clip names), current vs candidate
python $S/tier2.py t2_cur.jsonl passed.txt && python $S/tier2.py t2_new.jsonl passed.txt --model NEW.pt
python $S/tier2.py --compare t2_cur.jsonl t2_new.jsonl
```

(`score_cache.py` + `track_eval.py` give the same numbers as `replay.py` from
cached net outputs, for fast tracker tuning.)

Ground truth for games the bot played (the recordings then contain no human
cursor, so live accuracy and live-only effects — e.g. our own rendered cursor
— are otherwise unmeasurable):

```bash
python $S/label_clip.py training_data/lie_detector/<clip>.mp4 --speed 0.5   # follow the shape with the mouse -> <clip>_gtN.npz
python $S/compare_gt.py training_data/lie_detector/<clip>_gt1.npz           # bot vs your labels, off-shape episodes, plot
```

## Files

- `src/easymaple/detection/lie_detector_motion.py` — alignment, input
  builder, MotionNet, GridTracker, `MotionLieDetectorSolver` (runtime)
- `build_cache.py` → `train.py` → `score_cache.py` / `track_eval.py` /
  `replay.py` / `leak_test.py` / `demo.py` (this folder)
- `tests/test_lie_detector_motion.py`
