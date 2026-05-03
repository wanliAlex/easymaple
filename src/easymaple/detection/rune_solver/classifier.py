import cv2
import numpy as np
import torch
import torch.nn as nn
from torchvision import models, transforms
from pathlib import Path

from .dataset import DIRECTIONS, INPUT_SIZE

_infer_transform = transforms.Compose([
    transforms.ToPILImage(),
    transforms.Resize((INPUT_SIZE, INPUT_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


def build_model() -> nn.Module:
    # weights=None: load_model() overwrites every parameter with
    # arrow_classifier.pth, so downloading ImageNet weights here would
    # be wasted bandwidth and require network on first launch.
    model = models.mobilenet_v2(weights=None)
    model.classifier[1] = nn.Linear(model.last_channel, len(DIRECTIONS))
    return model


def load_model(weights_path: str | Path, device: torch.device) -> nn.Module:
    model = build_model()
    model.load_state_dict(torch.load(weights_path, map_location=device, weights_only=True))
    model.to(device)
    model.eval()
    return model


def predict(crops: list[np.ndarray], model: nn.Module, device: torch.device) -> list[str]:
    """
    crops: list of 4 BGR numpy arrays (arrow crops from split_panel).
    Returns list of 4 direction strings.
    """
    tensors = []
    for crop in crops:
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        tensors.append(_infer_transform(rgb))
    batch = torch.stack(tensors).to(device)
    with torch.no_grad():
        indices = model(batch).argmax(dim=1).tolist()
    return [DIRECTIONS[i] for i in indices]
