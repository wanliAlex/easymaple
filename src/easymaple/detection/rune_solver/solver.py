import cv2
import numpy as np
import torch
from pathlib import Path

from .detector import detect_panel, split_panel
from .classifier import load_model, predict

DEFAULT_WEIGHTS = Path(__file__).parents[4] / "assets" / "models" / "arrow_classifier.pth"


class RuneSolver:
    """
    Usage:
        solver = RuneSolver()
        result = solver.solve(bgr_image)
        # → ["up", "left", "down", "right"]  or  "no_image"
    """

    def __init__(self, weights_path: Path = DEFAULT_WEIGHTS):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = load_model(weights_path, self.device)

    def solve(self, image: np.ndarray) -> list[str] | str:
        """
        image: BGR numpy array (e.g. from cv2.imread or cv2.cvtColor).
        Returns ["up","left","down","right"] or "no_image".
        """
        panel = detect_panel(image)
        if panel is None:
            return "no_image"
        crops = split_panel(panel)
        return predict(crops, self.model, self.device)
