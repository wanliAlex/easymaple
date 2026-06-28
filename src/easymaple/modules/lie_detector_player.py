"""Runtime driver that plays the Lie Detector mini-game by moving the mouse to
follow the shape the :class:`LieDetectorSolver` tracks.

This is the thin I/O layer around the (offline-validated) solver: it pulls
frames from the capture thread, asks the solver for the shape's location, maps
that from frame coordinates to screen coordinates, and moves the cursor there.

Mouse control and the capture frame source are injected, so the class is
importable and unit-testable on any platform. The default mouse mover uses
``win32api.SetCursorPos`` (imported lazily, Windows-only).

NOTE: the solver/tracker is validated offline against recorded clips (see
``private_scripts/lie_detector/eval_solver.py`` and the design doc). The live
control loop here has not been exercised against the running game; treat it as
the integration entry point to validate in-game, not a verified auto-solver.
"""

import logging
import time

from src.easymaple.common import config
from src.easymaple.detection.lie_detector_solver import LieDetectorSolver

log = logging.getLogger(__name__)


def _default_move_mouse(screen_xy):
    import win32api
    win32api.SetCursorPos((int(screen_xy[0]), int(screen_xy[1])))


def _default_get_frame():
    cap = getattr(config, "capture", None)
    return getattr(cap, "frame", None) if cap is not None else None


class LieDetectorPlayer:
    """Drives the solver in a loop, moving the mouse to follow the shape.

    :param move_mouse: callable ``(screen_x, screen_y) -> None``. Defaults to
        ``win32api.SetCursorPos``.
    :param get_frame: callable ``() -> BGR frame`` (the captured game window).
        Defaults to reading ``config.capture.frame``.
    """

    def __init__(self, move_mouse=None, get_frame=None, fps=30):
        self.solver = LieDetectorSolver()
        self._move = move_mouse or _default_move_mouse
        self._get_frame = get_frame or _default_get_frame
        self._dt = 1.0 / fps

    def _window_origin(self):
        """Screen coordinates of the captured frame's top-left corner."""
        cap = getattr(config, "capture", None)
        win = getattr(cap, "window", None) if cap is not None else None
        if not win:
            return (0, 0)
        return (win.get("left", 0), win.get("top", 0))

    def solve(self, max_seconds=30, lost_grace=1.5):
        """Run the play loop until the play-box disappears (game over) or
        ``max_seconds`` elapses. Returns the number of frames the mouse moved.

        Frames where the solver returns no target (box not yet found, or the
        game has ended) are tolerated up to ``lost_grace`` seconds before the
        loop exits.
        """
        moves = 0
        ox, oy = self._window_origin()
        deadline = time.time() + max_seconds
        last_target_t = time.time()
        had_box = False
        while time.time() < deadline:
            frame = self._get_frame()
            if frame is not None:
                target = self.solver.process(frame)
                if target is not None:
                    had_box = True
                    last_target_t = time.time()
                    self._move((ox + target[0], oy + target[1]))
                    moves += 1
                elif had_box and time.time() - last_target_t > lost_grace:
                    break          # box gone after the game -> done
            time.sleep(self._dt)
        log.info("LieDetectorPlayer: finished, moved mouse on %d frames", moves)
        return moves
