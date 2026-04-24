"""Abstraction for screen capture, enabling dependency injection in tests."""

from abc import ABC, abstractmethod
import logging
import time

import mss
import mss.windows
import numpy as np

log = logging.getLogger(__name__)


class FrameSource(ABC):
    """Provides frames (screenshots) for game-state detection."""

    @abstractmethod
    def grab(self, window: dict) -> 'np.ndarray | None':
        """Return a captured frame for the given window bounds, or None on transient failure."""


class MssFrameSource(FrameSource):
    """Captures live frames from the screen using mss, reusing a single context."""

    def __init__(self):
        self._sct = None

    def grab(self, window: dict) -> 'np.ndarray | None':
        if self._sct is None:
            self._sct = mss.mss()
        try:
            return np.array(self._sct.grab(window))
        except mss.exception.ScreenShotError as e:
            log.warning("Screenshot failed: %s — retrying in 1s", e)
            time.sleep(1)
            self._sct = None  # recreate context on next call
            return None
