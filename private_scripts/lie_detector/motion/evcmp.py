"""Compare ``ev.py`` runs (FINDINGS §11-12). Reads ``training_data/lie_detector/eval``
(``LD_EVAL`` overrides).

  evcmp.py heldout A B         paired per (clip, perturbation): coverage, locked at end,
                               B - A per clip (mean +- se). Files A_<jit>.jsonl.
  evcmp.py live A B ...        per labelled game, mean over runs; deltas vs A.
                               Files live_A.jsonl. -m c60,c80,end60 picks metrics.
  evcmp.py lag A B ...         held-out re-scored with the human track advanced
                               0-6 frames (human reaction lag); needs ev.py --pos.
"""
import argparse
import collections
import glob
import json
import os
import re

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
D = os.environ.get("LD_EVAL") or os.path.join(ROOT, "training_data", "lie_detector", "eval")


def rows(path):
    out = []
    for line in open(path):
        try:
            out.append(json.loads(line))
        except ValueError:
            print(f"[{os.path.basename(path)}: corrupt line skipped]")
    return out


def load_heldout(tag):
    R = {}
    for p in glob.glob(os.path.join(D, tag + "_*.jsonl")):
        j = os.path.basename(p)[len(tag) + 1:-6]
        if re.fullmatch(r"-?\d+,-?\d+", j):          # TAG_<dx>,<dy>.jsonl only (not TAG_20_...)
            for r in rows(p):
                R[(r["clip"], j)] = r
    return R


def heldout(a, b):
    A, B = load_heldout(a), load_heldout(b)
    keys = sorted(set(A) & set(B))
    print(f"paired (clip, perturbation) runs: {len(keys)}  clips: {len({k[0] for k in keys})}")
    for t, R in ((a, A), (b, B)):
        def m(f):
            return np.mean([R[k][f] for k in keys])
        print(f"{t:14s} cov60 {m('cov60'):.3f}  locked@60 {m('ok60'):.3f}  cov80 {m('cov80'):.3f}  "
              f"locked@80 {m('ok80'):.3f}  longest {m('longest'):.2f}s  worst {min(R[k]['cov60'] for k in keys):.2f}")
    clips = sorted({k[0] for k in keys})
    pc = np.array([np.mean([B[k]["cov60"] - A[k]["cov60"] for k in keys if k[0] == c]) for c in clips])
    ok = np.array([np.mean([B[k]["ok60"] - A[k]["ok60"] for k in keys if k[0] == c]) for c in clips])
    print(f"{b} - {a}: cov60 {100 * pc.mean():+.2f} +- {100 * pc.std(ddof=1) / np.sqrt(len(pc)):.2f} pts per clip "
          f"(better >2pt {np.sum(pc > .02)}, worse >2pt {np.sum(pc < -.02)}); locked@60 {ok.sum():+.1f} clips")


def live(tags, mets):
    R = {}
    for t in tags:
        by = collections.defaultdict(list)
        for r in rows(os.path.join(D, f"live_{t}.jsonl")):
            by[r["clip"][:19]].append([r[k] for k in mets])
        R[t] = {k: np.mean(v, 0) for k, v in by.items()}
    games = sorted(R[tags[0]])
    print("metrics:", "/".join(mets), "| first tag absolute, others delta (points)")
    print(f"{'game':12s}" + "".join(f"{t:>22s}" for t in tags))
    for g in games:
        row = f"{g[5:16]:12s}"
        for t in tags:
            v = R[t].get(g)
            if v is None:
                row += f"{'-':>22s}"
            elif t == tags[0]:
                row += "".join(f"{x:7.3f}" for x in v).rjust(22)
            else:
                row += "".join(f"{100 * x:+7.1f}" for x in v - R[tags[0]][g]).rjust(22)
        print(row)
    for t in tags:
        gs = [g for g in games if g in R[t]]
        v = np.array([R[t][g] for g in gs])
        b = np.array([R[tags[0]][g] for g in gs])
        print(f"{t:14s} mean " + "/".join(f"{x:.3f}" for x in v.mean(0)) +
              "   worst delta " + "/".join(f"{100 * x:+.1f}" for x in (v - b).min(0)))


def lag(tags, ks=(0, 2, 3, 4, 6)):
    R = {t: load_heldout(t) for t in tags}
    keys = sorted(set.intersection(*[set(v) for v in R.values()]))
    print(f"runs {len(keys)}; human track advanced by k frames (x41 ms): {' '.join(map(str, ks))}")
    res = {}
    for t in tags:
        cov = np.zeros((len(keys), len(ks)))
        ok = np.zeros((len(keys), len(ks)))
        for i, key in enumerate(keys):
            r = R[t][key]
            cur = np.array([[np.nan if v is None else v for v in p] for p in r["cur"]], float)
            gtp = np.array([[np.nan if v is None else v for v in p] for p in r["gtp"]], float)
            for ki, k in enumerate(ks):
                idx = np.arange(len(cur)) + r["s_old"] - r["gt0"] + k
                g = np.full_like(cur, np.nan)
                v = (idx >= 0) & (idx < len(gtp))
                g[v] = gtp[idx[v]]
                d = np.hypot(*(cur - g).T)
                on = d[np.isfinite(d)] < 60
                cov[i, ki] = on.mean()
                ok[i, ki] = on[-30:].mean() >= 0.5
        res[t] = (cov, ok)
        print(f"{t:12s} cov60 " + " ".join(f"{v:.3f}" for v in cov.mean(0)) +
              " | locked@60 " + " ".join(f"{v:.3f}" for v in ok.mean(0)))
    clips = sorted({k[0] for k in keys})
    for t in tags[1:]:
        dc = res[t][0] - res[tags[0]][0]
        do = res[t][1] - res[tags[0]][1]
        pc = np.array([dc[[i for i, k in enumerate(keys) if k[0] == c]].mean(0) for c in clips])
        po = np.array([do[[i for i, k in enumerate(keys) if k[0] == c]].mean(0) for c in clips])
        se = pc.std(0, ddof=1) / np.sqrt(len(clips))
        print(f"{t} - {tags[0]}: cov60 " + " ".join(f"{100 * m:+.2f}+-{100 * s:.2f}" for m, s in zip(pc.mean(0), se)) +
              " | locked@60 clips " + " ".join(f"{v:+.1f}" for v in po.sum(0)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["heldout", "live", "lag"])
    ap.add_argument("tags", nargs="+")
    ap.add_argument("-m", default="c60,c80,end60", help="live metrics")
    a = ap.parse_args()
    if a.mode == "heldout":
        heldout(*a.tags[:2])
    elif a.mode == "live":
        live(a.tags, a.m.split(","))
    else:
        lag(a.tags)
