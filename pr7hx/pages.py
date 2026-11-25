"""PR7-HX's tabs: EditorPage (one file or disk: the hex view, and a side panel with the Data inspector, Bookmarks and
Checksums) and ComparePage (two files side by side, the differing bytes marked, Next / Previous difference)."""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QRadioButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from . import checksums, hexcompare, inspect, settings, theme
from .buffer import Buffer, DiskSource
from .hexview import HexView


def _field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def _dim(text=""):
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    return lab


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} bytes"
    f = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        f /= 1024
        if f < 1024 or unit == "TB":
            return f"{f:.2f} {unit}"
    return ""


class _Bridge(QObject):
    sums = Signal(object, object)       # results, error
    progress = Signal(int, int)


class EditorPage(QWidget):
    changed = Signal()                  # title, status, keys
    kind = "editor"

    def __init__(self, buf: Buffer, parent=None, sync: bool = False, ask=None):
        super().__init__(parent)
        self.buf, self.sync, self.ask = buf, sync, ask
        self.bookmarks: list[dict] = []          # {"name", "start", "end"}
        self.order = settings.get("byte_order", "little") or "little"
        self.view = HexView(buf)
        self.view.cursor_moved.connect(self._moved)
        self.view.edited.connect(self._edited)
        self.view.refused.connect(lambda msg: self.ask and self.ask("say", ("warning", msg)))
        self.bridge = _Bridge()
        self.bridge.sums.connect(self._summed)
        self.bridge.progress.connect(lambda d, t: self._sum_progress(d, t))
        self._cancel = threading.Event()
        self.summing = False

        self.side = QTabWidget()
        self.side.setFixedWidth(340)
        # Data inspector
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 6, 0, 0)
        self.inspector = QTreeWidget()
        self.inspector.setHeaderLabels(["TYPE", "VALUE"])
        self.inspector.setRootIsDecorated(False)
        self.inspector.setIndentation(0)
        self.inspector.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.inspector.itemDoubleClicked.connect(lambda it, _c: self.edit_value(it.text(0)))
        pl.addWidget(self.inspector, 1)
        row = QHBoxLayout()
        row.addWidget(_field("Byte order"))
        self.order_group = QButtonGroup(self)
        self.order_buttons = {}
        for key, text in (("little", "Little endian"), ("big", "Big endian")):
            r = QRadioButton(text)
            r.setChecked(self.order == key)
            r.toggled.connect(lambda on, k=key: on and self.set_order(k))
            self.order_group.addButton(r)
            row.addWidget(r)
            self.order_buttons[key] = r
        row.addStretch(1)
        pl.addLayout(row)
        self.side.addTab(page, "INSPECTOR")
        # Bookmarks
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 6, 0, 0)
        self.mark_list = QTreeWidget()
        self.mark_list.setHeaderLabels(["BOOKMARK", "OFFSET", "LENGTH"])
        self.mark_list.setRootIsDecorated(False)
        self.mark_list.setIndentation(0)
        self.mark_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.mark_list.itemDoubleClicked.connect(lambda it, _c: self.go_bookmark(self.mark_list.indexOfTopLevelItem(it)))
        pl.addWidget(self.mark_list, 1)
        row = QHBoxLayout()
        add = QPushButton("ADD")
        add.clicked.connect(lambda: self.add_bookmark())
        rem = QPushButton("REMOVE")
        rem.clicked.connect(lambda: self.remove_bookmark(self.mark_list.indexOfTopLevelItem(
            self.mark_list.currentItem()) if self.mark_list.currentItem() else -1))
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        pl.addLayout(row)
        self.side.addTab(page, "BOOKMARKS")
        # Checksums
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 6, 0, 0)
        self.sum_scope = _dim("")
        pl.addWidget(self.sum_scope)
        self.sum_list = QTreeWidget()
        self.sum_list.setHeaderLabels(["CHECKSUM", "VALUE"])
        self.sum_list.setRootIsDecorated(False)
        self.sum_list.setIndentation(0)
        self.sum_list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        pl.addWidget(self.sum_list, 1)
        row = QHBoxLayout()
        self.sum_button = QPushButton("CALCULATE")
        self.sum_button.clicked.connect(lambda: self.calculate())
        row.addWidget(self.sum_button)
        row.addStretch(1)
        pl.addLayout(row)
        self.side.addTab(page, "CHECKSUMS")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.side)
        self.side.setVisible(settings.get_bool("side_panel", True))
        self._moved()

    # ----------------------------------------------------------------- what's shown
    @property
    def is_disk(self) -> bool:
        return isinstance(self.buf.source, DiskSource)

    def name(self) -> str:
        if self.is_disk:
            return self.buf.source.label or self.buf.path
        return os.path.basename(self.buf.path) if self.buf.path else "Untitled"

    def title(self) -> str:
        return self.name() + (" *" if self.buf.modified else "")

    def modified(self) -> bool:
        return self.buf.modified

    def restyle(self):
        self.view.restyle()
        self._moved()

    def status(self) -> str:
        v = self.view
        a, b = v.selection()
        fmt = (lambda n: str(n)) if v.decimal_offsets else (lambda n: f"{n:X}")
        tag = "(d)" if v.decimal_offsets else "(h)"
        parts = [f"Offset{tag}: {fmt(v.cursor)}"]
        if b > a:
            parts += [f"Block{tag}: {fmt(a)}-{fmt(b - 1)}", f"Length{tag}: {fmt(b - a)}"]
        if self.is_disk:
            src = self.buf.source
            parts.insert(0, f"sector {v.cursor // src.sector:,} of {len(self.buf) // src.sector:,}".replace(",", " "))
        return "   ·   ".join(parts)

    def mode_text(self) -> str:
        bits = ["Read-only" if self.buf.read_only else ("Insert" if self.view.insert_mode else "Overwrite")]
        if self.buf.modified:
            n = sum(e - s for s, e in self.buf.changed_ranges(0, len(self.buf)))
            bits.append(f"{n} byte{'s' if n != 1 else ''} changed, unsaved")
        bits.append(fmt_size(len(self.buf)))
        return "   ·   ".join(bits)

    def _moved(self):
        self.fill_inspector()
        a, b = self.view.selection()
        self.sum_scope.setText(f"Of the selection ({b - a} bytes)" if b > a else f"Of the whole {'disk' if self.is_disk else 'file'}")
        self.changed.emit()

    def _edited(self):
        self.fill_inspector()
        self.changed.emit()

    # ----------------------------------------------------------------- inspector
    def fill_inspector(self):
        data = self.buf.read(self.view.cursor, 16)
        self.inspector.clear()
        for name, value, editable in inspect.rows(data, self.order):
            it = QTreeWidgetItem([name, value])
            it.setForeground(0, QColor(theme.TEXT_DIM))
            if not editable:
                it.setForeground(1, QColor(theme.TEXT_DIM))
            self.inspector.addTopLevelItem(it)

    def set_order(self, order: str):
        self.order = order
        settings.set("byte_order", order)
        self.fill_inspector()

    def inspector_value(self, name: str) -> str:
        return inspect.value(name, self.buf.read(self.view.cursor, 16), self.order)

    def edit_value(self, name: str) -> bool:
        """Type a new value for one of the inspector's types: its bytes overwrite those at the cursor."""
        if not inspect.BY_NAME[name][3]:
            return False
        text = self.ask("value", (name, self.inspector_value(name))) if self.ask else None
        if text is None:
            return False
        try:
            data = inspect.encode(name, text, self.order)
        except ValueError as err:
            self.ask("say", ("warning", f"{text} isn't a {name}: {err}"))
            return False
        at = self.view.cursor
        return self.view._edit(lambda: self.buf.overwrite(at, data))

    # ----------------------------------------------------------------- bookmarks
    def add_bookmark(self, name: str | None = None) -> bool:
        a, b = self.view.selection()
        if b <= a:
            a, b = self.view.cursor, self.view.cursor + 1
        if name is None:
            name = self.ask("bookmark_name", f"Bookmark at {a:X}") if self.ask else f"Bookmark at {a:X}"
            if not name:
                return False
        self.bookmarks.append({"name": name, "start": a, "end": b})
        self.bookmarks.sort(key=lambda m: m["start"])
        self._show_marks()
        return True

    def remove_bookmark(self, i: int) -> bool:
        if not 0 <= i < len(self.bookmarks):
            return False
        del self.bookmarks[i]
        self._show_marks()
        return True

    def go_bookmark(self, i: int) -> bool:
        if not 0 <= i < len(self.bookmarks):
            return False
        m = self.bookmarks[i]
        self.view.select(m["start"], m["end"])
        self.view.center_on(m["start"])
        return True

    def _show_marks(self):
        self.mark_list.clear()
        for m in self.bookmarks:
            self.mark_list.addTopLevelItem(QTreeWidgetItem([m["name"], f"{m['start']:X}", str(m["end"] - m["start"])]))
        self.view.marks = [(m["start"], m["end"]) for m in self.bookmarks]
        self.view.viewport().update()

    # ----------------------------------------------------------------- checksums
    def calculate(self):
        """Checksums of the selection, or of the whole file (on a thread; inline when sync)."""
        if self.summing:
            self._cancel.set()
            return
        a, b = self.view.selection()
        if b <= a:
            a, b = 0, len(self.buf)
        self._cancel.clear()
        self.summing = True
        self.sum_button.setText("STOP")
        self.side.setCurrentIndex(2)

        def work():
            try:
                got = checksums.compute(self.buf, a, b, progress=None if self.sync else self.bridge.progress.emit,
                                        cancelled=self._cancel.is_set)
                self.bridge.sums.emit(got, None)
            except checksums.Cancelled:
                self.bridge.sums.emit(None, "Stopped")
            except OSError as e:
                self.bridge.sums.emit(None, e.strerror or str(e))
        if self.sync:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()

    def _sum_progress(self, done: int, total: int):
        self.sum_button.setText(f"STOP  ·  {done * 100 // max(1, total)}%")

    def _summed(self, got, error):
        self.summing = False
        self.sum_button.setText("CALCULATE")
        self.sum_list.clear()
        if error:
            self.sum_list.addTopLevelItem(QTreeWidgetItem(["", error]))
            return
        self.results = got
        for name, value in got.items():
            it = QTreeWidgetItem([name, value])
            it.setForeground(0, QColor(theme.TEXT_DIM))
            it.setToolTip(1, value)
            self.sum_list.addTopLevelItem(it)

    def stop(self):
        self._cancel.set()


class ComparePage(QWidget):
    """Analysis > File compare: both files read-only, scrolled together, the differences marked."""

    changed = Signal()
    kind = "compare"

    def __init__(self, left: str, right: str, parent=None):
        super().__init__(parent)
        self.paths = (left, right)
        self.bufs = (Buffer.open(left, read_only=True), Buffer.open(right, read_only=True))
        self.runs = hexcompare.differences(*self.bufs)
        self.cur = 0 if self.runs else -1
        self.views = []
        self.heads = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(10)
        for path, buf in zip(self.paths, self.bufs):
            col = QWidget()
            cl = QVBoxLayout(col)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(0)
            head = QFrame()
            head.setObjectName("head")
            hl = QHBoxLayout(head)
            hl.setContentsMargins(10, 5, 10, 5)
            t = QLabel(os.path.basename(path))
            t.setStyleSheet("font-weight: 600;")
            hl.addWidget(t)
            p = _dim(path)
            p.setMinimumWidth(10)
            hl.addWidget(p, 1)
            hl.addWidget(_dim(f"{len(buf):,} bytes".replace(",", " ")))
            cl.addWidget(head)
            v = HexView(buf)
            v.editable = False
            v.diffs = self.runs
            cl.addWidget(v, 1)
            lay.addWidget(col, 1)
            self.views.append(v)
            self.heads.append(head)
        self._scrolling = False
        for i, v in enumerate(self.views):
            v.verticalScrollBar().valueChanged.connect(lambda val, i=i: self._scrolled(i, val))
            v.cursor_moved.connect(lambda i=i: self._cursor(i))
        self.restyle()
        if self.runs:
            self.go(0)

    def title(self) -> str:
        a, b = (os.path.basename(p) for p in self.paths)
        return (a if a == b else f"{a}  ·  {b}") + "  ·  compare"

    def modified(self) -> bool:
        return False

    def restyle(self):
        for h in self.heads:
            h.setStyleSheet(f"QFrame#head {{ background: {theme.DOCK_TOP}; border-bottom: 1px solid {theme.PANEL_EDGE}; }}")
        for v in self.views:
            v.restyle()

    def _scrolled(self, i: int, val: int):
        if self._scrolling:
            return
        self._scrolling = True
        self.views[1 - i].verticalScrollBar().setValue(val)
        self._scrolling = False

    def _cursor(self, i: int):
        if self._scrolling:
            return
        self._scrolling = True
        other = self.views[1 - i]
        other.cursor = min(self.views[i].cursor, len(other.buf))
        other.viewport().update()
        self._scrolling = False
        self.changed.emit()

    def go(self, k: int) -> bool:
        if not 0 <= k < len(self.runs):
            return False
        self.cur = k
        s, e = self.runs[k]
        for v in self.views:
            v.current_diff = (s, e)
            v.go(min(s, len(v.buf)))
            v.center_on(s)
        self.changed.emit()
        return True

    def next(self):
        cursor = self.views[0].cursor
        k = next((i for i, (s, _) in enumerate(self.runs) if s > cursor), None)
        return self.go(k) if k is not None else False

    def prev(self):
        cursor = self.views[0].cursor
        k = next((i for i in range(len(self.runs) - 1, -1, -1) if self.runs[i][0] < cursor), None)
        return self.go(k) if k is not None else False

    def status(self) -> str:
        if not self.runs:
            return "The files are identical"
        same = len(self.bufs[0]) == len(self.bufs[1])
        n = hexcompare.differing_bytes(self.runs)
        head = f"Difference {self.cur + 1} of {len(self.runs)}   ·   offset(h): {self.runs[self.cur][0]:X}" \
            if self.cur >= 0 else f"{len(self.runs)} differences"
        return f"{head}   ·   {n} bytes differ   ·   " + ("same length" if same else "different lengths")

    def mode_text(self) -> str:
        return "Read-only"

    def stop(self):
        for b in self.bufs:
            b.close()
