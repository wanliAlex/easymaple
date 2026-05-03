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

    Mirrors the upstream auto-maple crop pattern: a fixed 120 px below the
    top UI bar, halfway down the frame, with the middle 50% of the width.
    The panel detector inside ``RuneSolver`` finds the actual oval within
    this band, so the band only needs to be permissive enough to always
    contain the full panel — tighter percentage crops were clipping arrow
    tops on some window sizes.
    """
    h, w = frame.shape[:2]
    y0, y1 = 120, h // 2
    x0, x1 = w // 4, 3 * w // 4
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
