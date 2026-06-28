"""Render the tracking demo with velocity vectors drawn for the solver and the
ground-truth cursor, so the smoothness of the Kalman velocity is visible and
directly comparable with the real shape's motion.

  red  dot + arrow = solver estimate + its Kalman velocity
  green dot + arrow = ground-truth cursor + its (smoothed) velocity
  HUD = solver speed vs GT speed, in px/frame

Outputs <clip>_velocity.mp4 under training_data/lie_detector/demo/.

    python private_scripts/lie_detector/kalman/demo_velocity.py
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.easymaple.detection import lie_detector_solver as S

VID_DIR = "training_data/lie_detector"
OUT_DIR = "training_data/lie_detector/demo"
ARROW = 6.0          # px drawn per px/frame of velocity (visibility scale)


def gt_cursor(frame_bgr):
    box = S.detect_play_box(frame_bgr)
    if box is None:
        return None
    x, y, w, h = box
    m = S.BOX_INNER_MARGIN
    crop = frame_bgr[y + m:y + h - m, x + m:x + w - m]
    gm = S.green_cursor_mask(crop)
    cnts, _ = cv2.findContours(gm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 15:
        return None
    M = cv2.moments(c)
    return (x + m + M["m10"] / M["m00"], y + m + M["m01"] / M["m00"])


def smoothed_velocity(pts, i, half=2):
    """Central-difference velocity of a list of (x,y)|None at index i."""
    a = next((pts[j] for j in range(i, max(-1, i - half - 1), -1) if pts[j]), None)
    b = next((pts[j] for j in range(i, min(len(pts), i + half + 1)) if pts[j]), None)
    if a is None or b is None or a is b:
        return (0.0, 0.0)
    n = max(1, half)
    return ((b[0] - a[0]) / (2 * n), (b[1] - a[1]) / (2 * n))


def arrow(img, p, v, color, ox, oy):
    x, y = int(p[0] - ox), int(p[1] - oy)
    tip = (int(x + v[0] * ARROW), int(y + v[1] * ARROW))
    if abs(v[0]) + abs(v[1]) > 0.3:
        cv2.arrowedLine(img, (x, y), tip, color, 2, tipLength=0.35)


def run(vid):
    cap = cv2.VideoCapture(os.path.join(VID_DIR, vid))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    solver = S.LieDetectorSolver()
    frames, targets, gts, svels = [], [], [], []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        t = solver.process(fr)
        v = solver.tracker.vel if (solver.state == "TRACK" and solver.tracker) else (0.0, 0.0)
        frames.append(fr); targets.append(t); gts.append(gt_cursor(fr)); svels.append(v)
    cap.release()

    box = next((S.detect_play_box(f) for f in frames if S.detect_play_box(f) is not None), None)
    if box is None:
        print(f"{vid}: no box"); return
    x, y, w, h = box
    scale = 460.0 / w
    tw, th = int(w * scale), int(h * scale)
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, vid.replace(".mp4", "_velocity.mp4"))
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), 20, (tw, th))
    a, b = int(9.5 * fps), min(len(frames), int(22.6 * fps))
    for i in range(a, b):
        vis = frames[i][y:y + h, x:x + w].copy()
        gv = smoothed_velocity(gts, i)
        t, gt, sv = targets[i], gts[i], svels[i]
        if gt is not None:
            cv2.circle(vis, (int(gt[0] - x), int(gt[1] - y)), 10, (0, 255, 0), 2)
            arrow(vis, gt, gv, (0, 255, 0), x, y)
        if t is not None:
            cv2.circle(vis, (int(t[0] - x), int(t[1] - y)), 30, (0, 0, 255), 3)
            arrow(vis, t, sv, (0, 0, 255), x, y)
        ss = np.hypot(*sv); gs = np.hypot(*gv)
        cv2.rectangle(vis, (0, 0), (w, 30), (0, 0, 0), -1)
        cv2.putText(vis, f"{i/fps:4.1f}s  solver {ss:4.1f}px/f   truth {gs:4.1f}px/f",
                    (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        vw.write(cv2.resize(vis, (tw, th)))
    vw.release()
    print(f"{vid}: wrote {out}")


if __name__ == "__main__":
    for v in sorted(os.listdir(VID_DIR)):
        if v.endswith(".mp4"):
            run(v)
