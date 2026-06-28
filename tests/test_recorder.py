"""Tests for the Lie Detector clip recorder."""

import os
import time

import cv2
import numpy as np
import pytest

from src.easymaple.modules import recorder


def _frame(seed=0):
    # BGRA frame, like mss output: shape (H, W, 4)
    rng = np.full((48, 64, 4), seed % 256, dtype=np.uint8)
    rng[:, :, 3] = 255
    return rng


def _wait_until(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_record_clip_writes_playable_mp4(tmp_path):
    out_dir = str(tmp_path / "clips")
    counter = {"n": 0}

    def get_frame():
        counter["n"] += 1
        return _frame(counter["n"])

    started = recorder.record_clip(
        duration_s=0.3, fps=20, out_dir=out_dir, get_frame=get_frame
    )
    assert started is True

    assert _wait_until(lambda: not recorder.is_recording())

    files = [f for f in os.listdir(out_dir) if f.endswith(".mp4")]
    assert len(files) == 1
    path = os.path.join(out_dir, files[0])
    assert os.path.getsize(path) > 0

    cap = cv2.VideoCapture(path)
    try:
        assert cap.isOpened()
        ok, frame = cap.read()
        assert ok
        assert frame.shape == (48, 64, 3)  # BGRA -> BGR
    finally:
        cap.release()


def test_record_clip_returns_false_when_no_frame(tmp_path):
    started = recorder.record_clip(
        duration_s=0.2, fps=20, out_dir=str(tmp_path / "clips"),
        get_frame=lambda: None,
    )
    assert started is False
    assert recorder.is_recording() is False
