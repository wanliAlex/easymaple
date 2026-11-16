"""Records a short clip of the game window on demand (e.g. when the Lie
Detector mini-game is detected) for later training. Non-blocking: each call
spawns a daemon thread so callers like the notifier can continue to their
own blocking work (siren) while the clip is written."""

import logging
import os
import threading
import time
from datetime import datetime

import cv2
import numpy as np

log = logging.getLogger(__name__)

DEFAULT_OUT_DIR = os.path.join("training_data", "lie_detector")

_lock = threading.Lock()
_recording = False


def is_recording():
    """True while a clip is currently being written."""
    with _lock:
        return _recording


def _default_get_frame():
    """Reads the latest captured frame from shared config state."""
    from src.easymaple.common import config
    cap = getattr(config, "capture", None)
    return getattr(cap, "frame", None) if cap is not None else None


def _to_bgr(frame):
    """Converts an mss BGRA frame to BGR; passes BGR through unchanged."""
    if frame.ndim == 3 and frame.shape[2] == 4:
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    return frame


def _record(duration_s, fps, out_dir, get_frame, first_frame):
    global _recording
    writer = None
    try:
        first = _to_bgr(first_frame)
        height, width = first.shape[:2]

        os.makedirs(out_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(out_dir, f"{stamp}.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(path, fourcc, fps, (width, height))
        if not writer.isOpened():
            log.error("Recorder: failed to open VideoWriter at %s", path)
            return

        log.info("Recorder: writing %.0fs clip to %s", duration_s, path)
        interval = 1.0 / fps
        end = time.time() + duration_s
        stamps = []
        while time.time() < end:
            frame = get_frame()
            if frame is not None:
                frame = _to_bgr(frame)
                if frame.shape[:2] != (height, width):
                    frame = cv2.resize(frame, (width, height))
                writer.write(frame)
                stamps.append(time.time())
            time.sleep(interval)
        # The real time of every written frame: the container says `fps`, but
        # the actual rate is lower (~24.6 fps: the sleep comes on top of the
        # grab + encode), and the solver's timing is calibrated on real time.
        try:
            np.save(path[:-4] + "_t.npy", np.array(stamps, np.float64))
        except Exception as e:
            log.warning("Recorder: could not save frame times: %s", e)
        log.info("Recorder: finished clip %s", path)
    except Exception as e:
        log.exception("Recorder: clip failed: %s", e)
    finally:
        if writer is not None:
            writer.release()
        with _lock:
            _recording = False


def record_clip(duration_s: float = 30, fps: float = 30, out_dir: str = DEFAULT_OUT_DIR, get_frame=None) -> bool:
    """Starts recording a clip in a background daemon thread and returns
    immediately. No-op (returns False) if a recording is already running or
    no frame is available."""
    global _recording
    if get_frame is None:
        get_frame = _default_get_frame
    with _lock:
        if _recording:
            log.info("Recorder: recording already in progress; skipping")
            return False
        first = get_frame()
        if first is None:
            log.warning("Recorder: no frame available; aborting clip")
            return False
        _recording = True
    thread = threading.Thread(
        target=_record,
        args=(duration_s, fps, out_dir, get_frame, first),
        daemon=True,
    )
    thread.start()
    return True
