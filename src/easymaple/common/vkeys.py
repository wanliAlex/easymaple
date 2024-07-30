import time
from ctypes import CDLL

from src.easymaple.common.key_map import KEY_MAP

dll_path = r"D:\easymaple\src\easymaple\common\kmclassdll.dll"
driver_path = bytes(r"D:\easymaple\src\easymaple\common\kmclass.sys".encode("utf-8"))

service_name = "kmclass"

driver = CDLL(dll_path)
driver.LoadNTDriver(service_name, driver_path)
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