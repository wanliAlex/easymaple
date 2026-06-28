"""Offline evaluation + demo renderer for LieDetectorSolver.

Runs the production solver over recorded mini-game clips, scores its target
against the in-game green cursor (ground truth), and renders a demo video with
a red circle showing the solution following the shape.

Usage:
    python private_scripts/lie_detector/eval_solver.py
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.easymaple.detection import lie_detector_solver as S

VID_DIR = "training_data/lie_detector"
OUT_DIR = "training_data/lie_detector/demo"


def gt_cursor(frame_bgr):
    """Ground-truth green-cursor centroid in frame coords, or None."""
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


def run(vid):
    cap = cv2.VideoCapture(os.path.join(VID_DIR, vid))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    solver = S.LieDetectorSolver()
    rows = []          # (frame_idx, state, target, gt)
    frames = []
    f = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        target = solver.process(fr)
        gt = gt_cursor(fr)
        rows.append((f, solver.state, target, gt))
        frames.append(fr)
        f += 1
    cap.release()
    return frames, rows, fps


def puzzle_start_index(rows):
    """First frame where the puzzle really starts: the ground-truth cursor has
    moved away from its stationary prep position. Validation before this is
    meaningless (the shape just sits still)."""
    gts = [gt for _, _, _, gt in rows if gt is not None]
    if len(gts) < 10:
        return 0
    base = np.median(np.array(gts[:15]), axis=0)   # stationary prep position
    for i, (_, _, _, gt) in enumerate(rows):
        if gt is not None and np.hypot(gt[0] - base[0], gt[1] - base[1]) > 30:
            return i
    return 0


def metrics(rows, tol=60):
    """Continuous-coverage metrics over the moving/fading phase. Mean error is
    misleading (tracking well early then losing it still scores fine), so we
    report how much of the puzzle stays locked and the longest unbroken locked
    run — what actually matters for accumulating dwell time to pass."""
    start = puzzle_start_index(rows)
    on = []
    for _, state, t, gt in rows[start:]:
        if state in ("ACQUIRE", "TRACK") and t is not None and gt is not None:
            on.append(np.hypot(t[0] - gt[0], t[1] - gt[1]) < tol)
    on = np.array(on, bool)
    if on.size == 0:
        return dict(n=0, coverage=0.0, longest=0, locked_at_end=False)
    best = run = 0
    for v in on:
        run = run + 1 if v else 0
        best = max(best, run)
    return dict(n=int(on.size), coverage=float(on.mean()),
                longest=int(best), locked_at_end=bool(on[-15:].mean() > 0.5))


def render(vid, frames, rows, fps):
    os.makedirs(OUT_DIR, exist_ok=True)
    # Crop to a generous region around the play-box for a clear demo.
    box = None
    for fr in frames:
        box = S.detect_play_box(fr)
        if box:
            break
    if box is None:
        print(f"{vid}: no box; skipping render")
        return
    x, y, w, h = box
    pad = 10
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = x + w + pad, y + h + pad
    out = os.path.join(OUT_DIR, vid.replace(".mp4", "_demo.mp4"))
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (x1 - x0, y1 - y0))
    montage_cells = []
    montage_at = set(np.linspace(0, len(frames) - 1, 12).astype(int))
    for (fi, state, t, gt), fr in zip(rows, frames):
        vis = fr[y0:y1, x0:x1].copy()
        if gt is not None:
            cv2.circle(vis, (int(gt[0] - x0), int(gt[1] - y0)), 9, (0, 255, 0), 2)
        if t is not None:
            c = (int(t[0] - x0), int(t[1] - y0))
            col = (0, 165, 255) if state == "ACQUIRE" else (0, 0, 255)
            cv2.circle(vis, c, 34, col, 2)
            cv2.drawMarker(vis, c, col, cv2.MARKER_CROSS, 22, 2)
        cv2.putText(vis, f"{fi/fps:4.1f}s  {state}", (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(vis, "red=solver  green=ground-truth cursor", (8, vis.shape[0] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        vw.write(vis)
        if fi in montage_at:
            montage_cells.append(cv2.resize(vis, (300, 240)))
    vw.release()
    rowsimg = [np.hstack(montage_cells[i:i + 4]) for i in range(0, len(montage_cells), 4)]
    wmax = max(r.shape[1] for r in rowsimg)
    rowsimg = [np.pad(r, ((0, 0), (0, wmax - r.shape[1]), (0, 0))) for r in rowsimg]
    cv2.imwrite(os.path.join(OUT_DIR, vid.replace(".mp4", "_montage.png")), np.vstack(rowsimg))
    print(f"{vid}: wrote {out} and montage")


if __name__ == "__main__":
    for vid in sorted(os.listdir(VID_DIR)):
        if not vid.endswith(".mp4"):
            continue
        frames, rows, fps = run(vid)
        m60 = metrics(rows, tol=60)
        m80 = metrics(rows, tol=80)
        print(f"\n=== {vid} ===")
        print(f"  puzzle frames scored: {m60['n']}")
        print(f"  within 60px: coverage={100*m60['coverage']:.0f}%  "
              f"longest locked run={m60['longest']}/{m60['n']} "
              f"({m60['longest']/fps:.1f}s)  locked_at_end={m60['locked_at_end']}")
        print(f"  within 80px: coverage={100*m80['coverage']:.0f}%  "
              f"longest locked run={m80['longest']}/{m80['n']} ({m80['longest']/fps:.1f}s)")
        render(vid, frames, rows, fps)
