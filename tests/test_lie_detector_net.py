"""Tests for the learned shape detector's pure parts (no weights needed):
preprocessing geometry, label heatmaps, cursor inpainting (label leakage
guard), and the model's output contract."""
import cv2
import numpy as np
import pytest

from src.easymaple.detection import lie_detector_net as N


def test_plate_fill_erases_green_and_is_indistinguishable_from_plate():
    """The green reticle is the training label — if any of it survives in the
    input, the model learns to find the cursor instead of the shape. And the
    ERASURE must look like background (plate + shimmer), not a smudge the net
    could latch onto — at runtime that smudge would sit at our own cursor and
    recreate the self-tracking death spiral in ML form."""
    rng = np.random.RandomState(0)
    tan = np.array([110, 170, 200], np.float32)               # warm texture tone
    plate = np.clip(tan + rng.normal(0, 15, (N.NET_H, N.NET_W, 3)), 0, 255
                    ).astype(np.uint8)
    img = plate.copy()
    cv2.circle(img, (150, 100), 7, (0, 255, 0), -1)           # reticle at NET scale
    out = N.plate_fill(img, plate, np.random.RandomState(1))
    green = cv2.inRange(cv2.cvtColor(out, cv2.COLOR_BGR2HSV), N.GREEN_LO, N.GREEN_HI)
    # The reticle BLOB must be gone. (Single noisy background pixels can land
    # in the green range — the production cursor detector ignores anything
    # below 15px area, so that is the contract here too.)
    cnts, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    biggest = max((cv2.contourArea(c) for c in cnts), default=0.0)
    assert biggest < 15, f"a green blob survived the fill (area {biggest:.0f})"
    # filled pixels must match the plate up to shimmer noise
    region = out[90:110, 140:160].astype(np.float32) - plate[90:110, 140:160]
    assert np.abs(region).mean() < 3 * N.FILL_NOISE, "fill is a visible smudge"


def test_plate_fill_paints_decoys():
    """Training fills include decoys at random spots so the fill carries no
    label information."""
    rng = np.random.RandomState(2)
    plate = np.full((N.NET_H, N.NET_W, 3), 128, np.uint8)
    img = (plate.astype(np.int16) + 40).clip(0, 255).astype(np.uint8)  # differs from plate
    out = N.plate_fill(img, plate, rng, n_decoys=3)
    changed = np.abs(out.astype(np.int16) - img.astype(np.int16)).sum(axis=2) > 10
    assert changed.sum() >= 3 * 0.5 * np.pi * N.DECOY_R ** 2, "decoys not painted"


def test_frame_channels_geometry_and_dtype():
    img = np.random.RandomState(0).randint(0, 255, (404, 684, 3), np.uint8)
    ch = N.frame_channels(img)
    assert ch.shape == (N.NET_H, N.NET_W, 2)
    assert ch.dtype == np.uint8


def test_stack_to_tensor_layout():
    chans = [np.full((N.NET_H, N.NET_W, 2), i * 10, np.uint8)
             for i in range(N.N_FRAMES)]
    x = N.stack_to_tensor(chans)
    assert x.shape == (2 * N.N_FRAMES, N.NET_H, N.NET_W)
    assert x.dtype == np.float32 and 0.0 <= x.min() and x.max() <= 1.0
    # oldest frame first, most recent last
    assert x[0].max() == 0.0
    assert abs(x[-1].mean() - (N.N_FRAMES - 1) * 10 / 255.0) < 1e-6


def test_gt_to_heatmap_peaks_at_label():
    hm = N.gt_to_heatmap((200.0, 100.0))
    assert hm.shape == (N.HM_H, N.HM_W)
    iy, ix = np.unravel_index(np.argmax(hm), hm.shape)
    assert abs(ix - 200 / N.STRIDE) <= 1 and abs(iy - 100 / N.STRIDE) <= 1
    assert hm.max() > 0.99


def test_model_output_contract():
    torch = pytest.importorskip("torch")
    model = N.build_model().eval()
    x = torch.zeros(1, 2 * N.N_FRAMES, N.NET_H, N.NET_W)
    with torch.no_grad():
        y = model(x)
    assert tuple(y.shape) == (1, 1, N.HM_H, N.HM_W)
