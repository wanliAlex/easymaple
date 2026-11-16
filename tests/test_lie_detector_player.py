"""Tests for LieDetectorPlayer: the runtime driver that plays the mini-game.

Uses the synthetic game frames from test_lie_detector_solver. The player must
move the cursor like a human — park at the box centre during the countdown
(the shape always spawns in the middle), glide after the tracked shape with
bounded speed/acceleration (never teleport), and report a structured outcome
the notifier can act on.
"""
import numpy as np

from test_lie_detector_solver import BOX, FRAME_H, FRAME_W, make_frame, synth_sequence
from src.easymaple.detection import lie_detector_solver as S
from src.easymaple.modules.lie_detector_player import LieDetectorPlayer


DARK = np.full((FRAME_H, FRAME_W, 3), 20, np.uint8)     # no play-box anywhere


class FrameFeed:
    """get_frame stub: yields each frame once, then repeats the last one.
    ``clock`` is the matching capture time: one frame per 1/240 s."""

    def __init__(self, frames):
        self.frames = frames
        self.i = 0

    def __call__(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f

    def clock(self):
        return self.i / 240.0


def _play(frames, start=(30.0, 40.0), max_seconds=30):
    moves = []
    feed = FrameFeed(frames)
    player = LieDetectorPlayer(
        move_mouse=moves.append,
        get_frame=feed,
        get_cursor=lambda: start,
        fps=240,                                        # fast-forward the loop
        use_net=False,                                  # synthetic frames: classical
        clock=feed.clock,
    )
    result = player.solve(max_seconds=max_seconds, lost_grace=0.05)
    return result, np.array(moves, float) if moves else np.zeros((0, 2))


def test_player_parks_at_center_then_follows_to_the_end_without_teleports():
    n_countdown = 35
    countdown = [make_frame((0, 0), 0.0) for _ in range(n_countdown)]  # box, no shape
    seq = synth_sequence()
    # a bright, box-less aftermath: the normal (passed) end of a game
    game_over = [np.full((FRAME_H, FRAME_W, 3), 90, np.uint8) for _ in range(30)]
    result, moves = _play(countdown + [f for f, _, _ in seq] + game_over)

    assert result["outcome"] == "completed", result
    assert result["reached_track"], "player never reached TRACK"
    assert result["frames_moved"] == len(moves) > 0

    # Human motion: continuous from the starting cursor position, every step
    # inside the pilot's speed cap — across countdown, acquisition handoff,
    # tracking and re-acquisitions alike.
    path = np.vstack([(30.0, 40.0), moves])
    steps = np.linalg.norm(np.diff(path, axis=0), axis=1)
    assert steps.max() <= S.PILOT_SPEED + 1e-6, f"teleport: {steps.max():.0f}px step"

    # The shape spawns in the middle: by the end of the countdown the cursor
    # must be parked at the box centre, waiting for it.
    x, y, w, h = BOX
    center = (x + w / 2, y + h / 2)
    at_countdown_end = moves[n_countdown - 1]
    assert np.hypot(*(at_countdown_end - center)) < 40, \
        f"not parked at centre by countdown end: {at_countdown_end} vs {center}"

    # The pass criterion: still on the shape at the END of the game.
    truth_end = np.array(seq[-1][1])
    end_moves = moves[n_countdown + len(seq) - 3:n_countdown + len(seq)]
    end_err = min(np.hypot(*(m - truth_end)) for m in end_moves)
    assert end_err < 90, f"lost the shape at the end ({end_err:.0f}px off)"


def test_player_reports_failed_when_the_jail_room_follows_the_game(monkeypatch):
    """The Lie Detector failure state (observed live 2026-07-10): right after
    the play-box vanishes the character is in a near-black punishment room.
    The player must report outcome='failed' so the notifier keeps the bot
    paused instead of celebrating and resuming inside the jail."""
    from src.easymaple.modules import lie_detector_player as P
    # A failed game shows no SUCCESS! banner (the synthetic camouflage is
    # brighter than the real one and would read as it).
    monkeypatch.setattr(P, "_success_banner", lambda frame, box: False)
    countdown = [make_frame((0, 0), 0.0) for _ in range(30)]
    seq = synth_sequence()
    jail = [np.full((FRAME_H, FRAME_W, 3), 5, np.uint8) for _ in range(40)]
    result, moves = _play(countdown + [f for f, _, _ in seq] + jail)
    assert result["outcome"] == "failed", result
    assert result["reached_track"]


def test_player_reports_no_box_when_game_never_appears():
    result, moves = _play([DARK.copy() for _ in range(10)], max_seconds=0.8)
    assert result["outcome"] == "no_box"
    assert result["frames_moved"] == 0 and len(moves) == 0
    assert not result["reached_track"]


def test_player_reports_timeout_when_game_never_ends():
    frames = [make_frame((0, 0), 0.0) for _ in range(400)]   # box forever, no shape
    result, moves = _play(frames, max_seconds=0.8)
    assert result["outcome"] == "timeout"
    assert len(moves) > 0                                    # it was parking meanwhile
    assert not result["reached_track"]


def test_player_seeds_at_target_when_cursor_position_unavailable():
    """If the physical cursor can't be read, the pilot seeds at the first
    desired point instead of crashing (one-off; still smooth afterwards)."""
    frames = [make_frame((0, 0), 0.0) for _ in range(30)]
    moves = []
    player = LieDetectorPlayer(
        move_mouse=moves.append,
        get_frame=FrameFeed(frames),
        get_cursor=lambda: None,
        fps=240,
        use_net=False,
    )
    player.solve(max_seconds=0.5, lost_grace=0.05)
    assert len(moves) > 0
    x, y, w, h = BOX
    assert np.hypot(moves[0][0] - (x + w / 2), moves[0][1] - (y + h / 2)) < 5


# --- Shadow mode -------------------------------------------------------------
class ShadowFeed(FrameFeed):
    """FrameFeed whose get_cursor stub is the HUMAN's hand: it sits on the
    true shape of the frame last served (or at a fixed start before that)."""

    def __init__(self, frames, truths, start=(30.0, 40.0)):
        super().__init__(frames)
        self.truths, self.start = truths, start

    def cursor(self):
        k = self.i - 1
        if 0 <= k < len(self.truths) and self.truths[k] is not None:
            return self.truths[k]
        return self.start


def _shadow_game():
    countdown = [make_frame((0, 0), 0.0) for _ in range(35)]
    seq = synth_sequence()
    game_over = [np.full((FRAME_H, FRAME_W, 3), 90, np.uint8) for _ in range(30)]
    frames = countdown + [f for f, _, _ in seq] + game_over
    truths = [None] * len(countdown) + [t for _, t, _ in seq] + [None] * len(game_over)
    return frames, truths, len(countdown)


def test_shadow_mode_never_moves_the_mouse_and_reports_agreement():
    frames, truths, _ = _shadow_game()
    feed = ShadowFeed(frames, truths)
    moves = []
    player = LieDetectorPlayer(move_mouse=moves.append, get_frame=feed, get_cursor=feed.cursor,
                               fps=240, use_net=False, shadow=True, clock=feed.clock)
    result = player.solve(max_seconds=30, lost_grace=0.05)
    assert result["outcome"] == "completed" and result["reached_track"]
    assert moves == [] and result["frames_moved"] == 0, "shadowing must not touch the mouse"
    assert result["took_over"] is False and result["takeover_frame"] is None
    assert result["shadow_frames"] > 20
    assert result["shadow_agreement"] > 0.5          # it followed the same shape as the human
    assert len(result["trace"]["state"]) == len(result["trace"]["bot"])


def test_shadow_takeover_drives_from_the_humans_cursor_without_teleporting():
    frames, truths, n_countdown = _shadow_game()
    feed = ShadowFeed(frames, truths)
    k = n_countdown + 50                              # mid-game, shape well faded
    moves = []
    player = LieDetectorPlayer(move_mouse=moves.append, get_frame=feed, get_cursor=feed.cursor,
                               fps=240, use_net=False, shadow=True, clock=feed.clock,
                               takeover=lambda: feed.i > k)
    result = player.solve(max_seconds=30, lost_grace=0.05)
    assert result["took_over"] and result["takeover_frame"] == k
    assert result["outcome"] == "completed"
    assert result["frames_moved"] == len(moves) > 0
    # the first real move starts from where the human's hand was at takeover
    hand = np.array(truths[k])
    path = np.vstack([hand, np.array(moves, float)])
    steps = np.linalg.norm(np.diff(path, axis=0), axis=1)
    assert steps.max() <= S.PILOT_SPEED + 1e-6, f"teleport: {steps.max():.0f}px step"
    # and it is still on the shape at the end of the game
    truth_end = np.array(truths[n_countdown + len(synth_sequence()) - 1])
    assert min(np.hypot(*(m - truth_end)) for m in np.array(moves[-25:])) < 90


def test_shadow_takeover_before_the_game_drives_from_the_start():
    frames, truths, _ = _shadow_game()
    feed = ShadowFeed(frames, truths)
    moves = []
    player = LieDetectorPlayer(move_mouse=moves.append, get_frame=feed, get_cursor=feed.cursor,
                               fps=240, use_net=False, shadow=True, clock=feed.clock,
                               takeover=lambda: True)
    result = player.solve(max_seconds=30, lost_grace=0.05)
    assert result["took_over"] and result["takeover_frame"] == 0
    assert result["frames_moved"] > 0 and result["shadow_agreement"] is None



def test_player_prepositions_at_the_expected_box_before_it_opens():
    """Seen the prep banner but no play-box yet: glide to where it will open
    (the shape spawns at its centre), so the cursor is waiting at START."""
    x, y, w, h = BOX
    center = np.array([x + w / 2, y + h / 2])
    frames = [DARK.copy() for _ in range(40)] + [make_frame((0, 0), 0.0) for _ in range(10)]
    moves = []
    feed = FrameFeed(frames)
    player = LieDetectorPlayer(move_mouse=moves.append, get_frame=feed, get_cursor=lambda: (30.0, 40.0),
                               fps=240, use_net=False, clock=feed.clock, expected_box=BOX)
    player.solve(max_seconds=5, lost_grace=0.05)
    assert len(moves) >= 40, "moved during the prep, before the box existed"
    assert np.hypot(*(np.array(moves[39]) - center)) < 20, "waiting at the box centre when it opens"


def test_preposition_parking_is_not_a_game():
    """A false alarm (no box ever) must still end as no_box."""
    feed = FrameFeed([DARK.copy() for _ in range(10)])
    moves = []
    player = LieDetectorPlayer(move_mouse=moves.append, get_frame=feed, get_cursor=lambda: (30.0, 40.0),
                               fps=240, use_net=False, clock=feed.clock, expected_box=BOX)
    result = player.solve(max_seconds=0.6, lost_grace=0.05)
    assert result["outcome"] == "no_box"


def test_pilot_steps_stay_real_time_at_any_frame_rate():
    """The pilot advances 30 steps per second of capture time whether frames
    arrive at 60 Hz (every other frame steps), 30 Hz with jitter (one step
    each, no 0-2 stutter) or 15 Hz (two per frame)."""
    from src.easymaple.modules.lie_detector_player import _pilot_steps
    dt = 1 / 30

    def run(times):
        last, out = None, []
        for t in times:
            n, last = _pilot_steps(t, last, dt)
            out.append(n)
        return out

    n60 = run([k / 60 for k in range(601)])
    assert abs(sum(n60) - 300) <= 2, "60 Hz frames must not double the pilot speed"
    assert max(n60) == 1
    jitter = np.cumsum([dt * (0.8 if k % 2 else 1.2) for k in range(300)])
    assert run(jitter)[1:] == [1] * 299
    n15 = run([k / 15 for k in range(151)])
    assert n15[1:] == [2] * 150
    assert run([0.0, 1.0])[1] == 4, "a stall resumes instead of sprinting"


# --- Game-over / outcome guards (failure modes found in review) -------------
class ScriptedSolver:
    """Stands in for the solver: ``script`` gives (state, box, target) per
    processed frame; state "raise" raises instead."""

    def __init__(self, script):
        self.script, self.i = script, 0
        self.state, self.box, self.last_half = "WAIT", None, None

    def process(self, frame, cursor_xy=None, t=None):
        state, box, target = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        if state == "raise":
            raise RuntimeError("boom")
        self.state, self.box = state, box
        return target

    @property
    def box_center(self):
        if self.box is None:
            return None
        x, y, w, h = self.box
        return (x + w / 2.0, y + h / 2.0)


LIT = 120                                   # neither jail-dark nor banner-yellow
SBOX = (10, 10, 60, 40)


def _scripted(script, frames=None, max_seconds=3.0, lost_grace=0.05, **kw):
    frames = frames if frames is not None else [np.full((80, 100, 3), LIT, np.uint8) for _ in script]
    feed = FrameFeed(frames)
    moves = []
    player = LieDetectorPlayer(move_mouse=moves.append, get_frame=feed, get_cursor=lambda: (0.0, 0.0),
                               fps=240, clock=feed.clock, solver=ScriptedSolver(script), **kw)
    return player.solve(max_seconds=max_seconds, lost_grace=lost_grace), moves


def test_a_box_glimpsed_during_the_countdown_does_not_end_the_session():
    """Combat effects can pass for the box for a moment before the real one
    opens. Its disappearing is not a game over: keep waiting, play the game."""
    script = ([("WAIT", None, None)] * 5 + [("ACQUIRE", SBOX, None)] * 5
              + [("WAIT", None, None)] * 200                       # > lost_grace of no box
              + [("ACQUIRE", SBOX, None)] * 10 + [("TRACK", SBOX, (40.0, 30.0))] * 30
              + [("WAIT", None, None)] * 30)
    result, _ = _scripted(script)
    assert result["reached_track"] and result["outcome"] == "completed"


def test_a_capture_stall_after_the_game_started_is_not_a_pass():
    """No new frames is not "the box is gone": without positive evidence the
    game must not be declared over (the bot would resume mid-game)."""
    script = [("ACQUIRE", SBOX, None)] * 5 + [("TRACK", SBOX, (40.0, 30.0))] * 20
    result, _ = _scripted(script, max_seconds=0.5)           # then the feed freezes
    assert result["outcome"] == "timeout"


def test_one_bad_frame_does_not_abandon_the_game():
    script = ([("ACQUIRE", SBOX, None)] * 5 + [("TRACK", SBOX, (40.0, 30.0))] * 10
              + [("raise", None, None)] * 3 + [("TRACK", SBOX, (40.0, 30.0))] * 10
              + [("WAIT", None, None)] * 30)
    result, moves = _scripted(script)
    assert result["outcome"] == "completed" and result["errors"] == 3
    assert len(moves) > 20


def test_persistent_errors_end_the_game_as_error():
    script = [("ACQUIRE", SBOX, None)] * 5 + [("raise", None, None)] * 60
    result, _ = _scripted(script)
    assert result["outcome"] == "error"


def test_a_missed_game_that_ends_in_the_jail_is_a_failure_not_no_box():
    """No box recognised at all, but the screen went jail-dark: failed (the
    bot must stay paused), not "false alarm, resume"."""
    script = [("WAIT", None, None)] * 50
    frames = [np.zeros((80, 100, 3), np.uint8) for _ in script]
    result, _ = _scripted(script, frames=frames, max_seconds=0.4)
    assert result["outcome"] == "failed"


def test_a_dark_screen_after_success_is_still_a_pass():
    """Live 2026-10-26: SUCCESS! showed, then an event darkened the map ("Powerful
    monsters ... have appeared") and the dark aftermath was read as the jail.
    The banner is proof of a pass; the bot must resume."""
    box = (10, 10, 260, 160)
    lit = np.full((200, 300, 3), LIT, np.uint8)
    banner = lit.copy()
    banner[60:120, 40:240] = (0, 255, 255)                  # yellow SUCCESS! text
    dark = np.zeros_like(lit)
    script = ([("ACQUIRE", box, None)] * 5 + [("TRACK", box, (100.0, 80.0))] * 20
              + [("TRACK", box, (100.0, 80.0))] * 5 + [("WAIT", None, None)] * 40)
    frames = [f.copy() for f in [lit] * 25 + [banner] * 5 + [dark] * 40]   # each a new capture
    result, _ = _scripted(script, frames=frames)
    assert result["success_seen"]
    assert result["outcome"] == "completed", result


def test_failed_game_logs_survive_rotation(tmp_path, monkeypatch):
    """Only completed games rotate out: on 2026-10-13 ten passes deleted the
    logs of the 2026-10-11 failures that the post-mortems needed."""
    import datetime as dt
    from src.easymaple.modules import lie_detector_player as P

    clock = iter(dt.datetime(2026, 10, 13, 8, 0, s) for s in range(60))

    class FakeDatetime:
        @staticmethod
        def now():
            return next(clock)

    monkeypatch.setattr(P, "datetime", FakeDatetime)
    trace = dict(state=["TRACK"], target=[(1.0, 2.0)], bot=[(1.0, 2.0)], user=[None],
                 driving=[True], t=[0.0], ms=[1.0])
    outcomes = ["failed", "completed", "completed", "timeout", "completed", "completed"]
    for o in outcomes:
        P.save_trace(dict(outcome=o, mode="auto", trace=trace), out_dir=str(tmp_path), keep=2)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert [n for n in names if "failed" in n or "timeout" in n] == [
        "2026-10-13_08-00-00_auto_failed.npz", "2026-10-13_08-00-03_auto_timeout.npz"]
    assert [n for n in names if n.endswith("_completed.npz")] == [
        "2026-10-13_08-00-04_auto_completed.npz", "2026-10-13_08-00-05_auto_completed.npz"]
