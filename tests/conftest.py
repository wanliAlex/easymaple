"""Shared pytest fixtures."""

from pathlib import Path

import cv2
import pytest

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture
def test_frame():
    path = FIXTURES / 'test_image_1.PNG'
    frame = cv2.imread(str(path))
    assert frame is not None, f"Test fixture missing: {path}"
    return frame


@pytest.fixture
def test_frame_dark():
    path = FIXTURES / 'test_image_2.PNG'
    frame = cv2.imread(str(path))
    assert frame is not None, f"Test fixture missing: {path}"
    return frame
