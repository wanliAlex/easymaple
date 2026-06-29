"""Solver for the Lie Detector anti-bot mini-game.

The mini-game shows a rectangular camouflage play-field in which a bright shape
appears, sits still for a few seconds, then begins moving while fading into the
texture. The player must keep the mouse cursor on the moving shape; cumulative
dwell time determines pass/fail.

Approach (validated offline against the in-game cursor as ground truth):

1. **Locate the play-box** by its tan camouflage colour.
2. **Acquire** the shape while it is still a bright opaque blob (trivial).
3. **Work in the chromatic "coolness" channel** ``B - R`` (blue minus red), not
   luminance. This is the key to the whole solver. The shape is a *cool/white*
   disc over a *warm/tan* texture. As it fades, its brightness drops into the
   texture's brightness (the per-frame luminance shimmer, ~17 grey-levels,
   then buries it — luminance detection collapses to ~40% by mid-puzzle). But
   the texture's *hue* is steady, so the shape stays measurably cooler than its
   surroundings the whole way down: B-R detects it ~87-99% of late frames vs
   ~40% for luminance. The texture is static, so a per-pixel **median** of B-R
   over a rolling buffer recovers the background; ``current - plate`` isolates
   the shape's cool halo.
4. **Track** with a constant-velocity Kalman filter: the measurement is the
   deviation blob inside a Gaussian motion-prior window around the prediction.
   The deviation is *motion-compensated* (recent frames shifted by the velocity
   estimate and averaged, so the moving shape reinforces while residual shimmer
   cancels) and accepted only when it rises a robust *z-score* above the local
   floor — otherwise the filter coasts on velocity rather than latching a
   distractor. With the chromatic signal the shape is visible almost throughout,
   so the filter mostly *measures* rather than coasts.

Result (offline vs the green-cursor ground truth, continuous coverage over the
moving phase): the cursor stays within 60px of the shape ~70-99% of the puzzle.
The residual loss is brief deep-fade stretches near the box edges where even the
chromatic contrast thins. See ``private_scripts/lie_detector/README.md``.

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
# The opaque shape is a large round disc that sits still for ~4s; the countdown
# digits are thinner (low circularity), sit at the top of the box, and flicker.
# Circularity + a settling test (stable position over several frames) isolate
# the real shape before declaring motion onset.
ACQUIRE_BRIGHT = 205           # grayscale threshold for the opaque shape
ACQUIRE_MIN_AREA = 3500        # px, the opaque disc; excludes digits/specks
ACQUIRE_MAX_AREA = 14000       # px, ignore the large countdown circle / UI
ACQUIRE_MIN_CIRC = 0.50        # 4*pi*area/perimeter^2; disc ~0.55, digits <0.45
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
STARTSPOT_RADIUS = 55          # px disc around the settled shape masked from the
                               # plate (the stationary opaque shape sat there)
SEED_MIN_PEAK = 2.0            # min cool-deviation peak to seed/re-acquire from a
                               # global search (below this the box is just texture)

# --- Tracker (robust constant-velocity Kalman; tuned offline vs ground truth)-
# Runs on the chromatic B-R deviation (see ``cool_channel``). The shape moves
# smoothly and slowly (GT: ~2.5 px/frame avg, never > ~23). Two measures add
# robustness on top of the chromatic signal (both validated offline):
#
#  * Motion-compensated integration — the B-R channel still has some per-frame
#    shimmer while the shape is a *coherent* moving bump. The last few deviation
#    frames, each shifted forward by the velocity estimate so the moving shape
#    lines up, are averaged: the shape reinforces while residual shimmer averages
#    toward its mean.
#  * z-score gating — a measurement is accepted only when the prior-window peak
#    rises a robust z-score (MAD-based) above the local floor. Below that it is
#    just texture, so the filter coasts on velocity instead of latching a
#    distractor. The accepted measurement's confidence (hence Kalman gain) scales
#    with that z-score.
#
# The filter uses a ROBUST update: measurement noise is inflated both by low
# confidence and by innovation distance, so a single fast jump onto a distractor
# is down-weighted (the estimate never moves faster than the shape can) while a
# run of consistent measurements can still pull it back. A hard reject was tried
# and rejected — it locks in drift by discarding the corrective measurement too.
DEV_BLUR = 7
DEV_MC_K = 2                   # motion-compensated integration: shift+average the
                               # current + K previous deviation frames
PRIOR_SIGMA = 30.0             # Gaussian motion-prior width around the prediction
RELTHR = 0.6                   # posterior threshold for the centroid blob
MEASURE_EPS = 0.3              # posterior peak below this -> no measurement (coast)
MEASURE_Z_LO = 1.8             # min robust z (peak vs local shimmer) to accept
MEASURE_Z_HI = 3.8             # z at which the measurement is fully trusted
KF_Q_POS = 1.0                 # process noise: position
KF_Q_VEL = 4.0                 # process noise: velocity (smooth, allows gentle turns)
KF_R_MIN = 25.0                # measurement noise at full confidence (trust it)
KF_R_MAX = 500.0               # measurement noise at low confidence (trust velocity)
INNOV_SCALE = 16.0             # robust down-weighting: R *= 1 + (innov/INNOV_SCALE)^2
MAX_SPEED = 24.0               # px/frame hard velocity cap (GT max ~23)
COAST_DECAY = 0.93             # velocity *= this each blind frame, so a long coast
                               # through a deep-fade gap (where the shape turns
                               # unobserved) decays toward a stop instead of
                               # barrelling off in a straight line and overshooting
EDGE_MARGIN = 12               # px from a wall that counts as "at the edge"
EDGE_BOUNCE = 0.6              # fraction of outward velocity reflected inward

# --- Global re-acquisition (recover from a lost lock) ------------------------
# The local prior window cannot recover once the shape drifts out of it. But the
# chromatic signal is clean enough that the *global* strongest cool-deviation
# blob is the shape ~81-96% of frames (vs ~25% for luminance), so when the
# tracker has gone several frames without a confident measurement it searches the
# whole box (start-spot excluded) and jumps to a strong, significant blob.
REACQ_CONF = 0.15              # confidence at/below which a frame counts as "lost"
REACQ_AFTER = 8                # consecutive lost frames before a global re-acquire
REACQ_MIN_PEAK = 2.0           # min cool-deviation peak to re-acquire from
REACQ_Z = 3.0                  # robust z above the box floor required to re-acquire


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
    """Centroid + area of the brightest large round blob, or ``(None, 0)``.

    No green masking: the opaque shape (gray ~245) is far brighter than the
    green cursor reticle (gray ~150, below threshold), and masking green would
    punch a hole in the disc when the cursor overlaps it.
    """
    g = box_gray
    _, m = cv2.threshold(g, ACQUIRE_BRIGHT, 255, cv2.THRESH_BINARY)
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None, 0
    # Largest round blob in the shape's size range: excludes the countdown
    # circle (too large), digits (low circularity) and specks (too small).
    cand = []
    for c in cnts:
        area = cv2.contourArea(c)
        if not (ACQUIRE_MIN_AREA <= area <= ACQUIRE_MAX_AREA):
            continue
        per = cv2.arcLength(c, True)
        circ = 4 * np.pi * area / (per * per + 1e-6)
        if circ >= ACQUIRE_MIN_CIRC:
            cand.append((area, c))
    if not cand:
        return None, 0
    area, c = max(cand, key=lambda t: t[0])
    M = cv2.moments(c)
    return (M["m10"] / M["m00"], M["m01"] / M["m00"]), area


def build_plate(sig_buffer, mask_buffer):
    """Static-background estimate of the signal channel (B-R): per-pixel median
    over buffered frames with the green cursor excluded. Pixels that were green
    in *every* frame fall back to a plain median so the plate has no holes."""
    stack = np.array([np.where(mk > 0, np.nan, g) for g, mk in zip(sig_buffer, mask_buffer)])
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            plate = np.nanmedian(stack, axis=0)
    holes = np.isnan(plate)
    if holes.any():
        plate = np.where(holes, np.median(np.array(sig_buffer), axis=0), plate)
    return plate.astype(np.float32)


class ShapeTracker:
    """Constant-velocity Kalman tracker over a static-background deviation map.

    Each frame: predict the position from velocity; build a motion-compensated
    deviation map (recent frames shifted by the velocity estimate and averaged
    to reinforce the coherent shape against random shimmer); search a
    Gaussian-prior window around the prediction for the deviation blob; accept it
    only if it rises a robust z-score above the local shimmer floor and correct
    the filter, its noise scaled by that z-score's confidence. When no blob
    clears the floor (deep fade / edges) the filter coasts on velocity — which
    follows a smoothly moving shape far better than holding position, and avoids
    latching a texture distractor.

    Coordinates are in box-interior pixels. ``update`` is called once per frame
    with the box-interior B-R signal channel (``cool_channel``) and the
    green-cursor mask. The plate is the matching B-R background estimate.
    """

    def __init__(self, plate, seed_xy, startspot=None):
        self.plate = plate
        self.h, self.w = plate.shape
        self._startspot = startspot   # disc to exclude from global re-acquisition
        self._lost = 0                # consecutive frames without a confident fix
        self._raw = deque(maxlen=DEV_MC_K + 1)
        wsz = int(3 * PRIOR_SIGMA)
        ax = np.arange(-wsz, wsz + 1)
        px, py = np.meshgrid(ax, ax)
        self._wsz = wsz
        self._prior = np.exp(-(px ** 2 + py ** 2) / (2 * PRIOR_SIGMA ** 2)).astype(np.float32)

        kf = cv2.KalmanFilter(4, 2)
        kf.transitionMatrix = np.array([[1, 0, 1, 0], [0, 1, 0, 1],
                                        [0, 0, 1, 0], [0, 0, 0, 1]], np.float32)
        kf.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], np.float32)
        kf.processNoiseCov = np.diag([KF_Q_POS, KF_Q_POS,
                                      KF_Q_VEL, KF_Q_VEL]).astype(np.float32)
        kf.errorCovPost = np.eye(4, dtype=np.float32) * 10.0
        kf.statePost = np.array([[seed_xy[0]], [seed_xy[1]], [0], [0]], np.float32)
        self.kf = kf

    @property
    def pos(self):
        return (float(self.kf.statePost[0, 0]), float(self.kf.statePost[1, 0]))

    @property
    def vel(self):
        """Current velocity estimate (px/frame) — exposed for diagnostics."""
        return (float(self.kf.statePost[2, 0]), float(self.kf.statePost[3, 0]))

    def _dev_map(self, box_sig, green, vel):
        """Motion-compensated deviation map of the signal channel. The current
        and previous K deviation frames are averaged after shifting each previous
        frame forward by ``k * vel`` so the (moving) shape lines up across them:
        the shape reinforces while the per-frame shimmer averages toward its mean.
        """
        raw = cv2.GaussianBlur(np.clip(box_sig - self.plate, 0, None), (0, 0), DEV_BLUR)
        self._raw.append(raw)
        vx, vy = vel
        acc = [self._raw[-1]]
        for k in range(1, len(self._raw)):
            past = self._raw[-1 - k]
            if abs(vx) < 0.05 and abs(vy) < 0.05:
                acc.append(past)
            else:
                m = np.float32([[1, 0, k * vx], [0, 1, k * vy]])
                acc.append(cv2.warpAffine(past, m, (self.w, self.h),
                                          flags=cv2.INTER_LINEAR,
                                          borderMode=cv2.BORDER_REPLICATE))
        d = np.mean(acc, axis=0)
        d[green > 0] = 0.0
        return d

    def _measure(self, d, px, py):
        """Confidence-weighted deviation centroid in the prior window around the
        prediction, gated by a robust z-score. Returns ``(meas_xy, peak, z)``,
        or ``(None, peak, z)`` when the peak is only shimmer (z below threshold).
        ``z`` is the peak's deviation in MAD units above the local median — how
        far the candidate rises above the surrounding texture floor."""
        ws = self._wsz
        cx = int(round(np.clip(px, 0, self.w - 1)))
        cy = int(round(np.clip(py, 0, self.h - 1)))
        x0, x1 = max(0, cx - ws), min(self.w, cx + ws + 1)
        y0, y1 = max(0, cy - ws), min(self.h, cy + ws + 1)
        dloc = d[y0:y1, x0:x1]
        pr = self._prior[y0 - (cy - ws):y1 - (cy - ws), x0 - (cx - ws):x1 - (cx - ws)]
        post = dloc * pr
        peak = float(post.max()) if post.size else 0.0
        if peak <= MEASURE_EPS:
            return None, peak, 0.0
        # Robust z-score of the peak vs the local shimmer floor (median/MAD over
        # the non-zero window) — separates the coherent shape from texture noise.
        flat = dloc[dloc > 0]
        if flat.size > 20:
            med = float(np.median(flat))
            mad = float(np.median(np.abs(flat - med))) + 1e-3
            iy, ix = np.unravel_index(int(np.argmax(post)), post.shape)
            z = (float(dloc[iy, ix]) - med) / (1.4826 * mad)
        else:
            z = 0.0
        if z < MEASURE_Z_LO:
            return None, peak, z
        ys, xs = np.nonzero(post >= RELTHR * peak)
        wts = post[ys, xs]
        return (np.array([(xs * wts).sum() / wts.sum() + x0,
                          (ys * wts).sum() / wts.sum() + y0]), peak, z)

    def _reflect_at_edges(self):
        """Soft-bounce: if the prediction is past a wall with outward velocity,
        reflect (and damp) that velocity component instead of clamping it dead."""
        x, y = self.kf.statePre[0, 0], self.kf.statePre[1, 0]
        vx, vy = self.kf.statePre[2, 0], self.kf.statePre[3, 0]
        if x <= EDGE_MARGIN and vx < 0:
            vx = -vx * EDGE_BOUNCE
        elif x >= self.w - 1 - EDGE_MARGIN and vx > 0:
            vx = -vx * EDGE_BOUNCE
        if y <= EDGE_MARGIN and vy < 0:
            vy = -vy * EDGE_BOUNCE
        elif y >= self.h - 1 - EDGE_MARGIN and vy > 0:
            vy = -vy * EDGE_BOUNCE
        self.kf.statePre[0, 0] = np.clip(x, 0, self.w - 1)
        self.kf.statePre[1, 0] = np.clip(y, 0, self.h - 1)
        self.kf.statePre[2, 0] = vx
        self.kf.statePre[3, 0] = vy

    def update(self, box_sig, green):
        """Advance the tracker by one frame; return the estimated ``(x, y)``.

        ``box_sig`` is the box-interior B-R signal channel (``cool_channel``).
        """
        # Velocity from the *previous* step drives the motion compensation.
        vel = (float(self.kf.statePost[2, 0]), float(self.kf.statePost[3, 0]))
        d = self._dev_map(box_sig, green, vel)
        self.kf.predict()
        self._reflect_at_edges()
        px, py = float(self.kf.statePre[0, 0]), float(self.kf.statePre[1, 0])
        meas, peak, z = self._measure(d, px, py)
        conf = 0.0
        if meas is not None:
            innov = float(np.hypot(meas[0] - px, meas[1] - py))
            # Confidence from the z-score: a peak barely above the shimmer floor
            # is trusted little, a clear coherent blob a lot.
            conf = float(np.clip((z - MEASURE_Z_LO) / (MEASURE_Z_HI - MEASURE_Z_LO), 0, 1))
            # Robust update: low confidence OR a large jump both inflate the
            # measurement noise, so the filter leans on its smooth velocity.
            r = (KF_R_MAX - (KF_R_MAX - KF_R_MIN) * conf) * (1 + (innov / INNOV_SCALE) ** 2)
            self.kf.measurementNoiseCov = np.array([[r, 0], [0, r]], np.float32)
            self.kf.correct(np.array([[meas[0]], [meas[1]]], np.float32))
        else:                       # no signal: coast on velocity (decaying)
            self.kf.statePost = self.kf.statePre.copy()
            self.kf.statePost[2, 0] *= COAST_DECAY
            self.kf.statePost[3, 0] *= COAST_DECAY
        vx, vy = self.kf.statePost[2, 0], self.kf.statePost[3, 0]
        sp = np.hypot(vx, vy)
        if sp > MAX_SPEED:          # never move faster than the shape can
            self.kf.statePost[2, 0] = vx * MAX_SPEED / sp
            self.kf.statePost[3, 0] = vy * MAX_SPEED / sp
        # Global re-acquisition: after several blind frames the local window is
        # hopeless, so jump to the box-wide strongest cool blob if it is clearly
        # significant (the chromatic signal makes this reliable).
        self._lost = 0 if conf > REACQ_CONF else self._lost + 1
        if self._lost >= REACQ_AFTER:
            fix = self._global_reacquire(d)
            if fix is not None:
                self.kf.statePost[0, 0], self.kf.statePost[1, 0] = fix
                self.kf.statePost[2, 0] = self.kf.statePost[3, 0] = 0.0
                self._lost = 0
        x = float(np.clip(self.kf.statePost[0, 0], 0, self.w - 1))
        y = float(np.clip(self.kf.statePost[1, 0], 0, self.h - 1))
        self.kf.statePost[0, 0] = x
        self.kf.statePost[1, 0] = y
        return (x, y)

    def _global_reacquire(self, d):
        """Whole-box strongest cool-deviation blob (start-spot excluded), if it
        is both strong and a robust z above the box floor; else None."""
        dg = d
        if self._startspot is not None:
            dg = d.copy()
            cv2.circle(dg, (int(self._startspot[0]), int(self._startspot[1])),
                       STARTSPOT_RADIUS, 0.0, -1)
        _, mx, _, loc = cv2.minMaxLoc(dg)
        flat = dg[dg > 0]
        if mx <= REACQ_MIN_PEAK or flat.size < 50:
            return None
        med = float(np.median(flat))
        mad = float(np.median(np.abs(flat - med))) + 1e-3
        if (mx - med) / (1.4826 * mad) < REACQ_Z:
            return None
        return (float(loc[0]), float(loc[1]))


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

    def __init__(self):
        self.reset()

    BOX_LOST_FRAMES = 15             # consecutive misses before declaring game over

    def reset(self):
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
        self._mask_buf = deque(maxlen=PLATE_BUF_MAX)
        self._since_rebuild = 0
        self._plate_n = 0            # frame count the current plate was built from
        self.tracker = None
        self.last_target = None

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
        return gray, cool_channel(crop), green_cursor_mask(crop)

    def _to_frame(self, xy):
        return (self.inner[0] + xy[0], self.inner[1] + xy[1])

    def _start_tracking(self, seed_xy, cool, green):
        plate = build_plate(list(self._sig_buf), list(self._mask_buf))
        # The acquisition seed (last bright-blob position) goes stale the moment
        # the shape fades: by now the shape has moved off the start-spot. Re-seed
        # at its *current* position — the strongest cool-deviation blob, with the
        # start-spot disc excluded (it carries a fading plate artifact from where
        # the opaque shape sat). The chromatic signal is strong enough that this
        # global pick is reliable; fall back to the acquisition seed if weak.
        seed = self._locate_in_deviation(cool, plate, green) or seed_xy
        self.tracker = ShapeTracker(plate, seed, startspot=self._init_blob)
        self._plate_n = len(self._sig_buf)
        self._since_rebuild = 0
        self.state = "TRACK"
        log.info("LieDetectorSolver: initial plate (%d frames), seed=%s, switching to TRACK",
                 self._plate_n, tuple(round(v) for v in seed))

    def _locate_in_deviation(self, cool, plate, green):
        """Strongest cool-deviation blob in the whole box (start-spot excluded),
        used to seed/re-acquire the tracker. Returns ``(x, y)`` or None."""
        dev = cv2.GaussianBlur(np.clip(cool - plate, 0, None), (0, 0), DEV_BLUR)
        dev[green > 0] = 0.0
        if self._init_blob is not None:
            cv2.circle(dev, (int(self._init_blob[0]), int(self._init_blob[1])),
                       STARTSPOT_RADIUS, 0.0, -1)
        _, mx, _, loc = cv2.minMaxLoc(dev)
        return (float(loc[0]), float(loc[1])) if mx > SEED_MIN_PEAK else None

    def _maybe_rebuild_plate(self):
        """Rebuild the plate from the (now larger) rolling buffer as frames
        accumulate; a static background means more frames is strictly better."""
        self._since_rebuild += 1
        if self._since_rebuild >= PLATE_REBUILD_EVERY and len(self._sig_buf) > self._plate_n:
            self.tracker.plate = build_plate(list(self._sig_buf), list(self._mask_buf))
            self._plate_n = len(self._sig_buf)
            self._since_rebuild = 0

    def process(self, frame_bgr):
        """Process one frame; return the target ``(x, y)`` in frame coords or None."""
        crop = self._interior(frame_bgr)
        if crop is None:
            # Box gone: game not started or already over.
            if self.state == "TRACK":
                self.reset()
            return None
        gray, cool, green = crop

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

            # Buffer for the plate from settle onward. Before onset the shape
            # sits still, so its start-spot disc is masked out (excluded from the
            # plate); those frames give clean background everywhere else. After
            # onset the shape has left the start-spot, so unmasked frames fill it
            # in. The masked median therefore reaches full-window quality fast.
            mask_eff = green
            if not self._onset:
                mask_eff = green.copy()
                cv2.circle(mask_eff, (int(self._init_blob[0]), int(self._init_blob[1])),
                           STARTSPOT_RADIUS, 255, -1)
            self._sig_buf.append(cool)
            self._mask_buf.append(mask_eff)

            if self._onset:
                self._post_onset_n += 1
                if self._post_onset_n >= PLATE_MIN_FRAMES and self.last_target is not None:
                    seed = (self.last_target[0] - self.inner[0],
                            self.last_target[1] - self.inner[1])
                    self._start_tracking(seed, cool, green)
            return self.last_target

        if self.state == "TRACK":
            # Keep growing the rolling plate buffer and refine the plate.
            self._sig_buf.append(cool)
            self._mask_buf.append(green)
            self._maybe_rebuild_plate()
            xy = self.tracker.update(cool, green)
            self.last_target = self._to_frame(xy)
            return self.last_target

        return self.last_target
