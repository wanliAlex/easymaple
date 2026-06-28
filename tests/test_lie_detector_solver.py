"""Tests for the Lie Detector mini-game solver.

These are synthetic and self-contained (no recorded clips needed): a static
textured play-box with a bright disc that sits still, then moves while fading.
They guard the end-to-end pipeline — box detection, the static-background
plate, and shape tracking while the shape carries signal.
"""
import os

import cv2
import numpy as np
import pytest

from src.easymaple.detection import lie_detector_solver as S

RNG = np.random.RandomState(42)

# Frame + play-box geometry (box must clear the size/aspect/fill gates).
FRAME_W, FRAME_H = 1000, 800
BOX = (170, 150, 640, 420)                     # x, y, w, h (fits the central ROI)
TEXTURE = None


def _texture():
    """A fixed tan camouflage-like texture for the play-box (built once)."""
    global TEXTURE
    if TEXTURE is None:
        _, _, w, h = BOX
        noise = RNG.randint(0, 60, (h, w, 3), np.uint8)
        noise = cv2.GaussianBlur(noise, (0, 0), 6)     # smooth, low-frequency
        tan = np.array([110, 170, 200], np.uint8)      # BGR tan
        TEXTURE = np.clip(noise.astype(np.int16) + tan, 0, 255).astype(np.uint8)
    return TEXTURE


def make_frame(disc_xy, alpha):
    """Build a frame: dark background, tan textured box, and a bright disc of
    opacity ``alpha`` (0..1) composited at ``disc_xy`` (box-interior coords)."""
    frame = np.full((FRAME_H, FRAME_W, 3), 20, np.uint8)
    x, y, w, h = BOX
    box = _texture().copy()
    if alpha > 0:
        overlay = box.copy()
        cv2.circle(overlay, (int(disc_xy[0]), int(disc_xy[1])), 34, (245, 245, 245), -1)
        box = cv2.addWeighted(overlay, alpha, box, 1 - alpha, 0)
    frame[y:y + h, x:x + w] = box
    return frame


def synth_sequence():
    """Yield (frame, true_disc_center_in_frame_coords, alpha) for a full game:
    ~25 stationary opaque frames, then ~70 frames moving while fading."""
    x, y, w, h = BOX
    cx, cy = 250, 230                                  # interior start position
    seq = []
    for _ in range(25):                                # stationary, opaque
        seq.append(((cx, cy), 1.0))
    pos = np.array([cx, cy], float)
    vel = np.array([3.2, 1.7])
    for i in range(70):                                # moving + fading
        pos = pos + vel
        if not (40 < pos[0] < w - 40):
            vel[0] *= -1
        if not (40 < pos[1] < h - 40):
            vel[1] *= -1
        alpha = max(0.1, 1.0 - i / 60.0)
        seq.append((tuple(pos), alpha))
    return [(make_frame(p, a), (x + p[0], y + p[1]), a) for p, a in seq]


def test_detect_play_box_finds_the_box():
    frame, _, _ = synth_sequence()[0]
    box = S.detect_play_box(frame)
    assert box is not None
    x, y, w, h = box
    assert abs(x - BOX[0]) < 25 and abs(y - BOX[1]) < 25
    assert abs(w - BOX[2]) < 60 and abs(h - BOX[3]) < 60   # morphology trims a few px


def test_detect_play_box_rejects_small_tan_blobs():
    """A small tan rectangle (like a combat effect) must not be detected."""
    frame = np.full((FRAME_H, FRAME_W, 3), 20, np.uint8)
    frame[100:250, 100:340] = np.array([110, 170, 200], np.uint8)   # 240x150, too small
    assert S.detect_play_box(frame) is None


def test_build_plate_recovers_static_background():
    """The plate must recover the background despite a bright moving disc."""
    seq = synth_sequence()
    x, y, w, h = BOX
    m = S.BOX_INNER_MARGIN
    grays, masks = [], []
    for frame, _, _ in seq[30:]:                       # moving phase
        crop = frame[y + m:y + h - m, x + m:x + w - m]
        grays.append(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32))
        masks.append(np.zeros(grays[-1].shape, np.uint8))
    plate = build = S.build_plate(grays, masks)
    truth = cv2.cvtColor(_texture(), cv2.COLOR_BGR2GRAY).astype(np.float32)
    truth = truth[m:h - m, m:w - m]
    # Median plate should match the true texture closely almost everywhere.
    assert np.median(np.abs(plate - truth)) < 8.0


def test_solver_tracks_shape_while_signal_present():
    """End-to-end: the solver should follow the disc within ~a shape width
    while the shape still carries signal (opaque + early fade)."""
    solver = S.LieDetectorSolver()
    errs_with_signal = []
    reached_track = False
    for frame, truth_xy, alpha in synth_sequence():
        target = solver.process(frame)
        if solver.state == "TRACK":
            reached_track = True
        if target is not None and alpha >= 0.4:
            errs_with_signal.append(np.hypot(target[0] - truth_xy[0],
                                             target[1] - truth_xy[1]))
    assert reached_track, "solver never transitioned to TRACK"
    errs = np.array(errs_with_signal)
    # While the shape is reasonably visible, stay within ~one shape width.
    assert np.median(errs) < 70, f"median error {np.median(errs):.0f}px too high"
    assert np.mean(errs < 80) > 0.6, f"only {100*np.mean(errs<80):.0f}% within 80px"


def test_green_cursor_is_masked_from_tracking():
    """A bright green reticle drawn on the box must not be tracked as the shape
    (at runtime it is our own cursor)."""
    frame = make_frame((300, 300), 0.0)                # no shape
    x, y, w, h = BOX
    m = S.BOX_INNER_MARGIN
    crop = frame[y + m:y + h - m, x + m:x + w - m]
    mask = S.green_cursor_mask(crop)
    assert mask.sum() == 0                             # no green present
    cv2.circle(crop, (200, 200), 12, (0, 255, 0), -1)  # add green reticle
    mask = S.green_cursor_mask(crop)
    assert mask[200, 200] > 0                          # green detected -> maskable
