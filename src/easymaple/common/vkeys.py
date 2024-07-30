import time

from src.easymaple.common.driver_key import DriverKey

d_key = DriverKey()


def key_down(key):
    d_key.user_key_down(key)


def key_up(key):
    d_key.user_key_up(key)


def press(key, n=1, down_time=0.1, up_time=0.01):
    for _i in range(n):
        if key == "":
            return
        key_down(key)
        time.sleep(down_time)
        key_up(key)
        time.sleep(up_time)


def click():
    return NotImplementedError


