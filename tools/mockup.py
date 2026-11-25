"""Mock-up pictures of PR7-HX, drawn offscreen in the family theme (the bytes are real, the files made up):
QT_SCALE_FACTOR=2 python tools/mockup.py OUT_DIR

1_editor.png    A PNG open: offsets, 16 bytes a row, the text column; the IHDR width selected, two bytes changed
                (orange, unsaved), the Data inspector reading the bytes at the cursor (OBSIDIAN)
2_compare.png   File compare: two versions side by side, the differing bytes marked, Next / Previous difference (AURORA)
3_disk.png      Drive C: opened read-only: the NTFS boot sector, a bookmark on its signature, Checksums of the
                selection (OBSIDIAN)
"""
import datetime
import hashlib
import os
import struct
import sys
import zlib
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QIODevice, QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel, QTabBar,  # noqa: E402
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from pr7hx import theme, widgets  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/mockup")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
app.setFont(QFont("Inter", 10))

CHANGED = "#F07A2A"        # orange: a changed, unsaved byte
DIFF = "#D6457E"           # pink: a byte that differs from the other file
BOOKMARK = "#D6457E"


def style():
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())


def dim(text):
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    return lab


def field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def mono(px=13):
    f = QFont("DejaVu Sans Mono")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(px)
    return f


# ------------------------------------------------------------------ the bytes
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


# ------------------------------------------------------------------ the hex view
class HexView(QWidget):
    """HxD's view: offsets, 16 bytes per row (a gap after 8), the text column."""

    def __init__(self, data: bytes, base: int = 0, rows: int = 30, sel=None, cursor=None, changed=(), diff=(),
                 marks=(), current=None, compact=False):
        super().__init__()
        self.data, self.base, self.rows = data, base, rows
        self.sel, self.cursor, self.changed, self.diff = sel, cursor, set(changed), set(diff)
        self.marks, self.current, self.compact = list(marks), current, compact
        self.font = mono(12 if compact else 13)
        fm = QFontMetricsF(self.font)
        self.cw, self.lh = fm.horizontalAdvance("0"), fm.height() + (4 if compact else 6)
        self.setMinimumSize(QSize(int(self.cw * (80 if not compact else 76)), int(self.lh * (rows + 1.6))))

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.WIDGET))
        p.setFont(self.font)
        cw, lh = self.cw, self.lh
        off_w = cw * 11.5
        hex_x = off_w + cw
        txt_x = hex_x + cw * (16 * 3 + 2)
        p.fillRect(QRectF(0, 0, self.width(), lh), QColor(theme.DOCK_TOP))
        p.fillRect(QRectF(0, 0, off_w, self.height()), QColor(theme.DOCK_TOP))
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(QRectF(6, 0, off_w, lh), Qt.AlignmentFlag.AlignVCenter, "Offset (h)")
        for c in range(16):
            x = hex_x + cw * (c * 3 + (1 if c >= 8 else 0))
            p.drawText(QRectF(x, 0, cw * 2, lh), Qt.AlignmentFlag.AlignVCenter, f"{c:02X}")
        p.drawText(QRectF(txt_x, 0, cw * 16, lh), Qt.AlignmentFlag.AlignVCenter, "Decoded text")
        p.setPen(QPen(QColor(theme.PANEL_EDGE), 1))
        p.drawLine(int(txt_x - cw * .5), 0, int(txt_x - cw * .5), self.height())
        sel_fill = QColor(theme.ACCENT)
        sel_fill.setAlphaF(.32)
        diff_fill = QColor(DIFF)
        diff_fill.setAlphaF(.28 if theme.FINISH == "obsidian" else .3)
        cur_diff = QColor(DIFF)
        cur_diff.setAlphaF(.5)
        for r in range(self.rows):
            y = lh * (r + 1) + 2
            start = r * 16
            if start >= len(self.data):
                break
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(QRectF(6, y, off_w, lh), Qt.AlignmentFlag.AlignVCenter, f"{self.base + start:08X}")
            for c in range(16):
                i = start + c
                if i >= len(self.data):
                    break
                b = self.data[i]
                x = hex_x + cw * (c * 3 + (1 if c >= 8 else 0))
                tx = txt_x + cw * c
                box = QRectF(x - cw * .2, y + 1, cw * 2.4, lh - 2)
                tbox = QRectF(tx, y + 1, cw, lh - 2)
                if self.sel and self.sel[0] <= i < self.sel[1]:
                    p.fillRect(box, sel_fill)
                    p.fillRect(tbox, sel_fill)
                if i in self.diff:
                    f = cur_diff if self.current and self.current[0] <= i < self.current[1] else diff_fill
                    p.fillRect(box, f)
                    p.fillRect(tbox, f)
                for (a, z, colour) in self.marks:
                    if a <= i < z:
                        p.setPen(QPen(QColor(colour), 1.4))
                        p.drawLine(int(box.left()), int(box.bottom()), int(box.right()), int(box.bottom()))
                colour = CHANGED if i in self.changed else (theme.TEXT if b else theme.TEXT_DIM)
                p.setPen(QColor(colour))
                p.drawText(QRectF(x, y, cw * 2, lh), Qt.AlignmentFlag.AlignVCenter, f"{b:02X}")
                ch = chr(b) if 32 <= b < 127 else "."
                p.setPen(QColor(colour if 32 <= b < 127 else theme.TEXT_DIM))
                p.drawText(QRectF(tx, y, cw, lh), Qt.AlignmentFlag.AlignVCenter, ch)
                if self.cursor == i:
                    p.setPen(QPen(QColor(theme.ACCENT), 1.6))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(box)
                    p.setPen(QPen(QColor(theme.TEXT_DIM), 1))
                    p.drawRect(tbox)


def inspector(data: bytes, at: int):
    t = QTreeWidget()
    t.setHeaderLabels(["DATA INSPECTOR", "VALUE"])
    t.setRootIsDecorated(False)
    t.setIndentation(0)
    t.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    b = data[at:at + 8].ljust(8, b"\0")
    rows = [("Binary (8 bit)", f"{b[0]:08b}"), ("Int8", str(struct.unpack('<b', b[:1])[0])),
            ("UInt8", str(b[0])), ("Int16", str(struct.unpack('<h', b[:2])[0])),
            ("UInt16", str(struct.unpack('<H', b[:2])[0])), ("Int32", str(struct.unpack('<i', b[:4])[0])),
            ("UInt32", str(struct.unpack('<I', b[:4])[0])), ("Int64", str(struct.unpack('<q', b)[0])),
            ("Float (32 bit)", f"{struct.unpack('<f', b[:4])[0]:.6g}"),
            ("Double (64 bit)", f"{struct.unpack('<d', b)[0]:.6g}"),
            ("UInt32 (big endian)", str(struct.unpack('>I', b[:4])[0])),
            ("DOS date", "invalid"),
            ("Unix time (32 bit)", datetime.datetime.fromtimestamp(struct.unpack('<I', b[:4])[0],
                                                                   datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
            ("Characters (UTF-8)", "".join(chr(x) if 32 <= x < 127 else "." for x in b[:4]))]
    for name, value in rows:
        it = QTreeWidgetItem([name, value])
        it.setForeground(0, QColor(theme.TEXT_DIM))
        t.addTopLevelItem(it)
    t.setFixedWidth(330)
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(t, 1)
    order = QLabel("BYTE ORDER   LITTLE ENDIAN   ·   big endian")
    order.setProperty("role", "field")
    lay.addWidget(order)
    return box


def toolbar():
    bar = QWidget()
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(16, 10, 16, 6)
    lay.setSpacing(6)
    groups = [[("open", "Open"), ("save", "Save"), ("drive", "Open Disk")],
              [("undo", "Undo"), ("search", "Find"), ("goto", "Go To")],
              [("compare", "Compare"), ("hash", "Checksums"), ("gear", "Options")]]
    for i, group in enumerate(groups):
        if i:
            sep = QLabel()
            sep.setFixedSize(1, 40)
            sep.setStyleSheet(f"background: {theme.PANEL_EDGE};")
            lay.addSpacing(8)
            lay.addWidget(sep)
            lay.addSpacing(8)
        for icon, label in group:
            k = widgets.KeyButton(icon, label)
            k.setFixedSize(QSize(100, 62))
            lay.addWidget(k)
    lay.addStretch(1)
    return bar


def tabs(names, current):
    t = QTabBar()
    t.setExpanding(False)
    t.setDrawBase(False)
    t.setTabsClosable(True)
    for n in names:
        t.addTab(n)
    t.setCurrentIndex(current)
    h = QWidget()
    hl = QHBoxLayout(h)
    hl.setContentsMargins(16, 0, 16, 0)
    hl.addWidget(t)
    hl.addStretch(1)
    return h


def status(left, right):
    f = QFrame()
    f.setStyleSheet(f"QFrame {{ background: {theme.TAB_FRAME}; border-top: 1px solid {theme.PANEL_EDGE}; }}")
    lay = QHBoxLayout(f)
    lay.setContentsMargins(16, 6, 16, 6)
    lay.addWidget(dim(left))
    lay.addStretch(1)
    lay.addWidget(dim(right))
    return f


def window(body, status_bar, tab_names, current_tab=0):
    w = QWidget()
    w.setObjectName("win")
    w.setStyleSheet(f"QWidget#win {{ background: {theme.BACKGROUND}; }}")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(widgets.Header("HEX EDITOR"))
    lay.addWidget(toolbar())
    lay.addWidget(tabs(tab_names, current_tab))
    lay.addWidget(body, 1)
    lay.addWidget(status_bar)
    w.resize(1320, 820)
    return w


def shoot(widget, name):
    widget.show()
    app.processEvents()
    widget.grab().save(str(out / name))
    widget.close()


# ------------------------------------------------------------------ 1: the editor
png = bytearray(png_bytes())
original_w = bytes(png[16:20])
png[16:20] = struct.pack(">I", 1280)         # the width changed from 640 to 1280: unsaved
changed = [i for i in range(16, 20) if png[i] != original_w[i - 16]]
theme.set_finish("obsidian")
style()
body = QWidget()
bl = QHBoxLayout(body)
bl.setContentsMargins(16, 6, 16, 0)
bl.setSpacing(10)
bl.addWidget(HexView(bytes(png), rows=30, sel=(16, 24), cursor=16, changed=changed), 1)
bl.addWidget(inspector(bytes(png), 16))
shoot(window(body, status("Offset(h): 10   ·   Block(h): 10-17   ·   Length(h): 8", "Overwrite   ·   2 bytes changed, unsaved"),
             ["poster_draft.png *", "settings.dat  ·  compare", "Drive C:"]), "1_editor.png")

# ------------------------------------------------------------------ 2: compare
a, b = settings_dat(1), settings_dat(2)
diffs = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
theme.set_finish("aurora")
style()
body = QWidget()
bl = QHBoxLayout(body)
bl.setContentsMargins(16, 6, 16, 0)
bl.setSpacing(10)
for data, name, path in ((a, "settings.dat", r"D:\Studio\ELSEWORLD\settings.dat"),
                         (b, "settings.dat", r"\\NAS\Backup\ELSEWORLD\settings.dat")):
    col = QWidget()
    cl = QVBoxLayout(col)
    cl.setContentsMargins(0, 0, 0, 0)
    cl.setSpacing(0)
    head = QFrame()
    head.setStyleSheet(f"QFrame {{ background: {theme.DOCK_TOP}; border-bottom: 1px solid {theme.PANEL_EDGE}; }}")
    hl = QHBoxLayout(head)
    hl.setContentsMargins(10, 5, 10, 5)
    t = QLabel(name)
    t.setStyleSheet("font-weight: 600;")
    hl.addWidget(t)
    hl.addWidget(dim(path), 1)
    hl.addWidget(dim(f"{len(data)} bytes"))
    cl.addWidget(head)
    cl.addWidget(HexView(data, rows=8, diff=diffs, current=(diffs[0], diffs[0] + 4), compact=True), 1)
    bl.addWidget(col, 1)
shoot(window(body, status(f"Difference 1 of {len(set(d // 4 for d in diffs))}   ·   offset(h): {diffs[0]:X}",
                          f"{len(diffs)} bytes differ   ·   same length"),
             ["poster_draft.png *", "settings.dat  ·  compare", "Drive C:"], 1), "2_compare.png")

# ------------------------------------------------------------------ 3: a disk, read-only
boot = boot_sector()
theme.set_finish("obsidian")
style()
body = QWidget()
bl = QHBoxLayout(body)
bl.setContentsMargins(16, 6, 16, 0)
bl.setSpacing(10)
bl.addWidget(HexView(boot, rows=32, sel=(0, 11), cursor=3, marks=[(510, 512, BOOKMARK)]), 1)
side = QWidget()
sl = QVBoxLayout(side)
sl.setContentsMargins(0, 0, 0, 0)
sel = boot[0:11]
sums = QTreeWidget()
sums.setHeaderLabels(["CHECKSUM", "OF THE SELECTION (11 BYTES)"])
sums.setRootIsDecorated(False)
sums.setIndentation(0)
for name, value in (("CRC-32", f"{zlib.crc32(sel):08X}"), ("MD5", hashlib.md5(sel).hexdigest().upper()),
                    ("SHA-1", hashlib.sha1(sel).hexdigest().upper()[:32] + "…"),
                    ("SHA-256", hashlib.sha256(sel).hexdigest().upper()[:32] + "…")):
    it = QTreeWidgetItem([name, value])
    it.setForeground(0, QColor(theme.TEXT_DIM))
    sums.addTopLevelItem(it)
sums.setFixedHeight(150)
sl.addWidget(sums)
marks = QTreeWidget()
marks.setHeaderLabels(["BOOKMARK", "OFFSET"])
marks.setRootIsDecorated(False)
marks.setIndentation(0)
for name, value in (("OEM ID \u201cNTFS\u201d", "3"), ("Bytes per sector", "B"), ("MFT cluster", "30"),
                    ("Boot signature 55 AA", "1FE")):
    marks.addTopLevelItem(QTreeWidgetItem([name, value]))
marks.setColumnWidth(0, 230)
sl.addWidget(marks, 1)
note = QLabel("READ-ONLY   ·   writing to a disk is off until you turn it on (Edit > Read-only)")
note.setWordWrap(True)
note.setProperty("role", "field")
sl.addWidget(note)
side.setFixedWidth(330)
bl.addWidget(side)
shoot(window(body, status("Drive C:   ·   sector 0 of 999 161 856   ·   Offset(h): 3   ·   Block(h): 0-A",
                          "Read-only   ·   512 bytes per sector"),
             ["poster_draft.png *", "settings.dat  ·  compare", "Drive C:"], 2), "3_disk.png")
print("ok", out)
