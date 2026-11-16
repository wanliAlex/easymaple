"""Replay recordings through the RUNTIME solver (MotionLieDetectorSolver) with
the CursorPilot, exactly as the live player drives it — box detection, START
detection, reference handling and our own cursor blanked — and score the
piloted cursor against the human's cursor.

The recordings contain the human's reticle (blanked like any cursor) but not
ours, so our simulated cursor is passed in as ``cursor_xy`` and blanked too.
That makes this a conservative simulation: when we are off the shape, the
human's reticle still removes evidence at the true position.

Usage:
    python private_scripts/lie_detector/motion/replay.py [--split val|all] [--model PATH] [clips...]
"""
import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
from common import LM, ROOT  # noqa: E402
from src.easymaple.detection import lie_detector_solver as S  # noqa: E402
from src.easymaple.modules.lie_detector_player import _pilot_steps  # noqa: E402
from track_eval import metrics  # noqa: E402

VID_DIR = os.path.join(ROOT, "training_data", "lie_detector")


def replay(name, solver, keep_frames=False, hz=None, old_pilot=False, pilot_kw=None):
    """Run one clip. Returns dict with per-frame arrays in FRAME coordinates.

    ``hz`` simulates a slower live player: only frames at least 1/hz s after
    the last processed one are processed (the cursor holds in between, as the
    game would render it). Frame i is stamped i * FRAME_DT s — the clips'
    real rate (~24.6 fps, though the container says 30) — and the pilot steps
    every 1/30 s of that time, exactly as the live player does.
    """
    cap = cv2.VideoCapture(os.path.join(VID_DIR, name + ".mp4"))
    solver.reset()
    pilot = None
    rows = {"state": [], "target": [], "desired": [], "cursor": [], "ms": [], "processed": []}
    frames, evs = [], []
    cursor = None
    target = None
    last_t = None
    pilot_t = None
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        t_now = i * LM.FRAME_DT
        process = hz is None or last_t is None or t_now - last_t >= 1.0 / hz - 1e-6
        if process:
            t0 = time.perf_counter()
            target = solver.process(fr, cursor_xy=cursor, t=t_now)
            rows["ms"].append((time.perf_counter() - t0) * 1000)
            desired = target if target is not None else solver.box_center
            if desired is not None and pilot is None:
                h, w = fr.shape[:2]
                pilot = S.CursorPilot((w / 2.0, h / 2.0), **(pilot_kw or {}))
            if pilot is not None:
                # the pilot advances in 1/30 s steps, however sparse the frames
                if old_pilot:
                    n = 1
                else:
                    n, pilot_t = _pilot_steps(t_now, pilot_t, 1.0 / 30)
                for _ in range(n):
                    cursor = pilot.step(desired)
            last_t = t_now
        else:
            rows["ms"].append(np.nan)
        rows["processed"].append(process)
        rows["state"].append(solver.state)
        rows["target"].append((np.nan, np.nan) if target is None else target)
        rows["desired"].append((np.nan, np.nan) if not process or desired is None else desired)
        rows["cursor"].append((np.nan, np.nan) if cursor is None else cursor)
        if keep_frames:
            frames.append(fr)
            ev = getattr(solver, "last_evidence", None)
            evs.append(None if ev is None else ev.copy())
        i += 1
    cap.release()
    out = {k: np.array(v) for k, v in rows.items()}
    if keep_frames:
        out["frames"], out["evidence"] = frames, evs
    return out


def score(name, out):
    """Score the piloted cursor vs the human cursor over START..SUCCESS."""
    c = C.Clip(name)
    m = c.meta
    off = np.array([m["box"][0] + LM.BOX_MARGIN, m["box"][1] + LM.BOX_MARGIN], float)
    base = int(m["first"]) + int(m["w0"])          # frame index of cache index 0
    n = len(out["cursor"])
    gt = np.full((n, 2), np.nan)
    for i in range(c.n):
        if 0 <= base + i < n and np.isfinite(c.gt[i, 0]):
            gt[base + i] = c.gt[i] * LM.SCALE + off
    s, e = base + c.onset, base + c.end
    return dict(m60=metrics(out["cursor"], gt, s, e, 60), m80=metrics(out["cursor"], gt, s, e, 80),
                gt=gt, s=s, e=e)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="val")
    ap.add_argument("--model", default=LM.MODEL_PATH)
    ap.add_argument("--q", type=float, default=3.0)
    ap.add_argument("--beta", type=float, default=2.0)
    ap.add_argument("--hz", type=float, default=None, help="simulate a live player processing at most this many frames/s")
    ap.add_argument("--count-refs", action="store_true", help="old behaviour: reference frames by count, not time")
    ap.add_argument("--old-pilot", action="store_true", help="old behaviour: one pilot step per processed frame")
    ap.add_argument("--pilot", default="", help="CursorPilot overrides, e.g. speed=60,accel=12,kp=0.25")
    ap.add_argument("clips", nargs="*")
    a = ap.parse_args()
    names = a.clips or (C.split(C.clip_names())[1] if a.split == "val" else C.clip_names())
    solver = LM.MotionLieDetectorSolver(a.model, tracker_kw=dict(q=a.q, beta=a.beta),
                                        time_refs=not a.count_refs)
    pilot_kw = {k: float(v) for k, v in (kv.split("=") for kv in a.pilot.split(",") if kv)}
    rows = []
    for n in names:
        out = replay(n, solver, hz=a.hz, old_pilot=a.old_pilot, pilot_kw=pilot_kw)
        r = score(n, out)
        rows.append(r)
        ms = out["ms"][(np.array(out["state"]) == "TRACK") & out["processed"]]
        print(f"{n}: end60={r['m60']['endlock']:.2f} cov60={r['m60']['cov']:.2f} "
              f"longest={r['m60']['longest']:.1f}s  {'LOCKED' if r['m60']['ok'] else 'lost'}  "
              f"track ms/frame median {np.median(ms) if len(ms) else 0:.1f} p95 {np.percentile(ms, 95) if len(ms) else 0:.1f}",
              flush=True)
    print(f"\nREPLAY: clips={len(rows)} locked@60={sum(r['m60']['ok'] for r in rows)} "
          f"locked@80={sum(r['m80']['ok'] for r in rows)} cov60={np.mean([r['m60']['cov'] for r in rows]):.2f} "
          f"cov80={np.mean([r['m80']['cov'] for r in rows]):.2f} longest={np.mean([r['m60']['longest'] for r in rows]):.1f}s")
