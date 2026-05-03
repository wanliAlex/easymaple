"""Eval transforms for ViT inference (224x224 RGB, ImageNet normalized)."""
from __future__ import annotations

from torchvision import transforms as T

from .model_vit import INPUT_SIZE

_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)


def build_transforms(train: bool = False) -> T.Compose:
    base = [T.Resize((INPUT_SIZE, INPUT_SIZE))]
    if train:
        base += [
            T.RandomAffine(
                degrees=0,
                translate=(0.04, 0.04),
                scale=(0.95, 1.05),
                fill=0,
            ),
            T.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.15, hue=0.04),
        ]
    base += [T.ToTensor(), T.Normalize(_IMAGENET_MEAN, _IMAGENET_STD)]
    return T.Compose(base)
