"""Shared helpers for the motion detector scripts: cache loading, ground truth
cleaning, train/val split, per-frame network inputs and labels."""
import glob
import os
import sys

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)
from src.easymaple.detection import lie_detector_motion as LM  # noqa: E402

CACHE = os.environ.get("LD_CACHE") or os.path.join(ROOT, "training_data", "lie_detector", "motion_cache_full")
NEG_R = 60            # half-res px: farther than this from the cursor = negative
VAL_LIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "val_clips.txt")

if os.environ.get("LD_REFS"):         # e.g. LD_REFS=-8,-6,-4,-2 for a causal model
    LM.REF_OFFSETS = tuple(int(v) for v in os.environ["LD_REFS"].split(","))


def clip_names(success_only=True):
    out = []
    for p in sorted(glob.glob(os.path.join(CACHE, "*.meta.npz"))):
        m = np.load(p)
        if success_only and not bool(m["success"]):
            continue
        out.append(os.path.basename(p).replace(".meta.npz", ""))
    return out


def split(names):
    """Deterministic split: the 46 held-out clips in ``val_clips.txt`` (every
    6th human-played clip, by time order, of the first model's cache — frozen,
    so models stay comparable as clips are added: new clips train)."""
    if os.path.exists(VAL_LIST):
        held = set(open(VAL_LIST).read().split())
        val = [n for n in names if n in held]
        return [n for n in names if n not in held], val
    val = [n for i, n in enumerate(names) if i % 6 == 3]
    tr = [n for n in names if n not in val]
    return tr, val


class Clip:
    def __init__(self, name):
        self.name = name
        self.meta = m = dict(np.load(os.path.join(CACHE, name + ".meta.npz")))
        self.frames = np.load(os.path.join(CACHE, name + ".frames.npy"), mmap_mode="r")
        self.n = len(self.frames)
        self.onset = int(m["onset"])
        self.end = int(m["end"]) if int(m["end"]) > 0 else self.n - 1
        self.dup = m["dup"].astype(bool)
        self.offs = list(m["offs"])
        self.shifts = m["shifts"]
        self.blobs = m["blobs"]
        self.shape_r = float(m["shape_r"]) if np.isfinite(m["shape_r"]) else 20.0
        self.gt = clean_gt(m["cursor"], 0, self.n)

    def shift(self, t, s):
        k = self.offs.index(s - t)
        dx, dy, _ = self.shifts[t, k]
        return float(dx), float(dy)

    def holes(self, t):
        b = [tuple(p) for p in self.blobs[t] if np.isfinite(p[0])]
        if b:
            return b
        # Reticle not detected in this frame (edge clipping, overlap): blank
        # where it most likely is, so it can never leak into the input.
        for d in range(1, 6):
            for s in (t - d, t + d):
                if 0 <= s < self.n and np.isfinite(self.blobs[s, 0, 0]):
                    return [tuple(self.blobs[s, 0])]
        return []

    def refs(self, t):
        r = LM.pick_refs(t, self.dup, self.n, LM.REF_OFFSETS)
        if r is None or any(abs(s - t) > max(map(abs, self.offs)) for s in r):
            return None
        return r

    def input(self, t, holes_cur=None, holes_refs=None):
        refs = self.refs(t)
        if refs is None:
            return None
        hc = self.holes(t) if holes_cur is None else holes_cur
        hr = [self.holes(s) for s in refs] if holes_refs is None else holes_refs
        return LM.build_input(np.asarray(self.frames[t]), [np.asarray(self.frames[s]) for s in refs],
                              [self.shift(t, s) for s in refs], hc, hr)


def clean_gt(cur, start, end, tol=20.0):
    """Reject cursor detections that jump away from the local median (the
    START glow sometimes passes the green mask)."""
    cur = cur.astype(np.float64)
    out = np.full_like(cur, np.nan)
    for i in range(start, end):
        lo, hi = max(start, i - 3), min(end, i + 4)
        win = cur[lo:hi]
        win = win[np.isfinite(win[:, 0])]
        if len(win) < 3 or not np.isfinite(cur[i, 0]):
            continue
        med = np.median(win, axis=0)
        if np.hypot(*(cur[i] - med)) < tol:
            out[i] = cur[i]
    return out


def labels(clip, t, valid):
    """(pos, neg) bool maps for frame t; both restricted to ``valid``."""
    h, w = valid.shape
    g = clip.gt[t]
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.hypot(xx - g[0], yy - g[1])
    # The cursor's warped copies in the reference frames sit 10-40 px from it
    # (it moves relative to the field), so the exclusion zones eat the inner
    # ring; positives extend a little past the opaque shape's radius.
    r1 = max(LM.EXCL_R + 8, clip.shape_r + 8)
    pos = (d >= LM.EXCL_R) & (d <= r1) & valid
    neg = (d > NEG_R) & valid
    return pos, neg


def disc_kernel(r):
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    k = (np.hypot(xx, yy) <= r).astype(np.float32)
    return k / k.sum()


def pooled(score, valid, r=34):
    """Mean of ``score`` over valid pixels within a disc of radius r."""
    k = disc_kernel(r)
    v = valid.astype(np.float32)
    num = cv2.filter2D(score * v, -1, k, borderType=cv2.BORDER_CONSTANT)
    den = cv2.filter2D(v, -1, k, borderType=cv2.BORDER_CONSTANT)
    return num / np.maximum(den, 0.08), den
