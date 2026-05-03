"""Locate the rune panel in a 528x304 screenshot via NCC template matching.

Idea: extract a single "left endcap" template (a distinctive curved gold corner
that always appears at the panel's left edge), slide it across a bounded search
band, and place the four arrow boxes at fixed offsets within the panel frame.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

# src/easymaple/detection/rune_solver/panel_detect.py -> 4 levels up = repo root.
_REF_IMAGE = Path(__file__).resolve().parents[4] / "assets" / "rune_panel_template.png"

_PANEL_LEFT_REF = 25
_PANEL_TOP_REF = 120
_TPL_BOX = (_PANEL_LEFT_REF, _PANEL_TOP_REF, _PANEL_LEFT_REF + 50, _PANEL_TOP_REF + 80)
ARROW_CENTERS_REL: tuple[tuple[int, int], ...] = (
    (65, 45),
    (155, 45),
    (245, 45),
    (335, 45),
)
ARROW_HALF_W = 45
ARROW_HALF_H = 45

_SEARCH_X = (5, 80)
_SEARCH_Y = (95, 165)


def _to_chw_tensor(img: Image.Image) -> torch.Tensor:
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(arr).permute(2, 0, 1)


@lru_cache(maxsize=1)
def _template() -> torch.Tensor:
    img = Image.open(_REF_IMAGE)
    tpl = img.crop(_TPL_BOX)
    t = _to_chw_tensor(tpl)
    t = t - t.mean(dim=(1, 2), keepdim=True)
    return t


def _ncc_score(image: torch.Tensor, template: torch.Tensor) -> torch.Tensor:
    C, H, W = image.shape
    _, h, w = template.shape
    x = image.unsqueeze(0)
    k = template.unsqueeze(0)
    numer = F.conv2d(x, k.sum(dim=0, keepdim=True))
    ones = torch.ones(1, C, h, w, dtype=x.dtype, device=x.device)
    sum_x = F.conv2d(x, ones)
    sum_x2 = F.conv2d(x * x, ones)
    n = float(C * h * w)
    var = sum_x2 - sum_x * sum_x / n
    denom = torch.sqrt(torch.clamp(var, min=1e-6))
    return (numer / denom).squeeze(0).squeeze(0)


def detect_panel_origin(img: Image.Image) -> tuple[int, int]:
    image = _to_chw_tensor(img)
    tpl = _template()
    score = _ncc_score(image, tpl)
    H, W = score.shape
    mask = torch.full_like(score, float("-inf"))
    y0, y1 = _SEARCH_Y
    x0, x1 = _SEARCH_X
    mask[y0:y1, x0:x1] = 0.0
    score = score + mask
    flat = int(score.argmax().item())
    yy, xx = divmod(flat, W)
    return xx, yy


def arrow_boxes_for(img: Image.Image) -> list[tuple[int, int, int, int]]:
    px, py = detect_panel_origin(img)
    boxes: list[tuple[int, int, int, int]] = []
    for cx_rel, cy_rel in ARROW_CENTERS_REL:
        cx = px + cx_rel
        cy = py + cy_rel
        boxes.append((cx - ARROW_HALF_W, cy - ARROW_HALF_H, cx + ARROW_HALF_W, cy + ARROW_HALF_H))
    return boxes
