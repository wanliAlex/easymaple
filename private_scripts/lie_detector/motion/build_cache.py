"""Build the training/eval cache for the motion-based Lie Detector detector.

One pass per recording:

* lock the play box (size-gated: inventory windows and the countdown dialog
  are rejected), grow it to the field's real edges exactly as the runtime
  does (``LM.refine_box``: the detector clips the field's bottom ~48 px, which
  the first model never saw) and take the interior at half resolution;
* every green blob per frame (the reticle, plus any START-glow false
  positives) -> positions that will be blanked out, so a model can never see
  the cursor;
* duplicate frames (the capture repeats ~20% of frames);
* START (texture motion onset) and the SUCCESS banner frame (end of the
  puzzle; failed games have none);
* the shape's size from the opaque phase;
* direct phase-correlation shifts from each frame to its neighbours at offsets
  -8..+8 (the background/distractor motion that everything is aligned to),
  computed like the runtime (``LM.pc_crop``: unpadded — OpenCV's padding
  biases odd sizes by +0.5 px), unwindowed by default. ``LD_PC_WINDOW=1``
  pre-windows like the shipped net's training (train with ``--pc-window``):
  the window makes the alignment partly follow the static imprint at the box
  centre, which cancels it — nets trained unwindowed track worse closed-loop
  (FINDINGS §12).

Only human-played clips are cached: from ``AUTO_SINCE`` the bot plays the Lie
Detector itself, and the reticle in those recordings is its own cursor —
training on it would teach the net to follow us.

Output per clip under training_data/lie_detector/motion_cache_full/ (LD_CACHE overrides;
the first model's clipped, windowed cache is training_data/lie_detector/motion_cache/):
  <clip>.frames.npy  (N, h, w, 3) uint8, half-res interior, window [w0, w1)
  <clip>.meta.npz    everything else (frame-indexed relative to w0)

Usage:
    python private_scripts/lie_detector/motion/build_cache.py [--jobs 8]
"""
import argparse
import glob
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)
from src.easymaple.detection import lie_detector_solver as S  # noqa: E402
from src.easymaple.detection import lie_detector_motion as LM  # noqa: E402

VID_DIR = os.path.join(ROOT, "training_data", "lie_detector")
OUT_DIR = os.environ.get("LD_CACHE") or os.path.join(VID_DIR, "motion_cache_full")
MAX_OFF = 8
PC_WINDOW = os.environ.get("LD_PC_WINDOW") == "1"   # align like the shipped net's training (see above)
AUTO_SINCE = "2026-10-11_19-00-00"   # the bot has played the Lie Detector itself since
STAMP = "%Y-%m-%d_%H-%M-%S"


def human_played(name):
    """True if a human played this clip: recorded before ``AUTO_SINCE``, or a
    shadow-mode game log (written within 60 s after the clip starts) shows the
    bot never took over. Bot games and clips of unknown origin are skipped."""
    if name[:19] < AUTO_SINCE:
        return True
    s = datetime.strptime(name[:19], STAMP)
    for p in glob.glob(os.path.join(VID_DIR, "solver_logs", "*_shadow_*.npz")):
        t = datetime.strptime(os.path.basename(p)[:19], STAMP)
        if s <= t <= s + timedelta(seconds=60):
            return not np.load(p)["driving"].any()
    return False


def largest_green(crop):
    gm = S.green_cursor_mask(crop)
    cnts, _ = cv2.findContours(gm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return (np.nan, np.nan)
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 15:
        return (np.nan, np.nan)
    m = cv2.moments(c)
    return (m["m10"] / m["m00"], m["m01"] / m["m00"])


def success_frame(counts):
    """First frame of the yellow SUCCESS banner, or -1. ``counts``: frame index
    -> yellow pixel count, over the last ~100 frames of the game."""
    start = min(counts)
    c = np.array([counts[i] for i in sorted(counts)])
    on = np.where(c > np.median(c[:20]) + 3000)[0]
    return int(start + on[0]) if len(on) else -1


def build(path):
    name = os.path.basename(path)
    out_meta = os.path.join(OUT_DIR, name.replace(".mp4", ".meta.npz"))
    if os.path.exists(out_meta):
        return name, "cached"
    if not human_played(name):
        return name, "bot-played: skipped"
    # Pass 1: play-box per frame (and, where it passes the gates, the box
    # refined to the field's edges). Full frames are not kept (~2 GB a clip).
    cap = cv2.VideoCapture(path)
    boxes, refined = [], {}
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        b = S.detect_play_box(fr)
        b = b if (b and 690 < b[2] < 770 and 410 < b[3] < 480) else None
        if b:
            refined[len(boxes)] = LM.refine_box(fr, tuple(int(v) for v in b))
        boxes.append(b)
    cap.release()
    idx = [i for i, b in enumerate(boxes) if b]
    if not idx:
        return name, "no box"
    # Longest run of consistent detections (gaps < 1 s): a lone early false
    # positive must not define the game window.
    runs, cur = [], []
    for i in idx:
        b = boxes[i]
        c = (b[0] + b[2] / 2, b[1] + b[3] / 2)
        if cur:
            p = boxes[cur[-1]]
            pc = (p[0] + p[2] / 2, p[1] + p[3] / 2)
            if i - cur[-1] > 30 or abs(c[0] - pc[0]) > 25 or abs(c[1] - pc[1]) > 25:
                runs.append(cur)
                cur = []
        cur.append(i)
    runs.append(cur)
    run = max(runs, key=len)
    if len(run) < 120:
        return name, "box run too short"
    first, last = run[0], run[-1]
    det_box = tuple(int(v) for v in np.median(np.array([boxes[i] for i in run]), axis=0))
    # The field's real extent: median refined box once the dialog has opened.
    box = tuple(int(v) for v in np.median(np.array([refined[i] for i in run[10:]]), axis=0))
    x, y, w, h = box
    m = LM.BOX_MARGIN
    # Pass 2: the game window only, cropped to the field.
    cap = cv2.VideoCapture(path)
    crops, succ = [], {}
    dx0, dy0, dw, dh = det_box
    for i in range(last + 1):
        ok, fr = cap.read()
        if not ok:
            break
        if i < first:
            continue
        crops.append(fr[y + m:y + h - m, x + m:x + w - m].copy())
        if i >= last - 100:          # SUCCESS banner search (detected box, as before)
            cr = fr[dy0 + int(dh * 0.25):dy0 + int(dh * 0.75), dx0 + int(dw * 0.1):dx0 + int(dw * 0.9)]
            hsv = cv2.cvtColor(cr, cv2.COLOR_BGR2HSV)
            succ[i] = int(cv2.inRange(hsv, (20, 40, 225), (40, 255, 255)).sum() / 255)
    cap.release()
    last = first + len(crops) - 1

    half = [LM.half_res(c) for c in crops]
    gray = [LM.gray_f(f) for f in half]
    sl = LM.pc_crop(*gray[0].shape)
    if PC_WINDOW:
        win = cv2.createHanningWindow((sl[1].stop - sl[1].start, sl[0].stop - sl[0].start), cv2.CV_32F)
        pcg = [g[sl] * win for g in gray]
    else:
        pcg = [np.ascontiguousarray(g[sl]) for g in gray]
    n = len(half)
    # consecutive shift + dup flag
    cons = np.zeros((n, 3), np.float32)
    for i in range(1, n):
        (dx, dy), r = cv2.phaseCorrelate(pcg[i - 1], pcg[i])
        cons[i] = (dx, dy, r)
    absd = [0.0] + [float(np.abs(gray[i] - gray[i - 1]).mean()) for i in range(1, n)]
    dup = np.array([LM.is_duplicate(cons[i, 2], cons[i, 0], cons[i, 1], absd[i]) for i in range(n)])
    dup[0] = False
    sp = np.hypot(cons[:, 0], cons[:, 1])
    ok = (sp > 1.25) & ~dup
    onset = 20
    for i in range(20, n - 8):
        if ok[i] and ok[i:i + 8].sum() >= 5:
            onset = i
            break
    e_abs = success_frame(succ)
    e_rel = e_abs - first if e_abs >= 0 else -1

    # shape size from the opaque phase (largest bright blob below the countdown band)
    areas = []
    for i in range(max(0, onset - 40), onset):
        g = cv2.cvtColor(crops[i], cv2.COLOR_BGR2GRAY)
        _, a = S._bright_blob(g)
        if a:
            areas.append(a)
    shape_r = float(np.sqrt(np.median(areas) / np.pi)) if areas else np.nan

    # window to store
    w0 = max(0, onset - 15)
    w1 = min(n, (e_rel if e_rel > 0 else n) + 8)
    # direct shifts to neighbours
    offs = [o for o in range(-MAX_OFF, MAX_OFF + 1) if o]
    shifts = np.full((w1 - w0, len(offs), 3), np.nan, np.float32)
    for i in range(w0, w1):
        for k, o in enumerate(offs):
            j = i + o
            if 0 <= j < n:
                # shift that maps frame j onto frame i
                (dx, dy), r = cv2.phaseCorrelate(pcg[j], pcg[i])
                shifts[i - w0, k] = (dx, dy, r)
    cursor = np.array([largest_green(crops[i]) for i in range(w0, w1)], np.float32) / 2
    blobs = np.full((w1 - w0, 4, 2), np.nan, np.float32)
    for i in range(w0, w1):
        gm = S.green_cursor_mask(crops[i])
        k, lab, stats, cent = cv2.connectedComponentsWithStats(gm)
        cs = [cent[j] for j in np.argsort(-stats[1:, cv2.CC_STAT_AREA]) + 1
              if stats[j, cv2.CC_STAT_AREA] >= 15][:4]
        for q, c in enumerate(cs):
            blobs[i - w0, q] = c / 2
    os.makedirs(OUT_DIR, exist_ok=True)
    np.save(os.path.join(OUT_DIR, name.replace(".mp4", ".frames.npy")),
            np.array(half[w0:w1], np.uint8))
    np.savez(out_meta, box=np.array(box), det_box=np.array(det_box), first=first, last=last,
             w0=w0, w1=w1,
             onset=onset - w0, end=(e_rel - w0) if e_rel > 0 else -1,
             dup=dup[w0:w1], cons=cons[w0:w1], shifts=shifts, offs=np.array(offs),
             cursor=cursor, blobs=blobs, shape_r=shape_r / 2, success=e_rel > 0)
    return name, (w1 - w0, e_rel > 0, round(shape_r, 1), box)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("clips", nargs="*")
    a = ap.parse_args()
    paths = [os.path.join(VID_DIR, c) for c in a.clips] or sorted(glob.glob(os.path.join(VID_DIR, "*.mp4")))
    with ProcessPoolExecutor(a.jobs) as ex:
        for nm, r in ex.map(build, paths):
            print(nm, r, flush=True)
