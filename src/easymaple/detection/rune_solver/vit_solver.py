"""Offline ViT-based rune solver: panel template + per-arrow ViT + 5-offset TTA."""
from __future__ import annotations

from pathlib import Path

import torch
import torch.nn.functional as F
from PIL import Image

from .crop import DIRECTIONS
from .data_vit import build_transforms
from .model_vit import ArrowViT
from .panel_detect import arrow_boxes_for

_CKPT_DEFAULT = Path(__file__).resolve().parents[4] / "assets" / "models" / "arrow_vit.pt"

_TTA_OFFSETS: tuple[tuple[int, int], ...] = (
    (0, 0), (-3, 0), (3, 0), (0, -3), (0, 3),
)


class ViTSolver:
    def __init__(
        self,
        ckpt_path: Path | str = _CKPT_DEFAULT,
        device: str | None = None,
        tta: bool = True,
    ):
        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        ckpt_path = Path(ckpt_path)
        state = torch.load(ckpt_path, map_location=self.device, weights_only=True)
        backbone = state.get("backbone")
        kwargs = {"frozen": False}
        if backbone:
            kwargs["backbone_name"] = backbone
        self.model = ArrowViT(**kwargs).to(self.device)
        self.model.load_state_dict(state["model"])
        self.model.eval()
        self.tf = build_transforms(train=False)
        self.tta = tta

    def _crop_with_offset(
        self, image: Image.Image, box: tuple[int, int, int, int], dx: int, dy: int
    ) -> Image.Image:
        l, t, r, b = box
        W, H = image.size
        l2 = max(0, min(W - (r - l), l + dx))
        t2 = max(0, min(H - (b - t), t + dy))
        return image.crop((l2, t2, l2 + (r - l), t2 + (b - t)))

    @torch.no_grad()
    def solve(self, image: Image.Image | str | Path) -> list[str]:
        if not isinstance(image, Image.Image):
            image = Image.open(image)
        image = image.convert("RGB")
        if image.size != (528, 304):
            image = image.resize((528, 304), Image.LANCZOS)
        boxes = arrow_boxes_for(image)
        offsets = _TTA_OFFSETS if self.tta else ((0, 0),)
        tiles: list[torch.Tensor] = []
        for b in boxes:
            for dx, dy in offsets:
                tiles.append(self.tf(self._crop_with_offset(image, b, dx, dy)))
        batch = torch.stack(tiles).to(self.device)
        logits = self.model(batch)
        probs = F.softmax(logits, dim=-1).reshape(len(boxes), len(offsets), -1).mean(dim=1)
        preds = probs.argmax(-1).tolist()
        return [DIRECTIONS[p] for p in preds]
