"""Rune solver wrapper.

Delegates to the vendored ``rune_solver`` package (PyTorch / MobileNetV2)
while preserving the API the rest of the bot expects: ``load_model()`` and
``merge_detection(model, frame)`` returning ``[]`` or a list of 4 directions.
"""

from pathlib import Path

import cv2
import numpy as np

from src.easymaple.common import utils

# Lazy import — torch costs ~1s to import and we only need it once a rune
# actually appears (and the bot pre-warms it in a background thread).
_RuneSolver = None

WEIGHTS_PATH = Path('assets/models/arrow_classifier.pth')


def _ensure_solver_class():
    global _RuneSolver
    if _RuneSolver is None:
        from src.easymaple.detection.rune_solver.solver import RuneSolver
        _RuneSolver = RuneSolver
    return _RuneSolver


def load_model():
    """Loads the arrow classifier and returns a ready-to-use ``RuneSolver``."""
    solver_cls = _ensure_solver_class()
    return solver_cls(weights_path=WEIGHTS_PATH)


def _crop_rune_band(frame: np.ndarray) -> np.ndarray:
    """Crop the band of the game frame where the rune puzzle appears.

    Matches the crop used by ``Bot._save_training_frame`` so the solver runs
    on the same region of the screen it was trained on.
    """
    h, w = frame.shape[:2]
    y0, y1 = int(h * 0.24), int(h * 0.45)
    x0, x1 = int(w * 0.30), int(w * 0.74)
    cropped = frame[y0:y1, x0:x1]
    if cropped.shape[2] == 4:    # mss returns BGRA
        cropped = cv2.cvtColor(cropped, cv2.COLOR_BGRA2BGR)
    return cropped


@utils.run_if_enabled
def merge_detection(model, image):
    """Run the rune solver on the current game frame.

    Returns a list of 4 direction strings on success, or ``[]`` if no panel
    was detected (matches the previous TF-based implementation's contract).
    """
    cropped = _crop_rune_band(image)
    result = model.solve(cropped)
    if isinstance(result, list) and len(result) == 4:
        return result
    return []
