"""The made-up files of the mock-up and the screenshots: a real PNG, an NTFS boot sector, a binary settings file."""
import struct
import zlib

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QPainter

from pr7hx import theme


def png_bytes() -> bytes:
    img = QImage(640, 360, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.fillRect(img.rect(), theme.family_gradient(0, 0, 640, 0))
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    data = bytearray(bytes(buf.data()))
    data += b"tEXtComment\0ELSEWORLD poster draft"      # something readable further down
    return bytes(data)


def boot_sector() -> bytes:
    b = bytearray(512)
    b[0:3] = b"\xEB\x52\x90"
    b[3:11] = b"NTFS    "
    struct.pack_into("<HBH", b, 11, 512, 8, 0)
    b[21] = 0xF8
    struct.pack_into("<HHI", b, 24, 63, 255, 2048)
    struct.pack_into("<Q", b, 40, 999_161_855)
    struct.pack_into("<QQ", b, 48, 786_432, 2)
    b[64] = 0xF6
    b[68] = 0x01
    struct.pack_into("<Q", b, 72, 0x5A3C_91E2_0D4B_7710)
    code = b"\xFA\x33\xC0\x8E\xD0\xBC\x00\x7C\xFB\x68\xC0\x07\x1F\x1E\x68\x66\x00\xCB\x88\x16\x0E\x00"
    b[84:84 + len(code)] = code
    msg = b"\r\nA disk read error occurred\0\r\nBOOTMGR is missing\0\r\nBOOTMGR is compressed\0\r\nPress Ctrl+Alt+Del to restart\r\n\0"
    b[0x180:0x180 + len(msg)] = msg
    b[510:512] = b"\x55\xAA"
    return bytes(b)


def settings_dat(version: int) -> bytes:
    """A made-up binary settings file: header, a few fields, a name, a CRC."""
    body = bytearray()
    body += b"PRSD" + struct.pack("<HH", 2, version)
    body += struct.pack("<IIff", 3840, 2160, 23.976 if version == 1 else 24.0, 1.0)
    body += b"ELSEWORLD_master".ljust(32, b"\0")
    body += struct.pack("<I", 12 if version == 1 else 14)
    body += bytes(range(32, 32 + 48)) if version == 1 else bytes(range(32, 40)) + b"\x7F\x80" + bytes(range(42, 80))
    body += struct.pack("<I", zlib.crc32(bytes(body)))
    return bytes(body)


