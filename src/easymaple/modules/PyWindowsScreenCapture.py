import ctypes
import ctypes.wintypes


class PyWindowsScreenCapture:
    def __init__(self, dll_path):
        self.dll = ctypes.CDLL(dll_path)
        self._setup_methods()

    def _setup_methods(self):
        self.dll.GetMonitorsInfo.argtypes = [ctypes.POINTER(MonitorInfo)]
        self.dll.GetMonitorsInfo.restype = ctypes.c_int
        self.dll.CaptureMonitor.argtypes = [ctypes.c_int,
                                            ctypes.POINTER(ctypes.c_int),
                                            ctypes.POINTER(ctypes.c_int),
                                            ctypes.POINTER(MonitorInfo),
                                            ctypes.c_int]
        self.dll.CaptureMonitor.restype = ctypes.POINTER(ctypes.c_ubyte)
        self.dll.FreeAllCaptures.argtypes = []
        self.dll.FreeAllCaptures.restype = None

    def get_monitors_info(self):
        monitor_info_array = (MonitorInfo * 10)()
        num_monitors = self.dll.GetMonitorsInfo(monitor_info_array)
        return [monitor_info_array[i] for i in range(num_monitors)]

    def capture_monitor(self, monitor_index):
        width = ctypes.c_int()
        height = ctypes.c_int()
        monitor_info_array = (MonitorInfo * 10)()
        num_monitors = self.dll.GetMonitorsInfo(monitor_info_array)

        data = self.dll.CaptureMonitor(monitor_index, ctypes.byref(width), ctypes.byref(height),
                                       monitor_info_array, num_monitors)
        return data, width.value, height.value

    def free_all_captures(self):
        self.dll.FreeAllCaptures()

class MonitorInfo(ctypes.Structure):
    _fields_ = [("monitorIndex", ctypes.c_int),
                ("monitorRect", ctypes.wintypes.RECT),
                ("isPrimary", ctypes.c_bool)]