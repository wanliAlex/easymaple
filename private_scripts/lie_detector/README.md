# Lie Detector mini-game solver

Auto-solver for the Lie Detector anti-bot mini-game: keep the mouse cursor on a
shape that appears in a camouflage field and fades as it moves. **The game is
passed by following the shape all the way to the end** — not by a good average —
so the solver and its evaluation are built around staying locked through the
finish.

- Core algorithm: `src/easymaple/detection/lie_detector_solver.py`
- Runtime driver (moves the mouse): `src/easymaple/modules/lie_detector_player.py`
- Offline eval + demo renderer: `private_scripts/lie_detector/eval_solver.py`
- Tests (synthetic, no clips needed): `tests/test_lie_detector_solver.py`
- **How we got here** (the tracker investigation): `private_scripts/lie_detector/kalman/findings.md`

## How the mini-game works (from the recorded clips)

| Phase | Time (in clips) | Behaviour |
|-------|-----------------|-----------|
| Countdown | ~6–8 s | Big circle + digits (5,4,3,2,1) / "START" glow across the top of the box |
| **Stationary & opaque** | ~1–2 s | A bright white shape sits **still** — trivially detectable |
| **Moving & fading** | ~7–11 s → SUCCESS | The shape moves on an irregular path while fading into the texture |

The in-game cursor is a bright **green reticle**. In the recordings that is the
human's cursor (used here as ground truth); at runtime it is our own cursor,
which we park on the shape.

**The shape is not a disc.** Across the recordings it is a disc, a triangle, a
diamond, a pentagon, a cloud, a map-pin / speech-bubble icon, or a multi-point
**star** (circularity 0.18–0.90) — and the camouflage texture is built from the
*same* motif, so the shape hides among look-alikes. Acquisition therefore cannot
assume a round shape.

## The four keys

**1. Track colour, not brightness.** The shape is a cool/white blob; the
camouflage is warm/tan. While opaque the shape is trivially bright, but as it
moves it fades toward the texture's brightness, and the texture's strong
per-frame **luminance shimmer** then buries it — luminance detection of the faded
shape collapses to ~40%. But the texture's **hue** barely shimmers: the shape
stays measurably *cooler* than its surroundings the whole way down. Working in the
**B − R** (blue minus red) "coolness" channel, the faded shape's deviation peak
sits **~20 robust-σ above the texture floor** and is the single strongest cool
blob in **93–100%** of frames. Detection is never the problem.

**2. Association is the problem — solve it with a fixed-lag trajectory smoother.**
On the minority of frames a texture blob briefly out-shines the fading shape. A
greedy frame-by-frame tracker cannot tell *"the far strong peak is the shape,
still moving"* from *"it is a distractor, ignore it"*, and guessing wrong loses
the shape right at the finish. So the tracker is **not** greedy: each frame it
takes the top-K deviation peaks, keeps a short window of candidate sets, and runs
a tiny dynamic program for the smoothest strong path through them, outputting the
position a few frames back — i.e. informed by a few **future** frames. A
one-frame distractor never lies on a smooth path and is dropped; a genuinely
moving shape is followed because the path continues to it. This is the online
analog of the offline optimal-trajectory search, and it is what keeps the lock to
the end.

**3. Learn what cannot be hand-crafted — the shape net.** Some variants fade
the shape to *complete* invisibility for every classical statistic (seven
detectors measured pure noise), yet human players keep tracking it — so the
signal is in the captured pixels as a faint spatio-temporal pattern. A small
CNN (`lie_detector_net.py`, 328k params) learns it from the human recordings:
8 stacked frames (~0.5 s of motion) in, shape heatmap out, the human's
reticle as the label (erased from the inputs with a leak-proof plate fill).
Held-out validation: **12 px median error on a never-seen fade-to-zero clip**
(82% within 60 px). Its peaks feed the same smoother as extra candidates on
the same reward scale; everything degrades to classical tracking when the
model or torch is unavailable. See `kalman/findings.md` §11.

**4. Move the mouse like a human — the `CursorPilot`.** The tracker says *where
the shape is*; the pilot decides *how the hand gets there*. Raw tracker output
can step discontinuously (a smoother path-switch or re-acquisition legitimately
teleports the target — measured up to ~330 px in one frame), and a cursor that
teleports is an obvious bot tell. The pilot is a PD chase with the target's
velocity fed forward, under hard caps: ≤ 45 px/frame speed (~1350 px/s, a brisk
human flick) and ≤ 6 px/frame² acceleration (bell-shaped speed profiles, no
instant direction snaps). Feed-forward means a constant-velocity shape is
tracked with near-zero lag, so the smoothing costs no lock; the shape spawns in
the middle of the box, so the pilot parks the cursor at the box centre during
the countdown and is already sitting on the shape when it appears. All scoring
below is on the **piloted cursor** — what the game actually sees.

## Algorithm

1. **Locate the play-box** by its tan colour, large size and dense fill (rejects
   combat effects). Locked on first detection.
2. **Acquire** the opaque shape while it sits still — **shape-agnostically**: the
   largest bright, shape-sized blob in the *body* of the box (blobs up in the top
   "countdown-digit / START" band are ignored), confirmed stable for several
   frames. No roundness gate, so stars/triangles/pins all acquire.
3. **Background plate** in the **B − R channel**: the texture is static, so a
   per-pixel **median** over a rolling buffer of moving-phase frames recovers the
   background; `current − plate` isolates the shape's cool halo. The median is a
   plain (fast) median — the green cursor is a transient outlier it rejects on its
   own — capped at a few dozen frames, so a rebuild stays well under one frame
   time (the earlier green-masked `nanmedian` took ~2.7 s, which would freeze the
   live cursor for dozens of frames).
4. **Track** with the **fixed-lag trajectory smoother** (see key #2). Masked
   from the search: green pixels, a disc around our own **commanded cursor**
   (the reticle's glow leaks past the green mask at ~5× the texture floor — a
   tracker must never track itself; learned from the first live failure), and
   the shape's start-spot (fading plate artifact). Nothing else: border
   guards and blind-phase coasting were both tried and removed after the clip
   corpus showed they cost more end-lock than they saved (see
   `kalman/findings.md` §10).
5. **Fuse the shape net** (see key #3): once tracking starts, every frame is
   pushed through the learned detector (cursor erased with the same plate
   fill it was trained on) and its heatmap peaks join the smoother's
   candidate pool — whichever channel carries signal on a given frame wins
   the smooth-path competition. ~12 ms/frame on the local GPU.
6. **Drive the mouse** through the **`CursorPilot`** (see key #4): park at the
   box centre during the countdown, then glide after the tracker's target under
   human speed/acceleration caps — continuous motion whatever the tracker does.

## Offline results (vs the green-cursor ground truth)

Because passing means tracking **to the end**, the headline metric is
**locked-at-end** (on the shape over the final ~1 s of the active puzzle) and
the **longest unbroken lock**. Scored on the **piloted cursor** (what the game
sees), with the shape net fused:

| corpus | locked at end |
|--------|---------------|
| 19 easy clips | **18/19** (classical-only baseline: 17/19; the net rescues `22-31-07`) |
| 3 hard fade-to-zero clips (human-passed) | **2/3**, incl. the **held-out** `01-16-11` (53% end-lock, 7.4 s longest run — the classical tracker managed 20%/3.9 s there) |

Every cursor step stays inside the 45 px/frame human cap. The two remaining
misses: `11-07-43` (an easy-corpus endgame with a sustained distractor — the
long-standing hard case) and `00-20-14` (43% end-lock, just under the bar; its
final second is the weakest signal in the corpus and is exactly what the next
data refresh improves). For history: greedy Kalman 12/18 → fixed-lag smoother
16/18 → chromatic + pilot 17/19 → +shape net 20/22 (see `kalman/findings.md`).

## Remaining limits

- **Unseen variants.** The shape net was trained on the variants recorded so
  far (three textures, several shapes, two fade behaviours). A new variant
  may need a data refresh: every attempt — bot or human — records a 30 s clip
  automatically, so the retrain loop is: play/collect → `build_dataset.py` →
  `train_net.py` → re-run the eval gates. Human-passed recordings of any
  *failing* variant are the decisive ingredient (that is exactly how the
  fade-to-zero variant was cracked; see `kalman/findings.md` §11).
- The sustained end-fade distractor (`22-31-07`). Cleaner per-frame background
  subtraction (the causal plate is noisier than an oracle) would recover most
  of it; faster catch-up would not (it would need visibly non-human speeds).
- The net costs ~12 ms/frame on the local GPU; on a CPU-only machine it is
  slower than the frame budget — the solver then still works classically
  (`use_net` degrades gracefully), which handles every variant except
  fade-to-zero.

## Running

```bash
# Offline evaluation + demo video/montage (needs clips in training_data/lie_detector/)
python private_scripts/lie_detector/eval_solver.py
# -> prints locked-at-end / longest-lock / coverage per clip and writes
#    *_demo.mp4 and *_montage.png under training_data/lie_detector/demo/

# Retrain the shape net after collecting new recordings
python private_scripts/lie_detector/build_dataset.py   # extract + label
python private_scripts/lie_detector/train_net.py       # train -> assets/models/lie_detector_net.pt

# Tests (no clips required)
uv run --with pytest pytest tests/test_lie_detector_solver.py tests/test_lie_detector_net.py -v
```

## Runtime integration

Fully wired into the notifier, gated by a **Settings → Lie Detector →
"Auto-solve Lie Detector"** checkbox (persisted; default **on**):

- **Enabled:** on detecting the prep/in-progress banner the notifier records a
  training clip, pauses the routine, and runs `LieDetectorPlayer().solve()` —
  frames from the capture thread (BGRA accepted), cursor via
  `win32api.SetCursorPos`, motion through the `CursorPilot`. When the play-box
  disappears after a tracked game the bot **resumes automatically** and Discord
  gets a ✅ — unless the near-black punishment room ("Time Remaining" jail)
  follows, which means the test was **failed**: ❌ Discord ping, bot stays
  paused. An unsure outcome (timeout/error) also keeps the bot paused with a
  ⚠️ ping. A detection that never produces a play-box (false positive) resumes
  quietly.
- **Disabled:** one Discord message (no siren — deliberately) and the bot
  pauses for manual takeover.
- Either way a 90 s detection cooldown stops the lingering banner from
  re-triggering, and every detection records a 30 s clip to grow this corpus.

The smoother outputs a target a few frames behind the shape and the pilot adds
a small chase lag (~a few px on the slow shape) — both inside the pass
tolerance. The loop is validated offline against all recorded clips and by the
synthetic end-to-end tests; it has not yet been through a **live** Lie Detector,
so keep an eye on the first real one.
