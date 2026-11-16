"""Train the leak-proof motion detector (MotionNet) on the human-played clips.

Inputs: current frame + background-aligned differences to 4 reference frames
(half-res), every cursor blanked. Labels: a ring around the human's cursor
(just outside the exclusion radius) = positive, far away = negative, anything
whose receptive field could reach a blanked disc = ignored.

Usage:
    python private_scripts/lie_detector/motion/train.py [--epochs 12]
"""
import argparse
import os
import sys
import time

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
from common import LM  # noqa: E402


class FrameSet(Dataset):
    def __init__(self, names, stride=1, augment=True):
        self.names = names
        self.items = []
        for ci, n in enumerate(names):
            c = C.Clip(n)
            for t in range(max(c.onset - 4, 8), c.end - 5, stride):
                if np.isfinite(c.gt[t, 0]):
                    self.items.append((ci, t))
        self.augment = augment
        self._clips = {}
        # clips differ in size by a few pixels: pad every sample to the largest
        # (rounded up to a multiple of 8)
        hw = np.max([np.load(os.path.join(C.CACHE, n + ".frames.npy"), mmap_mode="r").shape[1:3]
                     for n in names], axis=0)
        self.pad = tuple(int(-(-v // 8) * 8) for v in hw)

    def clip(self, ci):
        if ci not in self._clips:
            self._clips[ci] = C.Clip(self.names[ci])
        return self._clips[ci]

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        ci, t = self.items[i]
        c = self.clip(ci)
        r = c.input(t)
        if r is None:
            x = np.zeros((3 + 3 * len(LM.REF_OFFSETS), *c.frames.shape[1:3]), np.float32)  # noqa
            pos = neg = np.zeros(c.frames.shape[1:3], bool)
        else:
            x, valid = r
            pos, neg = C.labels(c, t, valid)
        if self.augment:
            if np.random.rand() < 0.5:
                x, pos, neg = x[:, :, ::-1], pos[:, ::-1], neg[:, ::-1]
            if np.random.rand() < 0.5:
                x, pos, neg = x[:, ::-1], pos[::-1], neg[::-1]
        H, W = self.pad
        out = np.zeros((x.shape[0], H, W), np.float32)
        P = np.zeros((H, W), bool); N = np.zeros((H, W), bool)
        h, w = x.shape[1:]
        out[:, :h, :w] = x; P[:h, :w] = pos; N[:h, :w] = neg
        return torch.from_numpy(out), torch.from_numpy(P), torch.from_numpy(N)


def step_loss(net, x, p, n):
    logit = net(x)[:, 0]
    bce = torch.nn.functional.binary_cross_entropy_with_logits
    lp = bce(logit[p], torch.ones_like(logit[p])) if p.any() else logit.sum() * 0
    ln = bce(logit[n], torch.zeros_like(logit[n])) if n.any() else logit.sum() * 0
    return lp + ln, lp, ln


@torch.no_grad()
def validate(net, names, dev, every=6, max_clips=None):
    """Leak-free per-frame localisation: pooled score at the cursor vs the best
    pooled score > 50 px (half-res) away. Returns (pct, win, late_pct, late_win)."""
    net.eval()
    res = []
    for n in names[:max_clips]:
        c = C.Clip(n)
        for t in range(c.onset + 6, c.end - 5, every):
            if not np.isfinite(c.gt[t, 0]):
                continue
            r = c.input(t)
            if r is None:
                continue
            x, valid = r
            s = net(torch.from_numpy(x)[None].to(dev))[0, 0].float().cpu().numpy()
            A, den = C.pooled(s, valid)
            A[den < 0.08] = -1e9
            gx, gy = int(round(c.gt[t, 0])), int(round(c.gt[t, 1]))
            if not (0 <= gy < A.shape[0] and 0 <= gx < A.shape[1]):
                continue
            v = A[gy, gx]
            ok = A > -1e8
            pct = float((A[ok] < v).mean())
            yy, xx = np.mgrid[0:A.shape[0], 0:A.shape[1]]
            far = ok & (np.hypot(xx - gx, yy - gy) > 50)
            if not far.any() or v < -1e8:
                continue
            res.append(((t - c.onset) / max(1, c.end - c.onset), pct, v > A[far].max()))
    net.train()
    r = np.array(res, float)
    late = r[r[:, 0] > 0.8]
    return np.median(r[:, 1]), r[:, 2].mean(), np.median(late[:, 1]), late[:, 2].mean()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--per-epoch", type=int, default=16000)
    ap.add_argument("--bs", type=int, default=12)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--width", type=int, default=48)
    ap.add_argument("--out", default=os.path.normpath(LM.MODEL_PATH))
    ap.add_argument("--pc-window", action="store_true",
                    help="the cache was aligned with a Hanning window (e.g. the first cache, motion_cache): "
                         "the runtime must align the same way")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--init", default=None, help="start from these weights (fine-tune)")
    a = ap.parse_args()
    if a.seed is not None:
        torch.manual_seed(a.seed)
        np.random.seed(a.seed)
    names = C.clip_names()
    tr, va = C.split(names)
    print(f"clips: {len(names)} train {len(tr)} val {len(va)}", flush=True)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    ds = FrameSet(tr)
    print(f"train frames: {len(ds)}", flush=True)
    net = LM.make_net(width=a.width).to(dev)
    if a.init:
        net.load_state_dict(torch.load(a.init, map_location=dev, weights_only=False)["state"])
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
    total = a.epochs * -(-a.per_epoch // a.bs)     # the last batch of an epoch may be partial
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=total, pct_start=0.1)
    best = -1
    for ep in range(a.epochs):
        sampler = torch.utils.data.RandomSampler(ds, replacement=True, num_samples=a.per_epoch)
        dl = DataLoader(ds, batch_size=a.bs, sampler=sampler, num_workers=a.workers,
                        persistent_workers=False, pin_memory=True)
        t0 = time.time(); lsum = np.zeros(3); k = 0
        for x, p, n in dl:
            x, p, n = x.to(dev, non_blocking=True), p.to(dev), n.to(dev)
            loss, lp, ln = step_loss(net, x, p, n)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step(); sched.step()
            lsum += [loss.item(), lp.item(), ln.item()]; k += 1
        pct, win, lpct, lwin = validate(net, va, dev)
        print(f"ep {ep}: loss {lsum[0]/k:.4f} (pos {lsum[1]/k:.4f} neg {lsum[2]/k:.4f}) "
              f"{time.time()-t0:.0f}s | val pct {pct:.3f} win {win:.2f} late pct {lpct:.3f} win {lwin:.2f}", flush=True)
        score = win + lwin
        if score > best:
            best = score
            os.makedirs(os.path.dirname(a.out), exist_ok=True)
            torch.save({"state": net.state_dict(), "ref_offsets": LM.REF_OFFSETS, "width": a.width,
                        "hole_r": LM.HOLE_R, "rf_r": LM.NET_RF_R, "pc_window": a.pc_window}, a.out)
            print(f"  saved -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
