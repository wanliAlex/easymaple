"""Closed-loop replay of a live game from its solver log alone (FINDINGS §13),
for a failure whose recording is gone. The log keeps ~300 raw half-res box
frames (the last ~10 s of ACQUIRE/TRACK), which is exactly what the solver
consumes. The runtime solver and CursorPilot are seeded on the user's label
at the first logged frame and scored as the piloted cursor against the labels.

    halfreplay.py LOG.npz GT.npz OFFSET T_END name=spec [name=spec ...]

OFFSET: clip time minus log time, in s (fit the live target to the labels;
0.10 for 2026-10-28 12:16). T_END: the game's end in clip time.
spec: ``rt`` = the runtime's defaults, or ``TAU,K,FLOOR[,WALL]``.
Each spec runs 5 times, starting 0/2/4/6/8 logged frames later, since the
replay is deterministic.
"""
import sys

import cv2
import numpy as np

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from common import LM  # noqa: E402
from src.easymaple.detection import lie_detector_solver as S  # noqa: E402
from src.easymaple.modules.lie_detector_player import _pilot_steps  # noqa: E402


def run(d, g, off, t_end, net, start, clutter=None, floor=None, wall=None):
    lt = d["t"] - d["t"][0]
    half, hidx = d["half"], d["half_idx"]
    box = tuple(int(v) for v in d["box"])

    def gt_at(t):
        return np.array([np.interp(t, g["t"], g["xy"][:, 0]), np.interp(t, g["t"], g["xy"][:, 1])])

    s = LM.MotionLieDetectorSolver(net=net[0], device=net[1], clutter=clutter, den_floor=floor, wall_floor=wall)
    s._lock(box)
    s.state = "ACQUIRE"
    s._locate = lambda f, t: True        # the frames are already box crops
    s._crop = lambda f: f
    seed = gt_at(lt[hidx[start]] + off)
    s._blob = ((seed[0] - s.inner[0]) / LM.SCALE, (seed[1] - s.inner[1]) / LM.SCALE)
    pilot, pilot_t, own = S.CursorPilot(tuple(seed)), None, tuple(seed)
    blob = S._bright_blob
    S._bright_blob = lambda gray: (None, None)    # the seed comes from the labels
    T, CU = [], []
    try:
        for i in range(start, len(hidx)):
            t = lt[hidx[i]]
            h, w = half[i].shape[:2]
            # nearest-neighbour 2x: the solver's INTER_AREA half_res returns the frame exactly
            crop = cv2.resize(half[i], (w * LM.SCALE, h * LM.SCALE), interpolation=cv2.INTER_NEAREST)
            tg = s.process(crop, cursor_xy=own, t=t)
            desired = tg if (tg is not None and s.state == "TRACK") else own
            n, pilot_t = _pilot_steps(t, pilot_t, 1.0 / 30)
            for _ in range(n):
                own = pilot.step(desired)
            T.append(t + off)
            CU.append(own)
    finally:
        S._bright_blob = blob
    T, CU = np.array(T), np.array(CU, float)
    m = T <= t_end
    G = np.array([gt_at(t) for t in T[m]]).reshape(-1, 2)
    return T[m], np.hypot(*(CU[m] - G).T)


if __name__ == "__main__":
    log, gtp, off, t_end = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
    d = np.load(log, allow_pickle=True)
    g = np.load(gtp, allow_pickle=True)
    net = LM.load_net(LM.MODEL_PATH, None)
    for spec in sys.argv[5:]:
        name, _, par = spec.partition("=")
        kw = {}
        if par != "rt":
            v = [float(x) for x in par.split(",")]
            kw = dict(clutter=(v[0], v[1]), floor=v[2], wall=v[3] if len(v) > 3 else None)
        c60 = [np.mean(run(d, g, off, t_end, net, start, **kw)[1] < 60) for start in (0, 2, 4, 6, 8)]
        print(f"{name:14s} c60 " + " ".join(f"{v:.2f}" for v in c60) + f"  mean {np.mean(c60):.3f}", flush=True)
