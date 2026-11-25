"""The bytes being edited (no Qt): a piece table over a file that stays on disk, so a file of many gigabytes opens at
once and an insert or delete anywhere costs nothing.

A piece is (source, start, length): source ORIGINAL reads the file, ADDED reads `self.added` (every byte typed or
pasted, appended, never changed). The document is the pieces in order. Undo / Redo keep whole piece lists (tuples of
small tuples: cheap). Bytes from ADDED pieces are the changed ones (shown orange until saved).

Sources: `FileSource` (a file, read with seek + read) and `DiskSource` (a drive or a disk image: reads aligned to the
sector size, as Windows requires for \\\\.\\C:). Disks can't grow or shrink: their buffers allow overwriting only, and
`save` writes the changed sectors in place, only after `read_only` was turned off.
"""

from __future__ import annotations

import os
import tempfile
import threading
from bisect import bisect_right

ORIGINAL, ADDED = 0, 1
UNDO_LIMIT = 1000
CHUNK = 1 << 20


class FileSource:
    """A file on disk, read when needed (never loaded whole)."""

    resizable = True

    def __init__(self, path: str | None):
        self.path = path
        self.f = open(path, "rb") if path else None
        self.size = os.fstat(self.f.fileno()).st_size if self.f else 0
        self.lock = threading.Lock()

    def read(self, offset: int, n: int) -> bytes:
        if not self.f or n <= 0:
            return b""
        with self.lock:
            self.f.seek(offset)
            return self.f.read(n)

    def close(self):
        if self.f:
            self.f.close()
            self.f = None

    def stamp(self):
        try:
            st = os.stat(self.path)
            return st.st_size, st.st_mtime_ns
        except (OSError, TypeError):
            return None


class DiskSource:
    """A drive (\\\\.\\C:, \\\\.\\PhysicalDrive0) or a disk image: fixed size, read in whole sectors."""

    resizable = False

    def __init__(self, path: str, size: int, sector: int = 512, label: str = ""):
        self.path, self.size, self.sector, self.label = path, size, sector, label
        self.f = open(path, "rb", buffering=0)
        self.lock = threading.Lock()

    def read(self, offset: int, n: int) -> bytes:
        if n <= 0 or offset >= self.size:
            return b""
        n = min(n, self.size - offset)
        start = offset - offset % self.sector
        end = offset + n
        end += (-end) % self.sector
        with self.lock:
            self.f.seek(start)
            data = self.f.read(end - start)
        return data[offset - start:offset - start + n]

    def write_sectors(self, changes: list[tuple[int, bytes]]) -> None:
        """Write changed bytes in place, whole sectors at a time (read, patch, write)."""
        with self.lock, open(self.path, "r+b", buffering=0) as w:
            for offset, data in changes:
                start = offset - offset % self.sector
                end = offset + len(data)
                end += (-end) % self.sector
                self.f.seek(start)
                block = bytearray(self.f.read(end - start))
                block[offset - start:offset - start + len(data)] = data
                w.seek(start)
                w.write(bytes(block))
                w.flush()
                os.fsync(w.fileno())

    def close(self):
        if self.f:
            self.f.close()
            self.f = None

    def stamp(self):
        return None


class Buffer:
    def __init__(self, source: FileSource | DiskSource | None = None, read_only: bool = False):
        self.source = source or FileSource(None)
        self.added = bytearray()
        self.pieces: tuple = ((ORIGINAL, 0, self.source.size),) if self.source.size else ()
        self._index()
        self.undo_stack: list[tuple] = []
        self.redo_stack: list[tuple] = []
        self.saved_pieces = self.pieces
        self.read_only = read_only or isinstance(self.source, DiskSource)
        self.stamp = self.source.stamp()

    @classmethod
    def open(cls, path: str, read_only: bool = False) -> "Buffer":
        return cls(FileSource(path), read_only)

    # ----------------------------------------------------------------- reading
    def _index(self):
        self.starts = []
        pos = 0
        for p in self.pieces:
            self.starts.append(pos)
            pos += p[2]
        self.length = pos

    def __len__(self) -> int:
        return self.length

    @property
    def path(self) -> str | None:
        return self.source.path

    @property
    def resizable(self) -> bool:
        return self.source.resizable

    @property
    def modified(self) -> bool:
        return self.pieces != self.saved_pieces

    def _piece_at(self, offset: int) -> int:
        return bisect_right(self.starts, offset) - 1

    def _read_piece(self, src: int, start: int, n: int) -> bytes:
        if src == ADDED:
            return bytes(self.added[start:start + n])
        return self.source.read(start, n)

    def read(self, offset: int, n: int) -> bytes:
        if offset < 0:
            n += offset
            offset = 0
        n = min(n, self.length - offset)
        if n <= 0:
            return b""
        out = bytearray()
        i = self._piece_at(offset)
        while n > 0 and i < len(self.pieces):
            src, start, ln = self.pieces[i]
            skip = offset - self.starts[i]
            take = min(ln - skip, n)
            out += self._read_piece(src, start + skip, take)
            offset += take
            n -= take
            i += 1
        return bytes(out)

    def changed_ranges(self, offset: int, n: int) -> list[tuple[int, int]]:
        """[start, end) document ranges inside [offset, offset+n) whose bytes are new or changed."""
        out = []
        if n <= 0 or not self.pieces:
            return out
        i = max(0, self._piece_at(offset))
        end = offset + n
        while i < len(self.pieces) and self.starts[i] < end:
            src, _, ln = self.pieces[i]
            if src == ADDED:
                a, b = max(offset, self.starts[i]), min(end, self.starts[i] + ln)
                if b > a:
                    out.append((a, b))
            i += 1
        return out

    def iter_chunks(self, offset: int = 0, end: int | None = None, size: int = CHUNK):
        end = self.length if end is None else min(end, self.length)
        while offset < end:
            data = self.read(offset, min(size, end - offset))
            if not data:
                break
            yield offset, data
            offset += len(data)

    # ----------------------------------------------------------------- editing
    def group(self):
        """`with buf.group():` several edits undo as one (Replace All, a paste over a selection)."""
        buf = self

        class _Group:
            def __enter__(self):
                buf._grouping = getattr(buf, "_grouping", 0) + 1
                buf._group_pushed = buf._grouping > 1 and getattr(buf, "_group_pushed", False)
                return buf

            def __exit__(self, *exc):
                buf._grouping -= 1
                if not buf._grouping:
                    buf._group_pushed = False
                return False
        return _Group()

    def _push(self):
        if getattr(self, "_grouping", 0):
            if self._group_pushed:
                self.redo_stack.clear()
                return
            self._group_pushed = True
        self.undo_stack.append(self.pieces)
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()

    def _check(self, resizing: bool):
        if self.read_only:
            raise PermissionError("read-only")
        if resizing and not self.resizable:
            raise ValueError("a disk can't grow or shrink: overwrite only")

    def _split(self, pieces: list, starts: list, offset: int) -> int:
        """Split so a piece starts at `offset`; returns that piece's index (len(pieces) at the end)."""
        total = starts[-1] + pieces[-1][2] if pieces else 0
        if offset >= total:
            return len(pieces)
        i = bisect_right(starts, offset) - 1
        src, start, ln = pieces[i]
        cut = offset - starts[i]
        if cut == 0:
            return i
        pieces[i:i + 1] = [(src, start, cut), (src, start + cut, ln - cut)]
        starts[i:i + 1] = [starts[i], starts[i] + cut]
        return i + 1

    def _apply(self, offset: int, remove: int, data: bytes) -> None:
        pieces, starts = list(self.pieces), list(self.starts)
        a = self._split(pieces, starts, offset) if pieces else 0
        b = self._split(pieces, starts, offset + remove) if remove and pieces else a
        new = []
        if data:
            new.append((ADDED, len(self.added), len(data)))
            self.added += data
        pieces[a:b] = new
        merged: list = []
        for p in pieces:                       # join neighbours that continue each other (keeps lists short)
            if merged and merged[-1][0] == p[0] and merged[-1][1] + merged[-1][2] == p[1]:
                q = merged[-1]
                merged[-1] = (q[0], q[1], q[2] + p[2])
            elif p[2]:
                merged.append(p)
        self.pieces = tuple(merged)
        self._index()

    def overwrite(self, offset: int, data: bytes, join_undo: bool = False) -> None:
        """Write over the bytes at `offset` (past the end, a file grows; a disk doesn't). `join_undo`: part of the
        last edit (the second hex digit of a byte typed): one Undo step for both."""
        grow = offset + len(data) > self.length
        self._check(grow)
        if offset > self.length:
            raise ValueError("past the end")
        if join_undo and self.undo_stack:
            self.redo_stack.clear()
        else:
            self._push()
        self._apply(offset, min(len(data), self.length - offset), data)

    def insert(self, offset: int, data: bytes) -> None:
        self._check(True)
        if not 0 <= offset <= self.length:
            raise ValueError("outside the file")
        self._push()
        self._apply(offset, 0, data)

    def delete(self, offset: int, n: int) -> None:
        self._check(True)
        n = min(n, self.length - offset)
        if n <= 0:
            return
        self._push()
        self._apply(offset, n, b"")

    def fill(self, offset: int, n: int, pattern: bytes) -> None:
        """Fill a block with a repeated pattern (Edit > Fill Selection), overwriting."""
        if not pattern or n <= 0:
            return
        data = (pattern * (n // len(pattern) + 1))[:n]
        self.overwrite(offset, data)

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.pieces)
        self.pieces = self.undo_stack.pop()
        self._index()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.pieces)
        self.pieces = self.redo_stack.pop()
        self._index()
        return True

    # ----------------------------------------------------------------- saving
    def save(self, path: str | None = None, progress=None) -> str:
        """Write the document. A file goes through a temporary file next to it, then replaces the old one (a failed
        save never leaves half a file); a disk gets only its changed sectors written, in place."""
        if isinstance(self.source, DiskSource):
            if path and path != self.source.path:
                return self._write_copy(path, progress)
            if self.read_only:
                raise PermissionError("read-only")
            changes = [(a, self.read(a, b - a)) for a, b in self.changed_ranges(0, self.length)]
            self.source.write_sectors(changes)
            self._reset_to_source(self.source)
            return self.source.path
        target = path or self.source.path
        if not target:
            raise ValueError("no file name")
        if path and os.path.abspath(path) != os.path.abspath(self.source.path or ""):
            self._write_copy(path, progress)
            self._switch(FileSource(path))
            return path
        self._write_copy(target, progress, replacing=True)
        return target

    def _write_copy(self, target: str, progress=None, replacing: bool = False) -> str:
        folder = os.path.dirname(os.path.abspath(target))
        fd, tmp = tempfile.mkstemp(prefix=".pr7hx-", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "wb") as out:
                done = 0
                for _, data in self.iter_chunks():
                    out.write(data)
                    done += len(data)
                    if progress:
                        progress(done, self.length)
                out.flush()
                os.fsync(out.fileno())
            if replacing:
                try:
                    import shutil
                    shutil.copymode(target, tmp)
                except OSError:
                    pass
                self.source.close()              # Windows won't replace a file that's open
            os.replace(tmp, target)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            if replacing and self.source.f is None:
                self.source.f = open(self.source.path, "rb")
            raise
        if replacing:
            self._switch(FileSource(target))
        return target

    def _switch(self, source):
        """After a save, the saved file is the original: pieces point at it again."""
        old = self.source
        if old is not source:
            old.close()
        self._reset_to_source(source)

    def _reset_to_source(self, source):
        self.source = source
        self.added = bytearray()
        self.pieces = ((ORIGINAL, 0, source.size),) if source.size else ()
        if isinstance(source, DiskSource):
            self.pieces = ((ORIGINAL, 0, source.size),)
        self._index()
        self.saved_pieces = self.pieces
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.stamp = source.stamp()

    def changed_on_disk(self) -> bool:
        return self.stamp is not None and self.source.stamp() != self.stamp

    def close(self):
        self.source.close()
