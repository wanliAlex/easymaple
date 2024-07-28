# -*- coding: utf-8 -*-
from ctypes import CDLL
from time import sleep,time
import os
import threading
from src.easymaple.common import winio_key
import platform

driver_dir_path = r'driver'
dll_path = os.path.abspath(driver_dir_path+'/kmclassdll.dll')
driver_path = bytes(os.path.abspath(driver_dir_path+'/kmclass.sys').encode())


class DriverKey():
    def __init__(self):
        self.thread = threading.Thread(target=self._main)
        self.thread.daemon = True
        self.key_up_list = []
        self.key_down_list = []
        self.uname = platform.uname()
        if self.uname[2] != '7':  # platform release version
            self.load_driver()
        self.start()

    def start(self):
        """Starts this DriverKey's thread."""

        print('\n[~] Started DriverKey')
        self.thread.start()

    def _main(self):
        self.key_down_objs = {}
        self.key_up_objs = {}
        while (True):
            if len(self.key_up_list) > 0:
                new_key = self.key_up_list.pop()
                if not new_key in self.key_up_objs:
                    self.key_up_objs[new_key] = time()

            if len(self.key_down_list) > 0:
                new_key = self.key_down_list.pop()
                if not new_key in self.key_down_objs:
                    self.key_down_objs[new_key] = {'last_t': time(), 'count': 0}

            for k in self.key_up_objs:
                self._key_up(k)
                # self.key_up_objs.pop(k)
                if k in self.key_down_objs:
                    self.key_down_objs.pop(k)
            self.key_up_objs = {}

            for k in self.key_down_objs:
                temp_key = self.key_down_objs[k]
                if temp_key['count'] == 0:
                    self._key_down(k)
                    temp_key['count'] = temp_key['count'] + 1
                    temp_key['last_t'] = time()
                elif temp_key['count'] == 1:
                    if time() - temp_key['last_t'] >= 0.25:
                        self._key_down(k)
                        temp_key['last_t'] = time()
                        temp_key['count'] = temp_key['count'] + 1
                elif time() - temp_key['last_t'] >= 0.03:
                    self._key_down(k)
                    temp_key['last_t'] = time()
                    temp_key['count'] = temp_key['count'] + 1
            sleep(0.002)

    def user_key_down(self, key):
        self.key_down_list.append(key)

    def user_key_up(self, key):
        self.key_up_list.append(key)

    def _key_up(self, key):
        if self.uname[2] == '7':  # platform release version
            winio_key.key_up(key)
            return
        except_keys = [0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E]
        if key in except_keys:
            self._key_up_e1(key)
        else:
            self.driver.KeyUp(key)

    def _key_down(self, key):
        if self.uname[2] == '7':  # platform release version
            winio_key.key_down(key)
            return
        except_keys = [0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E]
        if key in except_keys:
            self._key_down_e0(key)
        else:
            self.driver.KeyDown(key)

    def _key_up_e1(self, key):
        self.driver.KeyUp(key)

    def _key_down_e0(self, key):
        self.driver.KeyDown(key)

    def _left_button_down(self):
        self.driver.MouseLeftButtonDown()

    def _left_button_up(self):
        self.driver.MouseLeftButtonUp()

    def _right_button_down(self):
        self.driver.MouseRightButtonDown()

    def _right_button_up(self):
        self.driver.MouseRightButtonUp()

    def _middle_button_down(self):
        self.driver.MouseMiddleButtonDown()

    def _middle_button_up(self):
        self.driver.MouseMiddleButtonUp()

    def _move_rel(self, x, y):
        self.driver.MouseMoveRELATIVE(x, y)

    def _move_to(self, x, y):
        self.driver.MouseMoveABSOLUTE(x, y)

    def load_driver(self):
        self.driver = CDLL(dll_path)
        self.driver.LoadNTDriver('kmclass', driver_path)
        self.driver.SetHandle()

    def unload_driver(self):
        self.driver.UnloadNTDriver('kmclass')
