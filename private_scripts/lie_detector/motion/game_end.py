"""Game end of each labelled live game, for ``ev.py live``'s scoring window:
the SUCCESS banner (yellow pixels in the play-box centre), else the moment
the field stops moving (a failed game). The labels run on past it (the user
presses Q on seeing SUCCESS, at half speed). New games are added to
``training_data/lie_detector/eval/live_end.json`` {clip[:19]: seconds}.

    python private_scripts/lie_detector/motion/game_end.py
"""
import glob
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.environ.get("LD_ROOT") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from label_clip import clip_times, find_game  # noqa: E402

VID = os.path.join(ROOT, "training_data", "lie_detector")
OUT = os.path.join(VID, "eval", "live_end.json")


def game_end(clip):
    """(seconds, how) for one clip."""
    cap = cv2.VideoCapture(clip)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ct = clip_times(clip, n)
    k_box, box = find_game(clip)
    if box is None:
        return None, "no box"
    x, y, w, h = box
    cy0, cy1, cx0, cx1 = y + int(h * 0.25), y + int(h * 0.75), x + int(w * 0.1), x + int(w * 0.9)
    yellow, moving, prev = [], [], None
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        cr = fr[cy0:cy1, cx0:cx1]
        yellow.append(int(cv2.inRange(cv2.cvtColor(cr, cv2.COLOR_BGR2HSV), (20, 40, 225), (40, 255, 255)).sum() / 255))
        g = cv2.cvtColor(cr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        moving.append(0.0 if prev is None else float(np.abs(g - prev).mean()))
        prev = g
    yellow, moving = np.array(yellow), np.array(moving)
    ct = ct[:len(yellow)]
    t_box = ct[k_box]
    base = np.median(yellow[(ct > t_box + 2) & (ct < t_box + 6)])
    on = np.flatnonzero((yellow > base + 3000) & (ct > t_box + 2))
    if len(on):
        return float(ct[on[0]]), "success"
    for i in np.flatnonzero(ct > t_box + 4):           # a failed game: the field stops for 0.5 s
        win = (ct >= ct[i]) & (ct < ct[i] + 0.5)
        if (moving[win] < 1.0).all():
            return float(ct[i]), "field stopped"
    return None, "?"


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for gt in sorted(glob.glob(os.path.join(VID, "*_gt1.npz"))):
        key = os.path.basename(gt)[:19]
        if key in res:
            continue
        end, how = game_end(gt[:-8] + ".mp4")
        res[key] = end
        print(key, how, end, "labels end", round(float(np.load(gt)["t"][-1]), 2))
    json.dump(res, open(OUT, "w"), indent=1)
