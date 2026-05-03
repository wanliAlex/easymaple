import cv2
import torch
from torch.utils.data import Dataset
from torchvision import transforms
from pathlib import Path

DIRECTIONS = ["up", "down", "left", "right"]
INPUT_SIZE = 96

train_transform = transforms.Compose([
    transforms.ToPILImage(),
    transforms.Resize((INPUT_SIZE, INPUT_SIZE)),
    transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.3, hue=0.1),
    transforms.RandomRotation(10),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

val_transform = transforms.Compose([
    transforms.ToPILImage(),
    transforms.Resize((INPUT_SIZE, INPUT_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


class ArrowCropDataset(Dataset):
    def __init__(self, crop_paths: list[Path], transform=None):
        self.paths = list(crop_paths)
        self.transform = transform if transform is not None else val_transform

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        path = self.paths[idx]
        direction = path.name.split("_")[0]  # first token is always the direction
        label = DIRECTIONS.index(direction)
        image = cv2.imread(str(path))
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        return self.transform(rgb), label
