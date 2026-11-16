"""Build the training dataset for the Lie Detector shape net.

For every human-played recording (19 easy + 3 hard-variant): lock the play
box, extract the human's green-reticle position per frame (the label), and
store the network's 2-channel representation of every active-window frame
(cursor inpainted — see lie_detector_net) plus the label positions in NET
coordinates. One .npz per clip under training_data/lie_detector/dataset/.

Usage:
    python private_scripts/lie_detector/build_dataset.py
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import eval_solver as E  # noqa: E402
from src.easymaple.detection import lie_detector_solver as S  # noqa: E402
from src.easymaple.detection import lie_detector_net as N  # noqa: E402

OUT_DIR = os.path.join(E.VID_DIR, "dataset")


def build(vid):
    cap = cv2.VideoCapture(os.path.join(E.VID_DIR, vid))
    frames = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        frames.append(fr)
    cap.release()

    box = None
    for fr in frames:
        box = S.detect_play_box(fr)
        if box:
            break
    if box is None:
        print(f"{vid}: no play box; skipped")
        return
    x, y, w, h = box
    m = S.BOX_INNER_MARGIN

    # Labels: green reticle centroid per frame, in interior coords.
    gts = []
    for f, fr in enumerate(frames):
        gt = E.gt_cursor(fr)
        gts.append(None if gt is None else (gt[0] - (x + m), gt[1] - (y + m)))
    rows = [(f, None, None, None, g) for f, g in enumerate(gts)]
    s, e = E.puzzle_start_index(rows), E.puzzle_end_index(rows)
    if e - s < 60:
        print(f"{vid}: active window too short ({e - s}); skipped")
        return

    # Store every frame the net could need: the active window plus the stack
    # history before it.
    f0 = max(0, s - (N.N_FRAMES - 1) * N.FRAME_STEP)
    f1 = min(e, len(frames))
    iw, ih = w - 2 * m, h - 2 * m

    # NET-scale BGR plate for the reticle fill (see lie_detector_net: the fill
    # must be indistinguishable from background, and decoys make any residual
    # fill cue uncorrelated with the label).
    rng = np.random.RandomState(hash(vid) % (2 ** 31))
    sample = [N.resize_net(frames[f][y + m:y + h - m, x + m:x + w - m])
              for f in range(s, f1, 6)]
    plate_net = np.median(np.array(sample), axis=0).astype(np.uint8)

    chans, labels, fidx = [], [], []
    for f in range(f0, f1):
        crop = frames[f][y + m:y + h - m, x + m:x + w - m]
        chans.append(N.frame_channels(crop, plate_net, rng, n_decoys=2))
        g = gts[f]
        if g is None:
            labels.append((np.nan, np.nan))
        else:
            labels.append((g[0] * N.NET_W / iw, g[1] * N.NET_H / ih))
        fidx.append(f)

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, vid.replace(".mp4", ".npz"))
    np.savez_compressed(
        out,
        chans=np.array(chans, np.uint8),          # (N, NET_H, NET_W, 2)
        labels=np.array(labels, np.float32),      # (N, 2) in NET coords, nan = no GT
        fidx=np.array(fidx, np.int32),
        active_start=s, active_end=e, frame0=f0,
    )
    n_lab = int(np.isfinite(np.array(labels)[:, 0]).sum())
    print(f"{vid}: {len(chans)} frames stored, {n_lab} labeled "
          f"(active {s}-{e}) -> {os.path.basename(out)}")


if __name__ == "__main__":
    for vid in sorted(os.listdir(E.VID_DIR)):
        if not vid.endswith(".mp4") or vid in E.BOT_PLAYED:
            continue
        build(vid)
