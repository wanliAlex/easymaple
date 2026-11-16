"""Tier-2 check (FINDINGS §13) on games the bot PASSED, which have no labels:
the bot's green reticle in the recording is a path that passed. A candidate
is replayed closed-loop, with its own simulated cursor blanked as in
``ev.py live --own``. The score is how long its cursor stays more than 80 px
from that path, from START to the SUCCESS banner. A candidate that strays far
in some game is a risk, and that game is the one to label next.

    tier2.py OUT.jsonl LIST.txt [--clutter TAU,K] [--den-floor X] [--wall-floor X] [--prev] [--shard i/n]

LIST.txt holds clip names (one per line) under training_data/lie_detector.
Summarise two runs with ``tier2.py --compare A.jsonl B.jsonl``.
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ev  # noqa: E402
from common import LM  # noqa: E402
from src.easymaple.detection import lie_detector_solver as S  # noqa: E402
from src.easymaple.modules.lie_detector_player import _pilot_steps, _success_banner  # noqa: E402

VID = ev.VID


def reticle(frame, box):
    """Centre of the largest green reticle blob inside the box (frame px), or None."""
    x, y, w, h = box
    m = cv2.inRange(cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2HSV), S.GREEN_HSV_LO, S.GREEN_HSV_HI)
    n, _, st, cent = cv2.connectedComponentsWithStats(m)
    if n <= 1:
        return None
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    return None if st[i, cv2.CC_STAT_AREA] < 8 else (x + cent[i][0], y + cent[i][1])


def one(clip, solver):
    ct = np.load(clip[:-4] + "_t.npy")
    ct = ct - ct[0]
    solver.reset()
    cap = cv2.VideoCapture(clip)
    pilot, pilot_t, own = None, None, None
    rows, started, success_t, k = [], False, None, 0
    while True:
        ok, fr = cap.read()
        if not ok or k >= len(ct):
            break
        t = float(ct[k])
        tg = solver.process(fr, cursor_xy=own, t=t)
        desired = tg if tg is not None else solver.box_center
        if desired is not None and pilot is None:
            h, w = fr.shape[:2]
            pilot = S.CursorPilot((w / 2.0, h / 2.0))
        if pilot is not None:
            n, pilot_t = _pilot_steps(t, pilot_t, 1.0 / 30)
            for _ in range(n):
                own = pilot.step(desired)
        started = started or solver.state == "TRACK"
        box = solver.box
        if started and box is not None and success_t is None:
            if _success_banner(fr, box):
                success_t = t
            else:
                r = reticle(fr, box)
                rows.append((t, own[0], own[1], np.nan if r is None else r[0], np.nan if r is None else r[1]))
        k += 1
    a = np.array(rows, float) if rows else np.zeros((0, 5))
    seen = np.isfinite(a[:, 3])
    d = np.hypot(a[seen, 1] - a[seen, 3], a[seen, 2] - a[seen, 4])
    return dict(clip=os.path.basename(clip), n=int(seen.sum()), success=success_t is not None,
                far80=float(np.mean(d > 80)) if len(d) else None, far60=float(np.mean(d > 60)) if len(d) else None,
                med=float(np.median(d)) if len(d) else None,
                t=[round(float(v), 3) for v in a[seen, 0]], d=[round(float(v), 1) for v in d])


def compare(pa, pb):
    A = {r["clip"]: r for r in map(json.loads, open(pa))}
    B = {r["clip"]: r for r in map(json.loads, open(pb))}
    keys = sorted(k for k in A if k in B and A[k]["far80"] is not None and B[k]["far80"] is not None)
    fa = np.array([A[k]["far80"] for k in keys])
    fb = np.array([B[k]["far80"] for k in keys])
    print(f"games {len(keys)}")
    for name, f in ((pa, fa), (pb, fb)):
        print(f"{os.path.basename(name):24s} far80 mean {f.mean():.4f}  p90 {np.percentile(f, 90):.3f}  "
              f"p99 {np.percentile(f, 99):.3f}  max {f.max():.3f}")
    d = fb - fa
    print(f"B - A: mean {d.mean():+.4f}; games worse by >5 pts {int((d > .05).sum())}, by >10 pts {int((d > .10).sum())}")
    for i in np.argsort(-d)[:10]:
        print(f"  {keys[i]}  A {fa[i]:.3f}  B {fb[i]:.3f}")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--compare":
        compare(sys.argv[2], sys.argv[3])
        sys.exit()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("clips")
    ap.add_argument("--model", default=LM.MODEL_PATH)
    ap.add_argument("--clutter", default=None)
    ap.add_argument("--den-floor", type=float, default=None)
    ap.add_argument("--wall-floor", type=float, default=None)
    ap.add_argument("--prev", action="store_true", help="the solver of 2026-10-14..28")
    ap.add_argument("--shard", default="0/1")
    a = ap.parse_args()
    if a.prev:
        a.clutter = a.clutter or "0.5,0.5"
        a.wall_floor = 0.0 if a.wall_floor is None else a.wall_floor
    i, n = (int(v) for v in a.shard.split("/"))
    names = [line.strip() for line in open(a.clips) if line.strip()][i::n]
    solver = ev.make_solver(a.model, None, (0, 0), {},
                            clutter=tuple(float(v) for v in a.clutter.split(",")) if a.clutter else None,
                            den_floor=a.den_floor, wall_floor=a.wall_floor)
    with open(a.out, "a") as out:
        for name in names:
            clip = os.path.join(VID, name)
            if not os.path.exists(clip):
                continue
            try:
                rec = one(clip, solver)
            except Exception as e:          # a damaged clip must not stop the batch
                print(name, "failed:", e, flush=True)
                continue
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(name, rec["n"], rec["far80"], flush=True)
