"""Analysis > Checksums (no Qt): CRC-32, MD5, SHA-1, SHA-256, SHA-512 of a block or the whole file, read in chunks
(a big file never loads whole); `progress(done, total)` and `cancelled()` let the window show and stop it."""

from __future__ import annotations

import hashlib
import zlib

from .buffer import Buffer

ALGORITHMS = ["CRC-32", "MD5", "SHA-1", "SHA-256", "SHA-512"]


class Cancelled(Exception):
    pass


def compute(buf: Buffer, start: int = 0, end: int | None = None, algorithms=ALGORITHMS, progress=None,
            cancelled=None) -> dict[str, str]:
    end = len(buf) if end is None else min(end, len(buf))
    hashes = {a: hashlib.new(a.replace("-", "").lower()) for a in algorithms if a != "CRC-32"}
    crc = 0
    for offset, data in buf.iter_chunks(start, end):
        if cancelled and cancelled():
            raise Cancelled()
        if "CRC-32" in algorithms:
            crc = zlib.crc32(data, crc)
        for h in hashes.values():
            h.update(data)
        if progress:
            progress(offset + len(data) - start, end - start)
    out = {}
    for a in algorithms:
        out[a] = f"{crc & 0xFFFFFFFF:08X}" if a == "CRC-32" else hashes[a].hexdigest().upper()
    return out
