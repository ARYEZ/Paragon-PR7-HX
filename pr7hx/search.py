"""Find and Replace (no Qt), HxD's kinds: hex values, a text string (in an encoding, optionally ignoring case), an
integer or a floating point number (size and byte order). Every kind becomes a bytes regular expression with a known
longest match, so the buffer is searched in chunks that overlap by that much: a match across a chunk border isn't
missed and a file of many gigabytes is never read whole."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from .buffer import CHUNK, Buffer

ENCODINGS = {"ANSI": "cp1252", "UTF-8": "utf-8", "UTF-16 LE": "utf-16-le", "UTF-16 BE": "utf-16-be"}
INT_SIZES = {"8 bit": 1, "16 bit": 2, "32 bit": 4, "64 bit": 8}
LIMIT = 100_000            # Find All / Replace All stop here (HxD warns too)


@dataclass
class Pattern:
    regex: re.Pattern
    maxlen: int
    data: bytes             # the plain bytes (for Replace and for showing)


def parse_hex(text: str) -> bytes:
    """ "4E 54 46 53", "4e544653", "0x4E,0x54" -> bytes. Raises ValueError for odd or non-hex digits."""
    t = re.sub(r"0x", "", text.strip(), flags=re.I)
    t = re.sub(r"[\s,;:\-]", "", t)
    if not t or len(t) % 2 or re.search(r"[^0-9a-fA-F]", t):
        raise ValueError("hex values are pairs of 0-9 A-F")
    return bytes.fromhex(t)


def encode_number(kind: str, text: str, size: int = 4, order: str = "little") -> bytes:
    endian = "<" if order == "little" else ">"
    if kind == "float":
        v = float(text.replace(",", "."))
        return struct.pack(endian + ("f" if size == 4 else "d"), v)
    v = int(text, 0)
    bits = 8 * size
    if -(1 << (bits - 1)) <= v < (1 << (bits - 1)):
        return v.to_bytes(size, order, signed=True)        # fits as a signed number (negative ones included)
    if 0 <= v < (1 << bits):
        return v.to_bytes(size, order, signed=False)       # only as unsigned: 4294967295 -> FF FF FF FF
    raise ValueError(f"doesn't fit in {bits} bits")


def make(kind: str, text: str, encoding: str = "ANSI", case: bool = True, size: int = 4,
         order: str = "little") -> Pattern:
    """kind: hex / text / int / float. `case` False = ignore case (text only)."""
    if kind == "hex":
        data = parse_hex(text)
    elif kind == "text":
        if not text:
            raise ValueError("nothing to find")
        codec = ENCODINGS.get(encoding, encoding)
        data = text.encode(codec, errors="strict")
        if not case:
            parts, longest = [], 0
            for ch in text:
                forms = {ch.encode(codec), ch.lower().encode(codec), ch.upper().encode(codec)}
                longest += max(len(f) for f in forms)
                parts.append(b"(?:" + b"|".join(re.escape(f) for f in sorted(forms)) + b")")
            return Pattern(re.compile(b"".join(parts), re.S), longest, data)
    elif kind in ("int", "float"):
        data = encode_number(kind, text, size, order)
    else:
        raise ValueError(kind)
    return Pattern(re.compile(re.escape(data), re.S), len(data), data)


def find(buf: Buffer, pat: Pattern, start: int = 0, backwards: bool = False, end: int | None = None):
    """The first match at or after `start` (before `start` going backwards): (offset, length) or None."""
    end = len(buf) if end is None else min(end, len(buf))
    over = max(0, pat.maxlen - 1)
    if not backwards:
        pos = max(0, start)
        while pos < end:
            data = buf.read(pos, min(CHUNK + over, end - pos))
            m = pat.regex.search(data)
            if m:
                return pos + m.start(), m.end() - m.start()
            if pos + len(data) >= end:
                return None
            pos += CHUNK
        return None
    hi = min(start, end)
    while hi > 0:
        lo = max(0, hi - CHUNK)
        data = buf.read(lo, min(hi + over, end) - lo)
        last = None
        for m in pat.regex.finditer(data):
            if lo + m.start() < hi:
                last = m
        if last is not None:
            return lo + last.start(), last.end() - last.start()
        hi = lo
    return None


def find_all(buf: Buffer, pat: Pattern, limit: int = LIMIT) -> list[tuple[int, int]]:
    out = []
    pos = 0
    while len(out) < limit:
        got = find(buf, pat, pos)
        if got is None:
            break
        out.append(got)
        pos = got[0] + max(1, got[1])
    return out


def replace_all(buf: Buffer, pat: Pattern, new: bytes, limit: int = LIMIT) -> int:
    """Replace every match (one Undo step). A disk (fixed size) needs the replacement to be as long as the match."""
    hits = find_all(buf, pat, limit)
    if not hits:
        return 0
    with buf.group():
        for offset, length in reversed(hits):
            if len(new) == length:
                buf.overwrite(offset, new)
            else:
                buf.delete(offset, length)
                if new:
                    buf.insert(offset, new)
    return len(hits)
