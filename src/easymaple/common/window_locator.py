"""Abstraction for game-window discovery, enabling dependency injection in tests."""

from abc import ABC, abstractmethod

import pygetwindow as gw


class WindowLocator(ABC):
    """Finds the game window and returns its bounds."""

    @abstractmethod
    def find(self) -> 'dict | None':
        """Return {left, top, width, height} for the game window, or None if not found."""


class GameWindowLocator(WindowLocator):
    """Locates the MapleStory window by known title fragments."""

    _TITLE_FRAGMENTS = (
        "Remote Desktop Connection",
        "远程桌面协议",
        "Maplestory",
        " - Moonlight",
    )

    def find(self) -> 'dict | None':
        for title in gw.getAllTitles():
            if any(fragment in title for fragment in self._TITLE_FRAGMENTS):
                win = gw.getWindowsWithTitle(title)[0]
                return {
                    'left': win.left,
                    'top': win.top,
                    'width': win.width,
                    'height': win.height,
                }
        return None
