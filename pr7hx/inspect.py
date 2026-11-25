"""The Data inspector (no Qt): the bytes at the cursor read as every common type, in the chosen byte order, and the
editable ones written back from text (HxD lets you type a value there)."""

from __future__ import annotations

import datetime
import struct
import uuid

EPOCH_1601 = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
EPOCH_1970 = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

# name, bytes needed, struct code (None = special), editable
TYPES = [("Binary (8 bit)", 1, None, True), ("Int8", 1, "b", True), ("UInt8", 1, "B", True),
         ("Int16", 2, "h", True), ("UInt16", 2, "H", True), ("Int24", 3, None, True), ("UInt24", 3, None, True),
         ("Int32", 4, "i", True), ("UInt32", 4, "I", True), ("Int64", 8, "q", True), ("UInt64", 8, "Q", True),
         ("Float (32 bit)", 4, "f", True), ("Double (64 bit)", 8, "d", True),
         ("DOS date", 2, None, False), ("DOS time", 2, None, False), ("FILETIME", 8, None, False),
         ("Unix time (32 bit)", 4, None, False), ("Unix time (64 bit)", 8, None, False), ("GUID", 16, None, False),
         ("Character (ANSI)", 1, None, False), ("Character (UTF-8)", 1, None, False),
         ("Character (UTF-16)", 2, None, False)]
BY_NAME = {t[0]: t for t in TYPES}


def _when(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def value(name: str, data: bytes, order: str = "little") -> str:
    """The text the inspector shows ("" when there aren't enough bytes, "invalid" for a bad date)."""
    _, need, code, _ = BY_NAME[name]
    if len(data) < need:
        return ""
    b = data[:need]
    e = "<" if order == "little" else ">"
    try:
        if code:
            v = struct.unpack(e + code, b)[0]
            return f"{v:.9g}" if code in "fd" else str(v)
        if name == "Binary (8 bit)":
            return f"{b[0]:08b}"
        if name in ("Int24", "UInt24"):
            return str(int.from_bytes(b, order, signed=name == "Int24"))
        if name == "DOS date":
            v = int.from_bytes(b, order)
            return datetime.date(1980 + (v >> 9), (v >> 5) & 15, v & 31).isoformat()
        if name == "DOS time":
            v = int.from_bytes(b, order)
            return datetime.time(v >> 11, (v >> 5) & 63, (v & 31) * 2).isoformat()
        if name == "FILETIME":
            v = int.from_bytes(b, order)
            return _when(EPOCH_1601 + datetime.timedelta(microseconds=v // 10))
        if name.startswith("Unix time"):
            v = int.from_bytes(b, order, signed=True)
            return _when(EPOCH_1970 + datetime.timedelta(seconds=v))
        if name == "GUID":
            return "{" + str(uuid.UUID(bytes_le=b) if order == "little" else uuid.UUID(bytes=b)).upper() + "}"
        if name == "Character (ANSI)":
            return b.decode("cp1252", errors="replace") if b[0] >= 32 else f"\\x{b[0]:02X}"
        if name == "Character (UTF-8)":
            for n in (1, 2, 3, 4):
                try:
                    ch = data[:n].decode("utf-8")
                    return ch if ch.isprintable() else f"U+{ord(ch):04X}"
                except UnicodeDecodeError:
                    continue
            return "invalid"
        if name == "Character (UTF-16)":
            ch = b.decode("utf-16-le" if order == "little" else "utf-16-be", errors="strict")
            return ch if ch.isprintable() else f"U+{ord(ch):04X}"
    except (ValueError, OverflowError, UnicodeDecodeError):
        return "invalid"
    return ""


def rows(data: bytes, order: str = "little") -> list[tuple[str, str, bool]]:
    return [(name, value(name, data, order), editable) for name, _, _, editable in TYPES]


def encode(name: str, text: str, order: str = "little") -> bytes:
    """Bytes for a typed value. Raises ValueError when it doesn't fit."""
    _, need, code, editable = BY_NAME[name]
    if not editable:
        raise ValueError("not editable")
    text = text.strip()
    if name == "Binary (8 bit)":
        v = int(text, 2)
        if not 0 <= v <= 255:
            raise ValueError("8 bits")
        return bytes([v])
    if name in ("Int24", "UInt24"):
        return int(text, 0).to_bytes(3, order, signed=name == "Int24")
    e = "<" if order == "little" else ">"
    try:
        return struct.pack(e + code, float(text.replace(",", ".")) if code in "fd" else int(text, 0))
    except struct.error as err:
        raise ValueError(str(err)) from err
