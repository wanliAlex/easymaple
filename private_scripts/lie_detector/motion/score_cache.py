"""Run MotionNet over clips and cache per-frame logit maps + validity masks.

Open-loop (only the recorded cursors are blanked). The tracker evaluation adds
our own simulated cursor by invalidating the exclusion zone around it, which
is exactly equivalent to blanking it in the input: the net cannot see past its
receptive field, so outputs outside that zone do not depend on the hole.

Usage:
    python private_scripts/lie_detector/motion/score_cache.py MODEL.pt OUTDIR [--split val|all]
"""
import argparse
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
from common import LM  # noqa: E402


def load_net(path, dev):
    net, _ = LM.load_net(path, dev)
    LM.REF_OFFSETS = net.ref_offsets      # inputs must match what it was trained on
    return net


@torch.no_grad()
def run_clip(net, name, dev, out_dir):
    out = os.path.join(out_dir, name + ".npz")
    if os.path.exists(out):
        return
    c = C.Clip(name)
    h, w = c.frames.shape[1:3]
    logit = np.zeros((c.n, h, w), np.float16)
    valid = np.zeros((c.n, h, w), bool)
    have = np.zeros(c.n, bool)
    for t in range(c.n):
        r = c.input(t)
        if r is None:
            continue
        x, v = r
        s = net(torch.from_numpy(x)[None].to(dev))[0, 0].float().cpu().numpy()
        logit[t] = s
        valid[t] = v
        have[t] = True
    np.savez_compressed(out, logit=logit, valid=valid, have=have)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("out_dir")
    ap.add_argument("--split", default="val")
    ap.add_argument("--clips", nargs="*")
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = load_net(a.model, dev)
    os.makedirs(a.out_dir, exist_ok=True)
    names = C.clip_names(success_only=False)
    if a.clips:
        names = a.clips
    elif a.split == "val":
        names = C.split(C.clip_names())[1]
    for n in names:
        run_clip(net, n, dev, a.out_dir)
        print(n, flush=True)


if __name__ == "__main__":
    main()
