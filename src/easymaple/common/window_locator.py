"""Abstraction for game-window discovery, enabling dependency injection in tests."""

from abc import ABC, abstractmethod
import ctypes

import pygetwindow as gw

_user32 = ctypes.windll.user32
_SB_HORZ = 0
_SB_VERT = 1
_WM_HSCROLL = 0x0114
_WM_VSCROLL = 0x0115
_SB_THUMBPOSITION = 4


class WindowLocator(ABC):
    """Finds and manipulates the game window."""

    @abstractmethod
    def find(self) -> 'dict | None':
        """Return {left, top, width, height} for the game window, or None if not found."""

    @abstractmethod
    def move(self, left: int, top: int) -> bool:
        """Move the game window's top-left to (left, top). Returns True on success."""

    @abstractmethod
    def scroll(self, dx: int, dy: int) -> bool:
        """Scroll the window content by (dx, dy) pixels relative to current position."""

    @abstractmethod
    def resize(self, width: int, height: int) -> bool:
        """Resize the window to (width, height), keeping the top-left fixed."""


class GameWindowLocator(WindowLocator):
    """Locates and manipulates the MapleStory window by known title fragments."""

    _TITLE_FRAGMENTS = (
        "Remote Desktop Connection",
        "远程桌面协议",
        "Maplestory",
        " - Moonlight",
    )

    def _get_win(self):
        """Return the pygetwindow Win32Window object, or None if not found."""
        for title in gw.getAllTitles():
            if any(fragment in title for fragment in self._TITLE_FRAGMENTS):
                wins = gw.getWindowsWithTitle(title)
                if wins:
                    return wins[0]
        return None

    def find(self) -> 'dict | None':
        win = self._get_win()
        if win is None:
            return None
        return {
            'left': win.left,
            'top': win.top,
            'width': win.width,
            'height': win.height,
        }

    def move(self, left: int, top: int) -> bool:
        win = self._get_win()
        if win is None:
            return False
        win.moveTo(left, top)
        return True

    def scroll(self, dx: int, dy: int) -> bool:
        win = self._get_win()
        if win is None:
            return False
        hwnd = win._hWnd
        curr_x = _user32.GetScrollPos(hwnd, _SB_HORZ)
        curr_y = _user32.GetScrollPos(hwnd, _SB_VERT)
        target_x = max(0, curr_x + dx)
        target_y = max(0, curr_y + dy)
        _user32.SendMessageW(hwnd, _WM_HSCROLL, _SB_THUMBPOSITION | (target_x << 16), 0)
        _user32.SendMessageW(hwnd, _WM_VSCROLL, _SB_THUMBPOSITION | (target_y << 16), 0)
        return True

    def resize(self, width: int, height: int) -> bool:
        win = self._get_win()
        if win is None:
            return False
        win.resizeTo(width, height)
        return True
