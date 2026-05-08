"""Hybrid solver: Roboflow detects, local ViT classifies."""
from __future__ import annotations

import torch
from PIL import Image

from .crop import DIRECTIONS
from .data_vit import build_transforms
from .model_vit import ArrowViT
from .roboflow_client import RoboflowClient


class HybridSolver:
    def __init__(
        self,
        vit_module: ArrowViT,
        device: torch.device,
        roboflow_kwargs: dict | None = None,
        margin: int = 4,
    ) -> None:
        self.vit = vit_module
        self.device = device
        self.tf = build_transforms(train=False)
        self.client = RoboflowClient(**(roboflow_kwargs or {}))
        self.margin = margin

    def _crop_box(self, img: Image.Image, p: dict) -> torch.Tensor:
        cx, cy = p["x"], p["y"]
        bw, bh = p["width"], p["height"]
        side = max(bw, bh) + 2 * self.margin
        l = max(0, int(round(cx - side / 2)))
        t = max(0, int(round(cy - side / 2)))
        r = min(img.width, int(round(cx + side / 2)))
        b = min(img.height, int(round(cy + side / 2)))
        return self.tf(img.crop((l, t, r, b)))

    @torch.no_grad()
    def solve(self, image: Image.Image) -> list[str]:
        if image.size != (528, 304):
            image = image.resize((528, 304), Image.LANCZOS)
        preds = self.client.infer(image)
        if len(preds) < 4:
            raise RuntimeError(f"Roboflow returned {len(preds)} detections (<4): {preds}")
        if len(preds) > 4:
            preds = sorted(preds, key=lambda p: -p["confidence"])[:4]
        preds = sorted(preds, key=lambda p: p["x"])
        crops = torch.stack([self._crop_box(image, p) for p in preds]).to(self.device)
        logits = self.vit(crops)
        idxs = logits.argmax(-1).tolist()
        return [DIRECTIONS[i] for i in idxs]
