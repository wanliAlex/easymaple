"""Demo video: previous solver vs the motion solver on one recording.

Panels (all cropped to the play-box):
  1. Previous solver (B-R plate + shape net), run under runtime conditions:
     the reticle on the shape is masked, as the live player masks its own.
  2. Motion solver (this work): runtime class + CursorPilot, our own cursor
     blanked.
  3. What the motion net sees: its per-frame evidence that "something here is
     not moving with the camouflage".
Green ring = the human's cursor (ground truth). Indicators turn green while a
solver's cursor is within 60 px of it. End card: coverage / end-lock.

Usage:
    python private_scripts/lie_detector/motion/demo.py CLIP [--out DIR] [--model PATH]
"""
import argparse
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
from common import LM, ROOT  # noqa: E402
from replay import replay, score, VID_DIR  # noqa: E402
from src.easymaple.detection import lie_detector_solver as S  # noqa: E402
from track_eval import metrics  # noqa: E402

TOL = 60
SCALE_P = 0.62
TRAIL = 18


def old_solver_masked(name, gt_frame):
    """Previous solver; the recorded reticle (on the shape) passed as its own
    cursor so it is masked exactly as the runtime masks its cursor."""
    cap = cv2.VideoCapture(os.path.join(VID_DIR, name + ".mp4"))
    solver = S.LieDetectorSolver(use_net=True)
    pilot, cur, last = None, [], None
    f = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        c = gt_frame[f] if f < len(gt_frame) and np.isfinite(gt_frame[f, 0]) else last
        if c is not None:
            last = c
        target = solver.process(fr, cursor_xy=None if c is None else tuple(c))
        desired = target if target is not None else solver.box_center
        if desired is not None and pilot is None:
            h, w = fr.shape[:2]
            pilot = S.CursorPilot((w / 2.0, h / 2.0))
        p = pilot.step(desired) if pilot is not None else None
        cur.append((np.nan, np.nan) if p is None else p)
        f += 1
    return np.array(cur)


def raw_cursor_frame(name, n):
    """Recorded reticle (uncleaned) in frame coords, for masking the old solver."""
    c = C.Clip(name)
    m = c.meta
    off = np.array([m["box"][0] + LM.BOX_MARGIN, m["box"][1] + LM.BOX_MARGIN], float)
    base = int(m["first"]) + int(m["w0"])
    out = np.full((n, 2), np.nan)
    for i in range(c.n):
        if 0 <= base + i < n and np.isfinite(m["cursor"][i, 0]):
            out[base + i] = m["cursor"][i] * LM.SCALE + off
    return out


def draw_cursor(img, p, col, trail):
    if p is None or not np.isfinite(p[0]):
        return
    trail.append((int(p[0]), int(p[1])))
    if len(trail) > TRAIL:
        trail.pop(0)
    for a, b in zip(trail, trail[1:]):
        cv2.line(img, a, b, col, 2)
    cv2.circle(img, trail[-1], 22, col, 2)
    cv2.circle(img, trail[-1], 3, col, -1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--out", default=os.path.join(ROOT, "training_data", "lie_detector", "demo"))
    ap.add_argument("--model", default=LM.MODEL_PATH)
    ap.add_argument("--q", type=float, default=3.0)
    ap.add_argument("--beta", type=float, default=2.0)
    a = ap.parse_args()
    name = a.clip.replace(".mp4", "")

    solver = LM.MotionLieDetectorSolver(a.model, tracker_kw=dict(q=a.q, beta=a.beta))
    new = replay(name, solver, keep_frames=True)
    sc = score(name, new)
    gt, s, e = sc["gt"], sc["s"], sc["e"]
    frames = new["frames"]
    old = old_solver_masked(name, raw_cursor_frame(name, len(frames)))
    m_old = metrics(old, gt, s, e, TOL); m_new = sc["m60"]

    c = C.Clip(name)
    x, y, w, h = [int(v) for v in c.meta["box"]]
    pad = 6
    x0, y0, x1, y1 = x - pad, y - pad, x + w + pad, y + h + pad
    pw, ph = int((x1 - x0) * SCALE_P), int((y1 - y0) * SCALE_P)
    head = 40
    W, H = 3 * pw + 2 * 6, ph + head + 26
    os.makedirs(a.out, exist_ok=True)
    out_path = os.path.join(a.out, name + "_motion_demo.mp4")
    vw = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), 30, (W, H))
    trails = [[], []]
    ev_last = None
    inner = (x + LM.BOX_MARGIN, y + LM.BOX_MARGIN)
    t_lo, t_hi = max(0, s - 75), min(len(frames), e + 45)
    for f in range(t_lo, t_hi):
        fr = frames[f]
        crop = fr[y0:y1, x0:x1]
        panels = []
        for k, (traj, col) in enumerate(((old, (0, 140, 255)), (new["cursor"], (255, 0, 255)))):
            img = crop.copy()
            g = gt[f]
            if np.isfinite(g[0]):
                cv2.circle(img, (int(g[0] - x0), int(g[1] - y0)), 30, (0, 255, 0), 2)
            p = traj[f] - np.array([x0, y0]) if np.isfinite(traj[f, 0]) else None
            draw_cursor(img, p, col, trails[k])
            panels.append(img)
        ev = new["evidence"][f]
        if ev is not None:
            ev_last = ev
        base = cv2.cvtColor(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        if ev_last is not None:
            evf = cv2.resize(ev_last, (w - 2 * LM.BOX_MARGIN, h - 2 * LM.BOX_MARGIN))
            heat = cv2.applyColorMap(np.clip(evf * 60 + 60, 0, 255).astype(np.uint8), cv2.COLORMAP_JET)
            ox, oy = inner[0] - x0, inner[1] - y0
            roi = base[oy:oy + heat.shape[0], ox:ox + heat.shape[1]]
            base[oy:oy + heat.shape[0], ox:ox + heat.shape[1]] = cv2.addWeighted(roi, 0.35, heat, 0.65, 0)
        if np.isfinite(gt[f, 0]):
            cv2.circle(base, (int(gt[f, 0] - x0), int(gt[f, 1] - y0)), 30, (0, 255, 0), 2)
        if np.isfinite(new["cursor"][f, 0]):
            cv2.circle(base, (int(new["cursor"][f, 0] - x0), int(new["cursor"][f, 1] - y0)), 22, (255, 0, 255), 2)
        panels.append(base)

        canvas = np.full((H, W, 3), 24, np.uint8)
        labels = ["Previous solver (runtime conditions)", "Motion solver (new)", "What the motion net sees"]
        active = s <= f < e
        for k, img in enumerate(panels):
            im = cv2.resize(img, (pw, ph), interpolation=cv2.INTER_AREA)
            ox = k * (pw + 6)
            canvas[head:head + ph, ox:ox + pw] = im
            cv2.putText(canvas, labels[k], (ox + 6, head + ph + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1)
            if k < 2 and active and np.isfinite(gt[f, 0]):
                traj = old if k == 0 else new["cursor"]
                on = np.isfinite(traj[f, 0]) and np.hypot(*(traj[f] - gt[f])) < TOL
                y0b = head + 6
                cv2.rectangle(canvas, (ox + pw - 96, y0b), (ox + pw - 6, y0b + 24), (60, 200, 60) if on else (60, 60, 220), -1)
                cv2.putText(canvas, "ON SHAPE" if on else "LOST", (ox + pw - 90, y0b + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        phase = "countdown" if f < s else ("tracking" if f < e else "SUCCESS")
        cv2.putText(canvas, f"{name}   t={f / 30:5.1f}s   {phase}   green ring = human cursor (ground truth)",
                    (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
        vw.write(canvas)
    # end card
    card = np.full((H, W, 3), 24, np.uint8)
    lines = [f"{name}   (scored START -> SUCCESS against the human cursor, 60 px)",
             "",
             f"Previous solver: coverage {100 * m_old['cov']:.0f}%   longest lock {m_old['longest']:.1f}s   "
             f"end-lock {100 * m_old['endlock']:.0f}%   {'LOCKED' if m_old['ok'] else 'LOST'} at end",
             f"Motion solver:   coverage {100 * m_new['cov']:.0f}%   longest lock {m_new['longest']:.1f}s   "
             f"end-lock {100 * m_new['endlock']:.0f}%   {'LOCKED' if m_new['ok'] else 'LOST'} at end"]
    for i, ln in enumerate(lines):
        cv2.putText(card, ln, (30, 80 + 40 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (240, 240, 240), 1)
    for _ in range(120):
        vw.write(card)
    vw.release()
    print(f"wrote {out_path}")
    print(f"old: {m_old}\nnew: {m_new}")


if __name__ == "__main__":
    main()
