"""Abstraction for game-window discovery, enabling dependency injection in tests."""

from abc import ABC, abstractmethod
import ctypes
import ctypes.wintypes
import time

import win32api
import win32con
import pygetwindow as gw

_user32 = ctypes.windll.user32
_SB_HORZ = 0
_SB_VERT = 1
_WM_HSCROLL = 0x0114
_WM_VSCROLL = 0x0115
_SB_THUMBPOSITION = 4
_SIF_ALL = 0x17

# System metric indices
_SM_CXVSCROLL = 2    # width of a vertical scrollbar
_SM_CYVSCROLL = 20   # height of a horizontal/vertical scrollbar arrow button


class _SCROLLINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize',    ctypes.wintypes.UINT),
        ('fMask',     ctypes.wintypes.UINT),
        ('nMin',      ctypes.c_int),
        ('nMax',      ctypes.c_int),
        ('nPage',     ctypes.wintypes.UINT),
        ('nPos',      ctypes.c_int),
        ('nTrackPos', ctypes.c_int),
    ]


class _RECT(ctypes.Structure):
    _fields_ = [
        ('left',   ctypes.c_long),
        ('top',    ctypes.c_long),
        ('right',  ctypes.c_long),
        ('bottom', ctypes.c_long),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]


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
        """
        Scroll the mstsc.exe window by (dx, dy) pixels using mouse simulation
        on the NC-area scrollbar thumb.  Saves and restores the cursor position.
        """
        win = self._get_win()
        if win is None:
            return False
        hwnd = win._hWnd

        wr = _RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(wr))

        pt = _POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        saved = (pt.x, pt.y)

        try:
            if dy != 0:
                self._drag_vert(hwnd, wr, dy)
            if dx != 0:
                self._drag_horz(hwnd, wr, dx)
        finally:
            win32api.SetCursorPos(saved)

        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_scroll_info(self, hwnd: int, bar: int) -> _SCROLLINFO:
        si = _SCROLLINFO()
        si.cbSize = ctypes.sizeof(_SCROLLINFO)
        si.fMask = _SIF_ALL
        _user32.GetScrollInfo(hwnd, bar, ctypes.byref(si))
        return si

    def _thumb_center_y(self, wr: _RECT, si: _SCROLLINFO) -> 'int | None':
        """Return screen-Y of the vertical thumb centre, or None if no scrollbar."""
        if si.nMax <= 0:
            return None
        arrow_h = _user32.GetSystemMetrics(_SM_CYVSCROLL)
        win_h   = wr.bottom - wr.top
        track_h = win_h - 2 * arrow_h
        if track_h <= 0:
            return None
        scroll_range = max(1, si.nMax - si.nMin)
        page_frac    = si.nPage / max(1, si.nMax - si.nMin + si.nPage)
        thumb_h      = max(arrow_h, int(page_frac * track_h))
        avail_h      = max(1, track_h - thumb_h)
        ratio        = (si.nPos - si.nMin) / scroll_range
        return wr.top + arrow_h + int(ratio * avail_h) + thumb_h // 2

    def _thumb_center_y_for_target(self, wr: _RECT, si: _SCROLLINFO, target: int) -> int:
        arrow_h      = _user32.GetSystemMetrics(_SM_CYVSCROLL)
        win_h        = wr.bottom - wr.top
        track_h      = win_h - 2 * arrow_h
        scroll_range = max(1, si.nMax - si.nMin)
        page_frac    = si.nPage / max(1, si.nMax - si.nMin + si.nPage)
        thumb_h      = max(arrow_h, int(page_frac * track_h))
        avail_h      = max(1, track_h - thumb_h)
        ratio        = (target - si.nMin) / scroll_range
        return wr.top + arrow_h + int(ratio * avail_h) + thumb_h // 2

    def _thumb_center_x(self, wr: _RECT, si: _SCROLLINFO) -> 'int | None':
        """Return screen-X of the horizontal thumb centre, or None if no scrollbar."""
        if si.nMax <= 0:
            return None
        arrow_w = _user32.GetSystemMetrics(_SM_CYVSCROLL)   # SM_CXHSCROLL = SM_CYVSCROLL
        win_w   = wr.right - wr.left
        track_w = win_w - 2 * arrow_w
        if track_w <= 0:
            return None
        scroll_range = max(1, si.nMax - si.nMin)
        page_frac    = si.nPage / max(1, si.nMax - si.nMin + si.nPage)
        thumb_w      = max(arrow_w, int(page_frac * track_w))
        avail_w      = max(1, track_w - thumb_w)
        ratio        = (si.nPos - si.nMin) / scroll_range
        return wr.left + arrow_w + int(ratio * avail_w) + thumb_w // 2

    def _thumb_center_x_for_target(self, wr: _RECT, si: _SCROLLINFO, target: int) -> int:
        arrow_w      = _user32.GetSystemMetrics(_SM_CYVSCROLL)
        win_w        = wr.right - wr.left
        track_w      = win_w - 2 * arrow_w
        scroll_range = max(1, si.nMax - si.nMin)
        page_frac    = si.nPage / max(1, si.nMax - si.nMin + si.nPage)
        thumb_w      = max(arrow_w, int(page_frac * track_w))
        avail_w      = max(1, track_w - thumb_w)
        ratio        = (target - si.nMin) / scroll_range
        return wr.left + arrow_w + int(ratio * avail_w) + thumb_w // 2

    def _drag_vert(self, hwnd: int, wr: _RECT, dy: int) -> None:
        si     = self._get_scroll_info(hwnd, _SB_VERT)
        from_y = self._thumb_center_y(wr, si)
        if from_y is None:
            return
        target = max(si.nMin, min(si.nMax, si.nPos + dy))
        to_y   = self._thumb_center_y_for_target(wr, si, target)
        sb_cx  = wr.right - _user32.GetSystemMetrics(_SM_CXVSCROLL) // 2
        self._mouse_drag(sb_cx, from_y, sb_cx, to_y)

    def _drag_horz(self, hwnd: int, wr: _RECT, dx: int) -> None:
        si     = self._get_scroll_info(hwnd, _SB_HORZ)
        from_x = self._thumb_center_x(wr, si)
        if from_x is None:
            return
        target = max(si.nMin, min(si.nMax, si.nPos + dx))
        to_x   = self._thumb_center_x_for_target(wr, si, target)
        sb_cy  = wr.bottom - _user32.GetSystemMetrics(_SM_CYVSCROLL) // 2
        self._mouse_drag(from_x, sb_cy, to_x, sb_cy)

    @staticmethod
    def _mouse_drag(from_x: int, from_y: int, to_x: int, to_y: int) -> None:
        win32api.SetCursorPos((from_x, from_y))
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0)
        time.sleep(0.05)
        # Move in a few steps so the window can track the thumb
        steps = 5
        for i in range(1, steps + 1):
            x = from_x + (to_x - from_x) * i // steps
            y = from_y + (to_y - from_y) * i // steps
            win32api.SetCursorPos((x, y))
            time.sleep(0.02)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0)

    def resize(self, width: int, height: int) -> bool:
        win = self._get_win()
        if win is None:
            return False
        win.resizeTo(width, height)
        return True
