import cv2
import numpy as np


def detect_panel(image: np.ndarray) -> np.ndarray | None:
    """
    Find the rune panel in a pre-cropped screenshot.
    Tries three strategies in order:
      1. Gold border detection — the most common amber/yellow oval border.
      2. Any-colour bright border — catches green/teal border variants.
      3. Arrow saturation detection — fallback for lighter-background runes.
    image: BGR numpy array (OpenCV format).
    Returns BGR crop of the panel, or None if not found.
    """
    result = _detect_by_gold_border(image)
    if result is not None:
        return result
    result = _detect_by_bright_border(image)
    if result is not None:
        return result
    return _detect_by_arrow_saturation(image)


def _detect_by_gold_border(image: np.ndarray) -> np.ndarray | None:
    """
    Detect the rune panel's gold oval border.
    Strategy: find the densest horizontal column band of gold pixels,
    then expand vertically to capture the full panel interior.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    img_h, img_w = image.shape[:2]

    lower_gold = np.array([15, 80, 150])
    upper_gold = np.array([40, 255, 255])
    gold_mask = cv2.inRange(hsv, lower_gold, upper_gold)

    kernel = np.ones((7, 7), np.uint8)
    gold_mask = cv2.dilate(gold_mask, kernel, iterations=3)

    # Column-wise density of gold pixels
    col_density = gold_mask.mean(axis=0).astype(float)
    smooth_k = max(3, img_w // 30) | 1
    col_density = np.convolve(col_density, np.ones(smooth_k) / smooth_k, mode="same")

    if col_density.max() == 0:
        return None

    # Find the densest contiguous column span (the oval column range)
    threshold = col_density.max() * 0.15
    dense_cols = np.where(col_density >= threshold)[0]
    if len(dense_cols) < img_w * 0.15:   # must span at least 15% of image width
        return None

    col_lo = int(dense_cols[0])
    col_hi = int(dense_cols[-1])

    # Find vertical extent: try broad (any pixel) then fall back to dense band only
    col_slice = gold_mask[:, col_lo:col_hi]
    row_density = col_slice.mean(axis=1).astype(float)
    for row_thresh_pct in (0.0, 0.4):
        if row_thresh_pct == 0.0:
            gold_rows = np.where(col_slice.any(axis=1))[0]
        else:
            gold_rows = np.where(row_density >= row_density.max() * row_thresh_pct)[0]
        if len(gold_rows) == 0:
            continue
        y_top = int(gold_rows[0])
        y_bot = int(gold_rows[-1])
        v_padding = max(8, (y_bot - y_top))
        y0 = max(0, y_top - v_padding)
        y1 = min(img_h, y_bot + v_padding)
        panel = image[y0:y1, col_lo:col_hi]
        ph, pw = panel.shape[:2]
        if pw >= 60 and ph >= 15 and pw / ph >= 2.0:
            return panel

    return None


def _detect_by_bright_border(image: np.ndarray) -> np.ndarray | None:
    """
    Second attempt: any highly-saturated, bright border pixel regardless of hue.
    Uses the same column-density logic but with a broader colour mask.
    Requires the resulting panel to be taller than the gold-only attempt would
    normally find, to reduce false positives from colourful game effects.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    img_h, img_w = image.shape[:2]

    # Any vivid, bright pixel — covers all observed border colours
    bright_mask = cv2.inRange(hsv, np.array([0, 100, 180]), np.array([180, 255, 255]))

    kernel = np.ones((5, 5), np.uint8)
    bright_mask = cv2.dilate(bright_mask, kernel, iterations=2)

    col_density = bright_mask.mean(axis=0).astype(float)
    smooth_k = max(3, img_w // 30) | 1
    col_density = np.convolve(col_density, np.ones(smooth_k) / smooth_k, mode="same")

    if col_density.max() == 0:
        return None

    threshold = col_density.max() * 0.25
    dense_cols = np.where(col_density >= threshold)[0]
    if len(dense_cols) < img_w * 0.20:
        return None

    col_lo = int(dense_cols[0])
    col_hi = int(dense_cols[-1])

    col_slice = bright_mask[:, col_lo:col_hi]
    row_has_bright = col_slice.any(axis=1)
    bright_rows = np.where(row_has_bright)[0]
    if len(bright_rows) == 0:
        return None

    y_top = int(bright_rows[0])
    y_bot = int(bright_rows[-1])

    v_padding = max(8, (y_bot - y_top))
    y0 = max(0, y_top - v_padding)
    y1 = min(img_h, y_bot + v_padding)

    panel = image[y0:y1, col_lo:col_hi]
    ph, pw = panel.shape[:2]

    if pw < 80 or ph < 20 or pw / ph < 2.5:
        return None

    return panel


def _detect_by_arrow_saturation(image: np.ndarray) -> np.ndarray | None:
    """
    Fallback: locate the panel by the dense band of highly-saturated arrow pixels.
    Only accepts regions that are wide (≥35% of image width) with aspect ≥ 4.0.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    img_h, img_w = image.shape[:2]

    sat_mask = ((hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 80)).astype(np.uint8) * 255

    kernel_size = max(3, img_h // 10) | 1

    row_density = sat_mask.mean(axis=1).astype(float)
    row_density = np.convolve(row_density, np.ones(kernel_size) / kernel_size, mode="same")
    row_threshold = row_density.max() * 0.4
    dense_rows = np.where(row_density >= row_threshold)[0]
    if len(dense_rows) == 0:
        return None
    row_min, row_max = int(dense_rows[0]), int(dense_rows[-1])

    band_mask = sat_mask[row_min : row_max + 1, :]
    col_density = band_mask.mean(axis=0).astype(float)
    col_density = np.convolve(col_density, np.ones(kernel_size) / kernel_size, mode="same")
    col_threshold = col_density.max() * 0.2
    dense_cols = np.where(col_density >= col_threshold)[0]
    if len(dense_cols) == 0:
        return None
    col_min, col_max = int(dense_cols[0]), int(dense_cols[-1])

    crop_h = row_max - row_min
    crop_w = col_max - col_min
    if crop_w == 0 or crop_h == 0:
        return None

    if crop_w / crop_h < 4.0 or crop_w < img_w * 0.35:
        return None

    return image[row_min : row_max + 1, col_min : col_max + 1]


def split_panel(panel: np.ndarray) -> list[np.ndarray]:
    """
    Split a panel into 4 arrow crops by finding brightness peaks.

    Arrows are bright colourful objects; decorative diamonds and gaps between
    them are comparatively dim. We sum pixel brightness column-by-column,
    find 4 peaks, then crop a fixed-width window around each peak.
    """
    gray = cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    col_brightness = gray.mean(axis=0).astype(float)
    kernel_size = max(3, w // 40) | 1
    smoothed = np.convolve(col_brightness, np.ones(kernel_size) / kernel_size, mode="same")

    peak_cols = []
    mask = smoothed.copy()
    suppress_radius = w // 6

    for _ in range(4):
        peak = int(np.argmax(mask))
        peak_cols.append(peak)
        lo = max(0, peak - suppress_radius)
        hi = min(w, peak + suppress_radius)
        mask[lo:hi] = 0

    peak_cols.sort()

    crop_half = w // 10
    crops = []
    for peak in peak_cols:
        x0 = max(0, peak - crop_half)
        x1 = min(w, peak + crop_half)
        crops.append(panel[:, x0:x1])

    target_w = max(c.shape[1] for c in crops)
    equal_crops = []
    for crop in crops:
        if crop.shape[1] < target_w:
            pad = target_w - crop.shape[1]
            crop = np.pad(crop, ((0, 0), (0, pad), (0, 0)), mode="edge")
        equal_crops.append(crop)

    return equal_crops
