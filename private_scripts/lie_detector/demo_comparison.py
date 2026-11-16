"""Side-by-side demo: classical tracker vs the net-fused tracker (the latest
solution) on one clip. Runs the production solver twice through eval_solver's
pipeline — identical frames, identical CursorPilot simulation — and renders a
single MP4 with both piloted cursors, a live ON SHAPE / LOST indicator per
panel, and an end card with the end-lock verdicts.

Usage:
    python private_scripts/lie_detector/demo_comparison.py [clip.mp4]
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_solver as E
from src.easymaple.detection import lie_detector_solver as S

CLIP = sys.argv[1] if len(sys.argv) > 1 else "2026-07-11_01-16-11.mp4"
TOL = 80                     # lock tolerance (px): live indicator + verdict
PAD = 10                     # crop padding around the play-box
LABEL_H = 30                 # per-panel label strip
HEADER_H = 44                # shared header bar
GAP = 6                      # gap between panels
END_CARD_S = 4.0             # end-card duration
TRAIL = 20                   # cursor-trail length (frames)

GT_COL = (0, 255, 0)
CUR_COL = (255, 0, 255)
ON_COL = (80, 220, 80)
OFF_COL = (60, 60, 255)


def crop_rect(frames):
    box = None
    for fr in frames:
        box = S.detect_play_box(fr)
        if box:
            break
    if box is None:
        raise SystemExit(f"{CLIP}: no play-box found")
    x, y, w, h = box
    return max(0, x - PAD), max(0, y - PAD), x + w + PAD, y + h + PAD


def panel(fr, row, rect, trail, active):
    """Render one tracker's view: ground truth, piloted cursor + trail, and a
    live lock indicator (only meaningful once the puzzle is active)."""
    x0, y0, x1, y1 = rect
    vis = fr[y0:y1, x0:x1].copy()
    _, state, _, cur, gt = row
    if gt is not None:
        cv2.circle(vis, (int(gt[0] - x0), int(gt[1] - y0)), 9, GT_COL, 2)
    if cur is not None:
        trail.append((int(cur[0] - x0), int(cur[1] - y0)))
        if len(trail) > TRAIL:
            trail.pop(0)
        for a, b in zip(trail, trail[1:]):
            cv2.line(vis, a, b, CUR_COL, 1)
        cv2.circle(vis, trail[-1], 26, CUR_COL, 2)
        cv2.circle(vis, trail[-1], 4, CUR_COL, -1)
    if active and state in ("ACQUIRE", "TRACK") and cur is not None and gt is not None:
        on = np.hypot(cur[0] - gt[0], cur[1] - gt[1]) < TOL
        txt, col = ("ON SHAPE", ON_COL) if on else ("LOST", OFF_COL)
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
        bx = vis.shape[1] - tw - 16
        cv2.rectangle(vis, (bx - 8, 8), (bx + tw + 8, 18 + th), (0, 0, 0), -1)
        cv2.putText(vis, txt, (bx, 12 + th), cv2.FONT_HERSHEY_SIMPLEX, 0.65, col, 2)
    return vis


def label_strip(width, text):
    strip = np.full((LABEL_H, width, 3), 28, np.uint8)
    cv2.putText(strip, text, (10, LABEL_H - 9), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (255, 255, 255), 1)
    return strip


def compose(left, right, t, w_total, plain=False):
    """Full frame from the two panels; ``plain`` skips the header text and
    legend so the end card gets a clean background."""
    header = np.full((HEADER_H, w_total, 3), 16, np.uint8)
    if not plain:
        cv2.putText(header, f"Lie Detector: classical vs net-fused tracker  |  "
                            f"held-out clip {CLIP.replace('.mp4', '')}  |  t={t:5.1f}s",
                    (10, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 220, 255), 1)
    body = np.hstack([left, np.full((left.shape[0], GAP, 3), 16, np.uint8), right])
    frame = np.vstack([header, body])
    if not plain:
        cv2.putText(frame, "green=shape (human ground truth)   magenta=our piloted cursor",
                    (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 1)
    return frame


def end_card(base_frame, m_cl, m_net):
    card = (base_frame.astype(np.float32) * 0.22).astype(np.uint8)
    h, w = card.shape[:2]
    cv2.putText(card, "VERDICT (final second of the puzzle)", (w // 2 - 250, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    for i, (name, m) in enumerate([("Classical tracker", m_cl),
                                   ("Net-fused (latest)", m_net)]):
        x = 60 + i * (w // 2)
        ok = m["locked_at_end"]
        col = ON_COL if ok else OFF_COL
        cv2.putText(card, name, (x, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                    (255, 255, 255), 2)
        cv2.putText(card, f"LOCKED AT END: {'YES' if ok else 'NO'}", (x, 175),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, col, 2)
        cv2.putText(card, f"end-lock: {100 * m['endlock']:.0f}%   "
                          f"longest lock: {m['longest_s']:.1f}s", (x, 215),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 220, 220), 1)
    cv2.putText(card, f"on the shape >=50% of the final ~1s, {TOL}px tolerance",
                (60, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (170, 170, 170), 1)
    return card


def main():
    print(f"running classical pass on {CLIP} ...")
    frames, rows_cl, fps = E.run(CLIP, use_net=False)
    print("running net-fused pass ...")
    _, rows_net, _ = E.run(CLIP, use_net=True)

    stats = {}
    for name, rows in (("classical", rows_cl), ("net-fused", rows_net)):
        m = E.metrics(rows, tol=TOL)
        m["longest_s"] = m["longest"] / fps
        stats[name] = m
        m60 = E.metrics(rows, tol=60)
        print(f"  {name:9s}: locked_at_end={m['locked_at_end']}  "
              f"endlock@{TOL}={100 * m['endlock']:.0f}%  @60={100 * m60['endlock']:.0f}%  "
              f"longest={m['longest_s']:.1f}s @{TOL}px ({m60['longest'] / fps:.1f}s @60px)")

    rect = crop_rect(frames)
    puzzle_start = E.puzzle_start_index(rows_cl)
    puzzle_end = E.puzzle_end_index(rows_cl)
    start = max(0, puzzle_start - int(2 * fps))
    end = min(len(frames), puzzle_end + int(0.5 * fps))
    pw, ph = rect[2] - rect[0], rect[3] - rect[1]
    w_total = pw * 2 + GAP
    h_total = HEADER_H + LABEL_H + ph

    out = os.path.join(E.OUT_DIR, CLIP.replace(".mp4", "_comparison.mp4"))
    os.makedirs(E.OUT_DIR, exist_ok=True)
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w_total, h_total))

    tr_cl, tr_net = [], []
    snap = None                       # last active-puzzle frame -> end-card base
    snap_idx = min(end, puzzle_end) - 1
    for i in range(start, end):
        active = i >= puzzle_start
        left = np.vstack([label_strip(pw, "Classical tracker"),
                          panel(frames[i], rows_cl[i], rect, tr_cl, active)])
        right = np.vstack([label_strip(pw, "Net-fused (latest)"),
                           panel(frames[i], rows_net[i], rect, tr_net, active)])
        vw.write(compose(left, right, i / fps, w_total))
        if i == snap_idx:
            snap = compose(left, right, i / fps, w_total, plain=True)
    card = end_card(snap, stats["classical"], stats["net-fused"])
    for _ in range(int(END_CARD_S * fps)):
        vw.write(card)
    vw.release()
    print(f"wrote {out}  ({w_total}x{h_total}, {(end - start) / fps + END_CARD_S:.1f}s)")


if __name__ == "__main__":
    main()
