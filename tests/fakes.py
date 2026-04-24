"""Test doubles for FrameSource and WindowLocator."""

from pathlib import Path

import cv2
import numpy as np

from src.easymaple.common.frame_source import FrameSource
from src.easymaple.common.window_locator import WindowLocator


class FileFrameSource(FrameSource):
    """Returns a fixed frame loaded from a file on disk. Intended for tests only."""

    def __init__(self, path):
        frame = cv2.imread(str(path))
        if frame is None:
            raise FileNotFoundError(f"Test fixture not found: '{path}'")
        self._frame = frame

    def grab(self, window: dict) -> np.ndarray:
        return self._frame.copy()


class FixedWindowLocator(WindowLocator):
    """Returns a fixed window bounds dict. Intended for tests only."""

    _DEFAULT = {'left': 0, 'top': 0, 'width': 1366, 'height': 768}

    def __init__(self, window: dict = None):
        self._window = window or self._DEFAULT.copy()

    def find(self) -> dict:
        return self._window.copy()
