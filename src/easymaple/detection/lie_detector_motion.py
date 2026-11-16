"""Motion-based detector for the Lie Detector mini-game.

What the recordings show (see ``private_scripts/lie_detector/motion/FINDINGS.md``):

* Once the game starts, the whole camouflage field **pans** (~4-8 px/frame,
  direction rotating smoothly). The distractor outlines/discs ride along with
  it: the distractors all move *in the same direction*.
* The real shape is opaque only for the first ~1 s. After that it is
  invisible in any single frame — no brightness, colour or edge excess at the
  cursor (measured leak-free over 278 human-played clips) — but it is
  visible **in motion**: the texture inside it does not move with the field.
  The motion-compensated residual around the human's cursor sits at the
  ~90-99th percentile of the box for the whole game.

So the detector works in the frame of reference of the distractors: every
reference frame is aligned to the current one by the field's global motion
(phase correlation), so everything that moves with the field cancels, and a
small fully-convolutional net turns the aligned stack into a per-pixel
"moving-independently" score.

**Leak-proofing.** In every recording the green reticle sits on the target, so
anything that can see the reticle learns "the target is where the cursor is"
(the previous solver's offline validation did exactly that: masked like the
runtime masks its own cursor, it fell from 22/23 to 0/23 locked-at-end). Here
the reticle (and its warped copies in the reference frames) is blanked with a
disc of radius ``HOLE_R``, and only pixels whose receptive field cannot reach a
blanked disc are ever supervised or scored (``EXCL_R``). The net therefore
cannot see where any cursor is — in training or at runtime.

This module is pure NumPy/OpenCV (+ optional torch for the net) and performs
no I/O.
"""

import logging
import os
import time

import cv2
import numpy as np

log = logging.getLogger(__name__)

BOX_MARGIN = 8            # px trimmed inside the detected play-box border
SCALE = 2                 # detector works at 1/SCALE resolution
REF_OFFSETS = (-7, -5, -3, -1)   # reference frames (raw frame offsets, dups skipped):
                                 # causal, so estimates are for the current frame
HOLE_R = 15               # half-res px blanked around every cursor (~30 px full-res:
                          # reticle + its anti-aliased halo + codec ringing)
NET_RF_R = 3              # receptive-field radius of MotionNet (7x7)
EXCL_R = HOLE_R + NET_RF_R + 1   # outputs within this of a hole are never used
MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                          "assets", "models", "lie_detector_motion.pt")


def half_res(crop_bgr):
    h, w = crop_bgr.shape[:2]
    return cv2.resize(crop_bgr, (w // SCALE, h // SCALE), interpolation=cv2.INTER_AREA)


def gray_f(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)


def shift_int(img, dx, dy, fill=0):
    """``out(x) = img(x - d)`` with ``d`` rounded to whole pixels; uncovered
    pixels get ``fill``. Integer shifts avoid interpolation blur (which leaves
    residue on the thin distractor outlines)."""
    dx, dy = int(round(dx)), int(round(dy))
    h, w = img.shape[:2]
    out = np.full_like(img, fill)
    if abs(dx) >= w or abs(dy) >= h:
        return out
    xs0, xs1 = max(0, -dx), min(w, w - dx)
    ys0, ys1 = max(0, -dy), min(h, h - dy)
    out[ys0 + dy:ys1 + dy, xs0 + dx:xs1 + dx] = img[ys0:ys1, xs0:xs1]
    return out


def pick_refs(t, dup, n, offsets=None):
    """Reference frame indices for frame ``t``: each offset, stepped outward
    past duplicate frames. Returns None if any falls outside ``[0, n)``."""
    offsets = REF_OFFSETS if offsets is None else offsets
    refs = []
    for o in offsets:
        s = t + o
        step = 1 if o > 0 else -1
        while 0 <= s < n and dup[s]:
            s += step
        if not (0 <= s < n):
            return None
        refs.append(s)
    return refs


def build_input(cur, refs, shifts, holes_cur, holes_refs):
    """Network input for one frame.

    :param cur: half-res BGR uint8 frame.
    :param refs: list of half-res BGR uint8 reference frames.
    :param shifts: per reference, the ``(dx, dy)`` that maps it onto ``cur``.
    :param holes_cur: cursor positions (half-res) in ``cur``.
    :param holes_refs: per reference, cursor positions in that frame.
    :returns: ``(x, valid)`` — float32 ``(3 + 3*len(refs), h, w)`` and a bool
        ``(h, w)`` map of pixels whose outputs may be used (outside
        ``EXCL_R`` of every blanked disc, and covered by every reference —
        filling uncovered pixels from another reference was tried on
        2026-10-13: no measurable gain, and it doubled a pull toward the wall
        the texture enters from).
    """
    h, w = cur.shape[:2]
    blank = np.zeros((h, w), np.uint8)
    for (x, y) in holes_cur:
        if np.isfinite(x):
            cv2.circle(blank, (int(round(x)), int(round(y))), HOLE_R, 1, -1)
    c = cur.astype(np.float32)
    chans = [c / 255.0 - 0.5]
    invalid = np.zeros((h, w), np.uint8)
    for ref, (dx, dy), hl in zip(refs, shifts, holes_refs):
        r = ref.astype(np.float32)
        hb = np.zeros((h, w), np.uint8)
        for (x, y) in hl:
            if np.isfinite(x):
                cv2.circle(hb, (int(round(x)), int(round(y))), HOLE_R, 1, -1)
        rw = shift_int(r, dx, dy, fill=np.nan)
        hbw = shift_int(hb, dx, dy, fill=0)
        blank |= hbw
        bad = np.isnan(rw[..., 0])
        invalid |= bad.astype(np.uint8)
        rw = np.nan_to_num(rw, nan=0.0)
        d = (c - rw) / 64.0
        d[bad] = 0.0
        chans.append(d)
    x = np.concatenate([ch.transpose(2, 0, 1) for ch in chans], axis=0)
    x[:, blank > 0] = 0.0
    # blank already covers HOLE_R; grow it by the receptive field (+1) so the
    # exclusion radius from a cursor is EXCL_R
    k = 2 * (NET_RF_R + 1) + 1
    near_hole = cv2.dilate(blank, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    k2 = 2 * NET_RF_R + 1
    near_bad = cv2.dilate(invalid, np.ones((k2, k2), np.uint8)) > 0
    valid = ~near_hole & ~near_bad
    return x.astype(np.float32), valid


POOL_R = 34               # half-res radius of the evidence pooling disc (~shape size)
DEN_MIN = 0.08            # min fraction of usable pixels in the disc for evidence
DEN_FLOOR = 0.4           # a disc with fewer usable pixels is averaged as if it had this
                          # many (the rest counting 0): near the walls (texture the
                          # pan just brought in has no reference) a mean over few
                          # pixels is noisy, and its spikes pulled the tracker off the
                          # shape. Mid-field discs are ~fully usable (FINDINGS §12)


def disc_kernel(r):
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    k = (np.hypot(xx, yy) <= r).astype(np.float32)
    return k / k.sum()


class GridTracker:
    """Track-before-detect: a Bayes filter over a coarse grid of positions.

    Each frame the belief diffuses (random walk, ``q`` half-res px/frame — the
    shape moves smoothly, rarely faster than ~5 px/frame at half res) and is
    multiplied by ``exp(beta * evidence)``. Weak, flickering evidence that a
    per-frame detector would get wrong accumulates along the shape's smooth
    path, while clutter that flickers around the box averages out. A small
    floor keeps every position reachable, so a lost track can recover.
    """

    def __init__(self, shape_hw, seed_xy, cell=2, q=3.0, beta=2.0, clip=3.0,
                 floor=1e-7, seed_sigma=6.0):
        self.cell = cell
        self.h, self.w = shape_hw[0] // cell, shape_hw[1] // cell
        self.q, self.beta, self.clip, self.floor = q, beta, clip, floor
        b = np.zeros((self.h, self.w), np.float64)
        cx = int(np.clip(seed_xy[0] / cell, 0, self.w - 1))
        cy = int(np.clip(seed_xy[1] / cell, 0, self.h - 1))
        b[cy, cx] = 1.0
        b = cv2.GaussianBlur(b, (0, 0), seed_sigma / cell)
        self.b = b / b.sum()
        self.pos = (float(seed_xy[0]), float(seed_xy[1]))

    def step(self, ev, dt_scale=1.0):
        """Advance one frame with evidence map ``ev``; returns the position
        estimate in half-res pixels. ``dt_scale`` = time since the previous
        step in 1/30 s units (the shape moves further between sparser frames)."""
        q = self.q * float(np.clip(dt_scale, 1.0, 3.0))
        b = cv2.GaussianBlur(self.b, (0, 0), q / self.cell)
        b = b + self.floor / b.size
        e = cv2.resize(ev, (self.w, self.h), interpolation=cv2.INTER_AREA)
        b = b * np.exp(self.beta * np.clip(e, -self.clip, self.clip))
        self.b = b / b.sum()
        yy, xx = np.unravel_index(np.argmax(self.b), self.b.shape)
        y0, y1 = max(0, yy - 3), min(self.h, yy + 4)
        x0, x1 = max(0, xx - 3), min(self.w, xx + 4)
        wgt = self.b[y0:y1, x0:x1]
        gy, gx = np.mgrid[y0:y1, x0:x1]
        cy = (wgt * gy).sum() / wgt.sum()
        cx = (wgt * gx).sum() / wgt.sum()
        self.pos = ((cx + 0.5) * self.cell, (cy + 0.5) * self.cell)
        return self.pos


def _disc_mask(h, w, pts, r):
    m = np.zeros((h, w), np.uint8)
    for (x, y) in pts:
        if np.isfinite(x):
            cv2.circle(m, (int(round(x)), int(round(y))), r, 1, -1)
    return m


_EXCL_K = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * (NET_RF_R + 1) + 1,) * 2)
_RF_K = np.ones((2 * NET_RF_R + 1,) * 2, np.uint8)


def build_input_fast(cur, refs, shifts, holes_cur, holes_refs):
    """Same result as :func:`build_input`, much faster (integer shifts as
    slices, differences written straight into the output over each
    reference's covered rectangle, no NaN round-trips). Used at runtime."""
    h, w = cur.shape[:2]
    n = len(refs)
    x = np.zeros((3 + 3 * n, h, w), np.float32)
    c = np.ascontiguousarray(cur.transpose(2, 0, 1), dtype=np.float32)
    np.multiply(c, 1.0 / 255.0, out=x[0:3])
    x[0:3] -= 0.5
    blank = _disc_mask(h, w, holes_cur, HOLE_R)
    covered = np.ones((h, w), bool)
    for k, (ref, (dx, dy), hl) in enumerate(zip(refs, shifts, holes_refs)):
        dx, dy = int(round(dx)), int(round(dy))
        if abs(dx) >= w or abs(dy) >= h:
            covered[:] = False
            continue
        xs0, xs1 = max(0, -dx), min(w, w - dx)
        ys0, ys1 = max(0, -dy), min(h, h - dy)
        ty, tx = slice(ys0 + dy, ys1 + dy), slice(xs0 + dx, xs1 + dx)
        d = x[3 + 3 * k:6 + 3 * k, ty, tx]
        np.subtract(c[:, ty, tx], ref.transpose(2, 0, 1)[:, ys0:ys1, xs0:xs1], out=d)
        d *= 1.0 / 64.0
        cov = np.zeros((h, w), bool)
        cov[ty, tx] = True
        covered &= cov
        if hl:
            hb = _disc_mask(h, w, hl, HOLE_R)
            hbw = np.zeros_like(hb)
            hbw[ys0 + dy:ys1 + dy, xs0 + dx:xs1 + dx] = hb[ys0:ys1, xs0:xs1]
            blank |= hbw
    invalid = (~covered).astype(np.uint8)
    if blank.any():
        x[:, blank > 0] = 0.0
    valid = (cv2.dilate(blank, _EXCL_K) == 0) & (cv2.dilate(invalid, _RF_K) == 0)
    return x, valid


GRID = 2                  # tracker / evidence cell size (half-res px)
_POOL_KG = disc_kernel(POOL_R // GRID)
WALL_FLOOR = 0.5          # DEN_FLOOR within WALL_BAND of the field edge: a stronger clutter
WALL_BAND = 20            # background left brief wall spikes the strongest competitors
                          # (FINDINGS §13). Only along the walls: mid-field the cursor
                          # hole lowers the tracked shape's own usable fraction to ~0.5
_FLOOR_MAPS = {}


def _floor_map(gh, gw, floor, wall_floor):
    key = (gh, gw, floor, wall_floor)
    if key not in _FLOOR_MAPS:
        yy, xx = np.mgrid[:gh, :gw]
        edge = np.minimum(np.minimum(yy + 0.5, gh - yy - 0.5), np.minimum(xx + 0.5, gw - xx - 0.5)) * GRID
        _FLOOR_MAPS[key] = np.where(edge < WALL_BAND, max(wall_floor, floor), floor).astype(np.float32)
    return _FLOOR_MAPS[key]


def evidence_grid(logit, valid, den_floor=None, wall_floor=None):
    """Per-position evidence that the shape is centred there, at the tracker's
    grid resolution (cell = ``GRID`` half-res px): the mean logit over usable
    pixels in a shape-sized disc (at least ``den_floor``, default
    ``DEN_FLOOR``, of it counted; ``wall_floor``, default ``WALL_FLOOR``,
    within ``WALL_BAND`` of the walls), relative to the box median. Positions
    with too few usable pixels get 0 (no information)."""
    v = valid.astype(np.float32)
    h, w = logit.shape
    gh, gw = h // GRID, w // GRID
    lv = cv2.resize((logit * v)[:gh * GRID, :gw * GRID], (gw, gh), interpolation=cv2.INTER_AREA)
    vv = cv2.resize(v[:gh * GRID, :gw * GRID], (gw, gh), interpolation=cv2.INTER_AREA)
    num = cv2.filter2D(lv, -1, _POOL_KG, borderType=cv2.BORDER_CONSTANT)
    den = cv2.filter2D(vv, -1, _POOL_KG, borderType=cv2.BORDER_CONSTANT)
    floor = DEN_FLOOR if den_floor is None else max(den_floor, 1e-6)
    wall = WALL_FLOOR if wall_floor is None else float(wall_floor)
    A = num / np.maximum(den, _floor_map(gh, gw, floor, wall) if wall > floor else floor)
    ok = den >= DEN_MIN
    if ok.any():
        A = A - np.median(A[ok])
    A[~ok] = 0.0
    return A


CLUTTER_TAU = 2.0         # s: memory of the clutter background (see ClutterBackground)
CLUTTER_K = 0.65          # weight of its positive part subtracted from the evidence (0 = off)
CLUTTER_MAX_DT = 0.12     # s: one update never spans more (~3 frames), so after a stalled
                          # stream the background is not replaced by a single frame


class ClutterBackground:
    """Evidence that stays put in the box is clutter, not the shape.

    Some clutter is fixed to the play-box rather than to the panning field: a
    faint imprint the opaque shape leaves at its start position (the box
    centre: the strongest spot of the time-averaged evidence away from the
    shape in all 46 held-out clips and 7 of 8 labelled live games), residue
    along the walls (FINDINGS §12). To the net it
    looks exactly like the shape (texture that does not move with the field),
    and the tracker parks on it. The shape keeps moving (it stays within 60 px
    of a spot for ~0.7 s typically), so an exponential average of each
    position's evidence over ``tau`` seconds is mostly clutter; ``k`` times its
    positive part is subtracted from each frame's evidence before the tracker
    sees it. ``k`` = 0 leaves the evidence untouched.

    The imprint is the shape's outline from the countdown, a ring ~50-70 px
    from the centre. When the shape fades for 1-3 s it is the strongest thing
    left, and τ = 0.5 s / k = 0.5 removed too little of it: both live failures
    (2026-10-13 11:35, 2026-10-28 12:16) drifted onto it. τ = 2 s / k = 0.65
    clears it, while a shape that lingers under a second stays mostly unlearned
    (FINDINGS §13).
    """

    def __init__(self, tau=CLUTTER_TAU, k=CLUTTER_K):
        self.tau, self.k = float(tau), float(k)
        self.bg = None
        self.t = None

    def apply(self, ev, t):
        """Evidence map at capture time ``t`` (s) in, suppressed map out."""
        if self.k <= 0:
            return ev
        if self.bg is None or self.bg.shape != ev.shape:
            self.bg = np.zeros_like(ev)
            self.t = t
        out = ev - self.k * np.maximum(self.bg, 0.0)
        a = 1.0 - np.exp(-min(max(t - self.t, 1e-3), CLUTTER_MAX_DT) / self.tau)
        self.bg += a * (ev - self.bg)
        self.t = t
        return out


def _torch():
    try:
        import torch  # noqa: F401
        return torch
    except Exception:          # pragma: no cover - torch missing
        return None


def make_net(n_refs=None, width=48):
    """Fully-convolutional per-pixel scorer with a 7x7 receptive field
    (``NET_RF_R`` = 3): three 3x3 convs, then 1x1 mixing."""
    in_ch = 3 + 3 * (len(REF_OFFSETS) if n_refs is None else n_refs)
    torch = _torch()
    nn = torch.nn
    return nn.Sequential(
        nn.Conv2d(in_ch, width, 3, padding=1), nn.ReLU(inplace=True),
        nn.Conv2d(width, width, 3, padding=1), nn.ReLU(inplace=True),
        nn.Conv2d(width, width, 3, padding=1), nn.ReLU(inplace=True),
        nn.Conv2d(width, width, 1), nn.ReLU(inplace=True),
        nn.Conv2d(width, 32, 1), nn.ReLU(inplace=True),
        nn.Conv2d(32, 1, 1),
    )


def load_net(path=MODEL_PATH, device=None):
    """Load MotionNet weights; returns ``(net, device)``. Raises if torch or
    the weights are unavailable."""
    torch = _torch()
    if torch is None:
        raise RuntimeError("torch unavailable")
    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    ck = torch.load(os.path.normpath(path), map_location=dev, weights_only=False)
    offsets = tuple(int(o) for o in ck.get("ref_offsets", REF_OFFSETS))
    for key, const in (("hole_r", HOLE_R), ("rf_r", NET_RF_R)):
        if key in ck and int(ck[key]) != const:
            raise ValueError(f"{path}: trained with {key}={ck[key]}, runtime uses {const}")
    net = make_net(len(offsets), width=int(ck.get("width", 48))).to(dev)
    net.load_state_dict(ck["state"])
    net.eval()
    net.ref_offsets = offsets
    # Checkpoints without the key were trained on Hanning-windowed alignment
    # (see pc_crop); they run with it, as trained.
    net.pc_window = bool(ck.get("pc_window", True))
    return net, dev


# --- Runtime solver ---------------------------------------------------------
BOX_W = (690, 770)        # accepted play-box size, as detected (the range the
BOX_H = (410, 480)        # training cache accepts). Wider gates let combat effects
                          # and the box's opening animation lock a wrong box.
BOX_AGREE_PX = 6          # detections within this of each other are the same box
BOX_LOCK_S = 0.15         # ... and must agree this long before the box is locked
BOX_LOST_S = 0.5          # the locked box gone this long: it is gone (time, not
                          # frames: 15 frames is only 0.25 s at 60 Hz capture)
MAX_RELOCKS = 3           # re-locks to a better box before START
START_SPEED = 1.25        # half-res px/frame: the field has started panning
START_CONFIRM = (5, 8)    # ... on >=5 of the last 8 non-duplicate frames
DUP_RESP = 0.97           # phase-correlation response of a repeated frame
FRAME_DT = 30.0 / 738     # the recordings' real frame interval (~24.6 fps: the
                          # recorder slept 1/30 s *after* each write; median 738
                          # frames per 30 s clip). REF_OFFSETS, START_SPEED and the
                          # tracker's per-step motion are in these units.
SCORE_MIN_DT = 0.75 * FRAME_DT  # scoring cap: every frame of a 30 fps stream, every
                          # other one at 60
MAX_AHEAD = 4.0           # extrapolate the estimate at most this many FRAME_DTs
BOX_FILL_MIN = 0.45       # tan fraction of the locked box below which it is gone


REFINE_BOX = True         # grow the detected box to the field's real edges (below)
REFINE_REACH = 80         # px searched beyond each detected edge
REFINE_FRAC = 0.6         # a row/column is field while this much of it is tan
REFINE_INSET = 24         # px trimmed off the span a row/column is measured over


def refine_box(frame, box):
    """Grow ``detect_play_box``'s box to the camouflage field's real edges.
    The detector only searches the central region (``h*0.72``, ``w*0.15``),
    which on the 1054x824 capture clips the field's bottom ~48 px and left
    ~13 px: the shape goes there (8% of final-second frames) and the solver
    could neither see nor reach it. Each edge moves outward while the next
    row/column is tan across the box's span (the dialog border beyond the
    field is dark; a global search would bridge to tan map scenery instead).
    Edges that start on non-field rows/columns move inward first: while the
    dialog opens the detector's box can include the dark header above the
    field (every live box on 2026-10-13 started 19 px too high)."""
    from src.easymaple.detection.lie_detector_solver import BOX_HSV_LO, BOX_HSV_HI
    x, y, w, h = box
    H, W = frame.shape[:2]
    tan = cv2.inRange(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV), BOX_HSV_LO, BOX_HSV_HI) > 0
    r, f, k = REFINE_REACH, REFINE_FRAC, REFINE_INSET
    xs = slice(x + k, x + w - k)
    y0, y1 = y, y + h
    while y0 < min(y + r, y1 - 1) and tan[y0, xs].mean() <= f:
        y0 += 1
    while y1 > max(y + h - r, y0 + 1) and tan[y1 - 1, xs].mean() <= f:
        y1 -= 1
    ys = slice(y0 + k, y1 - k)
    x0, x1 = x, x + w
    while x0 < min(x + r, x1 - 1) and tan[ys, x0].mean() <= f:
        x0 += 1
    while x1 > max(x + w - r, x0 + 1) and tan[ys, x1 - 1].mean() <= f:
        x1 -= 1
    x, y, w, h = x0, y0, x1 - x0, y1 - y0
    xs = slice(x + k, x + w - k)
    bottom = y + h
    while bottom < min(H, y + h + r) and tan[bottom, xs].mean() > f:
        bottom += 1
    ys = slice(y + k, bottom - k)
    left = x
    while left > max(0, x - r) and tan[ys, left - 1].mean() > f:
        left -= 1
    right = x + w
    while right < min(W, x + w + r) and tan[ys, right].mean() > f:
        right += 1
    top = y
    while top > max(0, y - r) and tan[top - 1, slice(left + k, right - k)].mean() > f:
        top -= 1
    return (left, top, right - left, bottom - top)


def pc_size(n):
    """Largest even ``m <= n`` that needs no FFT padding. ``cv2.phaseCorrelate``
    (OpenCV 4.9) biases the shift by +0.5 px on any axis padded to an *odd*
    size (217 rows pad to 225: identical frames read (0, 0.5)), and with a
    window it multiplies its inputs by it *in place* when no padding is
    needed. Correlating m-sized copies without a window avoids both."""
    m = n - (n % 2)
    while m > 8 and cv2.getOptimalDFTSize(m) != m:
        m -= 2
    return m


def pc_crop(h, w):
    """Centred ``pc_size`` slices of an h x w image, for ``phaseCorrelate``.
    No window: a Hanning window weights the field's centre, where the opaque
    shape sits still after START (and where the invisible shape's own motion
    then counts most) — the correlation followed the shape instead of the
    panning field. On the ten live games of 2026-10-13, 8-29% of tracking
    frames were > 2 px off the best whole-pixel alignment (up to 67% in the
    seconds after START); unwindowed 0-2%. Models trained before that were
    trained on windowed alignment and keep it (``net.pc_window``)."""
    ph, pw = pc_size(h), pc_size(w)
    y0, x0 = (h - ph) // 2, (w - pw) // 2
    return slice(y0, y0 + ph), slice(x0, x0 + pw)


def is_duplicate(resp, dx, dy, mean_absdiff):
    """The capture repeats frames (~20% in the recordings; every other one
    when 60 Hz capture meets a 30 fps stream). A repeat has (almost) zero
    shift and either (almost) no pixel change or a near-perfect correlation.
    (Small real motion of a smooth texture can change pixels very little, so
    the shift test is required — except for a bit-exact live repeat.)"""
    if mean_absdiff < 0.01:
        return True
    still = abs(dx) < 0.5 and abs(dy) < 0.5
    return still and (mean_absdiff < 0.8 or resp > DUP_RESP)


class MotionLieDetectorSolver:
    """End-to-end runtime solver: feed BGR(A) frames, get the point to put the
    mouse on (frame coordinates). Same interface as ``LieDetectorSolver``.

    * ``WAIT``    - looking for the play-box.
    * ``ACQUIRE`` - box locked; follow the opaque shape (largest bright blob)
      during the countdown, and watch for START: the moment the camouflage
      field starts to pan.
    * ``TRACK``   - the shape is invisible from here on; follow it with the
      leak-proof MotionNet + :class:`GridTracker`, seeded where the opaque
      shape was at START.

    Frame ``t`` is scored once its reference frames up to ``t+4`` have
    arrived, so estimates are a few frames old; the output extrapolates them
    to the present with the tracker's smoothed velocity.
    """

    BUF = 48

    def __init__(self, model_path=MODEL_PATH, device=None, tracker_kw=None, net=None,
                 time_refs=True, refine=None, clutter=None, den_floor=None, wall_floor=None):
        self.refine = REFINE_BOX if refine is None else refine
        # (tau, k) of the ClutterBackground, (0, 0) = off; evidence_grid's floor
        # (0 = a plain mean, the solver before 2026-10-14) and wall floor (0 =
        # none, the solver before 2026-10-28)
        self.clutter = (CLUTTER_TAU, CLUTTER_K) if clutter is None else tuple(clutter)
        self.den_floor = DEN_FLOOR if den_floor is None else float(den_floor)
        self.wall_floor = WALL_FLOOR if wall_floor is None else float(wall_floor)
        # time_refs: pick reference frames by capture time (FRAME_DT units), so
        # the spacing matches the recordings the net was trained on whatever
        # rate frames actually arrive at. False = by frame count (only correct
        # for a feed at the recordings' rate, e.g. replaying them).
        self.time_refs = time_refs
        if net is None:
            net, device = load_net(model_path, device)
        self.net, self.device = net, device
        self.ref_offsets = tuple(getattr(net, "ref_offsets", REF_OFFSETS))
        # align the way the net was trained (see pc_crop)
        self.pc_window = bool(getattr(net, "pc_window", False))
        self.tracker_kw = dict(tracker_kw or {})
        self.reset()

    def warm_up(self):
        """A few dummy passes so CUDA/cuDNN set-up happens now, not in a game."""
        torch = _torch()
        x = torch.zeros((1, 3 + 3 * len(self.ref_offsets), 216, 360), device=self.device)
        with torch.no_grad():
            for _ in range(3):
                self.net(x)

    def reset(self):
        self.state = "WAIT"
        self.box = None
        self.inner = None
        self._miss_t0 = None       # when the locked box was first missing
        self._cands = []           # (t, box) recent gate-passing detections
        self._relocks = 0
        self._clear_buffers()
        self._scored_time = None
        self._speed_hist = []
        self._next_t = None
        self._blob = None
        self.tracker = None
        self._est_prev = None
        self._vel = np.zeros(2)
        self._est_t = None
        self._est_time = None
        self.last_target = None
        self.last_evidence = None
        self.last_half = None

    def _clear_buffers(self):
        self._frames = {}         # T -> half-res BGR
        self._gray = {}           # T -> half-res gray f32
        self._dup = {}            # T -> bool
        self._holes = {}          # T -> half-res cursor positions to blank
        self._times = {}          # T -> capture time (s)
        self._pcg = {}            # T -> pc_crop of the gray frame, for phaseCorrelate
        self._last_nd = None      # newest non-duplicate frame
        self._T = -1
        self._pc_slices = None
        self._win = None
        self._pairs = {}          # (a, b) -> field motion a->b
        self._clutter = ClutterBackground(*self.clutter)

    @property
    def box_center(self):
        if self.box is None:
            return None
        x, y, w, h = self.box
        return (x + w / 2.0, y + h / 2.0)

    # -- helpers -------------------------------------------------------------
    def _detect(self, frame):
        from src.easymaple.detection.lie_detector_solver import detect_play_box
        b = detect_play_box(frame)
        if b is None or not (BOX_W[0] <= b[2] <= BOX_W[1] and BOX_H[0] <= b[3] <= BOX_H[1]):
            return None
        b = tuple(int(v) for v in b)
        return refine_box(frame, b) if self.refine else b

    def _stable_box(self, b, t):
        """Feed one detection (or None); the median box once detections have
        agreed for ``BOX_LOCK_S`` (a combat effect that passes for a box for a
        frame or two must not be locked), else None."""
        if b is None:
            self._cands = []
            return None
        self._cands = [(tc, c) for tc, c in self._cands
                       if max(abs(np.subtract(c, b))) <= BOX_AGREE_PX] + [(t, b)]
        if t - self._cands[0][0] < BOX_LOCK_S:
            return None
        return tuple(int(v) for v in np.median([c for _, c in self._cands], axis=0))

    def _lock(self, b):
        self.box = b
        self.inner = (b[0] + BOX_MARGIN, b[1] + BOX_MARGIN)
        self._miss_t0 = None

    def _locate(self, frame, t):
        """Find (WAIT) or confirm (afterwards) the play-box. Once locked, a
        cheap tan-fill check on the locked rectangle replaces full-frame
        detection (which costs ~10 ms a frame) — except before START, when
        detection keeps running: the first lock can include the dialog's
        header or be a sub-rectangle, and a better stable box re-locks."""
        if self.box is None:
            b = self._stable_box(self._detect(frame), t)
            if b is None:
                return False
            self._lock(b)
            self._cands = []
            return True
        if self.state == "ACQUIRE" and self._relocks < MAX_RELOCKS:
            b = self._stable_box(self._detect(frame), t)
            if b is not None and max(abs(np.subtract(b, self.box))) > BOX_AGREE_PX:
                log.info("MotionLieDetectorSolver: re-lock %s -> %s", self.box, b)
                self._relocks += 1
                self._lock(b)
                self._cands = []
                self._clear_buffers()     # crop size changed: start the history afresh
                self._speed_hist = []
                self._blob = None
        if not self._box_present(frame):
            if self._miss_t0 is None:
                self._miss_t0 = t
            return t - self._miss_t0 <= BOX_LOST_S
        self._miss_t0 = None
        return True

    def _box_present(self, frame):
        from src.easymaple.detection.lie_detector_solver import BOX_HSV_LO, BOX_HSV_HI
        x, y, w, h = self.box
        small = cv2.resize(frame[y:y + h, x:x + w], (w // 8, h // 8), interpolation=cv2.INTER_AREA)
        fill = cv2.inRange(cv2.cvtColor(small, cv2.COLOR_BGR2HSV), BOX_HSV_LO, BOX_HSV_HI)
        return float(fill.mean()) / 255.0 > BOX_FILL_MIN

    def _crop(self, frame):
        x, y, w, h = self.box
        m = BOX_MARGIN
        return frame[y + m:y + h - m, x + m:x + w - m]

    def _push(self, crop, cursor_xy, t_now):
        from src.easymaple.detection.lie_detector_solver import green_cursor_mask
        T = self._T = self._T + 1
        self._times[T] = t_now
        hb = half_res(crop)
        g = gray_f(hb)
        if self._pc_slices is None:
            self._pc_slices = pc_crop(*g.shape)
            ys, xs = self._pc_slices
            if self.pc_window:
                self._win = cv2.createHanningWindow((xs.stop - xs.start, ys.stop - ys.start), cv2.CV_32F)
        self._gray[T] = g
        c = g[self._pc_slices]
        self._pcg[T] = c * self._win if self._win is not None else np.ascontiguousarray(c)
        dup, speed = False, 0.0
        if T - 1 in self._gray:
            dx, dy, r = self._shift(T - 1, T)
            dup = is_duplicate(r, dx, dy, float(np.abs(g - self._gray[T - 1]).mean()))
            if not dup and self._last_nd is not None and self._last_nd in self._gray:
                # Field speed per FRAME_DT since the last *distinct* frame (a
                # repeat in between would halve the apparent speed).
                ref = self._last_nd
                dx, dy, _ = self._shift(ref, T)
                gap = max(self._times[T] - self._times[ref], FRAME_DT / 2)
                speed = float(np.hypot(dx, dy)) * FRAME_DT / gap
        if not dup:
            self._last_nd = T
        # Every cursor is blanked: each rendered reticle, plus where we put ours.
        gm = green_cursor_mask(hb)
        n, lab, st, cent = cv2.connectedComponentsWithStats(gm)
        holes = [tuple(cent[i]) for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 5]
        if cursor_xy is not None:
            holes.append(((cursor_xy[0] - self.inner[0]) / SCALE,
                          (cursor_xy[1] - self.inner[1]) / SCALE))
        self._frames[T], self._dup[T], self._holes[T] = hb, dup, holes
        self.last_half = hb           # the half-res box frame, for the game log
        for k in [k for k in self._frames if k < T - self.BUF]:
            for d in (self._frames, self._gray, self._dup, self._holes, self._times, self._pcg):
                d.pop(k, None)
        for key in [key for key in self._pairs if min(key) < T - self.BUF]:
            del self._pairs[key]
        if not dup:
            self._speed_hist = (self._speed_hist + [speed])[-START_CONFIRM[1]:]
        return T

    def _shift(self, a, b):
        """Field motion mapping frame a onto frame b: ``(dx, dy, response)``.
        Each pair is correlated once; the reverse pair reuses it."""
        if (a, b) not in self._pairs:
            if (b, a) in self._pairs:
                dx, dy, r = self._pairs[(b, a)]
                return -dx, -dy, r
            # Unpadded copies, pre-windowed only for nets trained that way
            # (see pc_size, pc_crop): never a window argument.
            (dx, dy), r = cv2.phaseCorrelate(self._pcg[a], self._pcg[b])
            self._pairs[(a, b)] = (dx, dy, r)
        return self._pairs[(a, b)]

    def _refs(self, t):
        if self.time_refs and all(o < 0 for o in self.ref_offsets):
            return self._refs_by_time(t)
        return self._refs_by_count(t)

    def _refs_by_time(self, t):
        """For each offset, the distinct earlier frame captured nearest to
        ``offset * FRAME_DT`` before frame t (nearest offsets assigned first,
        no frame used twice). None until there is enough history."""
        now = self._times[t]
        cand = [k for k in self._frames if k < t and not self._dup.get(k, False)]
        if len(cand) < len(self.ref_offsets):
            return None
        if min(self._times[k] for k in cand) > now + min(self.ref_offsets) * FRAME_DT + FRAME_DT:
            return None
        chosen = {}
        for o in sorted(self.ref_offsets, key=abs):
            target = now + o * FRAME_DT
            free = [k for k in cand if k not in chosen.values()]
            chosen[o] = min(free, key=lambda k: abs(self._times[k] - target))
        return [chosen[o] for o in self.ref_offsets]

    def _refs_by_count(self, t):
        refs = []
        for o in self.ref_offsets:
            s, step = t + o, (1 if o > 0 else -1)
            while self._dup.get(s, False):
                s += step
            if s > self._T:
                return "wait"       # a forward reference has not been captured yet
            if s not in self._frames:
                return None         # a backward reference already left the buffer
            refs.append(s)
        return refs

    def _score(self, t, refs):
        torch = _torch()
        shifts = [self._shift(s, t)[:2] for s in refs]
        x, valid = build_input_fast(self._frames[t], [self._frames[s] for s in refs], shifts,
                                    self._holes[t], [self._holes[s] for s in refs])
        with torch.no_grad():
            logit = self.net(torch.from_numpy(x)[None].to(self.device))[0, 0].float().cpu().numpy()
        ev = self._clutter.apply(evidence_grid(logit, valid, self.den_floor, self.wall_floor), self._times[t])
        self.last_evidence = ev       # for visualisation
        return ev

    def _to_frame(self, xy_half):
        return (self.inner[0] + xy_half[0] * SCALE, self.inner[1] + xy_half[1] * SCALE)

    # -- main entry ----------------------------------------------------------
    def process(self, frame_bgr, cursor_xy=None, t=None):
        """One captured frame in, target ``(x, y)`` (frame coords) or None out.
        ``cursor_xy``: where we put our own cursor (frame coords); blanked like
        every rendered reticle. ``t``: capture time in seconds (defaults to
        now) — reference frames are chosen by time, not by count."""
        from src.easymaple.detection.lie_detector_solver import _bright_blob
        if frame_bgr.ndim == 3 and frame_bgr.shape[2] == 4:
            frame_bgr = np.ascontiguousarray(frame_bgr[:, :, :3])
        t_now = time.perf_counter() if t is None else float(t)
        if not self._locate(frame_bgr, t_now):
            if self.state != "WAIT":
                self.reset()
            return None
        if self.state == "WAIT":
            self.state = "ACQUIRE"
        crop = self._crop(frame_bgr)
        T = self._push(crop, cursor_xy, t_now)

        if self.state == "ACQUIRE":
            blob, _ = _bright_blob(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))
            if blob is not None:
                self._blob = (blob[0] / SCALE, blob[1] / SCALE)
                self.last_target = self._to_frame(self._blob)
            moving = sum(s > START_SPEED for s in self._speed_hist)
            if moving >= START_CONFIRM[0] and self._blob is not None:
                kw = dict(self.tracker_kw)
                kw.setdefault("cell", GRID)
                self.tracker = GridTracker(self._frames[T].shape[:2], self._blob, **kw)
                self._next_t = max(min(self._frames), T - START_CONFIRM[1])
                self.state = "TRACK"
                log.info("MotionLieDetectorSolver: START at frame %d, seed=%s", T,
                         tuple(round(v) for v in self._blob))
            return self.last_target

        # TRACK: score every frame whose reference frames have arrived
        while self._next_t is not None and self._next_t <= T:
            t = self._next_t
            if t not in self._frames:
                self._next_t += 1
                continue
            if self._dup.get(t, False) or (
                    self._scored_time is not None and self._times[t] - self._scored_time < SCORE_MIN_DT):
                # A repeated frame carries no new motion (its nearest
                # reference would be its own original), and frames faster than
                # ~30 Hz are not scored; they only refresh the extrapolation.
                if t == T:
                    break              # newest frame not due yet
                self._next_t += 1
                continue
            refs = self._refs(t)
            if refs == "wait":
                break
            if refs is None:
                self._next_t += 1
                continue
            steps = 1.0 if self._scored_time is None else \
                max(self._times[t] - self._scored_time, 1e-3) / FRAME_DT
            p = np.array(self.tracker.step(self._score(t, refs), dt_scale=max(steps, 1.0)))
            if self._est_prev is not None:
                self._vel = 0.7 * self._vel + 0.3 * (p - self._est_prev) / max(steps, 0.5)
            self._est_prev, self._est_t, self._scored_time = p, t, self._times[t]
            self._est_time = self._times[t]
            self._next_t += 1
        if self._est_time is not None:
            # Extrapolate the last estimate to now — bounded: if no frame has
            # been scorable for a while (the stream froze) the target holds
            # instead of running off along a stale velocity.
            ahead = min((self._times[T] - self._est_time) / FRAME_DT, MAX_AHEAD)
            p = self._est_prev + self._vel * ahead
            h, w = self._frames[T].shape[:2]
            p = np.clip(p, 0, [w - 1, h - 1])
            self.last_target = self._to_frame(p)
        return self.last_target
