"""Learned shape detector for the Lie Detector mini-game.

Some game variants fade the shape below anything hand-crafted statistics can
see (measured: B-R, |dev|, gradients, temporal std, optical flow all at the
noise floor), yet humans keep tracking it — three human-played recordings
pass those variants with the cursor following the invisible shape the whole
way. The signal is therefore present in the captured pixels as a faint
spatio-temporal *pattern*. This module learns it: a small CNN takes a stack
of 8 recent frames (stride 2 ≈ 0.5 s of motion context — a shape moves, the
texture does not) and outputs a heatmap of the shape's location.

Ground truth is the human's green reticle in the recordings. The reticle is
**erased from every input frame** — it sits exactly at the label, and a model
that can see it would learn to find the cursor instead of the shape. The
erasure itself must also carry no information: a visible inpaint smudge (or a
too-static "hole" across the temporal stack) at the label position would be
learned just as happily — and at runtime the net would then lock onto *our
own* cursor's fill artifact, recreating the self-tracking death spiral in ML
form. So the fill is the per-pixel temporal-median plate plus shimmer-matched
noise (statistically indistinguishable from real background), and training
additionally paints identical *decoy* fills at random positions so any
residual fill cue is uncorrelated with the label.

Train/serve parity: all preprocessing (resize geometry, channel layout,
cursor fill, stacking) lives here and is imported by the dataset builder and
the runtime alike.
"""

from collections import deque
from pathlib import Path

import cv2
import numpy as np

# Geometry: box-interior crops are resized to this fixed input size.
NET_W, NET_H = 352, 208
STRIDE = 4                     # heatmap stride (output is NET_W/4 x NET_H/4)
HM_W, HM_H = NET_W // STRIDE, NET_H // STRIDE
N_FRAMES = 8                   # frames per stack ("cascading 8 images")
FRAME_STEP = 2                 # stride between stacked frames (~0.53 s span)
HM_SIGMA = 3.0                 # Gaussian radius of the target blob, in HM cells
FILL_NOISE = 2.5               # sigma of the shimmer noise added to plate fills
DECOY_R = 11                   # radius of training decoy fills (NET px)
DEFAULT_WEIGHTS = Path(__file__).resolve().parents[3] / "assets" / "models" / "lie_detector_net.pt"

GREEN_LO = np.array([40, 80, 80])
GREEN_HI = np.array([92, 255, 255])


def resize_net(box_bgr):
    """Box-interior crop -> fixed NET-size BGR."""
    return cv2.resize(box_bgr, (NET_W, NET_H), interpolation=cv2.INTER_AREA)


def cursor_fill_mask(img_net):
    """Mask (NET scale) of the green reticle, dilated over its glow."""
    m = cv2.inRange(cv2.cvtColor(img_net, cv2.COLOR_BGR2HSV), GREEN_LO, GREEN_HI)
    return cv2.dilate(m, np.ones((9, 9), np.uint8))


def plate_fill(img_net, plate_net, rng, n_decoys=0):
    """Erase the reticle by replacing it with plate + shimmer noise; optionally
    paint identical decoy fills at random spots (training only) so the fill
    itself carries no label information. Returns the filled image."""
    mask = cursor_fill_mask(img_net)
    for _ in range(n_decoys):
        cv2.circle(mask, (int(rng.randint(DECOY_R, NET_W - DECOY_R)),
                          int(rng.randint(DECOY_R, NET_H - DECOY_R))),
                   DECOY_R, 255, -1)
    if not mask.any():
        return img_net
    out = img_net.copy()
    sel = mask > 0
    noise = rng.normal(0.0, FILL_NOISE, (int(sel.sum()), 3))
    out[sel] = np.clip(plate_net[sel].astype(np.float32) + noise, 0, 255
                       ).astype(np.uint8)
    return out


def frame_channels(box_bgr, plate_net=None, rng=None, n_decoys=0):
    """One frame's 2 network channels as uint8 (NET_H, NET_W, 2): grayscale
    and B-R coolness (offset +128). When ``plate_net`` is given, the green
    reticle is erased with a plate fill first (see module docstring)."""
    img = resize_net(box_bgr)
    if plate_net is not None:
        img = plate_fill(img, plate_net, rng or np.random, n_decoys)
    f = img.astype(np.int16)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cool = np.clip(f[:, :, 0] - f[:, :, 2] + 128, 0, 255).astype(np.uint8)
    return np.dstack([gray, cool])


def stack_to_tensor(chans):
    """List of N_FRAMES (NET_H, NET_W, 2) uint8 -> float32 CHW in [0, 1],
    oldest first, most recent last."""
    x = np.concatenate([c.transpose(2, 0, 1) for c in chans], axis=0)
    return x.astype(np.float32) / 255.0


def gt_to_heatmap(xy_net):
    """Target heatmap for a GT position in NET pixel coords."""
    hm = np.zeros((HM_H, HM_W), np.float32)
    if xy_net is None:
        return hm
    cx, cy = xy_net[0] / STRIDE, xy_net[1] / STRIDE
    yy, xx = np.mgrid[0:HM_H, 0:HM_W]
    hm = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * HM_SIGMA ** 2))
    return hm.astype(np.float32)


def build_model():
    """Small heatmap CNN: 16ch (8 frames x [gray, B-R]) -> 1ch heatmap at
    stride 4. ~0.4M params — real-time on CPU, instant on GPU."""
    import torch.nn as nn

    class Block(nn.Module):
        def __init__(self, cin, cout, stride=1):
            super().__init__()
            self.conv = nn.Conv2d(cin, cout, 3, stride, 1, bias=False)
            self.bn = nn.BatchNorm2d(cout)
            self.act = nn.ReLU(inplace=True)

        def forward(self, x):
            return self.act(self.bn(self.conv(x)))

    class ShapeNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.stem = Block(2 * N_FRAMES, 32, 2)     # /2
            self.d1 = Block(32, 64, 2)                 # /4
            self.b1 = Block(64, 64)
            self.b2 = Block(64, 64)
            self.d2 = Block(64, 96, 2)                 # /8
            self.b3 = Block(96, 96)
            self.up = nn.Upsample(scale_factor=2, mode="bilinear",
                                  align_corners=False)
            self.fuse = Block(96 + 64, 64)             # /4 with skip
            self.head = nn.Conv2d(64, 1, 1)

        def forward(self, x):
            x = self.stem(x)
            s4 = self.b2(self.b1(self.d1(x)))
            s8 = self.b3(self.d2(s4))
            y = self.fuse(__import__("torch").cat([self.up(s8), s4], dim=1))
            return self.head(y)                        # logits (B,1,HM_H,HM_W)

    return ShapeNet()


class ShapeNetDetector:
    """Runtime wrapper: push box-interior BGR crops each frame, get heatmap
    peaks once enough frames are buffered.

    The net only runs once a background plate has been provided via
    :meth:`set_plate` — the reticle fill must match training (plate + shimmer
    noise), never a visible smudge the net could latch onto."""

    def __init__(self, weights=DEFAULT_WEIGHTS, device=None):
        import torch
        self._torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = build_model().to(self.device).eval()
        state = torch.load(weights, map_location=self.device, weights_only=True)
        self.model.load_state_dict(state)
        self._buf = deque(maxlen=(N_FRAMES - 1) * FRAME_STEP + 1)
        self._plate = None         # NET-size BGR background estimate
        self._rng = np.random.RandomState(0)
        self._shape = None         # interior (w, h) for coordinate mapping

    @property
    def ready(self):
        return self._plate is not None and len(self._buf) == self._buf.maxlen

    def reset(self):
        self._buf.clear()
        self._plate = None

    def set_plate(self, plate_net_bgr):
        """Provide/refresh the NET-size BGR background plate (the caller owns
        plate building — the solver already maintains the frame history)."""
        self._plate = plate_net_bgr

    def push(self, box_bgr):
        """Add this frame; returns the heatmap (HM_H, HM_W float32, sigmoid)
        or None while warming up / before a plate exists."""
        if self._plate is None:
            return None
        self._shape = (box_bgr.shape[1], box_bgr.shape[0])
        self._buf.append(frame_channels(box_bgr, self._plate, self._rng))
        if not self.ready:
            return None
        chans = [self._buf[i] for i in range(0, len(self._buf), FRAME_STEP)]
        x = self._torch.from_numpy(stack_to_tensor(chans))[None].to(self.device)
        with self._torch.no_grad():
            hm = self._torch.sigmoid(self.model(x))[0, 0].cpu().numpy()
        return hm

    def peaks(self, hm, k=4, floor=0.08):
        """Top-k heatmap peaks mapped back to box-interior pixel coords as
        (x, y, score 0..1), non-max suppressed.

        The floor is deliberately low: focal-trained heatmaps are
        conservative — measured on a held-out hard clip, peaks at sigmoid
        0.1-0.5 still localize the shape to ~5-15 px. Confidence weighting
        happens at the fusion layer, not by discarding peaks here."""
        if hm is None or self._shape is None:
            return []
        w, h = self._shape
        sx, sy = w / HM_W, h / HM_H
        d = hm.copy()
        out = []
        for _ in range(k):
            _, mx, _, loc = cv2.minMaxLoc(d)
            if mx < floor:
                break
            out.append((loc[0] * sx, loc[1] * sy, float(mx)))
            cv2.circle(d, loc, 8, 0.0, -1)
        return out
