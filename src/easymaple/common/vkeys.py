from ctypes import CDLL
import time
from src.easymaple.common.key_map import KEY_MAP

kmclass_dll_path = r"D:\easymaple\driver\kmclassdll.dll"
kmclass_driver_path = b"D:\\easymaple\\driver\\kmclass.sys"

driver = CDLL(kmclass_dll_path)
driver.LoadNTDriver("kmclass", kmclass_driver_path)
driver.SetHandle()


def key_down(key):
    if key == "":
        return
    driver.KeyDown(KEY_MAP[key])


def key_up(key):
    if key == "":
        return
    driver.KeyUp(KEY_MAP[key])


def press(key, n=1, down_time=0.1, up_time=0.01):
    if key == "":
        return
    for _ in range(n):
        key_down(key)
        time.sleep(down_time)
        key_up(key)
        time.sleep(up_time)