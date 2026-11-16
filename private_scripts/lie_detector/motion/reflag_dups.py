"""Re-derive the duplicate-frame flags in the motion cache with
``lie_detector_motion.is_duplicate`` (near-zero pixel change, or a near-perfect
correlation at near-zero shift). The first cache build flagged every frame
with correlation > 0.97 — but real footage does produce near-perfect
translations, so a third of those were moving frames.

Usage:
    python private_scripts/lie_detector/motion/reflag_dups.py
"""
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CACHE, LM  # noqa: E402

changed = total = 0
for p in sorted(glob.glob(os.path.join(CACHE, "*.meta.npz"))):
    m = dict(np.load(p))
    fr = np.load(p.replace(".meta.npz", ".frames.npy"), mmap_mode="r")
    cons = m["cons"]
    dup = np.zeros(len(fr), bool)
    prev = None
    for i in range(len(fr)):
        g = cv2.cvtColor(np.asarray(fr[i]), cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev is not None:
            dup[i] = LM.is_duplicate(cons[i, 2], cons[i, 0], cons[i, 1], float(np.abs(g - prev).mean()))
        prev = g
    changed += int((dup != m["dup"]).sum())
    total += len(dup)
    m["dup"] = dup
    np.savez(p, **m)
print(f"re-flagged {changed} of {total} frames")
