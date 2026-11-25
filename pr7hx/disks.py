"""File > Open Disk (no Qt): Windows' drives (C:, D: ...) and physical disks (PhysicalDrive0 ...) with their sizes and
sector sizes, opened read-only (writing needs Edit > Read-only turned off, and administrator rights). Disk images
(.img, .iso, .bin) open the same way with the sector size given."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from .buffer import Buffer, DiskSource

IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
IOCTL_DISK_GET_DRIVE_GEOMETRY = 0x00070000
DRIVE_TYPES = {2: "Removable", 3: "Fixed", 4: "Network", 5: "CD/DVD", 6: "RAM disk"}


@dataclass
class Disk:
    path: str              # \\.\C:  or  \\.\PhysicalDrive0  or an image file
    label: str             # "C: (Windows)"  "Physical disk 0"
    size: int
    sector: int = 512
    kind: str = ""


def _device_info(path: str) -> tuple[int, int] | None:
    """(size, sector size) of a device, or None (not there, or no rights)."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    h = k32.CreateFileW(path, 0x80000000, 0x1 | 0x2, None, 3, 0, None)      # GENERIC_READ, share read/write
    if h in (None, wintypes.HANDLE(-1).value):
        return None
    try:
        size = ctypes.c_longlong(0)
        got = wintypes.DWORD(0)
        if not k32.DeviceIoControl(h, IOCTL_DISK_GET_LENGTH_INFO, None, 0, ctypes.byref(size), 8,
                                   ctypes.byref(got), None):
            return None
        geo = (ctypes.c_byte * 24)()
        sector = 512
        if k32.DeviceIoControl(h, IOCTL_DISK_GET_DRIVE_GEOMETRY, None, 0, geo, 24, ctypes.byref(got), None):
            sector = int.from_bytes(bytes(geo)[20:24], "little") or 512
        return size.value, sector
    finally:
        k32.CloseHandle(h)


def list_disks() -> list[Disk]:
    if sys.platform != "win32":
        return []
    import ctypes
    out = []
    k32 = ctypes.windll.kernel32
    mask = k32.GetLogicalDrives()
    for i in range(26):
        if not mask >> i & 1:
            continue
        letter = chr(65 + i)
        kind = DRIVE_TYPES.get(k32.GetDriveTypeW(f"{letter}:\\"), "")
        if kind in ("Network", ""):
            continue
        name = ctypes.create_unicode_buffer(261)
        k32.GetVolumeInformationW(f"{letter}:\\", name, 261, None, None, None, None, 0)
        info = _device_info(f"\\\\.\\{letter}:")
        label = f"{letter}:" + (f" ({name.value})" if name.value else "")
        out.append(Disk(f"\\\\.\\{letter}:", label, info[0] if info else 0, info[1] if info else 512, kind))
    for n in range(16):
        info = _device_info(f"\\\\.\\PhysicalDrive{n}")
        if info:
            out.append(Disk(f"\\\\.\\PhysicalDrive{n}", f"Physical disk {n}", info[0], info[1], "Physical"))
    return out


def open_disk(d: Disk) -> Buffer:
    """Read-only always at first; PermissionError without administrator rights (Windows says access denied)."""
    return Buffer(DiskSource(d.path, d.size, d.sector, d.label), read_only=True)


def open_image(path: str, sector: int = 512) -> Buffer:
    return open_disk(Disk(path, os.path.basename(path), os.path.getsize(path), sector, "Image"))
