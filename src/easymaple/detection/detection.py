"""Rune solver wrapper.

Delegates to ``rune_solver.RuneSolver`` (ViT, with optional Roboflow Hybrid).
The wrapper crops the rune band, hands the BGR ndarray to the solver, and
returns either a 4-direction list or [] (no usable detection).
"""

from pathlib import Path

import cv2
import numpy as np

from src.easymaple.common import utils

# Lazy import — torch import costs ~1s and we only need it once a rune appears.
_RuneSolver = None

WEIGHTS_PATH = Path('assets/models/arrow_vit.pt')


def _ensure_solver_class():
    global _RuneSolver
    if _RuneSolver is None:
        from src.easymaple.detection.rune_solver import RuneSolver
        _RuneSolver = RuneSolver
    return _RuneSolver


def load_model():
    """Loads the ViT solver (and Hybrid if ROBOFLOW_API_KEY is set)."""
    solver_cls = _ensure_solver_class()
    return solver_cls(weights_path=WEIGHTS_PATH)


def _crop_rune_band(frame: np.ndarray) -> np.ndarray:
    """Crop the band of the game frame where the rune puzzle appears.

    Mirrors the upstream auto-maple pattern: a fixed 120 px below the top UI
    bar, halfway down the frame, with the middle 50% of the width. The
    panel detector inside the ViT solver locates the actual oval within
    this band, so the band only needs to be permissive enough to always
    contain the full panel.
    """
    h, w = frame.shape[:2]
    y0, y1 = 120, h // 2
    x0, x1 = w // 4, 3 * w // 4
    cropped = frame[y0:y1, x0:x1]
    if cropped.shape[2] == 4:
        cropped = cv2.cvtColor(cropped, cv2.COLOR_BGRA2BGR)
    return cropped


@utils.run_if_enabled
def merge_detection(model, image):
    """Run the rune solver on the current game frame.

    Returns a 4-direction list on success or ``[]`` on failure.
    """
    cropped = _crop_rune_band(image)
    result = model.solve(cropped)
    return result if isinstance(result, list) and len(result) == 4 else []
