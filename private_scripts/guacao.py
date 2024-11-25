from typing import List
import os
from dataclasses import dataclass
import math
import signal
from time import sleep
import argparse

import pyautogui
import pygetwindow as gw
import threading
from pynput.keyboard import Controller, Key
import mss
import cv2
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("-f", '--flower', type=int, default=5, help="Number of flowers (default: 5")
args = parser.parse_args()

stop_listening = threading.Event()
keyboard = Controller()

GAME_WINDOW_TITLE = 'Maplestory'
INTERACT_KEY = Key.alt
STOP_START_KEY= Key.f8
NUMBER_OF_FLOWERS = args.flower
CLICK_INTERVAL = 120

BULB_TEMPLATE = cv2.imread(os.path.join(os.getcwd(), 'bulb.jpg'), 0)
ASK_TEMPLATE = cv2.imread(os.path.join(os.getcwd(), 'ask.jpg'), 0)


def get_window_position():
    all_titles = gw.getAllTitles()
    window_name = None
    for title in all_titles:
        if "Remote Desktop Connection" in title or "远程桌面协议" in title:
            window_name = title
    window_obj = gw.getWindowsWithTitle(window_name)[0]
    window = dict()
    window['left'] = window_obj.left
    window['top'] = window_obj.top
    window['width'] = window_obj.width
    window['height'] = window_obj.height

    with mss.mss() as sct:
        # Grab the screen image
        image = np.array(sct.grab(window))

    return window, image


def single_match(frame, template):
    """
    Finds the best match within FRAME.
    :param frame:       The image in which to search for TEMPLATE.
    :param template:    The template to match with.
    :return:            The top-left and bottom-right positions of the best match.
    """

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    _, _, _, top_left = cv2.minMaxLoc(result)
    w, h = template.shape[::-1]
    bottom_right = (top_left[0] + w, top_left[1] + h)
    return top_left, bottom_right

def get_bulb_position(window, image) -> List[int]:
    tl, br = single_match(image, BULB_TEMPLATE)
    pos = [window["left"] + (tl[0] + br[0]) // 2, window["top"] + (tl[1] + br[1]) //2]
    return pos

def get_ask_position(window, image) -> List[int]:
    tl, br = single_match(image, ASK_TEMPLATE)
    pos = [window["left"] + (tl[0] + br[0]) // 2, window["top"] + (tl[1] + br[1]) //2]
    return pos

def left_click(position: List[int]) -> None:
    pyautogui.click(position[0], position[1])


def pipeline_of_actions() -> None:
    """A pipeline of actions to guacao"""
    window, image = get_window_position()
    left_click(get_ask_position(window, image))
    sleep(1)
    press_key(INTERACT_KEY)
    left_click(get_bulb_position(window, image))
    sleep(1)
    press_key(INTERACT_KEY)


def press_key(key) -> None:
    """
    Simulate a key press using pyautogui.

    Args:
    - key (str): The key to press. Can be letters, function keys like 'f1', 'f2', or special keys like 'alt', 'ctrl', etc.

    Example usage:
    press_key('a')      # Presses the 'a' key
    press_key('f1')     # Presses the 'F1' key
    press_key('ctrl')   # Presses the 'Ctrl' key
    """
    interval = 1

    for _ in range(10):
        keyboard.press(key)
        sleep(interval / 2.0)
        keyboard.release(key)
        sleep(interval / 2.0)


def main():
    print(f"Number of flowers = {NUMBER_OF_FLOWERS}, Interval = {CLICK_INTERVAL}s")
    for flower in range(NUMBER_OF_FLOWERS):
        number_of_clicks = math.ceil(1800 // CLICK_INTERVAL) + 1
        for click in range(number_of_clicks):
            print(f"Currently doing flower = `{flower + 1}|{NUMBER_OF_FLOWERS}` and click =`{click + 1}|{number_of_clicks}`")
            try:
                pipeline_of_actions()
            except Exception as e:
                pass
            sleep(CLICK_INTERVAL)
    os.system("shutdown -s -t 1")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Allow Ctrl+C to interrupt the program
    main()
