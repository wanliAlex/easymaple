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

parser = argparse.ArgumentParser()
parser.add_argument("-f", '--flower', type=int, default=5, help="Number of flowers (default: 5")
args = parser.parse_args()

stop_listening = threading.Event()
keyboard = Controller()

GAME_WINDOW_TITLE = 'Maplestory'
INTERACT_KEY = Key.alt
STOP_START_KEY=Key.f8
NUMBER_OF_FLOWERS = args.flower
CLICK_INTERVAL = 600

@dataclass
class Position:
    game_window_position: List[int]

    @property
    def ask_position(self):
        return [self.game_window_position[0] + 630, self.game_window_position[1] - 179]

    @property
    def bulb_position(self):
        return [self.game_window_position[0] + 44, self.game_window_position[1] - 468]

    @property
    def quest_position(self):
        return [self.game_window_position[0] + 759, self.game_window_position[1] - 459]


def get_current_window_position() -> List[int]:
    game_window = gw.getWindowsWithTitle(GAME_WINDOW_TITLE)
    if game_window:
        game_window = game_window[0]
        # The coordinates of the left-bottom point
        return [game_window.left, game_window.top + game_window.height]
    else:
        return None


def left_click(position: List[int]) -> None:
    pyautogui.click(position[0], position[1])


def pipeline_of_actions(pos: List[int]) -> None:
    """A pipeline of actions to guacao"""
    position_data = Position(game_window_position=pos)
    left_click(position_data.ask_position)
    sleep(1)
    press_key(INTERACT_KEY)
    left_click(position_data.bulb_position)
    sleep(1)
    press_key(INTERACT_KEY)
    left_click(position_data.quest_position)
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
            pipeline_of_actions(get_current_window_position())
            sleep(CLICK_INTERVAL)

    os.system("shutdown -s -t 1")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Allow Ctrl+C to interrupt the program
    main()
