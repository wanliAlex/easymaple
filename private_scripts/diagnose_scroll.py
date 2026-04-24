"""
Run this script while mstsc.exe is visible to inspect its scroll state.
Usage: uv run python private_scripts/diagnose_scroll.py
"""

import ctypes
import ctypes.wintypes

import pygetwindow as gw

_user32 = ctypes.windll.user32

TITLE_FRAGMENTS = (
    "Remote Desktop Connection",
    "远程桌面协议",
    "Maplestory",
    " - Moonlight",
)


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


def get_scroll_info(hwnd, bar):
    si = _SCROLLINFO()
    si.cbSize = ctypes.sizeof(_SCROLLINFO)
    si.fMask = 0x17  # SIF_ALL
    ok = _user32.GetScrollInfo(hwnd, bar, ctypes.byref(si))
    return si, ok


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


_EnumChildProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


def collect_children(hwnd):
    children = []
    def cb(child, _):
        children.append(child)
        return True
    _user32.EnumChildWindows(hwnd, _EnumChildProc(cb), 0)
    return children


for title in gw.getAllTitles():
    if not any(f in title for f in TITLE_FRAGMENTS):
        continue
    wins = gw.getWindowsWithTitle(title)
    if not wins:
        continue
    win = wins[0]
    hwnd = win._hWnd

    print(f"\n=== '{title}' hwnd={hwnd} class='{class_name(hwnd)}' ===")
    print(f"  outer: left={win.left} top={win.top} w={win.width} h={win.height}")

    for bar, name in [(0, 'HORZ'), (1, 'VERT')]:
        si, ok = get_scroll_info(hwnd, bar)
        print(f"  {name}: ok={ok} min={si.nMin} max={si.nMax} pos={si.nPos} page={si.nPage}")

    children = collect_children(hwnd)
    print(f"  children ({len(children)}):")
    for child in children:
        si_h, _ = get_scroll_info(child, 0)
        si_v, _ = get_scroll_info(child, 1)
        flag = "  <-- HAS SCROLL" if (si_h.nMax > 0 or si_v.nMax > 0) else ""
        print(
            f"    hwnd={child} class='{class_name(child)}'"
            f"  H={si_h.nPos}/{si_h.nMax}  V={si_v.nPos}/{si_v.nMax}{flag}"
        )

    # Attempt a test scroll of 5px right and 5px down
    print("\n  Attempting test scroll (+5, +5) ...")
    si, _ = get_scroll_info(hwnd, 0)
    target_x = si.nPos + 5
    si2 = _SCROLLINFO()
    si2.cbSize = ctypes.sizeof(_SCROLLINFO)
    si2.fMask = 0x04  # SIF_POS
    si2.nPos = target_x
    _user32.SetScrollInfo(hwnd, 0, ctypes.byref(si2), True)
    _user32.SendMessageW(hwnd, 0x0114, 5 | (target_x << 16), 0)   # WM_HSCROLL SB_THUMBTRACK
    _user32.SendMessageW(hwnd, 0x0114, 4 | (target_x << 16), 0)   # WM_HSCROLL SB_THUMBPOSITION
    _user32.SendMessageW(hwnd, 0x0114, 8, 0)                       # WM_HSCROLL SB_ENDSCROLL
    si_after, _ = get_scroll_info(hwnd, 0)
    print(f"  HORZ pos before={target_x - 5} after SetScrollInfo+Send: {si_after.nPos}")
    print("  (if 'after' changed, the scroll is working)")
    break
else:
    print("No matching window found. Start the game/RDP client and re-run.")
