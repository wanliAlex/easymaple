"""Pretrained-ViT classifier for per-arrow direction.

Backbone is a small ImageNet-pretrained ViT from timm (default: vit_small_patch16_224).
"""
from __future__ import annotations

import timm
import torch
from torch import nn

DEFAULT_BACKBONE = "vit_small_patch16_224.augreg_in21k_ft_in1k"
INPUT_SIZE = 224


class ArrowViT(nn.Module):
    def __init__(
        self,
        num_classes: int = 4,
        backbone_name: str = DEFAULT_BACKBONE,
        frozen: bool = True,
        pretrained: bool = True,
    ) -> None:
        super().__init__()
        self.backbone = timm.create_model(
            backbone_name,
            pretrained=pretrained,
            num_classes=0,
        )
        feat_dim = self.backbone.num_features
        if frozen:
            for p in self.backbone.parameters():
                p.requires_grad = False
        self.frozen = frozen
        self.head = nn.Sequential(
            nn.LayerNorm(feat_dim),
            nn.Dropout(0.1),
            nn.Linear(feat_dim, num_classes),
        )

    def train(self, mode: bool = True) -> "ArrowViT":  # type: ignore[override]
        super().train(mode)
        if self.frozen:
            self.backbone.eval()
        return self

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.frozen:
            with torch.no_grad():
                feats = self.backbone(x)
        else:
            feats = self.backbone(x)
        return self.head(feats)
