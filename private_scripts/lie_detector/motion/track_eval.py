"""Closed-loop evaluation of the motion tracker on cached net scores.

For each clip: seed at the opaque shape (bright blob just before START, as
the runtime does), then every frame: evidence from the net's logits with the
exclusion zones around OUR simulated cursor removed (current frame and its
warped positions in the reference frames — exactly what blanking our own
reticle does at runtime), GridTracker update, CursorPilot step. Scored on the
piloted cursor against the human's cursor, over START..SUCCESS.

Usage:
    python private_scripts/lie_detector/motion/track_eval.py SCORE_DIR [--q 3 --beta 1.5 ...]
"""
import argparse
import glob
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
from common import LM  # noqa: E402
from src.easymaple.detection import lie_detector_solver as S  # noqa: E402


def seed_from_blob(c):
    """Opaque-shape seed: largest bright blob (half-res) shortly before START."""
    for t in range(max(0, c.onset - 2), max(0, c.onset - 15), -1):
        g = cv2.cvtColor(np.asarray(c.frames[t]), cv2.COLOR_BGR2GRAY)
        _, m = cv2.threshold(g, S.ACQUIRE_BRIGHT, 255, cv2.THRESH_BINARY)
        n, lab, st, cent = cv2.connectedComponentsWithStats(m)
        best = None
        for i in range(1, n):
            a = st[i, cv2.CC_STAT_AREA]
            if not (S.ACQUIRE_MIN_AREA / 4 <= a <= S.ACQUIRE_MAX_AREA / 4):
                continue
            if cent[i][1] < S.ACQUIRE_TOP_REJECT * g.shape[0]:
                continue
            if best is None or a > best[0]:
                best = (a, cent[i])
        if best is not None:
            return best[1]
    return np.array([g.shape[1] / 2, g.shape[0] / 2])


def metrics(traj, gt, s, e, tol, end_frames=30):
    on = []
    for i in range(s, e):
        if np.isfinite(gt[i, 0]) and np.isfinite(traj[i, 0]):
            on.append(np.hypot(*(traj[i] - gt[i])) < tol)
    on = np.array(on, bool)
    if not on.size:
        return dict(cov=0.0, longest=0.0, endlock=0.0, ok=False)
    best = run = 0
    for v in on:
        run = run + 1 if v else 0
        best = max(best, run)
    el = float(on[-end_frames:].mean())
    return dict(cov=float(on.mean()), longest=best / 30.0, endlock=el, ok=el >= 0.5)


def run(name, score_dir, kw, lag=4, closed_loop=True, return_traj=False):
    c = C.Clip(name)
    z = np.load(os.path.join(score_dir, name + ".npz"))
    logit, valid, have = z["logit"], z["valid"], z["have"]
    h, w = logit.shape[1:]
    seed = seed_from_blob(c)
    trk = LM.GridTracker((h, w), seed, cell=LM.GRID, **kw)
    est = np.full((c.n, 2), np.nan)          # tracker estimate for frame t (half-res)
    cursor = np.full((c.n, 2), np.nan)       # piloted cursor at time t (full-res crop coords)
    pilot = S.CursorPilot((seed[0] * 2, seed[1] * 2))
    vel = np.zeros(2); prev = None
    yy, xx = np.mgrid[0:h, 0:w]
    k = 2 * (LM.NET_RF_R + 1) + 1
    t_start = max(0, c.onset - 4)
    for T in range(t_start, c.n):
        # at wall-clock frame T we can process frame t = T - lag (needs refs up to t+4)
        t = T - lag
        target = None
        if t >= t_start and have[t]:
            v = valid[t].copy()
            if closed_loop:
                holes = []
                if np.isfinite(cursor[t, 0]):
                    holes.append(cursor[t] / 2)
                refs = c.refs(t) or []
                for s in refs:
                    if np.isfinite(cursor[s, 0]):
                        dx, dy = c.shift(t, s)
                        holes.append(cursor[s] / 2 + np.array([dx, dy]))
                if holes:
                    blank = np.zeros((h, w), np.uint8)
                    for p in holes:
                        cv2.circle(blank, (int(round(p[0])), int(round(p[1]))), LM.HOLE_R, 1, -1)
                    near = cv2.dilate(blank, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
                    v &= ~near
            ev = LM.evidence_grid(logit[t].astype(np.float32), v)
            p = np.array(trk.step(ev))
            est[t] = p
            if prev is not None:
                vel = 0.7 * vel + 0.3 * (p - prev)
            prev = p
            target = (p + vel * lag) * 2             # extrapolate to now, full-res
        elif t < t_start:
            target = seed * 2
        cur = pilot.step(target) if target is not None else pilot.step(None)
        cursor[T] = cur
    gt = c.gt * 2
    s, e = c.onset, c.end
    r = dict(m60=metrics(cursor, gt, s, e, 60), m80=metrics(cursor, gt, s, e, 80),
             raw60=metrics(np.roll(est, 0, axis=0) * 2, gt, s, e, 60))
    if return_traj:
        return r, cursor, est * 2
    return r


def _job(args):
    name, score_dir, kw, lag, cl = args
    return name, run(name, score_dir, kw, lag, cl)


def summarize(rows, label):
    m60 = [r["m60"] for _, r in rows]; m80 = [r["m80"] for _, r in rows]; raw = [r["raw60"] for _, r in rows]
    print(f"{label}: clips={len(rows)} locked@60={sum(m['ok'] for m in m60)} locked@80={sum(m['ok'] for m in m80)} "
          f"end60={np.mean([m['endlock'] for m in m60]):.2f} cov60={np.mean([m['cov'] for m in m60]):.2f} "
          f"cov80={np.mean([m['cov'] for m in m80]):.2f} longest60={np.mean([m['longest'] for m in m60]):.1f}s "
          f"| raw: locked@60={sum(m['ok'] for m in raw)} cov60={np.mean([m['cov'] for m in raw]):.2f}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("score_dir")
    ap.add_argument("--q", type=float, default=3.0)
    ap.add_argument("--beta", type=float, default=2.0)
    ap.add_argument("--clip", type=float, default=3.0)
    ap.add_argument("--floor", type=float, default=1e-7)
    ap.add_argument("--lag", type=int, default=None,
                    help="frames between capture and scoring; default = largest forward reference offset")
    ap.add_argument("--open", action="store_true", help="no closed-loop hole at our cursor")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    if a.lag is None:
        a.lag = max(0, max(LM.REF_OFFSETS))
    names = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(a.score_dir, "*.npz")))
    names = [n for n in names if C.Clip(n).meta["success"]]
    grid = [dict(q=a.q, beta=a.beta, clip=a.clip, floor=a.floor)]
    if a.grid:
        grid = [dict(q=q, beta=b, clip=a.clip, floor=a.floor) for q in (2.0, 3.0, 4.5)
                for b in (0.8, 1.5, 3.0)]
    for kw in grid:
        with ProcessPoolExecutor(8) as ex:
            rows = list(ex.map(_job, [(n, a.score_dir, kw, a.lag, not a.open) for n in names]))
        if a.verbose:
            for n, r in rows:
                print(f"  {n} end60={r['m60']['endlock']:.2f} cov60={r['m60']['cov']:.2f} longest={r['m60']['longest']:.1f}s")
        summarize(rows, str(kw))
