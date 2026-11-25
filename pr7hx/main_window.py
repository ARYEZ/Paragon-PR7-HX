"""PR7-HX's window: HxD's menus and keys around tabs of files and disks (pages.EditorPage) and file compares
(pages.ComparePage). Every question goes through `_ask(kind)` (tests answer through `answers`); `sync = True` runs
checksums inline (tests)."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QEvent, QMimeData, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
                               QMessageBox, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from . import __version__, disks, export, finish, search, settings, theme, widgets
from .buffer import Buffer
from .dialogs import (BlockDialog, CompareDialog, FindDialog, GoToDialog, OpenDiskDialog, OptionsDialog,
                      parse_offset)
from .pages import ComparePage, EditorPage

MIME = "application/x-pr7hx-bytes"
COPY_LIMIT = 64 * 1024 * 1024        # a bigger block isn't put on the clipboard (Windows would choke on it)


def _dim(text=""):
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    return lab


class MainWindow(QMainWindow):
    def __init__(self, sync: bool = False):
        super().__init__()
        self.sync = sync
        self.answers: dict = {}
        self.said: list = []
        self.last_find: dict = {}
        self.setWindowTitle("Paragon PR7-HX")
        self.setAcceptDrops(True)
        self.resize(1320, 860)
        self._build()
        self.restyle()
        self._sync()

    # ================================================================ building
    def _build(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = widgets.Header("HEX EDITOR")
        lay.addWidget(self.header)
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 6)
        bl.setSpacing(6)
        self.keys: dict[str, widgets.KeyButton] = {}
        groups = [[("open", "open", "Open", self.open_dialog), ("save", "save", "Save", self.save),
                   ("disk", "drive", "Open Disk", self.open_disk_dialog)],
                  [("undo", "undo", "Undo", self.undo), ("find", "search", "Find", self.find),
                   ("goto", "goto", "Go To", self.go_to)],
                  [("compare", "compare", "Compare", self.compare_dialog),
                   ("checksums", "hash", "Checksums", self.checksums), ("options", "gear", "Options", self.options)]]
        for i, group in enumerate(groups):
            if i:
                sep = QLabel()
                sep.setObjectName("sep")
                sep.setFixedSize(1, 40)
                bl.addSpacing(8)
                bl.addWidget(sep)
                bl.addSpacing(8)
            for key, icon, label, slot in group:
                k = widgets.KeyButton(icon, label)
                k.setFixedSize(QSize(100, 62))
                k.clicked.connect(lambda _=False, s=slot: s())
                bl.addWidget(k)
                self.keys[key] = k
        bl.addStretch(1)
        lay.addWidget(bar)
        self.stack = QStackedWidget()
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabCloseRequested.connect(lambda i: self.close_tab(i))
        self.tabs.currentChanged.connect(lambda _: self._sync())
        self.welcome = QLabel("OPEN A FILE OR A DISK\n\nCtrl+O, or drop a file on this window")
        self.welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.welcome.setProperty("role", "dim")
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(self.tabs)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(16, 0, 16, 0)
        wl.addWidget(self.stack)
        lay.addWidget(wrap, 1)
        foot = QFrame()
        foot.setObjectName("foot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 6, 16, 6)
        self.status = _dim("")
        fl.addWidget(self.status, 1)
        self.mode = _dim("")
        fl.addWidget(self.mode)
        lay.addWidget(foot)
        self._menus()

    def _act(self, menu, text, slot, keys=None, key=None, checkable=False):
        a = QAction(text, self)
        if keys:
            a.setShortcuts([QKeySequence(k) for k in (keys if isinstance(keys, (list, tuple)) else [keys])])
        a.setCheckable(checkable)
        a.triggered.connect(lambda *_: slot())
        menu.addAction(a)
        if key:
            self.acts[key] = a
        return a

    def _menus(self):
        self.acts: dict[str, QAction] = {}
        mb = self.menuBar()
        m = mb.addMenu("&File")
        self._act(m, "New", self.new_file, "Ctrl+N", "new")
        self._act(m, "Open…", self.open_dialog, "Ctrl+O", "open")
        self._act(m, "Open Disk…", self.open_disk_dialog, None, "open_disk")
        self._act(m, "Open Disk Image…", self.open_image_dialog, None, "open_image")
        m.addSeparator()
        self._act(m, "Save", self.save, "Ctrl+S", "save")
        self._act(m, "Save As…", lambda: self.save(as_new=True), None, "save_as")
        m.addSeparator()
        self._act(m, "Close", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W", "close")
        self._act(m, "Exit", self.close, "Alt+F4")
        m = mb.addMenu("&Edit")
        self._act(m, "Undo", self.undo, "Ctrl+Z", "undo")
        self._act(m, "Redo", self.redo, ["Ctrl+Y", "Ctrl+Shift+Z"], "redo")
        m.addSeparator()
        self._act(m, "Cut", self.cut, "Ctrl+X", "cut")
        self._act(m, "Copy", self.copy, "Ctrl+C", "copy")
        cm = m.addMenu("Copy As")
        for fmt, text in export.FORMATS.items():
            self._act(cm, text, lambda f=fmt: self.copy_as(f), "Ctrl+Shift+C" if fmt == "hex" else None,
                      "copy_as_" + fmt)
        self._act(m, "Paste Insert", lambda: self.paste(write=False), "Ctrl+V", "paste")
        self._act(m, "Paste Write", lambda: self.paste(write=True), "Ctrl+B", "paste_write")
        m.addSeparator()
        self._act(m, "Select All", self.select_all, "Ctrl+A", "select_all")
        self._act(m, "Select Block…", self.select_block, "Ctrl+E", "select_block")
        self._act(m, "Fill Selection…", self.fill_selection, None, "fill")
        m.addSeparator()
        self._act(m, "Insert Mode", self.toggle_insert, None, "insert_mode", True)
        self._act(m, "Read-only", self.toggle_read_only, None, "read_only", True)
        m = mb.addMenu("&Search")
        self._act(m, "Find…", self.find, "Ctrl+F", "find")
        self._act(m, "Find Next", lambda: self.find_again(False), "F3", "find_next")
        self._act(m, "Find Previous", lambda: self.find_again(True), "Shift+F3", "find_prev")
        self._act(m, "Replace…", lambda: self.find(replace=True), "Ctrl+R", "replace")
        m.addSeparator()
        self._act(m, "Go To…", self.go_to, "Ctrl+G", "goto")
        m = mb.addMenu("&View")
        rm = m.addMenu("Bytes per Row")
        group = QActionGroup(self)
        cols = settings.get_int("bytes_per_row", 16) or 16
        for n in (8, 16, 32):
            a = self._act(rm, str(n), lambda n=n: self.set_cols(n), None, f"cols_{n}", True)
            a.setChecked(n == cols)
            group.addAction(a)
        self._act(m, "Offsets in Decimal", self.toggle_decimal, None, "decimal", True)
        self.acts["decimal"].setChecked(settings.get_bool("decimal_offsets", False))
        self._act(m, "Side Panel", self.toggle_side, "F12", "side_panel", True)
        self.acts["side_panel"].setChecked(settings.get_bool("side_panel", True))
        fm = m.addMenu("Finish")
        group = QActionGroup(self)
        self.finish_acts = {}
        for name in ("obsidian", "aurora"):
            a = self._act(fm, name.upper(), lambda n=name: self.set_finish(n), checkable=True)
            group.addAction(a)
            self.finish_acts[name] = a
        self.finish_acts[theme.FINISH].setChecked(True)
        m = mb.addMenu("&Analysis")
        self._act(m, "Checksums", self.checksums, "Ctrl+Shift+H", "checksums")
        self._act(m, "File Compare…", self.compare_dialog, "Ctrl+K", "compare")
        self._act(m, "Next Difference", lambda: self.page_call("next"), "F6", "next_diff")
        self._act(m, "Previous Difference", lambda: self.page_call("prev"), "Shift+F6", "prev_diff")
        m = mb.addMenu("&Bookmarks")
        self._act(m, "Add Bookmark", self.add_bookmark, "Ctrl+D", "add_bookmark")
        self._act(m, "Next Bookmark", lambda: self.step_bookmark(1), "Ctrl+Alt+Right", "next_bookmark")
        self._act(m, "Previous Bookmark", lambda: self.step_bookmark(-1), "Ctrl+Alt+Left", "prev_bookmark")
        m = mb.addMenu("&Tools")
        self._act(m, "Options…", self.options, None, "options")
        self._act(m, "Edit with PR7-HX in the Explorer Menu", self.toggle_explorer_menu, None, "explorer_menu", True)
        m = mb.addMenu("&Help")
        self._act(m, "Check for Updates…", self.check_updates, None, "updates")
        self._act(m, "About PR7-HX", self.about, None, "about")
        self._explorer_menu_state()

    # ================================================================ look
    def restyle(self):
        app = QApplication.instance()
        if app is not None:
            app.setPalette(theme.palette())
            app.setStyleSheet(theme.stylesheet())
        self.centralWidget().setStyleSheet(
            f"QWidget#central {{ background: {theme.BACKGROUND}; }} QLabel#sep {{ background: {theme.PANEL_EDGE}; }} "
            f"QFrame#foot {{ background: {theme.TAB_FRAME}; border-top: 1px solid {theme.PANEL_EDGE}; }} "
            f"QTabWidget::pane {{ border: none; background: {theme.BACKGROUND}; }}")
        self.header.update()
        for a_name, a in getattr(self, "finish_acts", {}).items():
            a.setChecked(a_name == theme.FINISH)
        for page in self.pages():
            page.restyle()

    def set_finish(self, name: str):
        theme.set_finish(name)
        finish.set(theme.FINISH)
        settings.set("finish", theme.FINISH)
        self.restyle()

    # ================================================================ asking
    def _ask(self, kind: str, payload=None):
        if kind == "say":                       # pages report through here: (kind, text)
            self._say(*payload)
            return None
        if kind in self.answers:
            a = self.answers[kind]
            return a(payload) if callable(a) else a
        if kind == "confirm":
            return QMessageBox.question(self, "PR7-HX", payload) == QMessageBox.StandardButton.Yes
        if kind == "save_changes":
            box = QMessageBox(QMessageBox.Icon.Question, "PR7-HX", f"Save the changes to {payload}?", parent=self)
            save = box.addButton("SAVE", QMessageBox.ButtonRole.AcceptRole)
            discard = box.addButton("DON'T SAVE", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton("CANCEL", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            return "save" if box.clickedButton() is save else "discard" if box.clickedButton() is discard else "cancel"
        if kind == "open_file":
            return QFileDialog.getOpenFileNames(self, "Open", payload or "")[0]
        if kind == "open_image":
            return QFileDialog.getOpenFileName(self, "Open Disk Image", payload or "",
                                               "Disk images (*.img *.ima *.iso *.bin *.dd *.raw);;All files (*)")[0]
        if kind == "save_as":
            return QFileDialog.getSaveFileName(self, "Save As", payload or "")[0]
        if kind == "find":
            dlg = FindDialog(self, payload[0], payload[1])
            return dlg.values() if dlg.exec() else None
        if kind == "goto":
            dlg = GoToDialog(self)
            return dlg.values() if dlg.exec() else None
        if kind == "block":
            dlg = BlockDialog(self, *payload)
            return dlg.values() if dlg.exec() else None
        if kind == "fill":
            text, ok = QInputDialog.getText(self, "Fill Selection", "HEX VALUES (REPEATED)", text="00")
            return text if ok else None
        if kind == "value":
            text, ok = QInputDialog.getText(self, "Data Inspector", payload[0].upper(), text=payload[1])
            return text if ok else None
        if kind == "bookmark_name":
            text, ok = QInputDialog.getText(self, "Add Bookmark", "NAME", text=payload)
            return text if ok else None
        if kind == "disk":
            dlg = OpenDiskDialog(self)
            return dlg.chosen() if dlg.exec() else None
        if kind == "compare":
            dlg = CompareDialog(self, *payload)
            return dlg.values() if dlg.exec() else None
        if kind == "options":
            dlg = OptionsDialog(self)
            if dlg.exec():
                dlg.save()
                return True
            return False
        if kind == "reload":
            return QMessageBox.question(self, "PR7-HX", payload) == QMessageBox.StandardButton.Yes
        return None

    def _say(self, kind: str, text: str):
        self.said.append((kind, text))
        if "say" in self.answers:
            self.answers["say"](kind, text)
            return
        icon = QMessageBox.Icon.Warning if kind in ("error", "warning") else QMessageBox.Icon.Information
        QMessageBox(icon, "PR7-HX", text, parent=self).exec()

    # ================================================================ tabs
    def pages(self) -> list:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def page(self):
        return self.tabs.currentWidget()

    def editor(self) -> EditorPage | None:
        p = self.page()
        return p if isinstance(p, EditorPage) else None

    def _add(self, page):
        page.changed.connect(lambda p=page: self._page_changed(p))
        i = self.tabs.addTab(page, page.title())
        self.tabs.setCurrentIndex(i)
        self.stack.setCurrentWidget(self.tabs)
        self._sync()
        if isinstance(page, EditorPage):
            page.view.setFocus()
        return page

    def _page_changed(self, page):
        i = self.tabs.indexOf(page)
        if i >= 0:
            self.tabs.setTabText(i, page.title())
            if isinstance(page, EditorPage):
                self.tabs.setTabToolTip(i, page.buf.path or "")
        if page is self.page():
            self._sync()

    def open_buffer(self, buf: Buffer) -> EditorPage:
        return self._add(EditorPage(buf, sync=self.sync, ask=self._ask))

    def open_files(self, paths: list[str]):
        got = None
        for p in paths:
            for page in self.pages():                        # already open: show that tab
                if isinstance(page, EditorPage) and page.buf.path and os.path.abspath(page.buf.path) == \
                        os.path.abspath(p):
                    self.tabs.setCurrentWidget(page)
                    got = page
                    break
            else:
                try:
                    got = self.open_buffer(Buffer.open(p))
                except OSError as e:
                    self._say("error", f"Couldn't open {p}:\n{e.strerror or e}")
        return got

    def new_file(self):
        return self.open_buffer(Buffer())

    def open_dialog(self):
        page = self.editor()
        start = os.path.dirname(page.buf.path) if page and page.buf.path and not page.is_disk else ""
        paths = self._ask("open_file", start)
        if paths:
            return self.open_files(list(paths) if isinstance(paths, (list, tuple)) else [paths])
        return None

    def open_disk_dialog(self):
        d = self._ask("disk")
        if d is None:
            return None
        try:
            return self.open_buffer(disks.open_disk(d))
        except PermissionError:
            self._say("error", f"Windows won't let PR7-HX read {d.label} without administrator rights.\n"
                               "Start PR7-HX as administrator (right-click it, Run as administrator) to open disks.")
        except OSError as e:
            self._say("error", f"Couldn't open {d.label}:\n{e.strerror or e}")
        return None

    def open_image_dialog(self):
        path = self._ask("open_image", "")
        if not path:
            return None
        try:
            return self.open_buffer(disks.open_image(path))
        except OSError as e:
            self._say("error", f"Couldn't open {path}:\n{e.strerror or e}")
            return None

    def close_tab(self, i: int) -> bool:
        page = self.tabs.widget(i)
        if page is None:
            return False
        if isinstance(page, EditorPage) and page.modified():
            got = self._ask("save_changes", page.name())
            if got in ("cancel", None):
                return False
            if got == "save" and not self._save_page(page):
                return False
        page.stop()
        self.tabs.removeTab(i)
        if isinstance(page, EditorPage):
            page.buf.close()
        page.deleteLater()
        if not self.tabs.count():
            self.stack.setCurrentWidget(self.welcome)
        self._sync()
        return True

    def closeEvent(self, e):
        for i in range(self.tabs.count() - 1, -1, -1):
            if not self.close_tab(i):
                e.ignore()
                return
        e.accept()

    # ================================================================ saving
    def save(self, as_new: bool = False) -> bool:
        page = self.editor()
        if page is None:
            return False
        got = self._save_page(page, as_new)
        self._sync()
        return got

    def _save_page(self, page: EditorPage, as_new: bool = False) -> bool:
        buf = page.buf
        path = None
        if as_new or (not buf.path):
            path = self._ask("save_as", buf.path or "")
            if not path:
                return False
        if page.is_disk and not path:
            if not self._ask("confirm", f"Write the changed bytes to {page.name()}?\n\nWriting to a disk can make "
                                        "it unreadable. There's no undo once it's written."):
                return False
        try:
            buf.save(path)
        except PermissionError:
            self._say("error", "It's read-only, or Windows refused: writing to a disk needs administrator rights.")
            return False
        except OSError as e:
            self._say("error", f"Couldn't save {path or buf.path}:\n{e.strerror or e}")
            return False
        page.view.refresh()
        page.changed.emit()
        return True

    # ================================================================ editing
    def undo(self):
        page = self.editor()
        if page and page.buf.undo():
            page.view.refresh()
            page._edited()
        self._sync()

    def redo(self):
        page = self.editor()
        if page and page.buf.redo():
            page.view.refresh()
            page._edited()
        self._sync()

    def _block(self, page) -> tuple[int, int]:
        return page.view.selection()

    def copy(self) -> bool:
        page = self.editor()
        if page is None:
            return False
        a, b = self._block(page)
        if b <= a:
            return False
        if b - a > COPY_LIMIT:
            self._say("warning", "That block is too big for the clipboard. Save it with Save As instead.")
            return False
        data = page.buf.read(a, b - a)
        md = QMimeData()
        md.setData(MIME, data)
        md.setText(export.as_text(data, "hex") if page.view.area == "hex" else data.decode("cp1252", "replace"))
        QApplication.clipboard().setMimeData(md)
        return True

    def copy_as(self, fmt: str) -> bool:
        page = self.editor()
        if page is None:
            return False
        a, b = self._block(page)
        if b <= a or b - a > COPY_LIMIT:
            return False
        QApplication.clipboard().setText(export.as_text(page.buf.read(a, b - a), fmt))
        return True

    def cut(self) -> bool:
        page = self.editor()
        if page is None or not self.copy():
            return False
        page.view.delete()
        self._sync()
        return True

    def clipboard_bytes(self, area: str) -> bytes:
        md = QApplication.clipboard().mimeData()
        if md is None:
            return b""
        if md.hasFormat(MIME):
            return bytes(md.data(MIME))
        text = md.text()
        if area == "hex":
            try:
                return search.parse_hex(text)
            except ValueError:
                pass
        return text.encode("cp1252", errors="replace")

    def paste(self, write: bool = False) -> bool:
        """Paste Insert (Ctrl+V: the bytes go in, replacing a selection) or Paste Write (Ctrl+B: over the bytes)."""
        page = self.editor()
        if page is None:
            return False
        data = self.clipboard_bytes(page.view.area)
        if not data:
            return False
        v, buf = page.view, page.buf
        a, b = v.selection()

        def do():
            with buf.group():
                if write or not buf.resizable:
                    buf.overwrite(a, data[:len(buf) - a] if not buf.resizable else data)
                else:
                    if b > a:
                        buf.delete(a, b - a)
                    buf.insert(a, data)
        if v._edit(do):
            v.select(a, a + len(data))
        self._sync()
        return True

    def select_all(self):
        page = self.editor()
        if page:
            page.view.select(0, len(page.buf))

    def select_block(self) -> bool:
        page = self.editor()
        if page is None:
            return False
        got = self._ask("block", page.view.selection())
        if not got:
            return False
        try:
            start = parse_offset(got["start"])
            n = parse_offset(got["end"])
        except ValueError:
            self._say("warning", "Offsets are hex numbers.")
            return False
        end = start + n if got["mode"] == "length" else n + 1
        page.view.select(start, end)
        return True

    def fill_selection(self) -> bool:
        page = self.editor()
        if page is None:
            return False
        a, b = page.view.selection()
        if b <= a:
            self._say("info", "Select the bytes to fill first.")
            return False
        text = self._ask("fill")
        if not text:
            return False
        try:
            pattern = search.parse_hex(text)
        except ValueError as e:
            self._say("warning", str(e))
            return False
        return page.view._edit(lambda: page.buf.fill(a, b - a, pattern))

    def toggle_insert(self):
        page = self.editor()
        if page:
            page.view.toggle_insert()
        self._sync()

    def toggle_read_only(self) -> bool:
        page = self.editor()
        if page is None:
            return False
        buf = page.buf
        if buf.read_only and page.is_disk:
            if not self._ask("confirm", f"Allow changes to {page.name()}?\n\nWriting to a disk can make it "
                                        "unreadable. Nothing is written until you Save, and Save asks again."):
                self._sync()
                return False
        buf.read_only = not buf.read_only
        page.changed.emit()
        self._sync()
        return True

    # ================================================================ search
    def find(self, replace: bool = False):
        page = self.editor()
        if page is None:
            return None
        got = self._ask("find", (replace, self.last_find))
        if not got:
            return None
        self.last_find = got
        try:
            pat = search.make(got["kind"], got["text"], got["encoding"], got["case"], got["size"], got["order"])
        except (ValueError, UnicodeEncodeError) as e:
            self._say("warning", f"Can't search for that: {e}")
            return None
        self._pattern = pat
        if got["action"] == "replace_all":
            try:
                repl = search.make(got["kind"], got["repl"], got["encoding"], True, got["size"], got["order"]).data \
                    if got["repl"] else b""
            except (ValueError, UnicodeEncodeError) as e:
                self._say("warning", f"Can't replace with that: {e}")
                return None
            n = [0]
            if page.view._edit(lambda: n.__setitem__(0, search.replace_all(page.buf, pat, repl))):
                page.view.refresh()
                self._say("info", f"{n[0]} replaced." if n[0] else "Nothing found.")
            self._sync()
            return n[0]
        if got["action"] == "find_all":
            hits = search.find_all(page.buf, pat)
            if not hits:
                self._say("info", "Nothing found.")
                return []
            page.view.select(hits[0][0], hits[0][0] + hits[0][1])
            page.view.center_on(hits[0][0])
            self._say("info", f"Found {len(hits)} time{'s' if len(hits) != 1 else ''}" +
                      (" (stopped there)" if len(hits) >= search.LIMIT else "") + ".")
            return hits
        start = 0 if got["direction"] == "all" else None
        return self._find_from(page, pat, got["direction"] == "backward", start)

    def find_again(self, backwards: bool):
        page = self.editor()
        pat = getattr(self, "_pattern", None)
        if page is None:
            return None
        if pat is None:
            return self.find()
        return self._find_from(page, pat, backwards)

    def _find_from(self, page: EditorPage, pat, backwards: bool, start: int | None = None):
        a, b = page.view.selection()
        if start is None:
            start = a if backwards else (a + 1 if b > a else page.view.cursor)
        hit = search.find(page.buf, pat, start, backwards)
        if hit is None:
            self._say("info", "Nothing more found." if start else "Nothing found.")
            return None
        page.view.select(hit[0], hit[0] + hit[1])
        page.view.center_on(hit[0])
        return hit

    def go_to(self) -> bool:
        page = self.editor()
        if page is None:
            return False
        got = self._ask("goto")
        if not got:
            return False
        try:
            n = parse_offset(got["offset"], got["base"])
        except ValueError:
            self._say("warning", "That isn't a number.")
            return False
        to = {"begin": n, "current": page.view.cursor + n, "end": len(page.buf) - n}[got["origin"]]
        if not 0 <= to <= len(page.buf):
            self._say("warning", f"That's outside the {'disk' if page.is_disk else 'file'}.")
            return False
        page.view.go(to)
        page.view.center_on(to)
        page.view.setFocus()
        return True

    # ================================================================ view
    def set_cols(self, n: int):
        settings.set("bytes_per_row", n)
        for page in self.pages():
            for v in ([page.view] if isinstance(page, EditorPage) else page.views):
                v.set_cols(n)

    def toggle_decimal(self):
        on = self.acts["decimal"].isChecked()
        settings.set("decimal_offsets", on)
        for page in self.pages():
            for v in ([page.view] if isinstance(page, EditorPage) else page.views):
                v.decimal_offsets = on
                v._layout()
                v.viewport().update()
        self._sync()

    def toggle_side(self):
        on = self.acts["side_panel"].isChecked()
        settings.set("side_panel", on)
        for page in self.pages():
            if isinstance(page, EditorPage):
                page.side.setVisible(on)

    def options(self) -> bool:
        if not self._ask("options"):
            return False
        n = settings.get_int("bytes_per_row", 16) or 16
        self.set_cols(n)
        self.acts[f"cols_{n}"].setChecked(True)
        self.acts["decimal"].setChecked(settings.get_bool("decimal_offsets", False))
        self.toggle_decimal()
        self.restyle()
        return True

    # ================================================================ analysis
    def checksums(self):
        page = self.editor()
        if page is None:
            return None
        if not self.acts["side_panel"].isChecked():
            self.acts["side_panel"].setChecked(True)
            self.toggle_side()
        page.calculate()
        return getattr(page, "results", None)

    def compare_dialog(self):
        page = self.editor()
        first = page.buf.path if page and page.buf.path and not page.is_disk else ""
        got = self._ask("compare", (first, ""))
        if not got:
            return None
        a, b = got
        for p in (a, b):
            if not os.path.isfile(p):
                self._say("error", f"{p or 'A file'} isn't there.")
                return None
        try:
            page = self._add(ComparePage(a, b))
        except OSError as e:
            self._say("error", f"Couldn't open {e.filename}:\n{e.strerror or e}")
            return None
        if not page.runs:
            self._say("info", "The files are identical.")
        return page

    def page_call(self, name: str):
        page = self.page()
        if page is not None and hasattr(page, name):
            got = getattr(page, name)()
            self._sync()
            return got
        return None

    def add_bookmark(self):
        page = self.editor()
        if page:
            page.add_bookmark()
            if not self.acts["side_panel"].isChecked():
                self.acts["side_panel"].setChecked(True)
                self.toggle_side()
            page.side.setCurrentIndex(1)

    def step_bookmark(self, d: int) -> bool:
        page = self.editor()
        if page is None or not page.bookmarks:
            return False
        c = page.view.cursor
        starts = [m["start"] for m in page.bookmarks]
        if d > 0:
            k = next((i for i, s in enumerate(starts) if s > c), 0)
        else:
            k = next((i for i in range(len(starts) - 1, -1, -1) if starts[i] < c), len(starts) - 1)
        return page.go_bookmark(k)

    # ================================================================ Explorer menu
    def _explorer_menu_state(self):
        a = self.acts.get("explorer_menu")
        if a is None:
            return
        if sys.platform != "win32":
            a.setEnabled(False)
            return
        from . import shell
        a.setChecked(shell.menu_registered())

    def toggle_explorer_menu(self):
        from . import shell
        try:
            if self.acts["explorer_menu"].isChecked():
                shell.register(shell.exe_command())
            else:
                shell.unregister()
        except OSError as e:
            self._say("error", f"Couldn't change the Explorer menu: {e}")
        self._explorer_menu_state()

    # ================================================================ files changed elsewhere
    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            page = self.editor()
            if page is not None:
                QTimer.singleShot(0, lambda p=page: self.check_disk(p))

    def check_disk(self, page: EditorPage) -> bool:
        buf = page.buf
        if not buf.changed_on_disk():
            return False
        buf.stamp = buf.source.stamp()               # ask once per change
        if not self._ask("reload", f"{page.name()} changed outside PR7-HX. Load it again?" +
                         ("\n\nYour unsaved changes would be lost." if buf.modified else "")):
            return False
        path = buf.path
        try:
            new = Buffer.open(path)
        except OSError as e:
            self._say("error", f"Couldn't load {path} again:\n{e.strerror or e}")
            return False
        buf.close()
        page.buf = page.view.buf = new
        page.view.refresh()
        page._edited()
        return True

    # ================================================================ drag and drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.open_files([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    # ================================================================ keys, menus, status
    def _sync(self):
        if not hasattr(self, "acts"):
            return
        page = self.page()
        ed = page if isinstance(page, EditorPage) else None
        cmp_ = isinstance(page, ComparePage)
        a = self.acts
        writable = bool(ed and not ed.buf.read_only)
        a["save"].setEnabled(bool(ed and ed.buf.modified))
        a["save_as"].setEnabled(bool(ed))
        a["close"].setEnabled(page is not None)
        a["undo"].setEnabled(bool(ed and ed.buf.undo_stack))
        a["redo"].setEnabled(bool(ed and ed.buf.redo_stack))
        has_sel = bool(ed and ed.view.has_selection())
        for k in ("copy",) + tuple("copy_as_" + f for f in export.FORMATS):
            a[k].setEnabled(has_sel)
        a["cut"].setEnabled(has_sel and writable and ed.buf.resizable)
        for k in ("paste", "paste_write"):
            a[k].setEnabled(writable)
        a["fill"].setEnabled(has_sel and writable)
        for k in ("select_all", "select_block", "find", "find_next", "find_prev", "goto", "checksums",
                  "add_bookmark", "next_bookmark", "prev_bookmark"):
            a[k].setEnabled(bool(ed))
        a["replace"].setEnabled(writable)
        a["insert_mode"].setEnabled(bool(ed and ed.buf.resizable and writable))
        a["insert_mode"].setChecked(bool(ed and ed.view.insert_mode))
        a["read_only"].setEnabled(bool(ed and ed.buf.path))
        a["read_only"].setChecked(bool(ed and ed.buf.read_only))
        for k in ("next_diff", "prev_diff"):
            a[k].setEnabled(cmp_ and bool(page.runs))
        self.keys["save"].setEnabled(a["save"].isEnabled())
        self.keys["undo"].setEnabled(a["undo"].isEnabled())
        for k in ("find", "goto", "checksums"):
            self.keys[k].setEnabled(bool(ed))
        self.status.setText(page.status() if page is not None else "Ready")
        self.mode.setText(page.mode_text() if page is not None else "")
        title = page.title() if page is not None else ""
        self.setWindowTitle(f"{title} - Paragon PR7-HX" if title else "Paragon PR7-HX")

    def check_updates(self):
        from . import update_ui
        update_ui.check(self, manual=True)

    def about(self):
        self._say("info", f"Paragon PR7-HX {__version__}\nA hex editor that works the way HxD works.")

