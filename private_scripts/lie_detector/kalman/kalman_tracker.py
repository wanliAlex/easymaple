"""Robust constant-velocity Kalman tracker for the Lie Detector shape.

Why this design (backed by measurement — see ``findings.md``)
-------------------------------------------------------------
The shape moves *slowly and smoothly*: from the ground-truth cursor it averages
~2.5 px/frame and **never exceeds ~23 px/frame** (p99 ~15). The earlier tracker
had no speed limit, so when the deviation centroid latched onto a texture
distractor it jumped 30-43 px/frame and drifted — in the 10 frames after any
>25 px jump the error averaged 160-280 px. So the fix is to make the filter obey
the shape's real dynamics.

What did NOT work: a **hard innovation gate** (reject any measurement farther than
G from the prediction). Once the prediction drifts, the gate also rejects the
*corrective* real measurement (now far from the bad prediction) and locks the
drift in — coverage dropped from 37% to 22%.

What works: a **robust soft update**. Every measurement is used, but its noise is
inflated with the innovation distance, ``R = R_conf * (1 + (innov/S)^2)``. A lone
fast jump is heavily down-weighted (the filter coasts on its smooth velocity),
yet a *run* of consistent far measurements still pulls the estimate back, so it
can recover. Measurement noise also scales with detection confidence (trust a
bright measurement, lean on velocity for a faint one — "trust measurement early,
prediction later"). A velocity cap and a soft edge-bounce complete it.

The tracker exposes ``pos`` and ``vel`` so the demo can draw the velocity vector
and compare it with the ground-truth velocity.
"""
from collections import deque

import cv2
import numpy as np

# Deviation map (matches the production solver)
DEV_BLUR = 7
DEV_NAVG = 3
PRIOR_SIGMA = 40.0
RELTHR = 0.6
MEASURE_EPS = 0.3

# Dynamics — tuned offline against the ground-truth cursor
KF_Q_POS = 1.0
KF_Q_VEL = 5.0          # velocity process noise (smooth, allows gentle turns)
KF_R_MIN = 40.0         # confident, on-track measurement -> trust it
KF_R_MAX = 600.0        # faint measurement -> lean on the velocity prediction
KF_CONF_SCALE = 8.0     # posterior peak that counts as full confidence
INNOV_SCALE = 18.0      # robust down-weighting: R *= 1 + (innov/INNOV_SCALE)^2
MAX_SPEED = 24.0        # px/frame hard cap (GT max ~23) — never move faster
EDGE_MARGIN = 12        # px from a wall that counts as "at the edge"
EDGE_BOUNCE = 0.6       # fraction of outward velocity retained, reflected inward


class KalmanShapeTracker:
    """Tracks the fading shape on a static-background deviation map.

    Coordinates are box-interior pixels. Call :meth:`update` once per frame with
    the grayscale crop and the green-cursor mask.
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
        self.last_measured = None     # raw measurement this frame (for the demo)
        self.downweighted = False     # measurement was treated as an outlier

    @property
    def pos(self):
        return (float(self.kf.statePost[0, 0]), float(self.kf.statePost[1, 0]))

    @property
    def vel(self):
        return (float(self.kf.statePost[2, 0]), float(self.kf.statePost[3, 0]))

    def _dev_map(self, box_gray, green):
        raw = cv2.GaussianBlur(np.clip(box_gray - self.plate, 0, None), (0, 0), DEV_BLUR)
        self._raw.append(raw)
        d = np.mean(self._raw, axis=0).copy()
        d[green > 0] = 0.0
        return d

    def _measure(self, d, px, py):
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

    def _reflect_at_edges(self):
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

    def update(self, box_gray, green):
        d = self._dev_map(box_gray, green)
        self.kf.predict()
        self._reflect_at_edges()
        px, py = float(self.kf.statePre[0, 0]), float(self.kf.statePre[1, 0])

        meas, peak = self._measure(d, px, py)
        self.last_measured = tuple(meas) if meas is not None else None
        self.downweighted = False
        if meas is not None:
            innov = np.hypot(meas[0] - px, meas[1] - py)
            conf = min(1.0, peak / KF_CONF_SCALE)
            # Robust soft update: confidence sets the base trust, the innovation
            # distance inflates it so a single fast jump barely moves the filter
            # while consistent measurements can still pull it back.
            r = (KF_R_MAX - (KF_R_MAX - KF_R_MIN) * conf) * (1 + (innov / INNOV_SCALE) ** 2)
            self.downweighted = innov > INNOV_SCALE
            self.kf.measurementNoiseCov = np.array([[r, 0], [0, r]], np.float32)
            self.kf.correct(np.array([[meas[0]], [meas[1]]], np.float32))
        else:
            self.kf.statePost = self.kf.statePre.copy()

        vx, vy = self.kf.statePost[2, 0], self.kf.statePost[3, 0]
        sp = np.hypot(vx, vy)
        if sp > MAX_SPEED:
            self.kf.statePost[2, 0] = vx * MAX_SPEED / sp
            self.kf.statePost[3, 0] = vy * MAX_SPEED / sp
        self.kf.statePost[0, 0] = float(np.clip(self.kf.statePost[0, 0], 0, self.w - 1))
        self.kf.statePost[1, 0] = float(np.clip(self.kf.statePost[1, 0], 0, self.h - 1))
        return self.pos
