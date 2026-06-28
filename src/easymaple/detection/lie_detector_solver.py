"""Solver for the Lie Detector anti-bot mini-game.

The mini-game shows a rectangular camouflage play-field in which a bright shape
appears, sits still for a few seconds, then begins moving while fading into the
texture. The player must keep the mouse cursor on the moving shape; cumulative
dwell time determines pass/fail.

Approach (validated offline against the in-game cursor as ground truth):

1. **Locate the play-box** by its tan camouflage colour.
2. **Acquire** the shape while it is still a bright opaque blob (trivial).
3. **Background plate**: the camouflage texture is static, so a one-time
   per-pixel median over a buffer of frames captured *after* the shape starts
   moving recovers the background (the shape covers any given pixel only
   briefly). ``current - plate`` then isolates the translucent shape.
4. **Track** the shape through the fade with a constant-velocity Kalman filter:
   the per-frame deviation map (multiplied by a Gaussian prior around the
   predicted position) provides the measurement; its noise is scaled by
   detection confidence. When the shape carries no signal (deep fade / edges)
   the filter coasts on velocity, which follows a smoothly moving shape far
   better than holding position.

Known limitation: the shape spends much of the puzzle hugging the box edges
where its faded signal is weak, so a continuous lock holds for ~1-2s rather
than the full duration. See ``private_scripts/lie_detector/README.md``.

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

# --- Tracker (constant-velocity Kalman; tuned offline vs cursor ground truth)-
# The shape moves smoothly but fades to near-invisible, especially while it hugs
# the box edges. A constant-velocity Kalman coasts on velocity through low-signal
# stretches (rather than holding position), and the measurement noise is scaled
# by detection confidence so weak/edge evidence nudges rather than yanks.
DEV_BLUR = 7
DEV_NAVG = 3
PRIOR_SIGMA = 60.0             # Gaussian motion-prior width around the prediction
RELTHR = 0.6                   # posterior threshold for the centroid blob
MEASURE_EPS = 0.3              # posterior peak below this -> no measurement (coast)
KF_Q_POS = 1.0                 # process noise: position
KF_Q_VEL = 5.0                 # process noise: velocity (allows smooth turns)
KF_R_MIN = 30.0               # measurement noise at full confidence (trust it)
KF_R_MAX = 400.0               # measurement noise at low confidence (trust velocity)
KF_CONF_SCALE = 8.0            # posterior peak that counts as "full confidence"


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


def build_plate(gray_buffer, mask_buffer):
    """Static-background estimate: per-pixel median over buffered frames with
    the green cursor excluded. Pixels that were green in *every* frame fall
    back to a plain median so the plate has no holes."""
    stack = np.array([np.where(mk > 0, np.nan, g) for g, mk in zip(gray_buffer, mask_buffer)])
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            plate = np.nanmedian(stack, axis=0)
    holes = np.isnan(plate)
    if holes.any():
        plate = np.where(holes, np.median(np.array(gray_buffer), axis=0), plate)
    return plate.astype(np.float32)


class ShapeTracker:
    """Constant-velocity Kalman tracker over a static-background deviation map.

    Each frame: predict the position from velocity, search a Gaussian-prior
    window around the prediction for the shape's deviation blob, and correct the
    filter with that measurement (its noise scaled by detection confidence).
    When the shape carries no signal (deep fade / edges) there is no
    measurement, so the filter coasts on velocity — which follows a smoothly
    moving shape far better than holding position.

    Coordinates are in box-interior pixels. ``update`` is called once per frame
    with the box-interior grayscale frame and the green-cursor mask.
    """

    def __init__(self, plate, seed_xy):
        self.plate = plate
        self.h, self.w = plate.shape
        self._raw = deque(maxlen=DEV_NAVG)
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

    def _dev_map(self, box_gray, green):
        raw = cv2.GaussianBlur(np.clip(box_gray - self.plate, 0, None), (0, 0), DEV_BLUR)
        self._raw.append(raw)
        d = np.mean(self._raw, axis=0).copy()
        d[green > 0] = 0.0
        return d

    def _measure(self, d, px, py):
        """Confidence-weighted deviation centroid in the prior window around the
        prediction. Returns ``(meas_xy, peak)`` or ``(None, peak)`` if no signal."""
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
            return None, peak
        ys, xs = np.nonzero(post >= RELTHR * peak)
        wts = post[ys, xs]
        return np.array([(xs * wts).sum() / wts.sum() + x0,
                         (ys * wts).sum() / wts.sum() + y0]), peak

    def update(self, box_gray, green):
        """Advance the tracker by one frame; return the estimated ``(x, y)``."""
        d = self._dev_map(box_gray, green)
        pred = self.kf.predict()
        meas, peak = self._measure(d, float(pred[0, 0]), float(pred[1, 0]))
        if meas is not None:
            conf = min(1.0, peak / KF_CONF_SCALE)
            r = KF_R_MAX - (KF_R_MAX - KF_R_MIN) * conf
            self.kf.measurementNoiseCov = np.array([[r, 0], [0, r]], np.float32)
            self.kf.correct(np.array([[meas[0]], [meas[1]]], np.float32))
        else:                       # no signal: coast on velocity
            self.kf.statePost = self.kf.statePre.copy()
        x = float(np.clip(self.kf.statePost[0, 0], 0, self.w - 1))
        y = float(np.clip(self.kf.statePost[1, 0], 0, self.h - 1))
        self.kf.statePost[0, 0] = x
        self.kf.statePost[1, 0] = y
        return (x, y)


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
        self._gray_buf = deque(maxlen=PLATE_BUF_MAX)
        self._mask_buf = deque(maxlen=PLATE_BUF_MAX)
        self._since_rebuild = 0
        self._plate_n = 0            # frame count the current plate was built from
        self.tracker = None
        self.last_target = None

    def _interior(self, frame_bgr):
        """Crop to the box interior; return (box_bgr, gray_f32, green_mask) or None.

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
        return crop, gray, green_cursor_mask(crop)

    def _to_frame(self, xy):
        return (self.inner[0] + xy[0], self.inner[1] + xy[1])

    def _start_tracking(self, seed_xy):
        plate = build_plate(list(self._gray_buf), list(self._mask_buf))
        self.tracker = ShapeTracker(plate, seed_xy)
        self._plate_n = len(self._gray_buf)
        self._since_rebuild = 0
        self.state = "TRACK"
        log.info("LieDetectorSolver: initial plate (%d frames), switching to TRACK", self._plate_n)

    def _maybe_rebuild_plate(self):
        """Rebuild the plate from the (now larger) rolling buffer as frames
        accumulate; a static background means more frames is strictly better."""
        self._since_rebuild += 1
        if self._since_rebuild >= PLATE_REBUILD_EVERY and len(self._gray_buf) > self._plate_n:
            self.tracker.plate = build_plate(list(self._gray_buf), list(self._mask_buf))
            self._plate_n = len(self._gray_buf)
            self._since_rebuild = 0

    def process(self, frame_bgr):
        """Process one frame; return the target ``(x, y)`` in frame coords or None."""
        crop = self._interior(frame_bgr)
        if crop is None:
            # Box gone: game not started or already over.
            if self.state == "TRACK":
                self.reset()
            return None
        _, gray, green = crop

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
            self._gray_buf.append(gray)
            self._mask_buf.append(mask_eff)

            if self._onset:
                self._post_onset_n += 1
                if self._post_onset_n >= PLATE_MIN_FRAMES and self.last_target is not None:
                    seed = (self.last_target[0] - self.inner[0],
                            self.last_target[1] - self.inner[1])
                    self._start_tracking(seed)
            return self.last_target

        if self.state == "TRACK":
            # Keep growing the rolling plate buffer and refine the plate.
            self._gray_buf.append(gray)
            self._mask_buf.append(green)
            self._maybe_rebuild_plate()
            xy = self.tracker.update(gray, green)
            self.last_target = self._to_frame(xy)
            return self.last_target

        return self.last_target
