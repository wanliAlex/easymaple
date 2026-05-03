"""Rune solver facade.

Preserves the BGR-ndarray contract used by ``detection.merge_detection``:
``RuneSolver().solve(image)`` returns either a 4-element list of direction
strings or an empty list on failure.

Backend selection:
- If ``ROBOFLOW_API_KEY`` is set in the environment, both ``HybridSolver``
  and ``ViTSolver`` are loaded and the hybrid path is tried first. On any
  hybrid runtime error we silently fall through to ViT.
- Otherwise, only ``ViTSolver`` is loaded and used directly.

The ViT module is built once and shared between both backends to avoid
double-loading the ~87 MB checkpoint.
"""
from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .hybrid_solver import HybridSolver
from .vit_solver import ViTSolver

DEFAULT_WEIGHTS = Path(__file__).resolve().parents[4] / "assets" / "models" / "arrow_vit.pt"


class RuneSolver:
    def __init__(self, weights_path: Path = DEFAULT_WEIGHTS):
        self._vit = ViTSolver(ckpt_path=weights_path)
        # Backwards-compat surface for bot.py warmup (it pokes at .device / .model)
        self.device = self._vit.device
        self.model = self._vit.model

        api_key = os.environ.get("ROBOFLOW_API_KEY")
        if api_key:
            self._hybrid = HybridSolver(
                vit_module=self._vit.model,
                device=self.device,
                roboflow_kwargs={"api_key": api_key},
            )
            self._mode = "hybrid+vit"
        else:
            self._hybrid = None
            self._mode = "vit"
        print(f"[~] Rune solver mode: {self._mode}")

    def solve(self, image: np.ndarray) -> list[str]:
        """BGR ndarray -> 4 direction strings, or [] on failure."""
        if image is None or image.size == 0:
            return []
        if image.ndim == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)

        if self._hybrid is not None:
            try:
                return self._hybrid.solve(pil)
            except Exception as e:
                print(f"[!] Hybrid solver error, falling back to ViT: {e}")

        try:
            return self._vit.solve(pil)
        except Exception as e:
            print(f"[!] ViT solver error: {e}")
            return []
