import pywinio
import time
import atexit
import ctypes
# Scancodes references : https://www.win.tue.nl/~aeb/linux/kbd/scancodes-1.html

# KeyBoard Commands
# Command port
KBC_KEY_CMD = 0x64
# Data port
KBC_KEY_DATA = 0x60

MAPVK_VK_TO_VSC = 0

g_winio = None
user32 = ctypes.WinDLL('user32', use_last_error=True)

def get_winio():
    global g_winio

    if g_winio is None:
            g_winio = pywinio.WinIO()
            def __clear_winio():
                    global g_winio
                    g_winio = None
            atexit.register(__clear_winio)

    return g_winio

def wait_for_buffer_empty():
    '''
    Wait keyboard buffer empty
    '''

    winio = get_winio()

    dwRegVal = 0x02
    while (dwRegVal & 0x02):
            dwRegVal = winio.get_port_byte(KBC_KEY_CMD)

def key_down(virtual_code):
    winio = get_winio()

    wait_for_buffer_empty();
    winio.set_port_byte(KBC_KEY_CMD, 0xd2);
    wait_for_buffer_empty();
    scancode = user32.MapVirtualKeyExW(virtual_code, MAPVK_VK_TO_VSC, 0)
    winio.set_port_byte(KBC_KEY_DATA, scancode)

def key_up(virtual_code):
    winio = get_winio()

    wait_for_buffer_empty();
    winio.set_port_byte( KBC_KEY_CMD, 0xd2);
    wait_for_buffer_empty();
    scancode = user32.MapVirtualKeyExW(virtual_code, MAPVK_VK_TO_VSC, 0)
    winio.set_port_byte( KBC_KEY_DATA, scancode | 0x80);

def key_press(scancode, press_time = 0.2):
    key_down( scancode )
    time.sleep( press_time )
    key_up( scancode )

