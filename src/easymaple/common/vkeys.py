from ctypes import CDLL
import time
from src.easymaple.common.key_map import KEY_MAP

dll_path = r"D:\easymaple\src\easymaple\common\kmclassdll.dll"
driver_path = b"D:\\easymaple\\src\\easymaple\\common\kmclass.sys"

driver = CDLL(dll_path)
driver.LoadNTDriver("easymaple-input", driver_path)
driver.SetHandle()

def key_down(key):
    print(key)
    driver.KeyDown(KEY_MAP[key])


def key_up(key):
    driver.KeyUp(KEY_MAP[key])


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


