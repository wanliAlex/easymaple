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

## The three keys

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

**3. Move the mouse like a human — the `CursorPilot`.** The tracker says *where
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
4. **Track** with the **fixed-lag trajectory smoother** (see key #2). Green is
   always masked so our own cursor is never tracked; the shape's start-spot is
   masked from the search (it carries a fading plate artifact).
5. **Drive the mouse** through the **`CursorPilot`** (see key #3): park at the
   box centre during the countdown, then glide after the tracker's target under
   human speed/acceleration caps — continuous motion whatever the tracker does.

## Offline results (vs the green-cursor ground truth)

Because passing means tracking **to the end**, the headline metric is
**locked-at-end** (on the shape over the final ~1 s of the active puzzle) and the
**longest unbroken lock**. Scored on the **piloted cursor** (what the game sees)
over all 19 recorded clips:

| metric (19 clips) | raw tracker | **piloted cursor** |
|-------------------|-------------|--------------------|
| **locked at end** | 17/19 | **17/19** |
| mean end-lock @80px | — | **82%** |
| max cursor step anywhere | ~330 px/frame | **45 px/frame** (= the cap) |

The human-motion layer costs **zero** locked-at-end clips: feed-forward tracking
absorbs the pilot's smoothing, and its inertia even *recovers* one clip the raw
tracker loses (`23-17-58` — a one-frame end flicker the physical cursor glides
straight through). For history, the greedy Kalman held the end on only 12/18
clips; the fixed-lag smoother took that to 16/18, and the current build scores
17/19 (see `kalman/findings.md`). The offline optimal trajectory (non-causal)
reaches ~96% coverage, so the chromatic signal supports near-perfect tracking.

The two clips that still slip share one failure: the shape fades to near the
texture in the final seconds while a *sustained* texture distractor is stronger.
On `11-07-43` both raw and cursor miss. On `22-31-07` the tracker wanders onto a
distractor for ~1.5 s just before the finish and only snaps back ~0.5 s from the
end — the raw point scores a lucky "locked", but any *physical* cursor (ours or
a human hand) pays a few frames of catch-up glide and misses the 50% bar.

## Remaining limits

- The sustained end-fade distractor above. Cleaner per-frame background
  subtraction (the causal plate is noisier than an oracle) would recover most
  of it; faster catch-up would not (it would need visibly non-human speeds).
- Tuned and validated on 19 clips. More recordings (the `recorder` feature
  gathers them — including during every auto-solve) would harden the
  colour/box/acquisition gates against new shape/texture variants.

## Running

```bash
# Offline evaluation + demo video/montage (needs clips in training_data/lie_detector/)
python private_scripts/lie_detector/eval_solver.py
# -> prints locked-at-end / longest-lock / coverage per clip and writes
#    *_demo.mp4 and *_montage.png under training_data/lie_detector/demo/

# Tests (no clips required)
uv run --with pytest pytest tests/test_lie_detector_solver.py -v
```

## Runtime integration

Fully wired into the notifier, gated by a **Settings → Lie Detector →
"Auto-solve Lie Detector"** checkbox (persisted; default **on**):

- **Enabled:** on detecting the prep/in-progress banner the notifier records a
  training clip, pauses the routine, and runs `LieDetectorPlayer().solve()` —
  frames from the capture thread (BGRA accepted), cursor via
  `win32api.SetCursorPos`, motion through the `CursorPilot`. When the play-box
  disappears after a tracked game the bot **resumes automatically** and Discord
  gets a ✅; an unsure outcome (timeout/error) keeps the bot paused with a ⚠️
  Discord ping and a single non-blocking siren sound. A detection that never
  produces a play-box (false positive) resumes quietly.
- **Disabled:** one Discord message (no siren — deliberately) and the bot
  pauses for manual takeover.
- Either way a 90 s detection cooldown stops the lingering banner from
  re-triggering, and every detection records a 30 s clip to grow this corpus.

The smoother outputs a target a few frames behind the shape and the pilot adds
a small chase lag (~a few px on the slow shape) — both inside the pass
tolerance. The loop is validated offline against all recorded clips and by the
synthetic end-to-end tests; it has not yet been through a **live** Lie Detector,
so keep an eye on the first real one.
