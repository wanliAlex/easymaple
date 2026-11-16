"""Closed-loop evaluation of a model / solver variant — the ship rule's tool
(FINDINGS §11-12). One run per box perturbation (``--jit``); run 5
(0,0 1,0 -1,0 0,1 0,-1) and compare with ``evcmp.py``.

  ev.py heldout OUT.jsonl --model M --jit=dx,dy [opts]
      the 46 held-out human clips through the runtime solver + pilot
      (replay.py), scored against the human reticle (full-field cache GT),
      from the first cache's onsets to SUCCESS.
  ev.py live OUT.jsonl --model M --jit=dx,dy --own [opts]
      the user-labelled live games (``*_gt1.npz``): our own simulated cursor is
      blanked (``--own``; without it the live bot's logged cursor is, which is
      unfair to anything that leaves the shipped bot's path), scored as the
      piloted cursor vs the labels (c60/c80/end60) from START to the game's end
      (``eval/live_end.json``, written by ``game_end.py``).

Solver options: the runtime's defaults unless overridden — ``--legacy`` (the
solver before 2026-10-14: no ClutterBackground, no DEN_FLOOR), ``--prev`` (the
solver of 2026-10-14..28: clutter 0.5 s / 0.5, no wall floor), ``--clutter
TAU,K``, ``--den-floor X``, ``--wall-floor X``, ``--window`` / ``--nowin`` (force the alignment),
``--tkw`` (GridTracker); prototypes in ``ens.py``: comma-separated
``--model`` (ensemble), ``--tta``, ``--bg``.
Feed options: ``--feed60`` (60 Hz capture: every frame twice), ``--hz``
(a slower player), ``--pos`` (heldout: store positions for ``evcmp.py lag``).
Results go wherever OUT points; ``evcmp.py`` reads ``training_data/lie_detector/eval``.
"""
import argparse
import glob
import json
import os
import sys
from datetime import datetime, timedelta

import cv2
import numpy as np

ROOT = os.environ.get("LD_ROOT") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "private_scripts", "lie_detector", "motion"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
from common import LM  # noqa: E402
import replay as RP  # noqa: E402

VID = os.path.join(ROOT, "training_data", "lie_detector")
_le = os.path.join(VID, "eval", "live_end.json")
LIVE_END = json.load(open(_le)) if os.path.exists(_le) else {}


def make_solver(model, window, jit, tkw=None, own_hole=True, wts=None, tta=1, bg=None, bg_mode="ema", bg_excl=0.0, bg_uexcl=0.0,
                clutter=None, den_floor=None, wall_floor=None):
    if "," in model or tta > 1 or bg:  # ensemble: evidence averaged over nets / flips; clutter suppression
        from ens import EnsembleSolver
        bg_tau, bg_k = bg or (0.0, 0.0)
        solver = EnsembleSolver(model.split(","), weights=wts, tta=tta, bg_tau=bg_tau, bg_k=bg_k,
                                bg_mode=bg_mode, bg_excl=bg_excl, bg_uexcl=bg_uexcl,
                                den_floor=den_floor, wall_floor=wall_floor, tracker_kw=tkw)
    else:
        # the runtime solver (clutter: None = the runtime default)
        solver = LM.MotionLieDetectorSolver(model, tracker_kw=tkw, clutter=clutter, den_floor=den_floor,
                                            wall_floor=wall_floor)
    if not own_hole:                 # diagnostic: never blank our own cursor
        proc = solver.process
        solver.process = lambda fr, cursor_xy=None, t=None: proc(fr, cursor_xy=None, t=t)
    if window is not None:           # force an alignment mode (default: as the net was trained)
        solver.pc_window = window
    if jit != (0, 0):
        orig = solver._lock
        solver._lock = lambda b: orig((b[0] + jit[0], b[1] + jit[1], b[2], b[3]))
    return solver


def heldout(a, solver, out):
    names = a.clips or C.split(C.clip_names())[1]
    from track_eval import metrics
    old_cache = os.path.join(VID, "motion_cache")
    for n in names:
        o = RP.replay(n, solver, hz=a.hz)
        r = RP.score(n, o)
        # Score from the first cache's onset (every earlier number did); the
        # unwindowed onset is often seconds earlier, in the countdown pan.
        om = np.load(os.path.join(old_cache, n + ".meta.npz"))
        s = int(om["first"]) + int(om["w0"]) + int(om["onset"])
        m60 = metrics(o["cursor"], r["gt"], s, r["e"], 60)
        m80 = metrics(o["cursor"], r["gt"], s, r["e"], 80)
        rec = dict(clip=n, cov60=m60["cov"], cov80=m80["cov"], end60=m60["endlock"],
                   ok60=bool(m60["ok"]), ok80=bool(m80["ok"]), longest=m60["longest"],
                   cov60_all=r["m60"]["cov"], s_old=s, s_new=int(r["s"]))
        cur, gt = o["cursor"], r["gt"]
        rec["d"] = [None if not (np.isfinite(gt[i, 0]) and np.isfinite(cur[i, 0])) else round(float(np.hypot(*(cur[i] - gt[i]))), 1)
                    for i in range(s, r["e"])]
        if a.pos:                    # positions, for lag-shifted re-scoring
            rec["cur"] = [[None if not np.isfinite(v) else round(float(v), 1) for v in cur[i]] for i in range(s, r["e"])]
            rec["gtp"] = [[None if not np.isfinite(v) else round(float(v), 1) for v in gt[i]] for i in range(max(0, s - 20), min(len(gt), r["e"] + 20))]
            rec["gt0"] = max(0, s - 20)
        out.write(json.dumps(rec) + "\n"); out.flush()
        print(n, rec["cov60"], rec["ok60"], flush=True)


def labelled_games():
    """(clip, labels, log) for every bot game the user labelled."""
    for gt in sorted(glob.glob(os.path.join(VID, "*_gt*.npz"))):
        if gt.endswith("_cmp.npz"):
            continue
        clip = gt[:gt.rindex("_gt")] + ".mp4"
        cs = datetime.strptime(os.path.basename(clip)[:19], "%Y-%m-%d_%H-%M-%S")
        for log in sorted(glob.glob(os.path.join(VID, "solver_logs", "*.npz"))):
            s = datetime.strptime(os.path.basename(log)[:19], "%Y-%m-%d_%H-%M-%S")
            if cs <= s <= cs + timedelta(seconds=60):
                yield clip, gt, log
                break
        else:                        # games from before solver logs: no logged cursor
            yield clip, gt, None


def live(a, solver, out):
    from src.easymaple.detection import lie_detector_solver as S
    from src.easymaple.modules.lie_detector_player import _pilot_steps
    for clip, gtp, logp in labelled_games():
        if a.clips and os.path.basename(clip)[:19] not in [c[:19] for c in a.clips]:
            continue
        g = np.load(gtp, allow_pickle=True)
        if logp is not None:
            d = np.load(logp, allow_pickle=True)
            lt = d["t"] - d["t"][0]
            bot = d["bot"]; ok = np.isfinite(bot[:, 0])
        tp = clip[:-4] + "_t.npy"
        ct = np.load(tp) if os.path.exists(tp) else np.arange(100000) * LM.FRAME_DT
        ct = ct - ct[0]
        solver.reset()
        cap = cv2.VideoCapture(clip)
        T, TG, ST, CU = [], [], [], []
        pilot, pilot_t, own = None, None, None
        last_proc = None
        k = 0
        while True:
            good, fr = cap.read()
            if not good:
                break
            t = ct[k]
            cur = None
            if a.own:
                # our own (simulated) cursor is blanked, as in a live run of this
                # solver; the live bot's rendered reticle is blanked by detection
                cur = own
            elif logp is not None and lt[ok][0] <= t <= lt[ok][-1]:
                cur = (float(np.interp(t, lt[ok], bot[ok, 0])), float(np.interp(t, lt[ok], bot[ok, 1])))
            # --feed60: a 60 Hz capture of the stream sees every frame twice, 1/60 s apart
            feeds = [t]
            if a.hz and last_proc is not None and t - last_proc < 1.0 / a.hz - 1e-6:
                feeds = []                     # a slower player: this frame is never seen
            else:
                last_proc = t
            if a.feed60 and k + 1 < len(ct) and ct[k + 1] - t > 1.0 / 60 + 1e-3:
                feeds.append(t + 1.0 / 60)
            for tf in feeds:
                if a.own:
                    cur = own
                tg = solver.process(fr, cursor_xy=cur, t=tf)
                if a.own:
                    desired = tg if tg is not None else solver.box_center
                    if desired is not None and pilot is None:
                        h, w = fr.shape[:2]
                        pilot = S.CursorPilot((w / 2.0, h / 2.0))
                    if pilot is not None:
                        n, pilot_t = _pilot_steps(tf, pilot_t, 1.0 / 30)
                        for _ in range(n):
                            own = pilot.step(desired)
            T.append(t); ST.append(solver.state)
            TG.append((np.nan, np.nan) if tg is None else tg)
            CU.append((np.nan, np.nan) if own is None else own)
            k += 1
        T = np.array(T); TG = np.array(TG, float); ST = np.array(ST); CU = np.array(CU, float)
        gx = np.interp(T, g["t"], g["xy"][:, 0]); gy = np.interp(T, g["t"], g["xy"][:, 1])
        tr = np.flatnonzero(ST == "TRACK")
        t_end = min(float(g["t"][-1]), LIVE_END.get(os.path.basename(clip)[:19]) or 1e9)   # SUCCESS / game over
        m = (T >= T[tr[0]]) & (T <= t_end) & np.isfinite(TG[:, 0]) if len(tr) else np.zeros(len(T), bool)
        dd = np.hypot(TG[m, 0] - gx[m], TG[m, 1] - gy[m])
        rec = dict(clip=os.path.basename(clip), gt=os.path.basename(gtp), on60=float((dd < 60).mean()),
                   on80=float((dd < 80).mean()), med=float(np.median(dd)), box=solver.box,
                   jit=a.jit, own=bool(a.own), tt=[round(float(v), 3) for v in T[m]], dd=[round(float(v), 1) for v in dd],
                   tg=[[round(float(v), 1) for v in p] for p in TG[m]])
        if a.own:
            mc = m & np.isfinite(CU[:, 0])
            dc = np.hypot(CU[mc, 0] - gx[mc], CU[mc, 1] - gy[mc])
            tl = T[mc]
            last = tl >= t_end - 1.0
            rec.update(c60=float((dc < 60).mean()), c80=float((dc < 80).mean()),
                       end60=float((dc[last] < 60).mean()), dc=[round(float(v), 1) for v in dc])
        out.write(json.dumps(rec) + chr(10)); out.flush()
        print({k: v for k, v in rec.items() if k not in ("tt", "dd", "tg", "dc")}, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["heldout", "live"])
    ap.add_argument("out")
    ap.add_argument("--model", default=LM.MODEL_PATH)
    ap.add_argument("--window", action="store_true", help="force Hanning-windowed alignment")
    ap.add_argument("--nowin", action="store_true", help="force unwindowed alignment")
    ap.add_argument("--jit", default="0,0")
    ap.add_argument("--tkw", default="{}", help="GridTracker overrides (JSON)")
    ap.add_argument("--no-own-hole", action="store_true", help="diagnostic: do not blank our cursor")
    ap.add_argument("--wts", default=None, help="ensemble weights, comma-separated")
    ap.add_argument("--hz", type=float, default=None, help="process at most this many frames/s (slow live player)")
    ap.add_argument("--feed60", action="store_true", help="live: feed every frame twice, 1/60 s apart (60 Hz capture)")
    ap.add_argument("--pos", action="store_true", help="heldout: store cursor and human positions")
    ap.add_argument("--own", action="store_true", help="live: simulate and blank our own cursor (not the logged one)")
    ap.add_argument("--bg", default=None, help="static-clutter suppression TAU,K (s, weight)")
    ap.add_argument("--bg-mode", default="ema", choices=["ema", "min"])
    ap.add_argument("--legacy", action="store_true",
                    help="the solver before 2026-10-14: no ClutterBackground, no DEN_FLOOR")
    ap.add_argument("--prev", action="store_true",
                    help="the solver of 2026-10-14..28: ClutterBackground 0.5 s / 0.5, DEN_FLOOR 0.4, no wall floor")
    ap.add_argument("--clutter", default=None, help="ClutterBackground TAU,K (default: the runtime's)")
    ap.add_argument("--den-floor", type=float, default=None, help="evidence DEN_FLOOR (default: the runtime's)")
    ap.add_argument("--wall-floor", type=float, default=None, help="evidence WALL_FLOOR (default: the runtime's; 0 = none)")
    ap.add_argument("--bg-uexcl", type=float, default=0.0, help="no background update within this many half-res px of the estimate")
    ap.add_argument("--bg-excl", type=float, default=0.0, help="no suppression within this many half-res px of the estimate")
    ap.add_argument("--tta", type=int, default=1, help="flip test-time augmentation: 1, 2 or 4 passes")
    ap.add_argument("clips", nargs="*")
    a = ap.parse_args()
    jit = tuple(int(v) for v in a.jit.split(","))
    if a.legacy:
        a.clutter = a.clutter or "0,0"
        a.den_floor = 0.0 if a.den_floor is None else a.den_floor
    if a.legacy or a.prev:
        a.clutter = a.clutter or "0.5,0.5"
        a.wall_floor = 0.0 if a.wall_floor is None else a.wall_floor
    solver = make_solver(a.model, True if a.window else (False if a.nowin else None), jit, json.loads(a.tkw), own_hole=not a.no_own_hole,
                         wts=[float(v) for v in a.wts.split(",")] if a.wts else None, tta=a.tta,
                         bg=tuple(float(v) for v in a.bg.split(",")) if a.bg else None,
                         bg_mode=a.bg_mode, bg_excl=a.bg_excl, bg_uexcl=a.bg_uexcl,
                         clutter=tuple(float(v) for v in a.clutter.split(",")) if a.clutter else None,
                         den_floor=a.den_floor, wall_floor=a.wall_floor)
    with open(a.out, "a") as out:
        (heldout if a.mode == "heldout" else live)(a, solver, out)
