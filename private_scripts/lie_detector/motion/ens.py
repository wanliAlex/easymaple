"""Prototype solver variants for ``ev.py`` (not used at runtime).

* Ensembles: the first net is primary — its alignment mode drives START /
  duplicate detection exactly as the single-net solver does; every net scores
  with references aligned the way it was trained; evidence grids are averaged
  (optionally weighted).
* ``tta``: flip test-time augmentation (2 or 4 passes).
* ``bg_*``: clutter suppression variants. ``bg_mode="ema"`` without the
  exclusions is what became the runtime ``ClutterBackground`` (bit-identical
  results); ``"min"`` (rolling minimum) and the exclusions near the estimate
  were worse (FINDINGS §12).
"""
import cv2
import numpy as np

from common import LM


class EnsembleSolver(LM.MotionLieDetectorSolver):
    def __init__(self, models, weights=None, tta=1, bg_tau=0.0, bg_k=0.0, bg_mode="ema", bg_excl=0.0, **kw):
        self.bg_mode = bg_mode      # "ema": EMA over bg_tau s; "min": minimum over the last bg_tau s (window full only)
        self.bg_excl = bg_excl      # no suppression within this many half-res px of the current estimate
        self.bg_uexcl = kw.pop("bg_uexcl", 0.0)  # the background is not updated within this of the estimate
        self.tta = tta              # 1: as is; 2: + horizontal flip; 4: + vertical, both
        # static-clutter suppression: subtract bg_k * (EMA over bg_tau s of the
        # evidence at each box position, positive part) - the shape moves,
        # clutter fixed to the box (walls, a second texture layer) does not
        self.bg_tau, self.bg_k = bg_tau, bg_k
        nets = [LM.load_net(m)[0] for m in models]
        self.nets = nets
        self.weights = np.asarray(weights if weights is not None else [1.0] * len(nets), float)
        self.weights = self.weights / self.weights.sum()
        super().__init__(net=nets[0], device=next(nets[0].parameters()).device, clutter=(0.0, 0.0), **kw)
        self.alt_window = [bool(getattr(n, "pc_window", False)) != self.pc_window for n in nets]
        offs = {tuple(getattr(n, "ref_offsets", LM.REF_OFFSETS)) for n in nets}
        assert len(offs) == 1, "all nets must use the same reference offsets"

    def _clear_buffers(self):
        super()._clear_buffers()
        self._bg = None
        self._bg_t = None
        self._bg_hist = []
        self._pcg2 = {}
        self._pairs2 = {}
        self._win2 = None

    def _push(self, crop, cursor_xy, t_now):
        T = super()._push(crop, cursor_xy, t_now)
        if any(self.alt_window):
            ys, xs = self._pc_slices
            c = self._gray[T][self._pc_slices]
            if self.pc_window:          # alt = unwindowed
                self._pcg2[T] = np.ascontiguousarray(c)
            else:
                if self._win2 is None:
                    self._win2 = cv2.createHanningWindow((xs.stop - xs.start, ys.stop - ys.start), cv2.CV_32F)
                self._pcg2[T] = c * self._win2
            for k in [k for k in self._pcg2 if k < T - self.BUF]:
                del self._pcg2[k]
            for key in [key for key in self._pairs2 if min(key) < T - self.BUF]:
                del self._pairs2[key]
        return T

    def _shift2(self, a, b):
        if (a, b) not in self._pairs2:
            if (b, a) in self._pairs2:
                dx, dy, r = self._pairs2[(b, a)]
                return -dx, -dy, r
            (dx, dy), r = cv2.phaseCorrelate(self._pcg2[a], self._pcg2[b])
            self._pairs2[(a, b)] = (dx, dy, r)
        return self._pairs2[(a, b)]

    def _score(self, t, refs):
        torch = LM._torch()
        evs = []
        inputs = {}
        for net, alt, wt in zip(self.nets, self.alt_window, self.weights):
            if alt not in inputs:
                sh = self._shift2 if alt else self._shift
                shifts = [sh(s, t)[:2] for s in refs]
                inputs[alt] = LM.build_input_fast(self._frames[t], [self._frames[s] for s in refs], shifts,
                                                  self._holes[t], [self._holes[s] for s in refs])
            x, valid = inputs[alt]
            with torch.no_grad():
                xt = torch.from_numpy(x)[None].to(self.device)
                if self.tta == 1:
                    logit = net(xt)[0, 0].float().cpu().numpy()
                else:
                    flips = [(), (3,), (2,), (2, 3)][:self.tta]
                    xb = torch.cat([xt.flip(f) if f else xt for f in flips])
                    out = net(xb)[:, 0]
                    logit = torch.stack([out[i].flip([d - 2 for d in f]) if f else out[i]
                                         for i, f in enumerate(flips)]).mean(0).float().cpu().numpy()
            evs.append(wt * LM.evidence_grid(logit, valid, self.den_floor, self.wall_floor))
        ev = np.sum(evs, axis=0)
        if self.bg_k > 0:
            now = self._times[t]
            if self.bg_mode == "ema":
                if self._bg is None or self._bg.shape != ev.shape:
                    self._bg = np.zeros_like(ev)
                    self._bg_t = now
                sup = np.maximum(self._bg, 0.0)
                a = 1.0 - np.exp(-max(now - self._bg_t, 1e-3) / self.bg_tau)
                if self.bg_uexcl > 0 and self.tracker is not None:
                    G = LM.GRID
                    yy, xx = np.mgrid[0:ev.shape[0], 0:ev.shape[1]]
                    px, py = self.tracker.pos
                    a = a * (np.hypot((xx + .5) * G - px, (yy + .5) * G - py) > self.bg_uexcl)
                self._bg += a * (ev - self._bg)
                self._bg_t = now
            else:
                h = [(tt, e) for tt, e in self._bg_hist if now - tt <= self.bg_tau and e.shape == ev.shape]
                if self._bg_t is None:
                    self._bg_t = now
                full = now - self._bg_t >= self.bg_tau
                sup = np.maximum(np.min([e for _, e in h], axis=0), 0.0) if (h and full) else np.zeros_like(ev)
                self._bg_hist = h + [(now, ev)]
            if self.bg_excl > 0 and self.tracker is not None:
                G = LM.GRID
                yy, xx = np.mgrid[0:ev.shape[0], 0:ev.shape[1]]
                px, py = self.tracker.pos
                sup = sup * (np.hypot((xx + .5) * G - px, (yy + .5) * G - py) > self.bg_excl)
            ev = ev - self.bg_k * sup
        self.last_evidence = ev
        return ev
