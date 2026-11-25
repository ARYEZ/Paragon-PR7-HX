"""The hex view, the way HxD's works: the offset column, the bytes (16 a row, a gap after 8), the decoded text; a cursor
in the hex or the text column, Shift to select, typing hex digits or characters (Insert / Overwrite), Backspace and
Delete. Only the rows on screen are read from the buffer, so a huge file scrolls at once. Changed bytes are orange,
compare differences pink, bookmarks underlined, the selection the family's red."""

from __future__ import annotations

from bisect import bisect_right

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import QAbstractScrollArea

from . import settings, theme
from .buffer import Buffer

HEX_DIGITS = "0123456789abcdefABCDEF"
BAR_LIMIT = 1_000_000_000         # a scroll bar holds an int: past this many rows each step is several rows
CHANGED = "#F07A2A"
DIFF = "#D6457E"


def mono_font() -> QFont:
    f = QFont("Consolas")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFamilies(["Consolas", "Cascadia Mono", "DejaVu Sans Mono", "Liberation Mono", "monospace"])
    f.setPointSizeF(max(6.0, settings.get_float("font_size", 10.0)))
    return f


class HexView(QAbstractScrollArea):
    cursor_moved = Signal()          # the cursor or the selection moved
    edited = Signal()                # the bytes changed
    refused = Signal(str)            # an edit that isn't allowed (read-only, a disk can't grow)

    def __init__(self, buf: Buffer, parent=None):
        super().__init__(parent)
        self.buf = buf
        self.cols = settings.get_int("bytes_per_row", 16) or 16
        self.decimal_offsets = settings.get_bool("decimal_offsets", False)
        self.cursor = 0
        self.nibble = 0                  # 1: the high half of the byte at the cursor was typed
        self.area = "hex"                # hex / text
        self.anchor: int | None = None   # where a selection started
        self.insert_mode = False
        self.diffs: list[tuple[int, int]] = []
        self.current_diff: tuple[int, int] | None = None
        self.marks: list[tuple[int, int]] = []     # bookmarks (start, end)
        self.editable = True
        self._press: int | None = None   # where a mouse drag started
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalScrollBar().valueChanged.connect(lambda _: self.viewport().update())
        self.restyle()

    def restyle(self):
        self.font_ = mono_font()
        fm = QFontMetricsF(self.font_)
        self.cw, self.lh = fm.horizontalAdvance("0"), fm.height() + 5
        self.setStyleSheet(f"QAbstractScrollArea {{ background: {theme.WIDGET}; border: none; }}")
        self._layout()
        self.viewport().update()

    # ----------------------------------------------------------------- geometry
    def _layout(self):
        digits = max(8, len(f"{max(1, len(self.buf)):X}"))
        if self.decimal_offsets:
            digits = max(8, len(str(max(1, len(self.buf)))))
        self.digits = digits
        self.off_w = self.cw * (digits + 3)
        self.hex_x = self.off_w + self.cw
        self.txt_x = self.hex_x + self.cw * (self.cols * 3 + self.cols // 8)
        self.total_w = self.txt_x + self.cw * (self.cols + 2)
        self._bars()

    def rows(self) -> int:
        return len(self.buf) // self.cols + 1                # one more: the place after the last byte

    def visible_rows(self) -> int:
        return max(1, int((self.viewport().height() - self.lh) / self.lh))

    def _scale(self) -> int:
        return max(1, -(-self.rows() // BAR_LIMIT))

    def _bars(self):
        s = self._scale()
        vb = self.verticalScrollBar()
        vb.setRange(0, max(0, (self.rows() - self.visible_rows()) // s + (1 if s > 1 else 0)))
        vb.setPageStep(max(1, self.visible_rows() // s))
        hb = self.horizontalScrollBar()
        hb.setRange(0, max(0, int(self.total_w - self.viewport().width())))
        hb.setPageStep(self.viewport().width())

    def top_row(self) -> int:
        return min(self.verticalScrollBar().value() * self._scale(), max(0, self.rows() - 1))

    def set_top_row(self, row: int):
        self.verticalScrollBar().setValue(max(0, row) // self._scale())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._bars()

    def byte_x(self, col: int) -> float:
        return self.hex_x + self.cw * (col * 3 + col // 8)

    def offset_at(self, x: float, y: float) -> tuple[int, str] | None:
        x += self.horizontalScrollBar().value()
        row = self.top_row() + int((y - self.lh) // self.lh)
        if y < self.lh:
            return None
        if x >= self.txt_x - self.cw * .5:
            col, area = int((x - self.txt_x) // self.cw), "text"
        else:
            col, area = 0, "hex"
            for c in range(self.cols):
                if x >= self.byte_x(c) - self.cw * .5:
                    col = c
        col = max(0, min(self.cols - 1, col))
        return min(len(self.buf), row * self.cols + col), area

    # ----------------------------------------------------------------- selection
    def selection(self) -> tuple[int, int]:
        """[start, end) of the selected block (HxD's: the bytes between the anchor and the cursor, the cursor's byte
        not included); (cursor, cursor) when nothing is selected."""
        if self.anchor is None:
            return self.cursor, self.cursor
        a, b = sorted((self.anchor, self.cursor))
        return a, min(b, len(self.buf))

    def has_selection(self) -> bool:
        a, b = self.selection()
        return b > a

    def select(self, start: int, end: int):
        """Select [start, end) and show it."""
        end = max(start, min(end, len(self.buf)))
        self.anchor = start if end > start else None
        self.cursor = end
        self.nibble = 0
        self.ensure_visible(start)
        self.viewport().update()
        self.cursor_moved.emit()

    def go(self, offset: int, keep_selection: bool = False):
        offset = max(0, min(offset, len(self.buf)))
        if not keep_selection:
            self.anchor = None
        self.cursor, self.nibble = offset, 0
        self.ensure_visible(offset)
        self.viewport().update()
        self.cursor_moved.emit()

    def ensure_visible(self, offset: int):
        row = offset // self.cols
        top, n = self.top_row(), self.visible_rows()
        if row < top:
            self.set_top_row(row)
        elif row >= top + n:
            self.set_top_row(row - n + 1)

    def center_on(self, offset: int):
        self.set_top_row(offset // self.cols - self.visible_rows() // 3)

    def set_cols(self, n: int):
        top = self.top_row() * self.cols
        self.cols = n
        self._layout()
        self.set_top_row(top // n)
        self.viewport().update()

    def refresh(self):
        """After the bytes changed outside the view (undo, replace, a reload)."""
        self.cursor = min(self.cursor, len(self.buf))
        if self.anchor is not None:
            self.anchor = min(self.anchor, len(self.buf))
        self._layout()
        self.viewport().update()

    # ----------------------------------------------------------------- painting
    def paintEvent(self, _):
        p = QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), QColor(theme.WIDGET))
        p.setFont(self.font_)
        p.translate(-self.horizontalScrollBar().value(), 0)
        cw, lh, cols = self.cw, self.lh, self.cols
        w = self.total_w + self.viewport().width()
        h = self.viewport().height()
        p.fillRect(QRectF(0, 0, w, lh), QColor(theme.DOCK_TOP))
        p.fillRect(QRectF(0, 0, self.off_w, h), QColor(theme.DOCK_TOP))
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(QRectF(cw, 0, self.off_w, lh), Qt.AlignmentFlag.AlignVCenter,
                   "Offset (d)" if self.decimal_offsets else "Offset (h)")
        for c in range(cols):
            p.drawText(QRectF(self.byte_x(c), 0, cw * 2, lh), Qt.AlignmentFlag.AlignVCenter, f"{c:02X}")
        p.drawText(QRectF(self.txt_x, 0, cw * 14, lh), Qt.AlignmentFlag.AlignVCenter, "Decoded text")
        p.setPen(QPen(QColor(theme.PANEL_EDGE), 1))
        p.drawLine(int(self.txt_x - cw * .6), 0, int(self.txt_x - cw * .6), h)
        top = self.top_row()
        n = self.visible_rows() + 1
        start = top * cols
        data = self.buf.read(start, n * cols)
        changed = self.buf.changed_ranges(start, n * cols)
        sel_a, sel_b = self.selection()
        sel = QColor(theme.ACCENT)
        sel.setAlphaF(.32)
        diff = QColor(DIFF)
        diff.setAlphaF(.28)
        cur_diff = QColor(DIFF)
        cur_diff.setAlphaF(.55)
        ends = [b for _, b in self.diffs]

        def in_ranges(ranges, i, ends_=None):
            k = bisect_right(ends_ if ends_ is not None else [b for _, b in ranges], i)
            return k < len(ranges) and ranges[k][0] <= i

        changed_ends = [b for _, b in changed]
        mark_ends = [b for _, b in self.marks]
        for r in range(n):
            y = lh * (r + 1)
            row_start = start + r * cols
            if row_start > len(self.buf):
                break
            p.setPen(QColor(theme.TEXT_DIM))
            label = f"{row_start:0{self.digits}d}" if self.decimal_offsets else f"{row_start:0{self.digits}X}"
            p.drawText(QRectF(cw, y, self.off_w, lh), Qt.AlignmentFlag.AlignVCenter, label)
            for c in range(cols):
                i = row_start + c
                x, tx = self.byte_x(c), self.txt_x + cw * c
                box = QRectF(x - cw * .25, y + 1, cw * 2.5, lh - 2)
                tbox = QRectF(tx, y + 1, cw, lh - 2)
                if i < len(self.buf):
                    b = data[i - start]
                    if sel_a <= i < sel_b:
                        p.fillRect(box, sel)
                        p.fillRect(tbox, sel)
                    if self.diffs and in_ranges(self.diffs, i, ends):
                        f = cur_diff if self.current_diff and self.current_diff[0] <= i < self.current_diff[1] \
                            else diff
                        p.fillRect(box, f)
                        p.fillRect(tbox, f)
                    if self.marks and in_ranges(self.marks, i, mark_ends):
                        p.setPen(QPen(QColor(DIFF), 1.5))
                        p.drawLine(int(box.left()), int(box.bottom()), int(box.right()), int(box.bottom()))
                    is_changed = bool(changed) and in_ranges(changed, i, changed_ends)
                    colour = CHANGED if is_changed else (theme.TEXT if b else theme.TEXT_DIM)
                    p.setPen(QColor(colour))
                    p.drawText(QRectF(x, y, cw * 2, lh), Qt.AlignmentFlag.AlignVCenter, f"{b:02X}")
                    printable = 32 <= b < 127
                    p.setPen(QColor(colour if printable else theme.TEXT_DIM))
                    p.drawText(QRectF(tx, y, cw, lh), Qt.AlignmentFlag.AlignVCenter, chr(b) if printable else ".")
                if i == self.cursor:
                    focus = self.hasFocus()
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    main, other = (box, tbox) if self.area == "hex" else (tbox, box)
                    p.setPen(QPen(QColor(theme.ACCENT), 1.6 if focus else 1))
                    if self.insert_mode and focus:
                        p.drawLine(int(main.left()), int(main.top()), int(main.left()), int(main.bottom()))
                    else:
                        if self.nibble and self.area == "hex":
                            main = QRectF(main.left() + cw, main.top(), main.width() - cw, main.height())
                        p.drawRect(main)
                    p.setPen(QPen(QColor(theme.TEXT_DIM), 1))
                    p.drawRect(other)

    # ----------------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        got = self.offset_at(e.position().x(), e.position().y())
        if got is None:
            return
        offset, area = got
        self.area = area
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self.anchor is None:
                self.anchor = self.cursor
            self._press = self.anchor
        else:
            self.anchor = None
            self._press = offset
        self.cursor, self.nibble = offset, 0
        self.viewport().update()
        self.cursor_moved.emit()

    def mouseMoveEvent(self, e):
        if not e.buttons() & Qt.MouseButton.LeftButton:
            return
        got = self.offset_at(e.position().x(), max(self.lh, e.position().y()))
        if got is None:
            return
        at = got[0]
        press = self._press if self._press is not None else at
        if at >= press:                       # the byte under the pointer is included, whichever way it goes
            self.anchor, self.cursor = press, min(len(self.buf), at + 1)
        else:
            self.anchor, self.cursor = min(len(self.buf), press + 1), at
        self.ensure_visible(self.cursor)
        self.viewport().update()
        self.cursor_moved.emit()

    def mouseReleaseEvent(self, e):
        if self.anchor == self.cursor:
            self.anchor = None
        self._press = None

    # ----------------------------------------------------------------- keys
    def event(self, e):
        # Undo / Redo / Copy / Paste are the window's (they act on the buffer, not on text)
        if e.type() == e.Type.ShortcutOverride:
            for k in (QKeySequence.StandardKey.Undo, QKeySequence.StandardKey.Redo, QKeySequence.StandardKey.Copy,
                      QKeySequence.StandardKey.Paste, QKeySequence.StandardKey.Cut,
                      QKeySequence.StandardKey.SelectAll):
                if e.matches(k):
                    e.ignore()
                    return False
        return super().event(e)

    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        moves = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: -self.cols, Qt.Key.Key_Down: self.cols,
                 Qt.Key.Key_PageUp: -self.cols * self.visible_rows(),
                 Qt.Key.Key_PageDown: self.cols * self.visible_rows()}
        if k in moves or k in (Qt.Key.Key_Home, Qt.Key.Key_End):
            if k == Qt.Key.Key_Home:
                to = 0 if ctrl else self.cursor - self.cursor % self.cols
            elif k == Qt.Key.Key_End:
                to = len(self.buf) if ctrl else min(len(self.buf), self.cursor - self.cursor % self.cols +
                                                    self.cols - 1)
            else:
                to = self.cursor + moves[k]
            if shift and self.anchor is None:
                self.anchor = self.cursor
            elif not shift:
                self.anchor = None
            self.go(to, keep_selection=shift)
            return
        if k == Qt.Key.Key_Tab:
            self.area = "text" if self.area == "hex" else "hex"
            self.nibble = 0
            self.viewport().update()
            return
        if k == Qt.Key.Key_Insert and not mods:
            self.toggle_insert()
            return
        if k == Qt.Key.Key_Backspace:
            self.backspace()
            return
        if k == Qt.Key.Key_Delete:
            self.delete()
            return
        text = e.text()
        if text and not ctrl and text.isprintable():
            self.type_text(text)
            return
        super().keyPressEvent(e)

    def toggle_insert(self):
        if not self.buf.resizable:
            self.refused.emit("A disk can't grow or shrink: Overwrite only.")
            return
        self.insert_mode = not self.insert_mode
        self.viewport().update()
        self.cursor_moved.emit()

    def _edit(self, fn) -> bool:
        if not self.editable:
            self.refused.emit("This view can't be edited.")
            return False
        try:
            fn()
        except PermissionError:
            self.refused.emit("It's read-only (Edit > Read-only).")
            return False
        except ValueError as err:
            msg = str(err)
            self.refused.emit("A disk can't grow or shrink: Overwrite only." if "disk" in msg else msg)
            return False
        self._layout()
        self.edited.emit()
        return True

    def type_text(self, text: str):
        """Typing: hex digits in the hex column, characters (ANSI) in the text column."""
        for ch in text:
            if self.area == "hex":
                if ch not in HEX_DIGITS:
                    continue
                d = int(ch, 16)
                at = self.cursor
                if self.nibble == 0:
                    if self.insert_mode or at >= len(self.buf):
                        ok = self._edit(lambda: self.buf.insert(at, bytes([d << 4])) if self.buf.resizable
                                        else self.buf.overwrite(at, bytes([d << 4])))
                    else:
                        old = self.buf.read(at, 1)[0]
                        ok = self._edit(lambda: self.buf.overwrite(at, bytes([(d << 4) | (old & 15)])))
                    if ok:
                        self.nibble = 1
                else:
                    old = self.buf.read(at, 1)[0]
                    if self._edit(lambda: self.buf.overwrite(at, bytes([(old & 0xF0) | d]), join_undo=True)):
                        self.nibble = 0
                        self.cursor = min(len(self.buf), at + 1)
            else:
                try:
                    b = ch.encode("cp1252")
                except UnicodeEncodeError:
                    continue
                at = self.cursor
                if self.insert_mode:
                    ok = self._edit(lambda: self.buf.insert(at, b))
                else:
                    ok = self._edit(lambda: self.buf.overwrite(at, b))
                if ok:
                    self.cursor = min(len(self.buf), at + len(b))
        self.anchor = None
        self.ensure_visible(self.cursor)
        self.viewport().update()
        self.cursor_moved.emit()

    def backspace(self):
        if self.has_selection():
            self.delete()
            return
        if self.cursor == 0:
            return
        if self.insert_mode:
            at = self.cursor - 1
            if self._edit(lambda: self.buf.delete(at, 1)):
                self.cursor = at
        else:
            self.cursor -= 1
        self.nibble = 0
        self.viewport().update()
        self.cursor_moved.emit()

    def delete(self):
        """Delete the selection (or the byte at the cursor): the file gets shorter (HxD's Delete)."""
        a, b = self.selection() if self.has_selection() else (self.cursor, self.cursor + 1)
        if a >= len(self.buf):
            return
        if self._edit(lambda: self.buf.delete(a, b - a)):
            self.anchor = None
            self.cursor, self.nibble = min(a, len(self.buf)), 0
            self.viewport().update()
            self.cursor_moved.emit()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.viewport().update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.viewport().update()
