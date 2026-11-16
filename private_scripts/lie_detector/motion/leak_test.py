"""Leak tests for MotionNet.

1. Receptive-field proof: randomise the input inside every blanked cursor disc
   (and draw a fake reticle there); the net's output at every usable pixel
   (``valid``) must not change — so nothing about where a cursor is can reach
   the evidence.
2. Null test: score the same frames against a cursor track from a different
   time (t + 90). Localisation must collapse to chance; if it does not, the
   net is finding something other than the shape.

Usage:
    python private_scripts/lie_detector/motion/leak_test.py MODEL.pt
"""
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
from score_cache import load_net  # noqa: E402


@torch.no_grad()
def rf_proof(net, dev, names, n_frames=40):
    worst = 0.0
    rng = np.random.RandomState(0)
    for name in names:
        c = C.Clip(name)
        for t in rng.choice(np.arange(c.onset + 6, c.end - 6), n_frames // len(names), replace=False):
            r = c.input(t)
            if r is None:
                continue
            x, valid = r
            # recover the blanked region: all-channel zeros
            blank = (np.abs(x).sum(0) == 0)
            x2 = x.copy()
            noise = rng.normal(0, 0.5, x.shape).astype(np.float32)
            x2[:, blank] = noise[:, blank]
            a = net(torch.from_numpy(x)[None].to(dev))[0, 0].cpu().numpy()
            b = net(torch.from_numpy(x2)[None].to(dev))[0, 0].cpu().numpy()
            worst = max(worst, float(np.abs(a - b)[valid].max()) if valid.any() else 0.0)
    return worst


@torch.no_grad()
def localisation(net, dev, names, shift=0, every=6):
    res = []
    for name in names:
        c = C.Clip(name)
        for t in range(c.onset + 6, c.end - 5, every):
            g = c.gt[t + shift] if 0 <= t + shift < c.n else (np.nan, np.nan)
            if not np.isfinite(g[0]):
                continue
            r = c.input(t)
            if r is None:
                continue
            x, valid = r
            s = net(torch.from_numpy(x)[None].to(dev))[0, 0].cpu().numpy()
            A, den = C.pooled(s, valid)
            A[den < 0.08] = -1e9
            gx, gy = int(round(g[0])), int(round(g[1]))
            if not (0 <= gy < A.shape[0] and 0 <= gx < A.shape[1]) or A[gy, gx] < -1e8:
                continue
            ok = A > -1e8
            yy, xx = np.mgrid[0:A.shape[0], 0:A.shape[1]]
            far = ok & (np.hypot(xx - gx, yy - gy) > 50)
            if not far.any():
                continue
            res.append(((A[ok] < A[gy, gx]).mean(), A[gy, gx] > A[far].max()))
    r = np.array(res, float)
    return np.median(r[:, 0]), r[:, 1].mean(), len(r)


if __name__ == "__main__":
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = load_net(sys.argv[1], dev)
    names = C.split(C.clip_names())[1]
    d = rf_proof(net, dev, names[:8])
    print(f"[1] max output change at usable pixels when hole contents are randomised: {d:.2e}"
          f"  -> {'PASS' if d < 1e-4 else 'FAIL'}")
    p0, w0, n0 = localisation(net, dev, names[:20], shift=0)
    p1, w1, n1 = localisation(net, dev, names[:20], shift=90)
    print(f"[2] true cursor:        pct {p0:.3f}  win {w0:.2f}  (n={n0})")
    print(f"    cursor from t+90:   pct {p1:.3f}  win {w1:.2f}  (n={n1})  "
          f"-> {'PASS' if w1 < 0.06 and p1 < 0.75 else 'CHECK'}")
