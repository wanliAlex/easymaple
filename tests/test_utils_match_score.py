"""Tests for utils.match_score."""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import numpy as np
from src.easymaple.common import utils


def test_match_score_returns_one_for_self_match():
    """A grayscale frame matched against itself should score very close to 1.0."""
    frame = np.array([[10, 20, 30, 40], [50, 60, 70, 80]], dtype=np.uint8)
    template = frame.copy()
    score = utils.match_score(frame, template)
    assert 0.99 <= score <= 1.0001


def test_match_score_returns_float_in_range():
    """Score against a different patch must be a finite float in [-1, 1] (TM_CCOEFF_NORMED range)."""
    rng = np.random.default_rng(seed=0)
    frame = rng.integers(0, 256, size=(40, 40), dtype=np.uint8)
    template = rng.integers(0, 256, size=(8, 8), dtype=np.uint8)
    score = utils.match_score(frame, template)
    assert isinstance(score, float)
    assert -1.0 <= score <= 1.0


def test_match_score_never_raises_on_degenerate_inputs():
    """Must never raise on degenerate inputs — returns 0.0. Long-lived loops in the
    notifier and bot threads call this every cycle; an exception here would silently
    kill the thread."""
    template = np.zeros((9, 9), dtype=np.uint8)
    # Empty array (1D shape (0,)) — would crash cv2.cvtColor in the old impl
    assert utils.match_score(np.array([]), template) == 0.0
    # 1D array — also invalid channel input to cvtColor
    assert utils.match_score(np.array([1, 2, 3], dtype=np.uint8), template) == 0.0
    # None — wouldn't even reach cv2 calls in old impl, but tested for safety
    assert utils.match_score(None, template) == 0.0
    assert utils.match_score(np.zeros((10, 10), dtype=np.uint8), None) == 0.0
