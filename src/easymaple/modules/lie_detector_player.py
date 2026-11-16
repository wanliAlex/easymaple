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

    {"outcome": "completed" | "failed" | "timeout" | "no_box" | "error",
     "reached_track": bool,          # the tracker followed the fading shape
     "success_seen": bool,           # the yellow SUCCESS! banner was shown
     "frames_moved": int}            # frames on which the mouse was driven

``completed`` + ``reached_track`` means the game was followed until the
play-box disappeared — the normal end of a passed game. ``failed`` means the
near-black punishment room (with its "Time Remaining" timer) followed the
game instead: the character is jailed and the bot must stay paused.
``timeout``: a box was seen but the game never visibly ran or ended (e.g. the
capture stalled); ``error``: per-frame processing kept failing.

In **shadow mode** the human plays while the solver follows along without
moving the mouse, ready to take over on request; the result additionally has
``took_over``, ``takeover_frame``, ``shadow_agreement`` /
``shadow_end_agreement`` / ``shadow_frames`` (how closely the solver tracked
the human while shadowing) and ``trace`` (per-frame log).
"""

import logging
import os
import threading
import time
from collections import deque
from datetime import datetime

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


# The pass state: a big yellow "SUCCESS!" banner across the middle of the
# play-box ~1 s before it closes. On all 293 recordings it separates passes
# (~10k banner pixels) from failures (<100) perfectly.
SUCCESS_HSV_LO = (20, 40, 225)
SUCCESS_HSV_HI = (40, 255, 255)
SUCCESS_MIN_PX = 3000


def _success_banner(frame, box):
    """True if the yellow SUCCESS! banner is showing in the play-box."""
    if box is None:
        return False
    x, y, w, h = box
    band = frame[y + int(h * 0.25):y + int(h * 0.75), x + int(w * 0.1):x + int(w * 0.9)]
    if band.size == 0:
        return False
    if band.ndim == 3 and band.shape[2] == 4:
        band = band[:, :, :3]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    return int(cv2.countNonZero(cv2.inRange(hsv, SUCCESS_HSV_LO, SUCCESS_HSV_HI))) > SUCCESS_MIN_PX


def _dark_fraction(frame):
    if frame.ndim == 3 and frame.shape[2] == 4:
        frame = frame[:, :, :3]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray < JAIL_DARK_GRAY))


def _pilot_steps(now, last_step, dt, max_steps=4):
    """How many 1/fps pilot steps are due at ``now``; returns ``(n, new_last_step)``.

    The fractional remainder carries over, so the pilot steps at 1/dt per
    second on average whatever the frame rate (rounding each frame on its own
    gave every 60 Hz frame a full step: double speed). A frame up to dt/4
    early still steps, so capture jitter around 30 Hz does not stutter 0-2-0.
    """
    if last_step is None:
        return 1, now
    n = int((now - last_step) / dt + 0.25)
    if n > max_steps:
        return max_steps, now
    return n, last_step + n * dt


# Game-over / outcome guards (each one a failure mode found in review):
GAMEOVER_MIN_FRAMES = 10       # new frames without the box before the game counts as
                               # over (a capture stall delivers none: not a game over)
MAX_FRAME_ERRORS = 30          # consecutive per-frame exceptions before giving up
TRACE_HALF_MAX = 300           # raw half-res box frames kept per game log (the last ~10 s)
TRACE_HALF_DT = 1.0 / 30       # ... at most this often


def _jailed(dark_hist):
    return len(dark_hist) >= 4 and float(np.median(dark_hist)) > JAIL_DARK_FRAC


class _TimerResolution:
    """1 ms Windows timer resolution while a game runs. sleep() is otherwise
    quantised to ~15.6 ms, which delays frame pick-up here and slows the
    capture thread's ~60 Hz pacing. No-op elsewhere."""

    def __enter__(self):
        self._on = False
        try:
            import ctypes
            self._on = ctypes.windll.winmm.timeBeginPeriod(1) == 0
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        if self._on:
            try:
                import ctypes
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass
        return False


class LieDetectorSession:
    """One Lie Detector game in progress, published as
    ``config.lie_detector_session`` while it runs.

    In shadow mode the human hands the mouse to the bot by pressing the
    takeover hotkey (:meth:`request_takeover`, from the listener) or by
    unticking "Shadow" in Settings mid-game; :meth:`takeover_requested` is
    what the player polls every frame.
    """

    def __init__(self, shadow, settings=None):
        self.shadow = shadow
        self._settings = settings
        self._event = threading.Event()

    def request_takeover(self):
        """Hotkey pressed. Returns True if this hands a shadowed game to the
        bot (first press while shadowing) — the caller confirms with a beep."""
        first = self.shadow and not self._event.is_set()
        self._event.set()
        return first

    def takeover_requested(self):
        if self._event.is_set():
            return True
        try:
            return self._settings is not None and not self._settings.get('shadow')
        except Exception:
            return False


TRACE_KEEP = 10               # game logs kept (each up to ~70 MB of raw frames)


def save_trace(result, out_dir=os.path.join("training_data", "lie_detector", "solver_logs"),
               keep=TRACE_KEEP):
    """Write a game's per-frame log (solver state and target, its cursor, the
    human cursor while shadowing, who was driving, capture time, processing
    ms, the last ~10 s of raw half-res box frames) next to the recorded clips,
    for post-mortems and for checking the solver against live play. The file
    name carries the outcome; only the newest ``keep`` *completed* games are
    kept, every other outcome stays (those are the post-mortems). Returns the
    path, or None. Slow (tens of MB): call it after acting on the outcome."""
    trace = result.get("trace")
    if not trace or not trace["state"]:
        return None

    def arr(seq):
        return np.array([(np.nan, np.nan) if p is None else p for p in seq], np.float32)

    os.makedirs(out_dir, exist_ok=True)
    mode = result.get("mode", "auto")
    outcome = result.get("outcome") or "unknown"
    path = os.path.join(out_dir, datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + f"_{mode}_{outcome}.npz")
    halves = list(trace.get("half", []))
    idx = list(trace.get("half_idx", []))
    shapes = {h.shape for h in halves}
    extra = {"half": np.stack(halves), "half_idx": np.array(idx)} if halves and len(shapes) == 1 else {}
    # Uncompressed: the camouflage barely compresses, and compressing took ~25 s.
    np.savez(path, state=np.array(trace["state"]), target=arr(trace["target"]),
             **extra,
             bot=arr(trace["bot"]), user=arr(trace["user"]),
             driving=np.array(trace["driving"], bool),
             t=np.array(trace["t"], np.float64), ms=np.array(trace["ms"], np.float32),
             **{k: np.array(-1 if v is None else v) for k, v in result.items()
                if k not in ("trace",)})
    # Rotate completed games only (and logs from before outcomes were in the
    # name: date_time_mode.npz).
    logs = sorted(f for f in os.listdir(out_dir)
                  if f.endswith("_completed.npz") or (f.endswith(".npz") and f.count("_") == 2))
    for old in logs[:-keep] if keep else []:
        try:
            os.remove(os.path.join(out_dir, old))
        except OSError:
            pass
    return path


_MOTION = {"solver": None, "error": None}
_MOTION_LOCK = threading.Lock()


def motion_solver(retry=False):
    """The motion solver, loaded once per process and warmed up (the first
    CUDA passes are slow and must not happen during a game). None if torch or
    the weights are unavailable; the error is logged. ``retry``: try again
    after an earlier failure (a transient CUDA init error must not disable it
    for the rest of the session)."""
    with _MOTION_LOCK:
        if _MOTION["solver"] is None and (_MOTION["error"] is None or retry):
            try:
                from src.easymaple.detection.lie_detector_motion import MotionLieDetectorSolver
                t0 = time.time()
                solver = MotionLieDetectorSolver()
                solver.warm_up()
                _MOTION["solver"] = solver
                _MOTION["error"] = None
                log.info("LieDetectorPlayer: motion solver ready on %s (%.1fs)",
                         solver.device, time.time() - t0)
            except Exception as e:
                _MOTION["error"] = e
                log.warning("LieDetectorPlayer: motion solver unavailable (%s)", e)
        return _MOTION["solver"]


def preload_motion_solver():
    """Load + warm the motion solver in the background (call at startup)."""
    threading.Thread(target=motion_solver, daemon=True, name="ld-preload").start()


DEFAULT_BOX = (145, 146, 746, 496)   # typical (refined) play-box in the 1054x824 capture
_BOX_KEY = "lie_detector_box"


def expected_box():
    """Where the play-box opened last time (frame coords), else the typical spot."""
    try:
        from src.easymaple.common import cache
        b = cache.load_cache().get(_BOX_KEY)
        if b and len(b) == 4:
            return tuple(int(v) for v in b)
    except Exception as e:
        log.debug("expected_box: %s", e)
    return DEFAULT_BOX


def remember_box(box):
    """Persist where the play-box opened, for the next game's pre-positioning."""
    if not box:
        return
    try:
        from src.easymaple.common import cache
        data = cache.load_cache()
        data[_BOX_KEY] = [int(v) for v in box]
        cache.save_cache(data)
    except Exception as e:
        log.warning("remember_box: %s", e)


SHADOW_TOL = 60                # px: the solver "agrees" with the human within this
SHADOW_END_FRAMES = 30         # ~1 s: the final stretch, where losing it costs the game


def timing_stats(trace):
    """Live frame rate and processing time while tracking (the first live
    failure ran at ~15 Hz without anyone noticing)."""
    t = [ti for ti, st in zip(trace["t"], trace["state"]) if st == "TRACK"]
    ms = [m for m, st in zip(trace["ms"], trace["state"]) if st == "TRACK"]
    hz = (len(t) - 1) / (t[-1] - t[0]) if len(t) > 1 and t[-1] > t[0] else 0.0
    return {"hz": round(float(hz), 1), "proc_ms": round(float(np.median(ms)), 1) if ms else 0.0}


def shadow_stats(trace):
    """How closely the solver's (virtual) cursor followed the human's while
    shadowing, over the frames it was tracking the invisible shape.

    Returns ``shadow_agreement`` (fraction within ``SHADOW_TOL``),
    ``shadow_end_agreement`` (the same over the last ``SHADOW_END_FRAMES`` of
    those frames) and ``shadow_frames`` (how many were compared); the
    agreements are None if nothing was comparable (e.g. an early takeover).
    """
    on = []
    for state, bot, user, driving in zip(trace["state"], trace["bot"], trace["user"],
                                         trace["driving"]):
        if driving or state != "TRACK" or bot is None or user is None:
            continue
        on.append(np.hypot(bot[0] - user[0], bot[1] - user[1]) < SHADOW_TOL)
    if not on:
        return {"shadow_agreement": None, "shadow_end_agreement": None, "shadow_frames": 0}
    return {"shadow_agreement": round(float(np.mean(on)), 3),
            "shadow_end_agreement": round(float(np.mean(on[-SHADOW_END_FRAMES:])), 3),
            "shadow_frames": len(on)}


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


def _default_frame_time(frame):
    """When the capture thread grabbed ``frame`` (perf_counter), or None."""
    cap = getattr(config, "capture", None)
    stamped = getattr(cap, "frame_stamped", None) if cap is not None else None
    if stamped is not None and stamped[0] is frame:
        return stamped[1]
    return None


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
                 use_net=True, solver=None, shadow=False, takeover=None, clock=None,
                 expected_box=None, frame_time=None):
        # expected_box: (x, y, w, h) in frame coords where the play-box will
        # open (last game's). Until it does, the cursor glides to its centre —
        # the shape spawns there — so it is waiting when the game starts.
        self.expected_box = expected_box
        self.last_box = None
        # shadow: the human plays and the solver only follows along (no mouse
        # moves) until takeover() returns True, then it drives from where the
        # human's cursor is. takeover defaults to "never".
        self.shadow = shadow
        self._takeover = takeover or (lambda: False)
        # Default: the motion solver (follows the invisible shape by the way
        # it moves against the panning camouflage; leak-proof — it cannot see
        # our cursor). Falls back to the previous solver if torch or the
        # motion weights are unavailable. Tests inject use_net=False (or a
        # solver) to stay deterministic on synthetic frames.
        self.solver = solver or self._default_solver(use_net)
        self.pilot = None
        self._move = move_mouse or _default_move_mouse
        self._get_frame = get_frame or _default_get_frame
        self._get_cursor = get_cursor or _default_get_cursor
        # Capture-time source (tests inject one): the capture thread's grab
        # stamp, else the time the frame is picked up. Not time.monotonic: on
        # Windows that ticks in ~15.6 ms steps, half a reference-frame gap.
        self._clock = clock or time.perf_counter
        self._frame_time = frame_time or (_default_frame_time if clock is None else (lambda f: None))
        self._dt = 1.0 / fps            # the pilot's step: it advances one step
                                        # per 1/fps s elapsed, however fast frames come
        import inspect
        try:
            self._solver_takes_t = "t" in inspect.signature(self.solver.process).parameters
        except (TypeError, ValueError):
            self._solver_takes_t = False

    @staticmethod
    def _default_solver(use_net):
        if use_net:
            solver = motion_solver()
            if solver is not None:
                solver.reset()
                return solver
        return LieDetectorSolver(use_net=use_net)

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

    def _user_cursor(self, origin):
        cur = self._get_cursor()
        return None if cur is None else (cur[0] - origin[0], cur[1] - origin[1])

    def solve(self, max_seconds=45, lost_grace=1.5):
        """Play until the game is over or ``max_seconds`` elapses; return the
        outcome dict (see module docstring).

        Each new captured frame advances the solver; the pilot then chases the
        solver's target — or the box centre while there is no shape yet, or
        where the box is expected before it opens — and the mouse is set to
        the pilot's position.

        The game counts as over only once it was really on (the tracker
        reached TRACK) and the box has then been gone for
        ``lost_grace`` s *and* ``GAMEOVER_MIN_FRAMES`` new frames: a box
        glimpsed during the countdown (skill effects) that vanishes again is
        not a game, and a capture stall (no new frames) is not a game over.
        At the deadline the outcome follows from what was seen: SUCCESS! →
        completed, a jail-dark screen → failed, never a box → no_box, else
        timeout. Persistent per-frame exceptions end it as ``error``.

        **Shadow mode** (``shadow=True``): the human plays; the solver runs on
        every frame with a *virtual* pilot but never touches the mouse, and its
        cursor is compared with the human's. The moment ``takeover()`` returns
        True the real pilot is seeded where the human's cursor is and the bot
        drives from there — already locked on, because it has been tracking
        the whole time.
        """
        with _TimerResolution():
            return self._solve(max_seconds, lost_grace)

    def _solve(self, max_seconds, lost_grace):
        ox, oy = self._window_origin()
        deadline = time.monotonic() + max_seconds
        last_seen = None
        box_seen = reached_track = success_seen = False
        lost_frames = 0
        moved = 0
        outcome = None
        last_frame = None
        dark_hist = deque(maxlen=8)     # darkness of the most recent frames
        shadowing = self.shadow
        takeover_frame = None
        frame_i = 0
        errors = consecutive_errors = 0
        trace = {"state": [], "target": [], "bot": [], "user": [], "driving": [],
                 "t": [], "ms": [], "half": deque(maxlen=TRACE_HALF_MAX),
                 "half_idx": deque(maxlen=TRACE_HALF_MAX)}
        last_half_t = None
        last_step = None
        while time.monotonic() < deadline:
            frame = self._get_frame()
            if frame is not None and frame is not last_frame:
                last_frame = frame
                try:
                    now = self._frame_time(frame)
                    if now is None:
                        now = self._clock()
                    if shadowing and self._takeover():
                        shadowing = False
                        takeover_frame = frame_i
                        # Hand over from wherever the human's hand is right now.
                        user = self._user_cursor((ox, oy))
                        if user is not None:
                            self.pilot = CursorPilot(user)
                        log.info("LieDetectorPlayer: takeover at frame %d (%s)", frame_i,
                                 self.solver.state)
                    # Track recent frame darkness: at game-over time this window
                    # holds the aftermath, and near-black means the jail.
                    dark_hist.append(_dark_fraction(frame))
                    # Tell the solver where our own cursor is — the reticle's glow
                    # leaks past its green mask and must never be tracked.
                    cursor = tuple(self.pilot.pos) if self.pilot is not None else None
                    # The capture time lets the motion solver space its reference
                    # frames in time as in the recordings it was trained on.
                    t_proc = time.perf_counter()
                    if self._solver_takes_t:
                        target = self.solver.process(frame, cursor_xy=cursor, t=now)
                    else:
                        target = self.solver.process(frame, cursor_xy=cursor)
                    reached_track = reached_track or self.solver.state == "TRACK"
                    box = getattr(self.solver, "box", None)
                    # Only once the game is on: before START the box is plain
                    # camouflage, whose bright tan can pass for the banner.
                    if reached_track and not success_seen and box is not None:
                        success_seen = _success_banner(frame, box)
                    # Park at the centre (where the shape spawns) until there is a
                    # shape to follow; box_center goes None once the box is gone.
                    desired = target if target is not None else self.solver.box_center
                    if desired is not None:
                        box_seen = True
                        last_seen = time.monotonic()
                        lost_frames = 0
                        if box is not None:
                            self.last_box = tuple(int(v) for v in box)
                    else:
                        lost_frames += 1
                        if not reached_track and self.expected_box is not None:
                            # No game yet — the box has not opened, or what looked
                            # like it vanished again: wait where it will open.
                            x, y, w, h = self.expected_box
                            desired = (x + w / 2.0, y + h / 2.0)
                    if desired is not None and self.pilot is None:
                        self._start_pilot((ox, oy), desired)
                    if self.pilot is not None:
                        # One pilot step per 1/fps s elapsed, the remainder carried
                        # over: its speed and acceleration caps stay real-time
                        # whatever the frame rate (at 60 Hz capture every other
                        # frame steps). After a stall (> 4 periods) it resumes
                        # rather than sprinting to catch up.
                        n, last_step = _pilot_steps(now, last_step, self._dt)
                        for _ in range(n):
                            x, y = self.pilot.step(desired)
                        if n and not shadowing:
                            self._move((ox + x, oy + y))
                            moved += 1
                    trace["ms"].append((time.perf_counter() - t_proc) * 1000)
                    trace["t"].append(now)
                    # Raw (uncompressed) half-res box frames: the recordings the
                    # model was trained on are MP4-compressed; live frames are not.
                    half = getattr(self.solver, "last_half", None)
                    if (half is not None and self.solver.state in ("ACQUIRE", "TRACK")
                            and (last_half_t is None or now - last_half_t >= 0.9 * TRACE_HALF_DT)):
                        trace["half"].append(half)
                        trace["half_idx"].append(frame_i)
                        last_half_t = now
                    trace["state"].append(self.solver.state)
                    trace["target"].append(desired)
                    trace["bot"].append(None if self.pilot is None else tuple(self.pilot.pos))
                    trace["user"].append(self._user_cursor((ox, oy)) if shadowing else None)
                    trace["driving"].append(not shadowing)
                    frame_i += 1
                    consecutive_errors = 0
                except Exception as e:
                    # One bad frame must not abandon the game: the pilot keeps
                    # its course and the next frame is tried. Persistent errors
                    # (CUDA gone, desktop locked) end it so the human is alerted.
                    errors += 1
                    consecutive_errors += 1
                    if errors <= 3:
                        log.exception("LieDetectorPlayer: frame %d failed: %s", frame_i, e)
                    if consecutive_errors >= MAX_FRAME_ERRORS:
                        outcome = "error"
                        break
            if (outcome is None and reached_track and last_seen is not None
                    and lost_frames >= GAMEOVER_MIN_FRAMES
                    and time.monotonic() - last_seen > lost_grace):
                # Game over. A near-black aftermath is the punishment room —
                # the test was FAILED; anything else is the normal end. The
                # SUCCESS! banner overrules the darkness: map events darken
                # the screen too (2026-10-26, right after a pass).
                outcome = "failed" if _jailed(dark_hist) and not success_seen else "completed"
                break
            # Short poll for the next capture frame. (A fixed 1/30 s sleep
            # after processing halved the live frame rate: ~15 Hz.)
            time.sleep(0.001)
        if outcome is None:
            if success_seen:
                outcome = "completed"
            elif _jailed(dark_hist):
                outcome = "failed"      # e.g. the box was never recognised
            elif not box_seen:
                outcome = "no_box"
            else:
                outcome = "timeout"
        result = {"outcome": outcome, "frames_moved": moved, "errors": errors,
                  "reached_track": reached_track, "success_seen": success_seen}
        result.update(timing_stats(trace), trace=trace, mode="shadow" if self.shadow else "auto",
                      solver=type(self.solver).__name__, box=self.last_box)
        if self.shadow:
            result.update(shadow_stats(trace), took_over=takeover_frame is not None,
                          takeover_frame=takeover_frame)
        log.info("LieDetectorPlayer: %s (%s, moved %d frames, reached_track=%s, success=%s, "
                 "%.1f Hz, %.0f ms/frame, %d errors%s)",
                 outcome, result["solver"], moved, reached_track, success_seen, result["hz"],
                 result["proc_ms"], errors,
                 "" if not self.shadow else
                 f", shadow agreement={result['shadow_agreement']}, took_over={result['took_over']}")
        return result
