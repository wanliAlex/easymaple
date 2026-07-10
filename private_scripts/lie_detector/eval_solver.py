"""Offline evaluation + demo renderer for LieDetectorSolver.

Runs the production solver over recorded mini-game clips and simulates the
runtime cursor: solver targets are fed through the same CursorPilot the live
player uses (park at the box centre during the countdown, then glide after the
shape — bounded speed/acceleration, no teleports). Scoring is on the PILOTED
CURSOR, because that is what the game sees; the raw tracker target is reported
alongside for reference. Renders a demo video showing both.

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

# Clips recorded while the BOT was playing: their green reticle is our own
# cursor, not a human's — there is no ground truth. Rendered, never scored,
# and never used as training labels.
BOT_PLAYED = {"2026-07-10_14-34-09.mp4", "2026-07-10_20-48-16.mp4"}


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


def run(vid, mask_own_cursor=False, use_net=True):
    """Run the solver + pilot over a clip.

    ``mask_own_cursor`` passes the simulated pilot position into the solver as
    ``cursor_xy`` — ONLY correct for bot-played clips. On human-played clips
    the shape already carries the human's (green-masked) reticle hole; the
    virtual pilot rides the same shape, so masking it too would punch a second
    hole runtime never sees and misread the recordings.

    ``use_net`` runs the deployment config (learned detector fused into the
    smoother); it degrades to classical automatically if weights are missing.
    """
    cap = cv2.VideoCapture(os.path.join(VID_DIR, vid))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    solver = S.LieDetectorSolver(use_net=use_net)
    pilot = None
    rows = []          # (frame_idx, state, target, cursor, gt)
    frames = []
    f = 0
    cursor = None
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        # Same policy as the live player: park at the box centre until there
        # is a shape to follow, then chase the tracker's target.
        target = solver.process(fr, cursor_xy=cursor if mask_own_cursor else None)
        desired = target if target is not None else solver.box_center
        if desired is not None and pilot is None:
            h, w = fr.shape[:2]
            pilot = S.CursorPilot((w / 2.0, h / 2.0))   # glide in from mid-screen
        cursor = pilot.step(desired) if pilot is not None else None
        gt = gt_cursor(fr)
        rows.append((f, solver.state, target, cursor, gt))
        frames.append(fr)
        f += 1
    cap.release()
    return frames, rows, fps


def puzzle_start_index(rows):
    """First frame where the puzzle really starts: the ground-truth cursor has
    moved away from its stationary prep position. Validation before this is
    meaningless (the shape just sits still)."""
    gts = [r[-1] for r in rows if r[-1] is not None]
    if len(gts) < 10:
        return 0
    base = np.median(np.array(gts[:15]), axis=0)   # stationary prep position
    for i, r in enumerate(rows):
        gt = r[-1]
        if gt is not None and np.hypot(gt[0] - base[0], gt[1] - base[1]) > 30:
            return i
    return 0


def puzzle_end_index(rows):
    """End of the ACTIVE puzzle: the last frame the shape still moved within the
    FIRST continuous ground-truth run. A sustained (>=15 frame) absence of the
    green cursor means the box/shape vanished (the game ended) — anything after
    it (a stray second box in a recording, the post-success banner) is ignored,
    and the trailing stationary stretch is dropped by taking the last movement."""
    run_end, gap, started, last_present = len(rows), 0, False, 0
    for i, r in enumerate(rows):
        if r[-1] is not None:
            started, gap, last_present = True, 0, i
        elif started:
            gap += 1
            if gap >= 15:
                run_end = last_present + 1
                break
    last_move, prev = 0, None
    for i in range(min(run_end, len(rows))):
        gt = rows[i][-1]
        if gt is None:
            continue
        if prev is not None and np.hypot(gt[0] - prev[0], gt[1] - prev[1]) > 3:
            last_move = i
        prev = gt
    return last_move + 1


def metrics(rows, tol=60, end_frames=30, col=3):
    """End-focused tracking metrics over the ACTIVE moving/fading phase. The
    mini-game is passed by following the shape *to the end*, so a high average is
    meaningless if the lock is lost at the finish. We therefore report, besides
    coverage, the **longest unbroken locked run** and **locked_at_end** — whether
    the cursor is on the shape over the final ``end_frames`` (~1 s) of the puzzle.

    ``col`` picks what is scored: 3 = the piloted cursor (what the game sees,
    the default), 2 = the raw tracker target (reference).
    """
    start = puzzle_start_index(rows)
    end = puzzle_end_index(rows)
    on = []
    for state, t, gt in ((r[1], r[col], r[-1]) for r in rows[start:min(end, len(rows))]):
        if state in ("ACQUIRE", "TRACK") and t is not None and gt is not None:
            on.append(np.hypot(t[0] - gt[0], t[1] - gt[1]) < tol)
    on = np.array(on, bool)
    if on.size == 0:
        return dict(n=0, coverage=0.0, longest=0, endlock=0.0, locked_at_end=False)
    best = run = 0
    for v in on:
        run = run + 1 if v else 0
        best = max(best, run)
    endlock = float(on[-end_frames:].mean())
    return dict(n=int(on.size), coverage=float(on.mean()), longest=int(best),
                endlock=endlock, locked_at_end=bool(endlock >= 0.5))


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
    trail = []
    for (fi, state, t, cur, gt), fr in zip(rows, frames):
        vis = fr[y0:y1, x0:x1].copy()
        if gt is not None:
            cv2.circle(vis, (int(gt[0] - x0), int(gt[1] - y0)), 9, (0, 255, 0), 2)
        if t is not None:
            c = (int(t[0] - x0), int(t[1] - y0))
            col = (0, 165, 255) if state == "ACQUIRE" else (0, 0, 255)
            cv2.drawMarker(vis, c, col, cv2.MARKER_CROSS, 18, 2)
        if cur is not None:
            trail.append((int(cur[0] - x0), int(cur[1] - y0)))
            if len(trail) > 20:
                trail.pop(0)
            for a, b in zip(trail, trail[1:]):      # recent path: shows the glide
                cv2.line(vis, a, b, (255, 0, 255), 1)
            cv2.circle(vis, trail[-1], 26, (255, 0, 255), 2)
            cv2.circle(vis, trail[-1], 4, (255, 0, 255), -1)
        cv2.putText(vis, f"{fi/fps:4.1f}s  {state}", (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(vis, "magenta=our cursor  cross=raw solver  green=ground truth",
                    (8, vis.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 1)
        vw.write(vis)
        if fi in montage_at:
            montage_cells.append(cv2.resize(vis, (300, 240)))
    vw.release()
    rowsimg = [np.hstack(montage_cells[i:i + 4]) for i in range(0, len(montage_cells), 4)]
    wmax = max(r.shape[1] for r in rowsimg)
    rowsimg = [np.pad(r, ((0, 0), (0, wmax - r.shape[1]), (0, 0))) for r in rowsimg]
    cv2.imwrite(os.path.join(OUT_DIR, vid.replace(".mp4", "_montage.png")), np.vstack(rowsimg))
    print(f"{vid}: wrote {out} and montage")


def cursor_motion(rows):
    """Max / p95 per-frame cursor step (px) — the human-motion check: the max
    must stay at or under S.PILOT_SPEED, with no teleports."""
    pts = [r[3] for r in rows if r[3] is not None]
    if len(pts) < 2:
        return 0.0, 0.0
    steps = np.linalg.norm(np.diff(np.array(pts), axis=0), axis=1)
    return float(steps.max()), float(np.percentile(steps, 95))


if __name__ == "__main__":
    summary = []
    for vid in sorted(os.listdir(VID_DIR)):
        if not vid.endswith(".mp4"):
            continue
        frames, rows, fps = run(vid, mask_own_cursor=vid in BOT_PLAYED)
        if vid in BOT_PLAYED:
            print(f"\n=== {vid} === (bot-played: no ground truth, render only)")
            render(vid, frames, rows, fps)
            continue
        m60 = metrics(rows, tol=60)                    # piloted cursor (the game's view)
        m80 = metrics(rows, tol=80)
        raw80 = metrics(rows, tol=80, col=2)           # raw tracker, reference
        smax, s95 = cursor_motion(rows)
        print(f"\n=== {vid} ===")
        print(f"  active puzzle frames scored: {m60['n']}")
        print(f"  CURSOR LOCKED AT END: {'YES' if m80['locked_at_end'] else 'NO'}  "
              f"(endlock@60={100*m60['endlock']:.0f}%  @80={100*m80['endlock']:.0f}%  "
              f"raw-solver@80={100*raw80['endlock']:.0f}%)")
        print(f"  longest unbroken lock: {m60['longest']/fps:.1f}s @60px  "
              f"({m80['longest']/fps:.1f}s @80px)")
        print(f"  coverage: {100*m60['coverage']:.0f}% @60px  {100*m80['coverage']:.0f}% @80px")
        print(f"  cursor motion: max {smax:.1f} px/frame (cap {S.PILOT_SPEED})  p95 {s95:.1f}")
        summary.append((vid, m80['locked_at_end'], raw80['locked_at_end'],
                        m80['endlock'], m80['longest'] / fps, smax))
        render(vid, frames, rows, fps)

    print("\n================= SUMMARY (piloted cursor) =================")
    for vid, lock, raw_lock, endlock, longest, smax in summary:
        flag = "OK " if lock else ("~  " if raw_lock else "X  ")
        print(f"  {flag} {vid}: end-lock {'YES' if lock else 'NO '} "
              f"(raw {'YES' if raw_lock else 'NO '}) endlock@80={100*endlock:3.0f}%  "
              f"longest={longest:4.1f}s  maxstep={smax:4.1f}")
    n = len(summary)
    print(f"\n  locked at end: {sum(1 for s in summary if s[1])}/{n} cursor, "
          f"{sum(1 for s in summary if s[2])}/{n} raw solver")
    print(f"  mean endlock@80: {100 * np.mean([s[3] for s in summary]):.0f}%")
    print(f"  max cursor step anywhere: {max(s[5] for s in summary):.1f} px/frame "
          f"(cap {S.PILOT_SPEED})")
