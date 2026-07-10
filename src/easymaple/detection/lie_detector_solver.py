"""Solver for the Lie Detector anti-bot mini-game.

The mini-game shows a rectangular camouflage play-field in which a bright shape
appears, sits still for a few seconds, then begins moving while fading into the
texture. The player must keep the mouse cursor on the moving shape **all the way
to the end** — the game is passed by tracking to the finish, not by a good
average.

Approach (validated offline against the in-game cursor as ground truth):

1. **Locate the play-box** by its tan camouflage colour.
2. **Acquire** the opaque shape while it sits still — *shape-agnostically*. The
   shape is not always a disc (the game uses discs, triangles, diamonds, clouds,
   map-pin/speech-bubble icons and multi-point stars, and the texture is built
   from the same motif), so acquisition takes the largest bright blob in the
   *body* of the box and ignores the countdown digits / "START" glow across the
   top — no roundness assumption.
3. **Work in the chromatic "coolness" channel** ``B - R`` (blue minus red), not
   luminance. The shape is *cool/white* over a *warm/tan* texture. As it fades
   its brightness drops into the texture's (and the per-frame luminance shimmer
   buries it — luminance detection collapses to ~40% by mid-puzzle), but its
   *hue* does not: it stays measurably cooler the whole way down. In the B-R
   channel, with the static background removed by a per-pixel **median** plate,
   the shape's deviation peak sits ~20 robust-sigma above the texture floor and
   is the single strongest cool blob in 93-100% of frames. Detection is never the
   problem.
4. **Track** with a **fixed-lag trajectory smoother** (see :class:`ShapeTracker`).
   *Association* is the hard part: on a minority of frames a texture blob briefly
   out-shines the fading shape, and a greedy per-frame tracker cannot tell a
   still-moving shape from a distractor and loses the lock right at the finish. So
   the tracker keeps the top-K deviation peaks over a short window and runs a
   small dynamic program for the smoothest strong path, emitting the position a
   few frames back — informed by that many *future* frames. A one-frame distractor
   never lies on a smooth path; a moving shape is followed because the path
   continues to it. It is the online analog of the offline optimal-trajectory
   search.
5. **Drive the mouse through the** :class:`CursorPilot` — the human-motion
   layer. Raw tracker output may legitimately step discontinuously (path
   switch, re-acquisition); the pilot turns it into continuous, speed- and
   acceleration-bounded cursor movement, parked at the box centre during the
   countdown (the shape spawns in the middle).

Result (offline vs the green-cursor ground truth, over all 19 recorded clips,
scored on the piloted cursor — what the game sees): **locked on the shape at
the finish on 17/19 clips** (mean end-lock ~82% @80px), with every cursor step
inside the 45 px/frame human cap. See
``private_scripts/lie_detector/README.md`` and ``kalman/findings.md``.

The in-game mouse cursor is a bright green reticle. Offline that reticle is the
human's cursor (our ground truth); at runtime it is *our own* cursor, which we
park on the shape. Either way it must be excluded from the shape signal, so the
tracker always masks green before measuring.

This module is pure OpenCV/NumPy and performs no I/O: ``LieDetectorSolver``
consumes BGR frames and returns the target point in frame coordinates. The
caller is responsible for grabbing frames and moving the mouse (e.g. via
``win32api.SetCursorPos``), which keeps the solver importable and testable on
any platform.
"""

import logging
from collections import deque

import cv2
import numpy as np

from src.easymaple.detection import lie_detector_net as net_mod

log = logging.getLogger(__name__)

# --- Play-box detection (tan camouflage region) -----------------------------
BOX_HSV_LO = np.array([8, 45, 115])
BOX_HSV_HI = np.array([33, 210, 255])
BOX_MIN_W, BOX_MIN_H = 550, 330  # the real play-field is large (~735x447)
BOX_ASPECT = (1.1, 1.9)
BOX_FILL = 0.70                # tan must densely fill the bbox (rejects combat FX)
BOX_INNER_MARGIN = 8           # crop inside the border (small: the shape hugs edges)

# --- Green in-game cursor reticle -------------------------------------------
GREEN_HSV_LO = np.array([40, 80, 80])
GREEN_HSV_HI = np.array([92, 255, 255])

# --- Acquisition (bright opaque shape) --------------------------------------
# The opaque shape sits still for ~4s, then moves. It is NOT always a disc: the
# game uses discs, triangles, diamonds, clouds, map-pin/speech-bubble icons and
# multi-point stars (circularity ranges ~0.18-0.90), and the camouflage texture
# is built from that same motif. So acquisition is shape-agnostic — no roundness
# gate. The one thing every shape shares is that it sits in the *body* of the
# box, while the countdown digits (5..1) and the "START" text glow in a band
# across the top; a blob centred in the top ACQUIRE_TOP_REJECT fraction is that
# text and is ignored. Inside the locked box the only bright content is the
# shape and that top text, so the largest bright blob below the band is the
# shape. A settling test (stable position over several frames) then locks it.
ACQUIRE_BRIGHT = 205           # grayscale threshold for the opaque shape
ACQUIRE_MIN_AREA = 2500        # px, smallest shape (small triangle ~3.1k) minus margin
ACQUIRE_MAX_AREA = 16000       # px, largest shape (big star ~13k) plus margin
ACQUIRE_TOP_REJECT = 0.32      # ignore bright blobs centred in the top of the box
                               # (countdown digits/START sit at cy~0.25H; shapes ~0.55H)
SETTLE_FRAMES = 12             # stable detections required to lock the shape
SETTLE_STD = 10.0              # px position std below which the shape is "settled"
MOTION_ONSET_PX = 14           # displacement from settled pos that marks motion
FADE_FRAC = 0.55               # blob area below this fraction of settled => fading
ONSET_CONFIRM = 4              # consecutive move/fade frames to confirm onset

# --- Background plate --------------------------------------------------------
# The plate is a per-pixel median over a rolling buffer of frames captured once
# the shape is moving. Tracking starts as soon as a rough plate is available and
# the plate is rebuilt as more frames accumulate (static background => more
# frames is strictly better), converging to the full-window quality.
PLATE_MIN_FRAMES = 30          # post-onset frames needed before tracking starts
PLATE_BUF_MAX = 180            # rolling buffer size (recent static-bg window)
PLATE_REBUILD_EVERY = 30       # rebuild cadence (frames) while the buffer grows
PLATE_MEDIAN_MAX = 64          # cap frames per median (static bg saturates fast;
                               # keeps a rebuild well under one frame time)
STARTSPOT_RADIUS = 55          # px disc around the settled shape masked from the
                               # plate (the stationary opaque shape sat there)
SEED_MIN_PEAK = 2.0            # min cool-deviation peak to seed/re-acquire from a
                               # global search (below this the box is just texture)

# --- Cursor pilot (human-like mouse motion) ----------------------------------
# The tracker's raw target is *where the shape is*; the pilot decides *how the
# hand moves there*. Raw targets can step discontinuously (smoother path switch,
# re-acquisition) and a cursor that teleports is an obvious bot tell — and not
# how a human plays. The pilot is a PD chase with the target's velocity fed
# forward, under hard speed/acceleration caps:
#
# * feed-forward makes a constant-velocity target (the shape's usual motion)
#   track with near-zero lag, so smoothing costs no lock;
# * the acceleration cap yields the bell-shaped speed profile of a human
#   correction (no instant direction snaps);
# * the speed cap (~1350 px/s at 30 fps) keeps even a re-acquisition flick
#   inside brisk-but-human motion, arriving in a few frames.
PILOT_SPEED = 45.0             # px/frame cap (~2x the shape's max speed)
PILOT_ACCEL = 6.0              # px/frame^2 cap
PILOT_KP = 0.14                # spring toward the target
PILOT_KD = 0.75                # damping on (target velocity - own velocity)
PILOT_TVEL_EMA = 0.3           # smoothing of the target-velocity estimate
PILOT_TVEL_CLAMP = 30.0        # px/frame; a target *jump* (re-acquisition) is not
                               # a velocity — clamp it out of the feed-forward

# --- Tracker (fixed-lag trajectory smoother) ---------------------------------
# Runs on the chromatic B-R deviation (see ``cool_channel``). The decisive
# measured fact (private_scripts/lie_detector/kalman/findings.md) is that the
# faded shape is an *overwhelming* signal in this channel: after the static
# background is subtracted its deviation peak sits ~20 robust-sigma above the
# texture floor and is the single strongest ("global") cool blob in ~93-100% of
# frames. Detection is therefore never the problem — *association* is: on the
# minority of frames a texture blob out-shines the fading shape, and a greedy
# frame-by-frame tracker cannot tell "the far strong peak is the shape, still
# moving" from "it is a distractor, ignore it". Guessing wrong loses the shape
# right at the finish — and the mini-game is passed by tracking to the END, not
# by a good average.
#
# So instead of a greedy filter this is a FIXED-LAG smoother. Each frame it takes
# the top ``SMOOTH_K`` deviation peaks (candidates), keeps the last
# ``SMOOTH_WINDOW`` candidate sets, and runs a tiny dynamic program for the
# lowest-cost path through them — cost = a per-peak strength reward minus a
# smoothness penalty (squared step, hard-capped at the shape's max speed). It
# outputs the path position ``SMOOTH_LAG`` frames back, i.e. informed by that
# many *future* frames: a one-frame distractor never lies on a smooth path and is
# dropped, and a genuinely moving shape is followed because the path continues to
# it. This is the online analog of the offline optimal-trajectory search and,
# unlike the greedy filters that preceded it, keeps the lock all the way to the
# end (measured: ~85% locked-at-finish vs ~50%). The ``SMOOTH_LAG`` frame delay
# (~0.13 s, a few px on the slow shape) is well inside the pass tolerance.
DEV_BLUR = 7                   # px, Gaussian blur of the deviation map
SMOOTH_WINDOW = 15             # candidate frames buffered for the trajectory DP
SMOOTH_LAG = 6                 # output this many frames back (uses that many future
                               # frames to disambiguate — the key to end-tracking;
                               # ~0.2 s of lag, a few px on the slow shape)
SMOOTH_K = 6                   # top deviation peaks kept as candidates per frame
SMOOTH_SUPPRESS = 30           # px suppression radius between candidate peaks
SMOOTH_MAXSTEP = 26.0          # px/frame allowed between consecutive path points
                               # (the shape's measured max ~23)
SMOOTH_SCALE = 220.0           # smoothness: per-frame step penalty = dist^2 / this
SMOOTH_STEP_PEN = 50.0         # extra penalty for a path step above SMOOTH_MAXSTEP
REWARD_CAP = 8.0               # cap a peak's z reward so a lone strong distractor
                               # cannot outweigh a smooth, decently-strong path
NET_REWARD_CAP = 10.0          # the learned detector's peaks may exceed the
                               # classical cap: validated at ~12px on held-out
                               # clips, they must out-vote plate-residual junk
                               # chains, which pay no step penalty and would
                               # otherwise win every reward tie on smoothness
FLOOR_Z = 2.0                  # min robust z for a peak to be a candidate at all

# --- Own-cursor masking (learned from the live failure 2026-07-10_14-34-09;
# see kalman/findings.md §10) -------------------------------------------------
# Live, our own reticle leaks a cool halo past the green mask (~5x the texture
# floor). Whenever the shape's signal dips below that, the strongest stable
# blob in the box is wherever the cursor already is — the tracker locks onto
# itself and the cursor freezes (that is exactly how the first live game was
# lost). The caller knows where it commanded the cursor, so a disc around that
# position is masked from every search: a tracker must never track itself.
#
# Two guards were tried on top of this and REMOVED after the corpus falsified
# them (details in findings §10): a border ring against combat-effect bleed
# (real shapes end hugging the wall — the ring cost more end-lock than the
# bleed ever did) and blind-phase coasting (real texture noise is not iid;
# static plate residuals chain as smoothly as a real path, so no path-quality
# gate separates "blind" from "weak shape" — and every gate tried threw away
# genuinely trackable weak endgames).
CURSOR_MASK_R = 32             # px disc masked around our own commanded cursor


def detect_play_box(frame_bgr):
    """Return the camouflage play-box as ``(x, y, w, h)`` in frame pixels, or
    ``None`` if not found. Searches only the central region to avoid the tan
    skill-bar / inventory icons along the screen edges."""
    h, w = frame_bgr.shape[:2]
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BOX_HSV_LO, BOX_HSV_HI)
    roi = np.zeros_like(mask)
    roi[int(h * 0.15):int(h * 0.72), int(w * 0.15):int(w * 0.85)] = 255
    mask = cv2.bitwise_and(mask, roi)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw < BOX_MIN_W or bh < BOX_MIN_H or not (BOX_ASPECT[0] < bw / bh < BOX_ASPECT[1]):
            continue
        if cv2.contourArea(c) / (bw * bh) < BOX_FILL:   # must be a solid tan rectangle
            continue
        if best is None or bw * bh > best[2] * best[3]:
            best = (x, y, bw, bh)
    return best


def green_cursor_mask(box_bgr):
    """Binary mask of the bright green cursor reticle, dilated to cover its
    anti-aliased edges."""
    m = cv2.inRange(cv2.cvtColor(box_bgr, cv2.COLOR_BGR2HSV), GREEN_HSV_LO, GREEN_HSV_HI)
    return cv2.dilate(m, np.ones((11, 11), np.uint8))


def cool_channel(box_bgr):
    """The chromatic "coolness" signal ``B - R`` (blue minus red) as float32.

    This is the signal the tracker runs on instead of luminance. The shape is a
    cool/white disc; the camouflage texture is warm/tan (red > blue, so its B-R
    is negative). The shape is cooler than its surroundings (higher B-R) — a
    contrast that is far steadier through the fade than brightness, because the
    texture's strong per-frame luminance shimmer barely touches its hue. Measured
    on the recorded clips: B-R locates the faded shape ~87-99% of late frames,
    luminance only ~40%.
    """
    b = box_bgr.astype(np.float32)
    return b[:, :, 0] - b[:, :, 2]


def _bright_blob(box_gray):
    """Centroid + area of the largest bright, shape-sized blob below the
    countdown band, or ``(None, 0)``.

    Shape-agnostic: no roundness gate (the shape may be a disc, triangle, star,
    diamond, cloud or map-pin icon). Blobs centred in the top ``ACQUIRE_TOP_REJECT``
    fraction of the box are the countdown digits / "START" text and are skipped;
    the largest remaining bright blob in the size range is the opaque shape.

    No green masking: the opaque shape (gray ~245) is far brighter than the green
    cursor reticle (gray ~150, below threshold), and masking green would punch a
    hole in the shape when the cursor overlaps it.
    """
    _, m = cv2.threshold(box_gray, ACQUIRE_BRIGHT, 255, cv2.THRESH_BINARY)
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    top_cut = ACQUIRE_TOP_REJECT * box_gray.shape[0]
    best = None
    for c in cnts:
        area = cv2.contourArea(c)
        if not (ACQUIRE_MIN_AREA <= area <= ACQUIRE_MAX_AREA):
            continue
        M = cv2.moments(c)
        cy = M["m01"] / M["m00"]
        if cy < top_cut:               # countdown digit / START text band
            continue
        if best is None or area > best[0]:
            best = (area, M["m10"] / M["m00"], cy)
    if best is None:
        return None, 0
    area, cx, cy = best
    return (cx, cy), area


def build_plate(sig_buffer, mask_buffer=None):
    """Static-background estimate of the signal channel (B-R): a per-pixel
    median over the buffered frames.

    The green cursor is a *transient* outlier — it tracks the moving shape, so no
    background pixel stays green for more than a few frames — and a plain median
    rejects it without explicit masking. Measured on real buffers, the plain
    median matches the old green-masked ``nanmedian`` to within ~4 B-R levels
    everywhere while costing ~1/6th as much. ``mask_buffer`` is accepted for
    backward compatibility but no longer needed.

    A static background saturates the median quickly, so at most
    ``PLATE_MEDIAN_MAX`` evenly-spaced frames are used. This keeps a rebuild well
    under one frame time; the previous full-buffer ``nanmedian`` took ~2.7 s,
    which would freeze the cursor for dozens of frames during live play.
    """
    stack = np.asarray(sig_buffer, dtype=np.float32)
    if len(stack) > PLATE_MEDIAN_MAX:
        stack = stack[np.linspace(0, len(stack) - 1, PLATE_MEDIAN_MAX).astype(int)]
    return np.median(stack, axis=0).astype(np.float32)


class ShapeTracker:
    """Fixed-lag trajectory smoother over the chromatic (B-R) deviation map.

    Each frame it extracts the top ``SMOOTH_K`` deviation peaks (candidates),
    keeps the last ``SMOOTH_WINDOW`` candidate sets, and runs a small dynamic
    program for the lowest-cost path through them (a per-peak strength reward
    minus a squared-step smoothness penalty, hard-capped at the shape's max
    speed). It returns the path position ``SMOOTH_LAG`` frames back — informed by
    that many *future* frames — so a one-frame distractor is dropped (it never
    lies on a smooth path) while a genuinely moving shape is followed to the end.
    This is the online analog of the offline optimal-trajectory search; unlike the
    greedy filters that preceded it, it keeps the lock all the way to the finish,
    which is what passes the mini-game.

    Coordinates are box-interior pixels. ``update`` is called once per frame with
    the box-interior B-R signal channel (``cool_channel``) and the green-cursor
    mask; ``plate`` (settable) is the matching B-R background estimate. ``seed_xy``
    is only the initial output before the buffer fills.
    """

    def __init__(self, plate, seed_xy, startspot=None):
        self.plate = plate
        self.h, self.w = plate.shape
        self._startspot = startspot   # disc to mask (fading plate artifact there)
        self._buf = deque(maxlen=SMOOTH_WINDOW)   # candidate list per buffered frame
        self._out = (float(seed_xy[0]), float(seed_xy[1]))
        self._prev = self._out

    @property
    def pos(self):
        return self._out

    @property
    def vel(self):
        """Per-frame output step (px/frame) — exposed for diagnostics."""
        return (self._out[0] - self._prev[0], self._out[1] - self._prev[1])

    def _dev(self, box_sig, green, cursor_xy=None):
        """Blurred positive B-R deviation from the plate, with everything that
        is *known not to be the shape* masked out: the green cursor pixels, a
        ``CURSOR_MASK_R`` disc around the cursor position we commanded (the
        reticle's anti-aliased glow leaks cool signal past the green mask — at
        ~5x the texture floor it out-shines a deeply faded shape, and a tracker
        must never track itself), and the start-spot (it carries a fading
        plate artifact from where the opaque shape sat)."""
        d = cv2.GaussianBlur(np.clip(box_sig - self.plate, 0, None), (0, 0), DEV_BLUR)
        d[green > 0] = 0.0
        if cursor_xy is not None:
            cv2.circle(d, (int(cursor_xy[0]), int(cursor_xy[1])),
                       CURSOR_MASK_R, 0.0, -1)
        if self._startspot is not None:
            cv2.circle(d, (int(self._startspot[0]), int(self._startspot[1])),
                       STARTSPOT_RADIUS, 0.0, -1)
        return d

    def _candidates(self, d):
        """Top ``SMOOTH_K`` deviation peaks as ``(x, y, reward)``: iteratively the
        strongest pixel, non-maximum suppressed by ``SMOOTH_SUPPRESS``, each scored
        by a robust z above the box floor and capped at ``REWARD_CAP`` so a lone
        strong distractor cannot outweigh a smooth path."""
        flat = d[d > 0]
        if flat.size >= 50:
            med = float(np.median(flat))
            scale = 1.4826 * (float(np.median(np.abs(flat - med))) + 1e-3)
        else:
            med, scale = 0.0, 1.0
        dd = d.copy()
        cand = []
        for _ in range(SMOOTH_K):
            _, mx, _, loc = cv2.minMaxLoc(dd)
            z = (mx - med) / scale
            if z < FLOOR_Z:
                break
            cand.append((float(loc[0]), float(loc[1]), min(z, REWARD_CAP)))
            cv2.circle(dd, loc, SMOOTH_SUPPRESS, 0.0, -1)
        return cand

    def update(self, box_sig, green, cursor_xy=None, extra=None):
        """Advance the smoother by one frame; return the estimated ``(x, y)``
        (lagged ``SMOOTH_LAG`` frames). ``box_sig`` is the B-R signal channel;
        ``cursor_xy`` is our own commanded cursor position (interior coords),
        masked from the search so the tracker can never track itself.

        ``extra`` is an optional list of ``(x, y, reward)`` candidates from
        another detector (the learned shape net) — they enter the same DP on
        the same reward scale, so whichever source carries signal on a given
        frame wins the smooth-path competition."""
        cand = self._candidates(self._dev(box_sig, green, cursor_xy))
        if extra:
            ex = [(float(x), float(y), min(float(r), NET_REWARD_CAP))
                  for (x, y, r) in extra]
            # Dedupe in the net's favour: a classical candidate that roughly
            # coincides with a (better-calibrated) net peak is its offset twin
            # — keeping both makes the path alternate between them and wobble.
            cand = [c for c in cand
                    if all(np.hypot(c[0] - e[0], c[1] - e[1]) > SMOOTH_SUPPRESS
                           for e in ex)]
            cand = cand + ex
        if not cand:                       # nothing above the floor: hold last output
            cand = [(self._out[0], self._out[1], 0.0)]
        self._buf.append(cand)

        # Forward DP over the buffered candidate sets for the smoothest strong path:
        # score[t][j] = best cumulative (reward - step penalty) ending at candidate
        # j of frame t; back[t][j] is the previous frame's chosen candidate.
        n = len(self._buf)
        score = [[c[2] for c in self._buf[0]]]
        back = [[-1] * len(self._buf[0])]
        for t in range(1, n):
            cur, prev, pscore = self._buf[t], self._buf[t - 1], score[t - 1]
            sc, bk = [], []
            for (x, y, z) in cur:
                best, bestk = -1e18, 0
                for k, (pxk, pyk, _) in enumerate(prev):
                    dist = np.hypot(x - pxk, y - pyk)
                    pen = dist * dist / SMOOTH_SCALE + (0.0 if dist <= SMOOTH_MAXSTEP
                                                        else SMOOTH_STEP_PEN)
                    val = pscore[k] - pen
                    if val > best:
                        best, bestk = val, k
                sc.append(best + z)
                bk.append(bestk)
            score.append(sc)
            back.append(bk)

        # Backtrack the best path and read the position SMOOTH_LAG frames back.
        j = int(np.argmax(score[-1]))
        path = [0] * n
        for t in range(n - 1, -1, -1):
            path[t] = j
            if t > 0:
                j = back[t][j]
        of = max(0, n - 1 - SMOOTH_LAG)
        c = self._buf[of][path[of]]
        self._prev = self._out
        self._out = (float(np.clip(c[0], 0, self.w - 1)),
                     float(np.clip(c[1], 0, self.h - 1)))
        return self._out


class CursorPilot:
    """Human-like cursor motion toward tracker targets (see the ``PILOT_*``
    constants above for the rationale).

    ``step(target_xy)`` advances one frame and returns the cursor position to
    set. Feed it a target every frame — pass ``None`` while there is nothing to
    chase and it brakes smoothly to rest. Motion is guaranteed continuous: per
    frame the position moves at most ``PILOT_SPEED`` px and the velocity changes
    at most ``PILOT_ACCEL`` px, whatever the target does. Coordinates are
    whatever space the targets are in (the caller maps to screen pixels).
    """

    def __init__(self, start_xy):
        self.pos = np.array(start_xy, np.float64)
        self.vel = np.zeros(2)
        self._tprev = None            # last target, for the velocity estimate
        self._tvel = np.zeros(2)      # EMA of the target's per-frame velocity

    @staticmethod
    def _cap(vec, limit):
        n = float(np.hypot(vec[0], vec[1]))
        return vec * (limit / n) if n > limit else vec

    def step(self, target_xy):
        """Advance one frame toward ``target_xy`` (or brake if ``None``);
        return the new cursor position as ``(x, y)``."""
        if target_xy is None:
            self._tprev = None
            self._tvel[:] = 0.0
            acc = -PILOT_KD * self.vel                 # brake to rest
        else:
            t = np.asarray(target_xy, np.float64)
            if self._tprev is not None:
                # A re-acquisition JUMP is not a velocity: clamp the delta so
                # the feed-forward only ever carries physical shape motion.
                d = np.clip(t - self._tprev, -PILOT_TVEL_CLAMP, PILOT_TVEL_CLAMP)
                self._tvel = (1 - PILOT_TVEL_EMA) * self._tvel + PILOT_TVEL_EMA * d
            self._tprev = t
            acc = PILOT_KP * (t - self.pos) + PILOT_KD * (self._tvel - self.vel)
        self.vel = self._cap(self.vel + self._cap(acc, PILOT_ACCEL), PILOT_SPEED)
        self.pos = self.pos + self.vel
        return (float(self.pos[0]), float(self.pos[1]))


class LieDetectorSolver:
    """End-to-end solver: feed BGR frames, get the target point to move the
    mouse to.

    State machine:

    * ``WAIT``    – searching for the play-box.
    * ``ACQUIRE`` – box found, follow the bright opaque shape; buffer frames
      once it starts moving.
    * ``TRACK``   – plate built, follow the fading shape with ``ShapeTracker``.

    ``process(frame_bgr)`` returns ``(x, y)`` in **frame** coordinates (the same
    coordinate space as the input frame), or ``None`` when there is no target
    yet / the game is over. Map that to screen coordinates by adding the capture
    window origin before calling ``SetCursorPos``.
    """

    def __init__(self, use_net=False):
        # The learned shape detector (see lie_detector_net) is opt-in: the
        # runtime player and offline eval enable it; unit tests and synthetic
        # runs stay classical. The model object survives reset() — only its
        # frame buffer is cleared.
        self.use_net = use_net
        self._net = None
        self._net_failed = False
        self._net_bgr = deque(maxlen=PLATE_BUF_MAX)   # NET-size BGR, for its plate
        self.reset()

    BOX_LOST_FRAMES = 15             # consecutive misses before declaring game over
    NET_PLATE_FRAMES = 32            # frames sampled into the net's BGR plate

    def reset(self):
        if self._net is not None:
            self._net.reset()
        self._net_bgr.clear()
        self.state = "WAIT"
        self.box = None              # locked (x, y, w, h) of the play-box
        self.inner = None            # (ix0, iy0) interior origin in frame coords
        self._misses = 0
        self._init_blob = None       # locked stationary shape position (settled)
        self._settled_area = None    # blob area when settled (for fade detection)
        self._onset = False          # the shape has started moving/fading
        self._onset_cnt = 0          # consecutive move/fade frames seen
        self._post_onset_n = 0       # frames buffered since onset
        self._acq_hist = deque(maxlen=SETTLE_FRAMES)
        self._sig_buf = deque(maxlen=PLATE_BUF_MAX)   # B-R signal channel, for the plate
        self._since_rebuild = 0
        self._plate_n = 0            # frame count the current plate was built from
        self.tracker = None
        self.last_target = None

    @property
    def box_center(self):
        """Centre of the locked play-box in frame coordinates, or ``None``.

        The shape always spawns in the middle of the box, so this is where the
        cursor should park during the countdown — before there is a shape to
        follow — arriving on the shape the moment it appears."""
        if self.box is None:
            return None
        x, y, w, h = self.box
        return (x + w / 2.0, y + h / 2.0)

    def _interior(self, frame_bgr):
        """Crop to the box interior; return (gray_f32, cool_f32, green_mask) or None.

        ``gray`` (luminance) drives acquisition of the bright opaque shape;
        ``cool`` (the B-R chromatic channel) drives plate-building and tracking.

        The play-box is fixed for the duration of the game, so its coordinates
        are locked on first detection and reused — this keeps the crop size
        constant (required for the background plate and tracker) and is robust
        to the few-pixel jitter in per-frame detection. After enough consecutive
        misses the game is assumed over and state is reset by the caller.
        """
        if self.box is None:
            box = detect_play_box(frame_bgr)
            if box is None:
                return None
            self.box = box
        else:
            # Confirm the box is still present; tolerate brief detection misses.
            if detect_play_box(frame_bgr) is None:
                self._misses += 1
                if self._misses > self.BOX_LOST_FRAMES:
                    return None
            else:
                self._misses = 0
        x, y, w, h = self.box
        m = BOX_INNER_MARGIN
        ix0, iy0 = x + m, y + m
        self.inner = (ix0, iy0)
        crop = frame_bgr[iy0:y + h - m, ix0:x + w - m]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
        return crop, gray, cool_channel(crop), green_cursor_mask(crop)

    def _to_frame(self, xy):
        return (self.inner[0] + xy[0], self.inner[1] + xy[1])

    def _start_tracking(self, seed_xy, cool, green, cursor_xy=None):
        plate = build_plate(list(self._sig_buf))
        # The acquisition seed (last bright-blob position) goes stale the moment
        # the shape fades: by now the shape has moved off the start-spot. Re-seed
        # at its *current* position — the strongest cool-deviation blob, with the
        # start-spot disc excluded (it carries a fading plate artifact from where
        # the opaque shape sat). The chromatic signal is strong enough that this
        # global pick is reliable; fall back to the acquisition seed if weak.
        seed = self._locate_in_deviation(cool, plate, green, cursor_xy) or seed_xy
        self.tracker = ShapeTracker(plate, seed, startspot=self._init_blob)
        self._plate_n = len(self._sig_buf)
        self._since_rebuild = 0
        self._refresh_net_plate()
        self.state = "TRACK"
        log.info("LieDetectorSolver: initial plate (%d frames), seed=%s, switching to TRACK",
                 self._plate_n, tuple(round(v) for v in seed))

    def _locate_in_deviation(self, cool, plate, green, cursor_xy=None):
        """Strongest cool-deviation blob in the whole box (start-spot and our
        own cursor excluded), used to seed/re-acquire the tracker.
        Returns ``(x, y)`` or None."""
        dev = cv2.GaussianBlur(np.clip(cool - plate, 0, None), (0, 0), DEV_BLUR)
        dev[green > 0] = 0.0
        if cursor_xy is not None:
            cv2.circle(dev, (int(cursor_xy[0]), int(cursor_xy[1])),
                       CURSOR_MASK_R, 0.0, -1)
        if self._init_blob is not None:
            cv2.circle(dev, (int(self._init_blob[0]), int(self._init_blob[1])),
                       STARTSPOT_RADIUS, 0.0, -1)
        _, mx, _, loc = cv2.minMaxLoc(dev)
        return (float(loc[0]), float(loc[1])) if mx > SEED_MIN_PEAK else None

    def _maybe_rebuild_plate(self):
        """Rebuild the plate from the (now larger) rolling buffer as frames
        accumulate. This matters: early in tracking the slow-moving shape has not
        yet spread across the box, so an early plate is contaminated where the
        shape lingered; incorporating later frames (the shape now elsewhere)
        cleans it. Stopping early measurably lowered coverage, so we keep
        refreshing — the median is fast (``PLATE_MEDIAN_MAX``-capped)."""
        self._since_rebuild += 1
        if self._since_rebuild >= PLATE_REBUILD_EVERY and len(self._sig_buf) > self._plate_n:
            self.tracker.plate = build_plate(list(self._sig_buf))
            self._plate_n = len(self._sig_buf)
            self._since_rebuild = 0
            self._refresh_net_plate()

    def process(self, frame_bgr, cursor_xy=None):
        """Process one frame; return the target ``(x, y)`` in frame coords or None.

        Accepts BGR (the recorded clips) or BGRA (the live mss capture); the
        alpha plane is dropped. ``cursor_xy`` is our own cursor's position in
        frame coords (the caller commanded it, so it knows); it is masked from
        the shape search — the reticle's glow leaks past the green mask and a
        tracker must never track itself."""
        if frame_bgr.ndim == 3 and frame_bgr.shape[2] == 4:
            frame_bgr = np.ascontiguousarray(frame_bgr[:, :, :3])
        crop = self._interior(frame_bgr)
        if crop is None:
            # Box gone: game not started or already over.
            if self.state == "TRACK":
                self.reset()
            return None
        bgr, gray, cool, green = crop
        if cursor_xy is not None:
            cursor_xy = (cursor_xy[0] - self.inner[0], cursor_xy[1] - self.inner[1])
        return self._step(bgr, gray, cool, green, cursor_xy)

    def _get_net(self):
        """The learned detector, constructed on first use (or None: opted out,
        weights missing, torch unavailable — tracking degrades gracefully to
        the classical channel)."""
        if not self.use_net or self._net_failed:
            return None
        if self._net is None:
            try:
                from src.easymaple.detection.lie_detector_net import ShapeNetDetector
                self._net = ShapeNetDetector()
                log.info("LieDetectorSolver: shape net loaded (%s)", self._net.device)
            except Exception as e:
                self._net_failed = True
                log.warning("LieDetectorSolver: shape net unavailable (%s); "
                            "tracking classically", e)
        return self._net

    def _refresh_net_plate(self):
        """(Re)build the net's NET-scale BGR plate from the same rolling
        window the classical plate uses."""
        net = self._get_net()
        if net is None or not self._net_bgr:
            return
        stack = list(self._net_bgr)
        if len(stack) > self.NET_PLATE_FRAMES:
            stack = [stack[i] for i in
                     np.linspace(0, len(stack) - 1, self.NET_PLATE_FRAMES).astype(int)]
        net.set_plate(np.median(np.asarray(stack), axis=0).astype(np.uint8))

    def _net_candidates(self, bgr, cursor_xy):
        """Push this frame through the shape net; return smoother candidates
        ``(x, y, reward)`` in interior coords — never at our own cursor."""
        net = self._get_net()
        if net is None:
            return None
        hm = net.push(bgr)
        if hm is None:
            return None
        extra = []
        for (px, py, sc) in net.peaks(hm):
            if cursor_xy is not None and \
                    np.hypot(px - cursor_xy[0], py - cursor_xy[1]) <= CURSOR_MASK_R:
                continue
            # Focal-trained heatmap confidences are conservative (a correct
            # peak often reads ~0.2-0.5); saturate at 0.35 so a moderately
            # confident net peak reaches NET_REWARD_CAP — above the classical
            # cap, because a static plate-residual junk chain pays no step
            # penalty and would win every reward tie on smoothness alone.
            extra.append((px, py, NET_REWARD_CAP * min(1.0, sc / 0.35)))
        return extra

    def _step(self, bgr, gray, cool, green, cursor_xy=None):
        """Advance the state machine on one frame's box-interior signals.

        Split out from :meth:`process` so the state machine can be driven
        directly on pre-cropped interior signals (unit tests, offline tuning)
        without repeating play-box detection and cropping each call. ``bgr``
        is the interior crop, ``gray`` its luminance (float32), ``cool`` the
        B-R channel, ``green`` the cursor mask, ``cursor_xy`` our own
        commanded cursor in interior coords.
        """
        if self.state in ("WAIT", "ACQUIRE"):
            blob, area = _bright_blob(gray)
            if self.state == "WAIT":
                if blob is None:
                    return None
                self.state = "ACQUIRE"

            # Phase 1 — settle: lock the stationary shape once its position is
            # stable for SETTLE_FRAMES (ignores flickering countdown UI).
            if self._init_blob is None:
                if blob is not None:
                    self._acq_hist.append(blob)
                    self.last_target = self._to_frame(blob)
                    if len(self._acq_hist) == SETTLE_FRAMES:
                        arr = np.array(self._acq_hist)
                        if arr.std(axis=0).max() < SETTLE_STD:
                            self._init_blob = tuple(arr.mean(axis=0))
                            self._settled_area = area
                return self.last_target

            # Phase 2 — settled: keep following the bright shape and watch for
            # onset (it moves, fades, or vanishes). Once onset, buffer frames so
            # the plate is built from the shape-is-moving period, then hand off
            # to the tracker seeded at the last position we actually saw it.
            if blob is not None:
                self.last_target = self._to_frame(blob)
                if not self._onset:
                    moved = np.hypot(blob[0] - self._init_blob[0],
                                     blob[1] - self._init_blob[1]) > MOTION_ONSET_PX
                    faded = area < FADE_FRAC * self._settled_area
                    # Require the condition to persist so transient occlusion of
                    # the disc by the cursor during prep doesn't trip onset.
                    self._onset_cnt = self._onset_cnt + 1 if (moved or faded) else 0
                    self._onset = self._onset_cnt >= ONSET_CONFIRM
            else:
                self._onset_cnt += 1
                self._onset = self._onset or self._onset_cnt >= ONSET_CONFIRM

            # Buffer B-R frames for the plate from settle onward. The plate is a
            # plain median, which rejects the moving shape (a per-pixel minority)
            # on its own; the stationary opaque shape at the start-spot survives it
            # for a few frames, but the tracker masks the start-spot from its
            # search anyway, so no explicit exclusion is needed here.
            self._sig_buf.append(cool)
            if self.use_net:
                self._net_bgr.append(net_mod.resize_net(bgr))

            if self._onset:
                self._post_onset_n += 1
                if self._post_onset_n >= PLATE_MIN_FRAMES and self.last_target is not None:
                    seed = (self.last_target[0] - self.inner[0],
                            self.last_target[1] - self.inner[1])
                    self._start_tracking(seed, cool, green, cursor_xy)
            return self.last_target

        if self.state == "TRACK":
            # Keep growing the rolling plate buffer and refine the plate.
            self._sig_buf.append(cool)
            if self.use_net:
                self._net_bgr.append(net_mod.resize_net(bgr))
            self._maybe_rebuild_plate()
            xy = self.tracker.update(cool, green, cursor_xy,
                                     extra=self._net_candidates(bgr, cursor_xy))
            self.last_target = self._to_frame(xy)
            return self.last_target

        return self.last_target
