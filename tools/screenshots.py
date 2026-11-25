"""Screenshots of the real PR7-HX window (made-up files): QT_SCALE_FACTOR=2 python tools/screenshots.py OUT_DIR

editor.png    a PNG with its width changed (unsaved), the Data inspector (OBSIDIAN)
compare.png   two versions of a binary file compared (AURORA)
disk.png      a disk image opened read-only, bookmarks and checksums (OBSIDIAN)
"""
import os
import struct
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ["PARAGON_FAMILY_FILE"] = os.path.join(tempfile.mkdtemp(), "finish")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])

from pr7hx import disks, theme  # noqa: E402

theme.load_fonts()
app.setFont(QFont("Inter", 10))
import mockup_data  # noqa: E402
from pr7hx.main_window import MainWindow  # noqa: E402

d = Path(tempfile.mkdtemp()) / "Studio"
d.mkdir()
png = d / "poster_draft.png"
png.write_bytes(mockup_data.png_bytes())
a, b = d / "settings.dat", d / "Backup"
b.mkdir()
a.write_bytes(mockup_data.settings_dat(1))
(b / "settings.dat").write_bytes(mockup_data.settings_dat(2))
img = d / "usb_stick.img"
img.write_bytes(mockup_data.boot_sector() + bytes(512 * 63))


def shoot(w, name):
    w.show()
    for _ in range(5):
        app.processEvents()
    w.grab().save(str(out / name))


theme.set_finish("obsidian")
w = MainWindow(sync=True)
w.answers.update({"say": lambda k, t: None, "confirm": True, "save_changes": "discard"})
w.resize(1320, 820)
w.restyle()
page = w.open_files([str(png)])
page.buf.overwrite(16, struct.pack(">I", 1280))
page.view.refresh()
page.view.select(16, 24)
page.view.cursor = 16
page.view.anchor = 24
page._moved()
w.answers["compare"] = (str(a), str(b / "settings.dat"))
w.compare_dialog()
disk = w.open_buffer(disks.open_image(str(img)))
disk.view.select(0, 11)
for name, s, e in (("OEM ID “NTFS”", 3, 11), ("Bytes per sector", 11, 13), ("Boot signature 55 AA", 510, 512)):
    disk.view.select(s, e)
    disk.add_bookmark(name)
disk.view.select(3, 11)
disk.calculate()
w.tabs.setCurrentIndex(0)
w._sync()
shoot(w, "editor.png")
w.set_finish("aurora")
w.tabs.setCurrentIndex(1)
shoot(w, "compare.png")
w.set_finish("obsidian")
w.tabs.setCurrentIndex(2)
w._sync()
shoot(w, "disk.png")
for p in w.pages():
    p.buf.undo_stack.clear() if hasattr(p, "buf") else None
w.answers["save_changes"] = "discard"
w.close()
print("ok", out)
