"""Buff Sequence dialog: click 'Use Unapplied Buffs' after auto-buff.

The fixture is the real dialog cut out of a 1047x822 window capture (no
character names), pasted into synthetic frames at its original position
(312, 240). Its middle - the list of missing buffs - changes every time, so
only the fixed header and the "Please select the buff effect range." line are
matched; the tests vary everything else.
"""
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.easymaple.common import config
from src.easymaple.detection import buff_sequence
from src.easymaple.routine import components

H, W = 822, 1047
DIALOG = cv2.imread('tests/fixtures/buff_sequence_dialog.png')
ORIGIN = (312, 240)                 # where the dialog sat in the capture
BUTTON = (528, 559)                 # 'Use Unapplied Buffs' centre in that capture
LIST_ROWS = slice(120, 200)         # rows of the buff list inside the fixture


def background(seed=0):
    rng = np.random.default_rng(seed)
    noise = rng.integers(40, 200, size=(H // 8, W // 8, 3), dtype=np.uint8)
    frame = cv2.resize(noise, (W, H), interpolation=cv2.INTER_LINEAR)
    frame[:38] = 240
    return frame


def frame_with(dialog=DIALOG, origin=ORIGIN):
    frame = background()
    x, y = origin
    frame[y:y + dialog.shape[0], x:x + dialog.shape[1]] = dialog
    return frame


def find(frame):
    return buff_sequence.find_unapplied_button(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))


def assert_near(point, expected, tol=2):
    assert point is not None, 'dialog not found'
    assert abs(point[0] - expected[0]) <= tol and abs(point[1] - expected[1]) <= tol, (point, expected)


#################################
#           Detection           #
#################################
def test_finds_the_button_in_the_real_dialog():
    point, info = find(frame_with())
    assert_near(point, BUTTON)
    assert info['lined_up'] and info['top'] > 0.9 and info['prompt'] > 0.95


def test_dialog_elsewhere_on_screen():
    point, _ = find(frame_with(origin=(ORIGIN[0] + 90, ORIGIN[1] - 60)))
    assert_near(point, (BUTTON[0] + 90, BUTTON[1] - 60))


@pytest.mark.parametrize('extra_rows', [-40, 40, 120])
def test_longer_or_shorter_buff_list(extra_rows):
    """More/fewer missing buffs: the dialog grows/shrinks in the middle."""
    if extra_rows > 0:
        filler = np.repeat(DIALOG[LIST_ROWS][:16], extra_rows // 16 + 1, axis=0)[:extra_rows]
        dialog = np.vstack([DIALOG[:200], filler, DIALOG[200:]])
    else:
        dialog = np.vstack([DIALOG[:200 + extra_rows], DIALOG[200:]])
    point, info = find(frame_with(dialog))
    assert_near(point, (BUTTON[0], BUTTON[1] + extra_rows))
    assert info['lined_up']


def test_different_buffs_listed():
    """Other buff names: scribble over the list, nothing else changes."""
    dialog = DIALOG.copy()
    rng = np.random.default_rng(3)
    for y in range(LIST_ROWS.start, LIST_ROWS.stop, 16):
        x0 = int(rng.integers(60, 140))
        cv2.putText(dialog, 'Some Other Buff ' + str(y), (x0, y + 12), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (120, 230, 220), 1)
    assert_near(find(frame_with(dialog))[0], BUTTON)


def test_header_hidden_by_a_banner_still_found_by_the_prompt():
    """A tall dialog can slide under the 'item effect has disappeared' banner."""
    dialog = DIALOG.copy()
    dialog[0:110] = background(5)[0:110, 0:dialog.shape[1]]
    point, info = find(frame_with(dialog))
    assert_near(point, BUTTON)
    assert not info['lined_up']


def test_hover_highlight_and_cursor_do_not_matter():
    """The button highlight follows the mouse; our own cursor sits on it on a retry."""
    dialog = DIALOG.copy()
    bx, by = BUTTON[0] - ORIGIN[0], BUTTON[1] - ORIGIN[1]
    dialog[by - 12:by + 12, 20:140] = (200, 160, 60)            # 'Use All Buffs' lit up
    dialog[by - 12:by + 12, bx - 58:bx + 58] = (170, 120, 40)   # 'Use Unapplied' back to blue
    cursor = np.array([[0, 0], [0, 18], [5, 13], [12, 13]], np.int32) + (200, 250)
    cv2.fillPoly(dialog, [cursor], (255, 255, 255))             # a cursor on the prompt text
    assert_near(find(frame_with(dialog))[0], BUTTON)


def test_nothing_on_ordinary_screens():
    assert find(background())[0] is None
    for path in ['tests/fixtures/lie_detector_prep_screen.png',
                 'tests/fixtures/lie_detector_in_progress_screen.png']:
        assert find(cv2.imread(path))[0] is None, path
    for path in ['tests/fixtures/qworld_farm_topleft.png', 'tests/fixtures/qworld_lobby_topleft.png']:
        frame = background()
        tile = cv2.imread(path)
        frame[40:40 + tile.shape[0], :tile.shape[1]] = tile
        assert find(frame)[0] is None, path


def test_header_without_prompt_is_not_the_dialog():
    """Only the header (prompt cut off): don't click blindly - Esc handles it."""
    dialog = DIALOG.copy()
    dialog[230:] = background(9)[230:DIALOG.shape[0], 0:dialog.shape[1]]
    assert find(frame_with(dialog))[0] is None


#################################
#   dismiss_buff_active_popup   #
#################################
@pytest.fixture
def popup_env(monkeypatch):
    frames = []
    clicks, keys = [], []
    capture = SimpleNamespace(frame=None, window={'left': 100, 'top': 50})

    def next_frame():
        if len(frames) > 1:
            capture.frame = frames.pop(0)
        else:
            capture.frame = frames[0]

    def on_click(position):
        clicks.append(position)
        next_frame()                    # the game reacts to the click

    monkeypatch.setattr(config, 'capture', capture)
    monkeypatch.setattr(components, '_click_screen', on_click)
    monkeypatch.setattr(components, 'press', lambda key, *a, **k: keys.append(key))
    monkeypatch.setattr(components, 'BUFF_SEQUENCE_CLOSE_WAIT_S', 0)

    def start(*sequence):
        frames[:] = list(sequence)
        next_frame()
    return start, clicks, keys


def test_clicks_use_unapplied_buffs_instead_of_esc(popup_env):
    start, clicks, keys = popup_env
    start(frame_with(), background())   # dialog, then gone after the click
    components.Component().dismiss_buff_active_popup()
    assert len(clicks) == 1
    assert_near(clicks[0], (100 + BUTTON[0], 50 + BUTTON[1]))  # window origin + frame point
    assert keys == [], 'Esc would Cancel the dialog'


def test_falls_back_to_esc_when_the_click_does_not_close_it(popup_env):
    start, clicks, keys = popup_env
    start(frame_with())                 # stays open whatever we click
    components.Component().dismiss_buff_active_popup()
    assert len(clicks) == components.BUFF_SEQUENCE_CLICKS
    assert keys == ['esc'], 'previous behaviour as the last resort'


def test_no_click_while_a_lie_detector_game_owns_the_mouse(popup_env, monkeypatch):
    """A game started while the buff was pressed: the solver owns the
    cursor, so Esc rather than fight it."""
    start, clicks, keys = popup_env
    monkeypatch.setattr(config, 'lie_detector_session', object(), raising=False)
    start(frame_with(), background())
    components.Component().dismiss_buff_active_popup()
    assert clicks == [] and keys == ['esc']


def test_other_popups_still_get_esc(popup_env):
    start, clicks, keys = popup_env
    popup = cv2.cvtColor(components.BUFF_ACTIVE_POPUP_TEMPLATES[0], cv2.COLOR_GRAY2BGR)
    frame = background()
    frame[300:300 + popup.shape[0], 300:300 + popup.shape[1]] = popup
    start(frame)
    components.Component().dismiss_buff_active_popup()
    assert clicks == [] and keys == ['esc']


def test_nothing_on_screen_does_nothing(popup_env):
    start, clicks, keys = popup_env
    start(background())
    components.Component().dismiss_buff_active_popup()
    assert clicks == [] and keys == []
