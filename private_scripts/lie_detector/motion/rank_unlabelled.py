"""Which bot-played games are worth labelling next? Replays two models on
every unlabelled bot game and ranks the games by how long the two solver
targets disagree (> 80 px apart): only frames where models disagree can tell
them apart, and games both get right add little. Writes the ranking to
``training_data/lie_detector/label_queue.txt``, which ``label_clip.py``
serves first.

    python private_scripts/lie_detector/motion/rank_unlabelled.py --models A.pt B.pt
    python private_scripts/lie_detector/motion/rank_unlabelled.py --models A.pt@0.5,0.5,0.4,0 A.pt   # the solver of 2026-10-14..28 vs now

A model is ``PATH[@TAU,K[,FLOOR[,WALL]]]``: the solver's ClutterBackground,
evidence floor and wall floor (default: the runtime's; ``@0,0,0,0`` = the
solver before 2026-10-14, ``@0.5,0.5,0.4,0`` = 2026-10-14..28).
"""
import argparse
import glob
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import LM, ROOT  # noqa: E402
from build_cache import human_played  # noqa: E402

VID = os.path.join(ROOT, "training_data", "lie_detector")
QUEUE = os.path.join(VID, "label_queue.txt")
FAR = 80.0          # px between the two targets that counts as disagreement


def make_solver(spec):
    path, _, opts = spec.partition("@")
    v = [float(x) for x in opts.split(",")] if opts else []
    return LM.MotionLieDetectorSolver(path, clutter=tuple(v[:2]) if len(v) >= 2 else None,
                                      den_floor=v[2] if len(v) >= 3 else None,
                                      wall_floor=v[3] if len(v) >= 4 else None)


def targets(clip, model):
    """Solver target per frame (TRACK only, else NaN) and the clip times. The
    bot's rendered reticle is blanked like any cursor."""
    solver = make_solver(model)
    tp = clip[:-4] + "_t.npy"
    cap = cv2.VideoCapture(clip)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    t = np.load(tp)[:n] if os.path.exists(tp) else np.arange(n) * LM.FRAME_DT
    t = t - t[0]
    out = np.full((n, 2), np.nan)
    for k in range(n):
        ok, fr = cap.read()
        if not ok:
            break
        tg = solver.process(fr, t=float(t[k]))
        if tg is not None and solver.state == "TRACK":
            out[k] = tg
    return out, t


def disagreement(args):
    clip, ma, mb = args
    a, t = targets(clip, ma)
    b, _ = targets(clip, mb)
    both = np.isfinite(a[:, 0]) & np.isfinite(b[:, 0])
    if not both.any():
        return clip, None
    d = np.hypot(*(a - b).T)
    far = both & (d > FAR)
    runs, start = [], None
    for k in range(len(far) + 1):
        f = k < len(far) and far[k]
        if f and start is None:
            start = k
        elif not f and start is not None:
            if t[k - 1] - t[start] >= 0.3:
                runs.append((t[start], t[k - 1]))
            start = None
    return clip, dict(frac=float(far.sum() / both.sum()), runs=runs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs=2, required=True)
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    clips = [c for c in sorted(glob.glob(os.path.join(VID, "????-??-??_??-??-??.mp4")))
             if not human_played(os.path.basename(c)) and not glob.glob(c[:-4] + "_gt*.npz")]
    print(f"{len(clips)} unlabelled bot games", flush=True)
    res = []
    with ProcessPoolExecutor(a.jobs) as ex:
        for clip, r in ex.map(disagreement, [(c, *a.models) for c in clips]):
            if r is not None:
                res.append((clip, r))
    res.sort(key=lambda x: -x[1]["frac"])
    with open(QUEUE, "w") as f:
        for clip, r in res:
            f.write(os.path.basename(clip) + "\n")
    for clip, r in res:
        # player time: the clips play at 30 fps but were recorded at ~24.9
        win = ", ".join(f"{s:.1f}-{e:.1f} s (player {s * 24.9 / 30:.1f}-{e * 24.9 / 30:.1f})" for s, e in r["runs"])
        print(f"{os.path.basename(clip)}  models disagree {100 * r['frac']:4.1f}% of the game  {win}")
    print("queue ->", QUEUE)
