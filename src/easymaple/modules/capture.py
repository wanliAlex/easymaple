"""A module for tracking useful in-game information."""

import ctypes
import threading
import time

import cv2
import numpy as np

from src.easymaple.common import config, utils
from src.easymaple.common.frame_source import FrameSource, MssFrameSource
from src.easymaple.common.window_locator import WindowLocator, GameWindowLocator

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


# The distance between the top of the minimap and the top of the screen
MINIMAP_TOP_BORDER = 5

# The thickness of the other three borders of the minimap
MINIMAP_BOTTOM_BORDER = 9

# Offset in pixels to adjust for windowed mode
WINDOWED_OFFSET_TOP = 36
WINDOWED_OFFSET_LEFT = 10

# Assumed game resolution (MapleStory window inside the RDP session)
GAME_WIDTH = 1024
GAME_HEIGHT = 768

# The top-left and bottom-right corners of the minimap
MM_TL_TEMPLATE = cv2.imread('assets/minimap_tl_template.png', 0)
MM_BR_TEMPLATE = cv2.imread('assets/minimap_br_template.png', 0)

MMT_HEIGHT = max(MM_TL_TEMPLATE.shape[0], MM_BR_TEMPLATE.shape[0])
MMT_WIDTH = max(MM_TL_TEMPLATE.shape[1], MM_BR_TEMPLATE.shape[1])

# The player's symbol on the minimap
PLAYER_TEMPLATE = cv2.imread('assets/player_template.png', 0)
PT_HEIGHT, PT_WIDTH = PLAYER_TEMPLATE.shape


class Capture:
    """
    A class that tracks player position and various in-game events. It constantly updates
    the config module with information regarding these events. It also annotates and
    displays the minimap in a pop-up window.
    """

    def __init__(
        self,
        frame_source: FrameSource = None,
        window_locator: WindowLocator = None,
    ):
        """
        :param frame_source:    How to grab screenshots. Defaults to MssFrameSource (live screen).
        :param window_locator:  How to find the game window. Defaults to GameWindowLocator.
        """
        config.capture = self

        self.frame_source = frame_source or MssFrameSource()
        self.window_locator = window_locator or GameWindowLocator()

        self.frame = None
        self.minimap = {}
        self.minimap_ratio = 1
        self.minimap_sample = None
        self.window = {
            'left': 0,
            'top': 0,
            'width': 1366,
            'height': 768
        }

        self.ready = False
        self.calibrated = False
        self.thread = threading.Thread(target=self._main)
        self.thread.daemon = True

    def start(self):
        """Starts this Capture's thread."""

        print('\n[~] Started video capture')
        self.thread.start()

    def _main(self):
        """Constantly monitors the player's position and in-game events."""
        while True:
            window = self.window_locator.find()
            if window is None:
                continue

            self.window.update(window)
            self.ready = True

            # Grab one frame for calibration
            frame = self.frame_source.grab(self.window)
            if frame is None:
                continue
            self.frame = frame

            bounds = self._find_minimap_bounds(frame)
            if bounds is None:
                continue

            mm_tl, mm_br = bounds
            self.minimap_ratio = (mm_br[0] - mm_tl[0]) / (mm_br[1] - mm_tl[1])
            self.minimap_sample = frame[mm_tl[1]:mm_br[1], mm_tl[0]:mm_br[0]]
            self.calibrated = True

            # Main capture loop — runs until calibration is invalidated
            while True:
                if not self.calibrated:
                    break

                frame = self.frame_source.grab(self.window)
                if frame is None:
                    continue
                self.frame = frame

                minimap = frame[mm_tl[1]:mm_br[1], mm_tl[0]:mm_br[0]]
                player_pos = self._detect_player(minimap)
                if player_pos is not None:
                    config.player_pos = player_pos

                self.minimap = {
                    'minimap': minimap,
                    'rune_active': config.bot.rune_active,
                    'rune_pos': config.bot.rune_pos,
                    'path': config.path,
                    'player_pos': config.player_pos
                }
                time.sleep(1/30)

    def _find_minimap_bounds(self, frame: np.ndarray):
        """
        Locate the minimap corners in FRAME.
        Returns (mm_tl, mm_br) on success, None if the bounds fail the sanity check.
        """
        tl, _ = utils.single_match(frame, MM_TL_TEMPLATE)
        _, br = utils.single_match(frame, MM_BR_TEMPLATE)
        mm_tl = (tl[0] + 2, tl[1] + 2)
        mm_br = (
            max(mm_tl[0] + PT_WIDTH, br[0] - 8),
            max(mm_tl[1] + PT_HEIGHT, br[1] - 9)
        )
        if not self._mini_map_sanity_check(mm_tl, mm_br):
            return None
        return mm_tl, mm_br

    def _detect_player(self, minimap: np.ndarray):
        """
        Find the player icon in MINIMAP.
        Returns relative (x, y) in [0, 1] on success, None if not found.
        """
        player = utils.multi_match(minimap, PLAYER_TEMPLATE, threshold=0.8)
        if player:
            return utils.convert_to_relative(player[0], minimap)
        return None

    def align_to_minimap(self) -> bool:
        """
        Align the view to the minimap without moving the window's top-left:
          1. Scroll the RDP content so the minimap reaches the client-area origin.
          2. Shrink the window from the bottom-right to hide the now-invisible
             area that was scrolled away.

        Returns True on success, False if the frame or minimap bounds are unavailable.
        """
        if self.frame is None:
            print('[!] Cannot align window: no frame captured yet')
            return False
        bounds = self._find_minimap_bounds(self.frame)
        if bounds is None:
            print('[!] Cannot align window: minimap not detected')
            return False
        mm_tl, _ = bounds
        scroll_x = mm_tl[0] - WINDOWED_OFFSET_LEFT
        scroll_y = mm_tl[1] - WINDOWED_OFFSET_TOP
        if not self.window_locator.scroll(scroll_x, scroll_y):
            return False
        new_w = self.window['width'] - scroll_x
        new_h = self.window['height'] - scroll_y
        self.window_locator.resize(new_w, new_h)
        print(f'[~] Window aligned: scrolled ({scroll_x}, {scroll_y}), resized to ({new_w}x{new_h})')
        return True

    def _mini_map_sanity_check(self, mm_tl, mm_br):
        width = abs(mm_tl[0] - mm_br[0])
        height = abs(mm_tl[1] - mm_br[1])
        if width < 100 or width > 500:
            return False
        if height < 50 or height > 500:
            return False
        return True
