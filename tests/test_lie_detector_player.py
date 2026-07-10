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
    """get_frame stub: yields each frame once, then repeats the last one."""

    def __init__(self, frames):
        self.frames = frames
        self.i = 0

    def __call__(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f


def _play(frames, start=(30.0, 40.0), max_seconds=30):
    moves = []
    player = LieDetectorPlayer(
        move_mouse=moves.append,
        get_frame=FrameFeed(frames),
        get_cursor=lambda: start,
        fps=240,                                        # fast-forward the loop
        use_net=False,                                  # synthetic frames: classical
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


def test_player_reports_failed_when_the_jail_room_follows_the_game():
    """The Lie Detector failure state (observed live 2026-07-10): right after
    the play-box vanishes the character is in a near-black punishment room.
    The player must report outcome='failed' so the notifier keeps the bot
    paused instead of celebrating and resuming inside the jail."""
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
