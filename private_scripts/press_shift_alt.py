import argparse
import signal
from time import sleep

from pynput.keyboard import Controller, Key

parser = argparse.ArgumentParser()
parser.add_argument("-i", "--interval", type=float, default=0.5, help="Seconds between key presses (default: 0.5)")
parser.add_argument("-d", "--delay", type=float, default=3, help="Seconds to wait before starting (default: 3)")
args = parser.parse_args()

keyboard = Controller()

KEYS = [Key.shift_l, Key.alt_l]
HOLD_TIME = 0.05


def press_key(key) -> None:
    keyboard.press(key)
    sleep(HOLD_TIME)
    keyboard.release(key)


def main():
    print(f"Starting in {args.delay}s, switch to the game window. Ctrl+C to stop.")
    sleep(args.delay)
    count = 0
    while True:
        # Press one at a time so Windows never sees Alt+Shift (input-language switch).
        for key in KEYS:
            press_key(key)
            sleep(args.interval)
        count += 1
        print(f"\rCycles: {count}", end="", flush=True)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Allow Ctrl+C to interrupt the program
    main()
