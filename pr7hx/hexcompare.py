"""Analysis > File compare (no Qt), the way HxD compares: byte for byte at the same offsets (no realigning), the
differences as runs of neighbouring bytes. A tail one file has and the other hasn't is one more difference."""

from __future__ import annotations

from .buffer import CHUNK, Buffer

LIMIT = 100_000


def differences(a: Buffer, b: Buffer, limit: int = LIMIT, cancelled=None) -> list[tuple[int, int]]:
    """[start, end) runs where the bytes differ (or exist on one side only)."""
    out: list[tuple[int, int]] = []
    common = min(len(a), len(b))
    run = None
    pos = 0
    while pos < common and len(out) < limit:
        if cancelled and cancelled():
            break
        n = min(CHUNK, common - pos)
        x, y = a.read(pos, n), b.read(pos, n)
        if x == y:
            if run is not None:
                out.append((run, pos))
                run = None
            pos += n
            continue
        for i in range(n):
            if x[i] != y[i]:
                if run is None:
                    run = pos + i
            elif run is not None:
                out.append((run, pos + i))
                run = None
        pos += n
    if run is not None:
        out.append((run, common))
    if len(a) != len(b) and len(out) < limit:
        if out and out[-1][1] == common:
            out[-1] = (out[-1][0], max(len(a), len(b)))
        else:
            out.append((common, max(len(a), len(b))))
    return out


def differing_bytes(runs: list[tuple[int, int]]) -> int:
    return sum(e - s for s, e in runs)
