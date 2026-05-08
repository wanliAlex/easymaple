"""Diagnose why a specific training-data PNG fails to classify.

Runs the exact same pipeline merge_detection() uses (filter_color -> canny ->
get_boxes -> sort_by_confidence + rotated) but on a pre-cropped training image
so we skip the outer frame crop. Saves intermediate stages to disk so we can
eyeball where the pipeline breaks down.

Usage: uv run python private_scripts/test_rune_detection.py [path_to_png]
"""

import os
import sys
import time

import cv2
import numpy as np

# Make the project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.easymaple.detection import detection


IMAGE_PATH = sys.argv[1] if len(sys.argv) > 1 else 'training_data/rune_20260503_144634_583.png'
OUT_DIR = 'private_scripts/rune_debug'


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    image = cv2.imread(IMAGE_PATH)
    if image is None:
        print(f'Could not read {IMAGE_PATH}')
        return
    print(f'Loaded {IMAGE_PATH}, shape={image.shape}')

    # The training-data crop is tighter than what merge_detection's outer crop
    # produces, so feed it straight into the same preprocessing pipeline
    # (filter_color -> canny -> get_boxes) without cropping again.
    print('\n[1] filter_color (HSV mask 1..75 / 100..255 / 100..255)')
    filtered = detection.filter_color(image)
    cv2.imwrite(f'{OUT_DIR}/01_filtered.png', filtered)
    nonzero = int(np.count_nonzero(filtered.sum(axis=-1)))
    print(f'    nonzero pixels: {nonzero} / {image.shape[0]*image.shape[1]} '
          f'({100.0*nonzero/(image.shape[0]*image.shape[1]):.1f}%)')

    print('\n[2] canny edges')
    cannied = detection.canny(filtered)
    cv2.imwrite(f'{OUT_DIR}/02_cannied.png', cannied)
    print(f'    shape={cannied.shape}, edge pixels={int(np.count_nonzero(cannied[:,:,0]))}')

    print('\n[3] load model + warmup')
    model = detection.load_model()
    # Warm up to avoid timing the JIT cost
    detection.run_inference_for_single_image(model, np.zeros_like(cannied))

    print('\n[4] get_boxes (first inference) — should return 4 bounding boxes')
    t0 = time.time()
    boxes = detection.get_boxes(model, cannied)
    print(f'    found {len(boxes)} boxes in {time.time()-t0:.2f}s')
    for i, b in enumerate(boxes):
        # b is (box, class). box is normalized [ymin, xmin, ymax, xmax]
        box, cls = b
        print(f'      box {i}: cls={int(cls)} ({_label(int(cls))}) '
              f'norm=[{box[0]:.3f},{box[1]:.3f},{box[2]:.3f},{box[3]:.3f}]')

    # Also dump the full inference output (incl. low-confidence detections)
    print('\n[5] full raw inference on cannied (all detections, any confidence)')
    out = detection.run_inference_for_single_image(model, cannied)
    scores = out['detection_scores']
    boxes_all = out['detection_boxes']
    classes = out['detection_classes']
    n = min(10, int(out['num_detections']))
    print(f'    top {n} detections sorted by score:')
    order = np.argsort(scores)[::-1][:n]
    for idx in order:
        s = scores[idx]
        c = classes[idx]
        b = boxes_all[idx]
        print(f'      score={s:.3f} cls={int(c)} ({_label(int(c))}) '
              f'box=[{b[0]:.3f},{b[1]:.3f},{b[2]:.3f},{b[3]:.3f}]')

    # Annotate the cannied image with the top-4 boxes for eyeballing
    annotated = cannied.copy()
    h, w = cannied.shape[:2]
    for idx in np.argsort(scores)[::-1][:4]:
        s, c, b = scores[idx], int(classes[idx]), boxes_all[idx]
        y1, x1, y2, x2 = int(b[0]*h), int(b[1]*w), int(b[2]*h), int(b[3]*w)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(annotated, f'{_label(c)} {s:.2f}', (x1, max(15, y1-5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
    cv2.imwrite(f'{OUT_DIR}/03_annotated_top4.png', annotated)

    print(f'\nIntermediates written to {OUT_DIR}/')

    print('\n[6] full merge_detection (sets config.enabled briefly so the')
    print('    @run_if_enabled decorator lets it run)')
    from src.easymaple.common import config as cfg
    cfg.enabled = True
    try:
        # merge_detection re-crops, so to test fairly we'd pass a frame that,
        # after [120:h/2, w/4:3w/4], yields our image. We can fake this by
        # padding the image into a larger black canvas at the right offset.
        padded = _embed_for_merge_detection(image)
        result = detection.merge_detection(model, padded)
    finally:
        cfg.enabled = False
    print(f'    merge_detection returned: {result}')


def _label(c):
    return {1: 'up', 2: 'down', 3: 'left', 4: 'right'}.get(c, '?')


def _embed_for_merge_detection(crop):
    """Place the (already-cropped) training image inside a synthetic full
    frame so merge_detection's inner crop [120:h/2, w/4:3w/4] yields back
    approximately the same image. Training crop is [h*0.24:0.45, w*0.30:0.74].
    """
    ch, cw = crop.shape[:2]
    # We need a frame where [0.24h, 0.30w] -> [0.45h, 0.74w] equals our crop.
    # That means full h ≈ ch / (0.45 - 0.24) = ch / 0.21, full w ≈ cw / 0.44.
    full_h = int(ch / 0.21)
    full_w = int(cw / 0.44)
    canvas = np.zeros((full_h, full_w, 3), dtype=np.uint8)
    y0 = int(full_h * 0.24)
    x0 = int(full_w * 0.30)
    canvas[y0:y0+ch, x0:x0+cw] = crop
    return canvas


if __name__ == '__main__':
    main()
