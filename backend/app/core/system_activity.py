"""Whether someone is using the computer and whether it runs on battery, for background work that must
only happen when nobody would notice it (preextract_service).

Only Windows answers, through GetLastInputInfo (user32) and GetSystemPowerStatus (kernel32), called with
the standard library's ctypes. Elsewhere, or if a call fails, the answer is None (unknown), and callers
treat unknown as "not idle", so nothing runs in the background where it can't be checked.
"""

import ctypes
import sys


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


class _PowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


def idle_seconds():
    """Seconds since the last keyboard or mouse input in this session, or None where that can't be read."""
    if sys.platform != "win32":
        return None
    info = _LastInputInfo(ctypes.sizeof(_LastInputInfo), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    kernel32 = ctypes.windll.kernel32
    kernel32.GetTickCount.restype = ctypes.c_uint
    # Both are milliseconds since startup in 32 bits, which wrap every 49.7 days; the mask keeps the difference right.
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


def on_battery():
    """True on battery or with battery saver on, False on mains power, None where that can't be read."""
    if sys.platform != "win32":
        return None
    status = _PowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)) or status.ACLineStatus == 255:
        return None
    return status.ACLineStatus == 0 or bool(status.SystemStatusFlag & 1)
