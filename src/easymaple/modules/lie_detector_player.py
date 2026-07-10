"""Runtime driver that plays the Lie Detector mini-game by moving the mouse to
follow the shape the :class:`LieDetectorSolver` tracks.

This is the thin I/O layer around the (offline-validated) solver: it pulls
frames from the capture thread, asks the solver for the shape's location, and
drives the cursor there through a :class:`CursorPilot` — the human-motion layer
that turns raw tracker targets into continuous, speed/acceleration-bounded
mouse movement. The cursor parks at the box centre during the countdown (the
shape always spawns in the middle), follows the shape to the end, and never
teleports, whatever the tracker output does.

Mouse control, cursor readback and the capture frame source are injected, so
the class is importable and unit-testable on any platform. The defaults use
``win32api`` (imported lazily, Windows-only).

``solve()`` returns a structured outcome the notifier acts on::

    {"outcome": "completed" | "failed" | "timeout" | "no_box",
     "reached_track": bool,          # the tracker followed the fading shape
     "frames_moved": int}            # frames on which the mouse was driven

``completed`` + ``reached_track`` means the game was followed until the
play-box disappeared — the normal end of a passed game. ``failed`` means the
near-black punishment room (with its "Time Remaining" timer) followed the
game instead: the character is jailed and the bot must stay paused.
"""

import logging
import time
from collections import deque

import cv2
import numpy as np

from src.easymaple.common import config
from src.easymaple.detection.lie_detector_solver import CursorPilot, LieDetectorSolver

log = logging.getLogger(__name__)

# The Lie Detector FAILURE state: the character is teleported to a near-black
# jail room showing a "Time Remaining" timer (observed live 2026-07-10). If the
# frames right after the play-box vanished are overwhelmingly dark, we failed.
JAIL_DARK_GRAY = 20            # pixel counts as dark below this grayscale value
JAIL_DARK_FRAC = 0.70          # frame is "jail-dark" above this dark fraction


def _dark_fraction(frame):
    if frame.ndim == 3 and frame.shape[2] == 4:
        frame = frame[:, :, :3]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray < JAIL_DARK_GRAY))


def _default_move_mouse(screen_xy):
    import win32api
    win32api.SetCursorPos((int(screen_xy[0]), int(screen_xy[1])))


def _default_get_cursor():
    try:
        import win32api
        return win32api.GetCursorPos()
    except Exception:                      # pragma: no cover - Windows-only path
        return None


def _default_get_frame():
    cap = getattr(config, "capture", None)
    return getattr(cap, "frame", None) if cap is not None else None


class LieDetectorPlayer:
    """Drives the solver in a loop, moving the mouse like a human.

    :param move_mouse: callable ``(screen_x, screen_y) -> None``. Defaults to
        ``win32api.SetCursorPos``.
    :param get_frame: callable ``() -> BGR frame`` (the captured game window).
        Defaults to reading ``config.capture.frame``.
    :param get_cursor: callable ``() -> (x, y) | None``, the cursor's current
        screen position — where the glide starts. Defaults to
        ``win32api.GetCursorPos``.
    """

    def __init__(self, move_mouse=None, get_frame=None, get_cursor=None, fps=30,
                 use_net=True):
        # use_net: the learned shape detector handles the fade-to-invisible
        # variants; the solver degrades to classical tracking if the model
        # or torch is unavailable. Tests inject use_net=False to stay
        # deterministic on synthetic frames.
        self.solver = LieDetectorSolver(use_net=use_net)
        self.pilot = None
        self._move = move_mouse or _default_move_mouse
        self._get_frame = get_frame or _default_get_frame
        self._get_cursor = get_cursor or _default_get_cursor
        self._dt = 1.0 / fps

    def _window_origin(self):
        """Screen coordinates of the captured frame's top-left corner."""
        cap = getattr(config, "capture", None)
        win = getattr(cap, "window", None) if cap is not None else None
        if not win:
            return (0, 0)
        return (win.get("left", 0), win.get("top", 0))

    def _start_pilot(self, origin, fallback_xy):
        """Seed the pilot at the cursor's real position (frame coords) so the
        approach glide starts from where the hand actually is; fall back to the
        first target if the position cannot be read."""
        cur = self._get_cursor()
        if cur is not None:
            start = (cur[0] - origin[0], cur[1] - origin[1])
        else:
            start = fallback_xy
        self.pilot = CursorPilot(start)

    def solve(self, max_seconds=45, lost_grace=1.5):
        """Play until the play-box disappears (game over) or ``max_seconds``
        elapses; return the outcome dict (see module docstring).

        Each new captured frame advances the solver; the pilot then chases the
        solver's target — or the box centre while there is no shape yet — and
        the mouse is set to the pilot's position. When the box vanishes the
        pilot brakes to rest and, after ``lost_grace`` seconds without any
        target, the game is considered over.
        """
        ox, oy = self._window_origin()
        deadline = time.time() + max_seconds
        last_seen = time.time()
        had_box = reached_track = False
        moved = 0
        outcome = "timeout"
        last_frame = None
        dark_hist = deque(maxlen=8)     # darkness of the most recent frames
        while time.time() < deadline:
            frame = self._get_frame()
            if frame is not None and frame is not last_frame:
                last_frame = frame
                # Track recent frame darkness: at game-over time this window
                # holds the aftermath, and near-black means the jail.
                dark_hist.append(_dark_fraction(frame))
                # Tell the solver where our own cursor is — the reticle's glow
                # leaks past its green mask and must never be tracked.
                cursor = tuple(self.pilot.pos) if self.pilot is not None else None
                target = self.solver.process(frame, cursor_xy=cursor)
                reached_track = reached_track or self.solver.state == "TRACK"
                # Park at the centre (where the shape spawns) until there is a
                # shape to follow; box_center goes None once the box is gone.
                desired = target if target is not None else self.solver.box_center
                if desired is not None:
                    had_box = True
                    last_seen = time.time()
                if desired is not None and self.pilot is None:
                    self._start_pilot((ox, oy), desired)
                if self.pilot is not None:
                    x, y = self.pilot.step(desired)
                    self._move((ox + x, oy + y))
                    moved += 1
            if had_box and time.time() - last_seen > lost_grace:
                # Game over. A near-black aftermath is the punishment room —
                # the test was FAILED; anything else is the normal end.
                jailed = (len(dark_hist) >= 4
                          and float(np.median(dark_hist)) > JAIL_DARK_FRAC)
                outcome = "failed" if jailed else "completed"
                break
            time.sleep(self._dt)
        if not had_box:
            outcome = "no_box"
        log.info("LieDetectorPlayer: %s (moved %d frames, reached_track=%s)",
                 outcome, moved, reached_track)
        return {"outcome": outcome, "frames_moved": moved,
                "reached_track": reached_track}
