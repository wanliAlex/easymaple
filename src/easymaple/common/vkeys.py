"""A module for simulating low-level keyboard and mouse key presses."""

import ctypes
import win32con
import win32api
from src.easymaple.common import utils, driver_key, settings
from ctypes import wintypes
from random import random
from pynput.keyboard import Key, Controller
import win32gui, win32ui, win32con, win32api
import win32process

user32 = ctypes.WinDLL('user32', use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

MAPVK_VK_TO_VSC = 0

# record unreleased key for stopping script
unreleased_key = []

# https://docs.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes?redirectedfrom=MSDN
KEY_MAP = {
    'left': 0x25,  # Arrow keys
    'up': 0x26,
    'right': 0x27,
    'down': 0x28,

    'backspace': 0x08,  # Special keys
    'tab': 0x09,
    'enter': 0x0D,
    'shift': 0x10,
    'ctrl': 0x11,
    'alt': 0x12,
    'caps lock': 0x14,
    'esc': 0x1B,
    'space': 0x20,
    'pageup': 0x21,
    'pagedown': 0x22,
    'end': 0x23,
    'home': 0x24,
    'insert': 0x2D,
    'delete': 0x2E,

    '0': 0x30,  # Numbers
    '1': 0x31,
    '2': 0x32,
    '3': 0x33,
    '4': 0x34,
    '5': 0x35,
    '6': 0x36,
    '7': 0x37,
    '8': 0x38,
    '9': 0x39,

    'a': 0x41,  # Letters
    'b': 0x42,
    'c': 0x43,
    'd': 0x44,
    'e': 0x45,
    'f': 0x46,
    'g': 0x47,
    'h': 0x48,
    'i': 0x49,
    'j': 0x4A,
    'k': 0x4B,
    'l': 0x4C,
    'm': 0x4D,
    'n': 0x4E,
    'o': 0x4F,
    'p': 0x50,
    'q': 0x51,
    'r': 0x52,
    's': 0x53,
    't': 0x54,
    'u': 0x55,
    'v': 0x56,
    'w': 0x57,
    'x': 0x58,
    'y': 0x59,
    'z': 0x5A,

    'f1': 0x70,  # Functional keys
    'f2': 0x71,
    'f3': 0x72,
    'f4': 0x73,
    'f5': 0x74,
    'f6': 0x75,
    'f7': 0x76,
    'f8': 0x77,
    'f9': 0x78,
    'f10': 0x79,
    'f11': 0x7A,
    'f12': 0x7B,
    'num lock': 0x90,
    'scroll lock': 0x91,

    ';': 0xBA,  # Special characters
    '=': 0xBB,
    ',': 0xBC,
    '-': 0xBD,
    '.': 0xBE,
    '/': 0xBF,
    '`': 0xC0,
    '[': 0xDB,
    '\\': 0xDC,
    ']': 0xDD,
    "'": 0xDE
}

#################################
#     C Struct Definitions      #
#################################
wintypes.ULONG_PTR = wintypes.WPARAM
d_key = None
if settings.driver_key == True:
    d_key = driver_key.DriverKey()


class KeyboardInput(ctypes.Structure):
    _fields_ = (('wVk', wintypes.WORD),
                ('wScan', wintypes.WORD),
                ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD),
                ('dwExtraInfo', wintypes.ULONG_PTR))

    def __init__(self, *args, **kwargs):
        super(KeyboardInput, self).__init__(*args, **kwargs)
        if not self.dwFlags & KEYEVENTF_UNICODE:
            self.wScan = user32.MapVirtualKeyExW(self.wVk, MAPVK_VK_TO_VSC, 0)


class MouseInput(ctypes.Structure):
    _fields_ = (('dx', wintypes.LONG),
                ('dy', wintypes.LONG),
                ('mouseData', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD),
                ('dwExtraInfo', wintypes.ULONG_PTR))


class HardwareInput(ctypes.Structure):
    _fields_ = (('uMsg', wintypes.DWORD),
                ('wParamL', wintypes.WORD),
                ('wParamH', wintypes.WORD))


class Input(ctypes.Structure):
    class _Input(ctypes.Union):
        _fields_ = (('ki', KeyboardInput),
                    ('mi', MouseInput),
                    ('hi', HardwareInput))

    _anonymous_ = ('_input',)
    _fields_ = (('type', wintypes.DWORD),
                ('_input', _Input))


LPINPUT = ctypes.POINTER(Input)


def err_check(result, _, args):
    if result == 0:
        raise ctypes.WinError(ctypes.get_last_error())
    else:
        return args


user32.SendInput.errcheck = err_check
user32.SendInput.argtypes = (wintypes.UINT, LPINPUT, ctypes.c_int)

nput_keyboard = Controller()


#################################
#           Functions           #
#################################
@utils.run_if_enabled
def key_down(key, down_time=0.05):
    """
    Simulates a key-down action. Can be cancelled by Bot.toggle_enabled.
    :param key:     The key to press.
    :return:        None
    """

    key = key.lower()
    key_combination = []
    # print('key down : ', key)
    if "+" in key:
        key_combination = key.split("+")
        # print('key_combination')
    else:
        key_combination.append(key)

    if key == '':
        pass
    else:
        for k in key_combination:
            if k not in KEY_MAP.keys():
                print(f"Invalid keyboard input: '{key}'.")
            elif not k in unreleased_key:
                unreleased_key.append(k)
                if settings.driver_key == True:
                    # try new input method
                    global d_key
                    if d_key == None:
                        d_key = driver_key.DriverKey()
                    d_key.user_key_down(KEY_MAP[k])
                else:
                    # default input method
                    x = Input(type=INPUT_KEYBOARD, ki=KeyboardInput(wVk=KEY_MAP[k]))
                    user32.SendInput(1, ctypes.byref(x), ctypes.sizeof(x))

                if len(key_combination) > 1:
                    time.sleep(0.02 * (0.9 + 0.7 * random()))
    time.sleep(down_time * (0.8 + 0.7 * random()))


def pynput_key_down(key):
    if len(key) > 1:
        nput_keyboard.press(Key[key])
    else:
        nput_keyboard.press(key)


def key_up(key, up_time=0.05):
    """
    Simulates a key-up action. Cannot be cancelled by Bot.toggle_enabled.
    This is to ensure no keys are left in the 'down' state when the program pauses.
    :param key:     The key to press.
    :return:        None
    """

    key = key.lower()
    key_combination = []
    if "+" in key:
        key_combination = key.split("+")
    else:
        key_combination.append(key)

    if key == '':
        pass
    else:
        for k in key_combination:
            if k not in KEY_MAP.keys():
                print(f"Invalid keyboard input: '{key}'.")
            elif k in unreleased_key:
                unreleased_key.remove(k)
                if settings.driver_key == True:
                    # try new input method
                    global d_key
                    if d_key == None:
                        d_key = driver_key.DriverKey()
                    d_key.user_key_up(KEY_MAP[k])
                else:
                    # default input method
                    x = Input(type=INPUT_KEYBOARD, ki=KeyboardInput(wVk=KEY_MAP[k], dwFlags=KEYEVENTF_KEYUP))
                    user32.SendInput(1, ctypes.byref(x), ctypes.sizeof(x))
                if len(key_combination) > 1:
                    time.sleep(0.04 * (0.9 + 0.7 * random()))
    time.sleep(up_time * (0.9 + 0.6 * random()))

    # if key == '':
    #     return
    # elif key not in KEY_MAP.keys() :
    #     print(f"Invalid keyboard input: '{key}'.")
    # elif key in unreleased_key:
    #     x = Input(type=INPUT_KEYBOARD, ki=KeyboardInput(wVk=KEY_MAP[key], dwFlags=KEYEVENTF_KEYUP))
    #     user32.SendInput(1, ctypes.byref(x), ctypes.sizeof(x))
    #     unreleased_key.remove(key)
    #     time.sleep(up_time * (0.7 + 0.8 * random()))


def pynput_key_up(key):
    if len(key) > 1:
        nput_keyboard.release(Key[key])
    else:
        nput_keyboard.release(key)


def release_unreleased_key():
    print("release ", unreleased_key)
    for key in unreleased_key:
        key_up(key)


@utils.run_if_enabled
def press(key, n=1, down_time=0.1, up_time=0.08):
    """
    Presses KEY N times, holding it for DOWN_TIME seconds, and releasing for UP_TIME seconds.
    :param key:         The keyboard input to press.
    :param n:           Number of times to press KEY.
    :param down_time:   Duration of down-press (in seconds).
    :param up_time:     Duration of release (in seconds).
    :return:            None
    """

    for _ in range(n):
        if key == '':
            break
        key_down(key, down_time)
        key_up(key, up_time)


def type(word):
    nput_keyboard.type(word)


def click(position, button='left', click_time=1):
    """
    Simulate a mouse click with BUTTON at POSITION.
    :param position:    The (x, y) position at which to click.
    :param button:      Either the left or right mouse button.
    :return:            None
    """

    if button not in ['left', 'right']:
        print(f"'{button}' is not a valid mouse button.")
    else:
        for _ in range(click_time):
            time.sleep(0.2 * (0.9 + 0.7 * random()))
            if button == 'left':
                down_event = win32con.MOUSEEVENTF_LEFTDOWN
                up_event = win32con.MOUSEEVENTF_LEFTUP
            else:
                down_event = win32con.MOUSEEVENTF_RIGHTDOWN
                up_event = win32con.MOUSEEVENTF_RIGHTUP
            win32api.SetCursorPos(position)
            win32api.mouse_event(down_event, position[0], position[1], 0, 0)
            win32api.mouse_event(up_event, position[0], position[1], 0, 0)