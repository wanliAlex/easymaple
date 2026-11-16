"""Ground truth for games the bot played: replay a recorded Lie Detector clip
and follow the shape with the mouse, like playing it again. Your mouse
position is recorded for every frame (full-frame pixels), so the solver's
live log can be scored against it.

    python private_scripts/lie_detector/motion/label_clip.py --speed 0.5       # next game to label (label_queue.txt first), half speed
    python private_scripts/lie_detector/motion/label_clip.py training_data/lie_detector/2026-10-13_11-35-19.mp4

Controls (click the video window first):
    SPACE        start / pause
    hold LEFT    while you are sure where the shape is; release when you lose it
                 (frames recorded without the button are marked unsure)
    R            restart from the beginning as a new attempt
    S            save this attempt now
    Q / ESC      save and quit

Playback starts ~1 s before the play-box appears and runs at the clip's real
speed (from ``*_t.npy``; the container's 30 fps is too fast) times
``--speed``. The green reticle you see is the bot's cursor — ignore it.
Each attempt is saved as ``<clip>_gt<N>.npz``: ``k`` (frame indices),
``t`` (clip seconds), ``xy`` (mouse, full-frame px), ``sure`` (left button
held), ``speed``.
"""
import argparse
import glob
import os
import sys
import time

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)
from src.easymaple.detection import lie_detector_motion as LM  # noqa: E402
from src.easymaple.detection.lie_detector_solver import detect_play_box  # noqa: E402

PAD = 40                       # px of context shown around the play-box
FALLBACK_DT = LM.FRAME_DT      # clips recorded before *_t.npy existed


def clip_times(path, n):
    tp = path[:-4] + "_t.npy"
    if os.path.exists(tp):
        t = np.load(tp)
        if len(t) >= n:
            return t[:n] - t[0]
    return np.arange(n) * FALLBACK_DT


def find_game(path, step=5):
    """(first frame with the play-box, refined box) — scans every ``step``
    frames."""
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    for k in range(0, n, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, k)
        ok, fr = cap.read()
        if not ok:
            break
        b = detect_play_box(fr)
        if b is not None and LM.BOX_W[0] <= b[2] <= LM.BOX_W[1] and LM.BOX_H[0] <= b[3] <= LM.BOX_H[1]:
            # a few frames later the dialog has finished opening
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(n - 1, k + 10))
            ok, fr2 = cap.read()
            b2 = detect_play_box(fr2) if ok else None
            b = b2 if b2 is not None else b
            return k, LM.refine_box(fr2 if ok else fr, tuple(int(v) for v in b))
    return 0, None


def default_clip():
    """The first unlabelled clip in ``label_queue.txt`` (written by
    ``rank_unlabelled.py``: games where two models disagree most); else the
    newest clip the bot played (it has a game log, written within 60 s after
    the clip starts) that has no labels yet — failed games first."""
    from datetime import datetime, timedelta
    vid_dir = os.path.join(ROOT, "training_data", "lie_detector")
    queue = os.path.join(vid_dir, "label_queue.txt")
    if os.path.exists(queue):
        for name in open(queue).read().split():
            c = os.path.join(vid_dir, name)
            if os.path.exists(c) and not glob.glob(c[:-4] + "_gt*.npz"):
                return c
    clips = sorted(glob.glob(os.path.join(vid_dir, "????-??-??_??-??-??.mp4")))
    logs = sorted(glob.glob(os.path.join(vid_dir, "solver_logs", "*.npz")), reverse=True)
    logs = [p for p in logs if "_failed" in p] + [p for p in logs if "_failed" not in p]
    for log in logs:
        s = datetime.strptime(os.path.basename(log)[:19], "%Y-%m-%d_%H-%M-%S")
        for c in reversed(clips):
            cs = datetime.strptime(os.path.basename(c)[:19], "%Y-%m-%d_%H-%M-%S")
            if cs <= s <= cs + timedelta(seconds=60) and not glob.glob(c[:-4] + "_gt*.npz"):
                return c
    return None


def next_attempt_path(path):
    have = glob.glob(path[:-4] + "_gt*.npz")
    nums = [int(os.path.basename(p)[len(os.path.basename(path)) - 4 + 3:-4]) for p in have
            if os.path.basename(p)[len(os.path.basename(path)) - 4 + 3:-4].isdigit()]
    return path[:-4] + f"_gt{max(nums, default=0) + 1}.npz"


class Attempt:
    """Per-frame mouse record for one play-through."""

    def __init__(self, n):
        self.xy = np.full((n, 2), np.nan, np.float32)
        self.sure = np.zeros(n, bool)
        self.seen = np.zeros(n, bool)

    def record(self, k, xy, sure):
        self.xy[k] = xy
        self.sure[k] = sure
        self.seen[k] = True

    def save(self, path, t, speed, clip):
        ks = np.flatnonzero(self.seen)
        if not len(ks):
            return None
        np.savez(path, k=ks, t=t[ks], xy=self.xy[ks], sure=self.sure[ks], speed=speed,
                 clip=os.path.basename(clip))
        return path


def run(path, speed, start=None, selftest=False):
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    t = clip_times(path, n)
    k_box, box = find_game(path)
    if box is None:
        raise SystemExit("no play-box found in " + path)
    k0 = int(np.searchsorted(t, max(0.0, t[k_box] - 1.0))) if start is None else int(np.searchsorted(t, start))
    x, y, w, h = box
    H, W = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    cx0, cy0 = max(0, x - PAD), max(0, y - PAD)
    cx1, cy1 = min(W, x + w + PAD), min(H, y + h + PAD)
    print(f"{os.path.basename(path)}: {n} frames, {t[-1]:.1f} s real; play-box {box} from {t[k_box]:.1f} s; "
          f"playback from {t[k0]:.1f} s at {speed:g}x")

    mouse = {"xy": (np.nan, np.nan), "down": False}

    def on_mouse(ev, mx, my, flags, _):
        mouse["xy"] = (float(mx + cx0), float(my + cy0))
        if ev == cv2.EVENT_LBUTTONDOWN:
            mouse["down"] = True
        elif ev == cv2.EVENT_LBUTTONUP:
            mouse["down"] = False

    win = "Lie Detector labeler - SPACE start/pause, hold LEFT while sure, R restart, Q quit"
    if not selftest:
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(win, on_mouse)

    def show(fr, status):
        img = fr[cy0:cy1, cx0:cx1].copy()
        cv2.putText(img, status, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
        cv2.putText(img, status, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        if not selftest:
            cv2.imshow(win, img)

    attempt, saved = Attempt(n), []
    cap.set(cv2.CAP_PROP_POS_FRAMES, k0)
    k = k0
    ok, fr = cap.read()
    playing, wall0 = selftest, None
    sim = iter(range(10 ** 9))
    while True:
        if not playing:
            show(fr, f"t={t[k]:5.2f}s  PAUSED  attempt {len(saved) + 1}  (SPACE to play)")
            key = cv2.waitKey(30) & 0xFF if not selftest else ord(" ")
        else:
            if wall0 is None:
                wall0 = time.perf_counter() - (t[k] - t[k0]) / speed
            due = wall0 + (t[k] - t[k0]) / speed
            wait = due - time.perf_counter()
            show(fr, f"t={t[k]:5.2f}s  {'SURE' if mouse['down'] else 'unsure'}  {speed:g}x  attempt {len(saved) + 1}")
            key = (cv2.waitKey(max(1, int(wait * 1000))) & 0xFF) if not selftest else 255
            if selftest:                      # synthetic mouse: a circle, button held
                i = next(sim)
                mouse["xy"] = (x + w / 2 + 100 * np.cos(i / 20), y + h / 2 + 80 * np.sin(i / 20))
                mouse["down"] = True
            attempt.record(k, mouse["xy"], mouse["down"])
            k += 1
            ok, fr = cap.read()
            if not ok or k >= n:
                p = attempt.save(next_attempt_path(path), t, speed, path)
                saved.append(p)
                print(f"end of clip: saved {p}  (R = another attempt, Q = quit)")
                if selftest:
                    return saved
                playing, attempt = False, Attempt(n)
                k = k0
                cap.set(cv2.CAP_PROP_POS_FRAMES, k0)
                ok, fr = cap.read()
                wall0 = None
                continue
        if key == ord(" "):
            playing = not playing
            wall0 = None
        elif key in (ord("r"), ord("R")):
            if attempt.seen.any():
                saved.append(attempt.save(next_attempt_path(path), t, speed, path))
                print("saved", saved[-1])
            attempt, playing, wall0, k = Attempt(n), False, None, k0
            cap.set(cv2.CAP_PROP_POS_FRAMES, k0)
            ok, fr = cap.read()
        elif key in (ord("s"), ord("S")) and attempt.seen.any():
            saved.append(attempt.save(next_attempt_path(path), t, speed, path))
            print("saved", saved[-1])
            attempt = Attempt(n)
        elif key in (ord("q"), ord("Q"), 27):
            if attempt.seen.any():
                saved.append(attempt.save(next_attempt_path(path), t, speed, path))
                print("saved", saved[-1])
            break
        if not selftest and cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
            if attempt.seen.any():
                saved.append(attempt.save(next_attempt_path(path), t, speed, path))
                print("saved", saved[-1])
            break
    cv2.destroyAllWindows()
    return saved


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip", nargs="?", default=None,
                    help="clip to label (default: next in label_queue.txt, else the newest unlabelled bot game)")
    ap.add_argument("--speed", type=float, default=1.0, help="playback speed (0.5 = half speed)")
    ap.add_argument("--start", type=float, default=None, help="start at this clip second")
    ap.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    clip = a.clip or default_clip()
    if clip is None:
        raise SystemExit("every game the bot played is labelled")
    run(os.path.abspath(clip), a.speed, a.start, a.selftest)
