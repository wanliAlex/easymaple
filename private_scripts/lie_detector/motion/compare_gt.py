"""Score a live game against human ground truth from ``label_clip.py``:
where the bot's cursor (and the solver's target) were relative to the shape
you followed, frame by frame.

    python private_scripts/lie_detector/motion/compare_gt.py training_data/lie_detector/2026-10-13_11-35-19_gt1.npz
    python private_scripts/lie_detector/motion/compare_gt.py GT.npz --log training_data/lie_detector/solver_logs/....npz --lag 0.1

The game log is found automatically (the one written within 60 s after the
clip started) and aligned to the clip by matching its raw half-res frames.
``--lag``: your reaction lag in clip seconds (your cursor trails the shape);
the labels are shifted back by it. Prints coverage (bot cursor within 60 px
of your cursor, frames you marked sure), the off-shape episodes, and writes
``<gt>_cmp.png`` (distance over time).
"""
import argparse
import glob
import os
from datetime import datetime, timedelta

import cv2
import numpy as np

TOL = 60.0


def find_log(clip_path, log_dir):
    stamp = datetime.strptime(os.path.basename(clip_path)[:19], "%Y-%m-%d_%H-%M-%S")
    best = None
    for p in glob.glob(os.path.join(log_dir, "*.npz")):
        try:
            s = datetime.strptime(os.path.basename(p)[:19], "%Y-%m-%d_%H-%M-%S")
        except ValueError:
            continue
        if stamp <= s <= stamp + timedelta(seconds=60) and (best is None or s < best[0]):
            best = (s, p)
    return best[1] if best else None


def align(clip_path, log, n_probe=12):
    """clip time - log time, from the log's raw half-res frames matched to the
    clip's frames."""
    half, hidx, lt = log["half"], log["half_idx"], log["t"]
    bx, by = (int(v) for v in log["box"][:2])
    hh, hw = half.shape[1:3]
    ct = np.load(clip_path[:-4] + "_t.npy")
    cap = cv2.VideoCapture(clip_path)
    crops = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        c = f[by + 8:by + 8 + 2 * hh, bx + 8:bx + 8 + 2 * hw]
        crops.append(cv2.resize(c, (hw, hh), interpolation=cv2.INTER_AREA).astype(np.float32))
    offs = []
    for j in np.linspace(0, len(half) - 1, n_probe).astype(int):
        err = [np.mean(np.abs(c - half[j])) for c in crops]
        k = int(np.argmin(err))
        if err[k] < 5.0:
            offs.append((ct[k] - ct[0]) - (lt[hidx[j]] - lt[0]))
    if not offs:
        raise SystemExit("could not align the log to the clip")
    return float(np.median(offs)), float(np.ptp(offs))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gt")
    ap.add_argument("--log", default=None)
    ap.add_argument("--lag", type=float, default=0.0, help="your reaction lag, clip seconds")
    a = ap.parse_args()
    g = np.load(a.gt, allow_pickle=True)
    clip = os.path.join(os.path.dirname(a.gt), str(g["clip"]))
    log_path = a.log or find_log(clip, os.path.join(os.path.dirname(clip), "solver_logs"))
    if log_path is None:
        raise SystemExit("no game log found for " + clip + " (pass --log)")
    log = np.load(log_path, allow_pickle=True)
    off, spread = align(clip, log)
    lt = log["t"] - log["t"][0]
    st, bot, tgt = log["state"], log["bot"], log["target"]
    track = np.flatnonzero(st == "TRACK")
    t_gt = g["t"] - a.lag                    # when the shape was where you pointed
    xy, sure = g["xy"], g["sure"]
    ok_b = np.isfinite(bot[:, 0])
    ok_t = np.isfinite(tgt[:, 0])
    tl = t_gt - off                          # in log time
    in_game = (tl >= lt[track[0]]) & (tl <= lt[track[-1]]) & np.isfinite(xy[:, 0])
    use = in_game & (sure if sure.any() else True)
    bx = np.interp(tl, lt[ok_b], bot[ok_b, 0])
    by = np.interp(tl, lt[ok_b], bot[ok_b, 1])
    tx = np.interp(tl, lt[ok_t], tgt[ok_t, 0])
    ty = np.interp(tl, lt[ok_t], tgt[ok_t, 1])
    d_bot = np.hypot(bx - xy[:, 0], by - xy[:, 1])
    d_tgt = np.hypot(tx - xy[:, 0], ty - xy[:, 1])
    print(f"log {os.path.basename(log_path)} (outcome {log['outcome']}); clip-log offset {off:+.3f} s (spread {spread:.3f})")
    print(f"frames scored: {use.sum()} of {in_game.sum()} in the game ({'only frames marked sure' if sure.any() else 'all'})")
    on = d_bot[use] < TOL
    print(f"bot cursor on the shape (<{TOL:.0f} px of yours): {on.mean():.0%}; solver target: {np.mean(d_tgt[use] < TOL):.0%}; "
          f"median distance {np.median(d_bot[use]):.0f} px")
    # off-shape episodes
    tt = g["t"][use]
    print("off-shape episodes > 0.3 s (clip seconds; player time = x 24.9/30):")
    run0 = None
    for i, v in enumerate(list(on) + [True]):
        if not v and run0 is None:
            run0 = i
        elif v and run0 is not None:
            if tt[i - 1] - tt[run0] > 0.3:
                print(f"  {tt[run0]:6.2f} - {tt[i - 1]:6.2f} s  ({tt[i - 1] - tt[run0]:.2f} s, player {tt[run0] * 24.9 / 30:.1f}-{tt[i - 1] * 24.9 / 30:.1f})"
                      f"  max {d_bot[use][run0:i].max():.0f} px")
            run0 = None
    # plot
    W, H = 900, 260
    img = np.full((H, W, 3), 255, np.uint8)
    t0, t1 = g["t"][in_game].min(), g["t"][in_game].max()
    def px(t, d):
        return int((t - t0) / (t1 - t0) * (W - 40) + 30), int(H - 20 - min(d, 300) / 300 * (H - 40))
    cv2.line(img, px(t0, TOL), px(t1, TOL), (0, 160, 0), 1)
    for arr, col in ((d_tgt, (200, 120, 200)), (d_bot, (0, 0, 220))):
        pts = [px(t, v) for t, v, u in zip(g["t"], arr, in_game) if u]
        for p, q in zip(pts, pts[1:]):
            cv2.line(img, p, q, col, 1)
    for s in range(int(t0), int(t1) + 1):
        cv2.putText(img, str(s), (px(s, 0)[0] - 6, H - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1)
    cv2.putText(img, "distance to your cursor (px, capped 300): red = bot cursor, purple = solver target, green = 60 px",
                (30, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
    out = a.gt[:-4] + "_cmp.png"
    cv2.imwrite(out, img)
    print("wrote", out)


if __name__ == "__main__":
    main()
