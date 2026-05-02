"""A module for tracking useful in-game information."""

import ctypes
import threading
import time
from ctypes import wintypes

import cv2
import mss
import mss.windows
import numpy as np
import pygetwindow as gw

from src.easymaple.common import config, utils

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


# The distance between the top of the minimap and the top of the screen
MINIMAP_TOP_BORDER = 5

# The thickness of the other three borders of the minimap
MINIMAP_BOTTOM_BORDER = 9

# Offset in pixels to adjust for windowed mode
WINDOWED_OFFSET_TOP = 36
WINDOWED_OFFSET_LEFT = 10

# The top-left and bottom-right corners of the minimap
MM_TL_TEMPLATE = utils.load_image('assets/minimap_tl_template.png', cv2.IMREAD_GRAYSCALE)
MM_BR_TEMPLATE = utils.load_image('assets/minimap_br_template.png', cv2.IMREAD_GRAYSCALE)

MMT_HEIGHT = max(MM_TL_TEMPLATE.shape[0], MM_BR_TEMPLATE.shape[0])
MMT_WIDTH = max(MM_TL_TEMPLATE.shape[1], MM_BR_TEMPLATE.shape[1])

# The player's symbol on the minimap
PLAYER_TEMPLATE = utils.load_image('assets/player_template.png', cv2.IMREAD_GRAYSCALE)
PT_HEIGHT, PT_WIDTH = PLAYER_TEMPLATE.shape


class Capture:
    """
    A class that tracks player position and various in-game events. It constantly updates
    the config module with information regarding these events. It also annotates and
    displays the minimap in a pop-up window.
    """

    def __init__(self):
        """Initializes this Capture object's main thread."""

        config.capture = self

        self.frame = None
        self.minimap = {}
        self.minimap_ratio = 1
        self.minimap_sample = None
        self.sct = None
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

    def _find_game_window(self):
        """Returns a pygetwindow object for the game window, or None if not found."""
        for title in gw.getAllTitles():
            if ("Remote Desktop Connection" in title or "远程桌面协议" in title
                    or "Maplestory" in title or " - Moonlight" in title):
                windows = gw.getWindowsWithTitle(title)
                if windows:
                    return windows[0]
        return None

    def _main(self):
        """Constantly monitors the player's position and in-game events."""
        window_obj = None
        while True:
            # Only search for the game window when we don't already have a handle
            if window_obj is None:
                window_obj = self._find_game_window()
                if window_obj is None:
                    time.sleep(0.5)
                    continue

            self.ready = True

            try:
                self.window['left'] = window_obj.left
                self.window['top'] = window_obj.top
                self.window['width'] = window_obj.width
                self.window['height'] = window_obj.height
            except Exception:
                window_obj = None
                continue

            # Calibrate by finding the bottom right corner of the minimap
            with mss.mss() as self.sct:
                self.frame = self.screenshot()

            if self.frame is None:
                continue

            gray_frame = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
            result_tl = cv2.matchTemplate(gray_frame, MM_TL_TEMPLATE, cv2.TM_CCOEFF_NORMED)
            _, _, _, tl = cv2.minMaxLoc(result_tl)
            result_br = cv2.matchTemplate(gray_frame, MM_BR_TEMPLATE, cv2.TM_CCOEFF_NORMED)
            _, _, _, br_tl = cv2.minMaxLoc(result_br)
            br = (br_tl[0] + MM_BR_TEMPLATE.shape[1], br_tl[1] + MM_BR_TEMPLATE.shape[0])
            mm_tl = (
                tl[0] + 2,
                tl[1] + 2
            )
            mm_br = (
                max(mm_tl[0] + PT_WIDTH, br[0] - 8),
                max(mm_tl[1] + PT_HEIGHT, br[1] - 9)
            )
            self.minimap_ratio = (mm_br[0] - mm_tl[0]) / (mm_br[1] - mm_tl[1])
            self.minimap_sample = self.frame[mm_tl[1]:mm_br[1], mm_tl[0]:mm_br[0]]

            is_valid_mm_map = self._mini_map_sanity_check(mm_tl, mm_br)
            if not is_valid_mm_map:
                continue

            self.calibrated = True

            with mss.mss() as self.sct:
                while True:
                    if not self.calibrated:
                        break

                    # Take screenshot
                    self.frame = self.screenshot()
                    if self.frame is None:
                        continue

                    # Crop the frame to only show the minimap
                    minimap = self.frame[mm_tl[1]:mm_br[1], mm_tl[0]:mm_br[0]]

                    # Determine the player's position
                    player = utils.multi_match(minimap, PLAYER_TEMPLATE, threshold=0.8)
                    if player:
                        config.player_pos = utils.convert_to_relative(player[0], minimap)

                    # Package display information to be polled by GUI
                    self.minimap = {
                        'minimap': minimap,
                        'rune_active': config.bot.rune_active,
                        'rune_pos': config.bot.rune_pos,
                        'path': config.path,
                        'player_pos': config.player_pos
                    }

                    if not self.ready:
                        self.ready = True
                    time.sleep(1/30)

    def _mini_map_sanity_check(self, mm_tl, mm_br):
        width = abs(mm_tl[0] - mm_br[0])
        height = abs(mm_tl[1] - mm_br[1])
        if width < 100 or width > 500:
            return False
        if height < 50 or height > 500:
            return False
        return True

    def screenshot(self, delay=1):
        try:
            return np.array(self.sct.grab(self.window))
        except mss.exception.ScreenShotError:
            print(f'\n[!] Error while taking screenshot, retrying in {delay} second')
            time.sleep(delay)