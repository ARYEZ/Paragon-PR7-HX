"""PR7-HX's dialogs: Find / Replace, Go To, Select Block, Fill Selection, Open Disk, File Compare, Options."""

from __future__ import annotations

import os

from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import disks, search, settings

KINDS = [("hex", "Hex values"), ("text", "Text string"), ("int", "Integer number"), ("float", "Floating point number")]


def _field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def _radios(parent, layout, choices, current):
    """Radio buttons in their own group (siblings would otherwise be one set)."""
    group = QButtonGroup(parent)
    buttons = {}
    for key, text in choices:
        r = QRadioButton(text)
        r.setChecked(key == current)
        group.addButton(r)
        layout.addWidget(r)
        buttons[key] = r
    return buttons


def _chosen(buttons) -> str:
    return next((k for k, b in buttons.items() if b.isChecked()), next(iter(buttons)))


class FindDialog(QDialog):
    """Find (and, with replace=True, Replace): what = (kind, text, encoding, case, size, order, direction)."""

    def __init__(self, parent=None, replace: bool = False, last: dict | None = None):
        super().__init__(parent)
        last = last or {}
        self.setWindowTitle("Replace" if replace else "Find")
        self.setMinimumWidth(520)
        self.action = "find"
        form = QFormLayout()
        self.text = QLineEdit(last.get("text", ""))
        form.addRow(_field("Search for"), self.text)
        self.repl = QLineEdit(last.get("repl", ""))
        if replace:
            form.addRow(_field("Replace with"), self.repl)
        self.kind = QComboBox()
        for k, t in KINDS:
            self.kind.addItem(t, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(last.get("kind", "hex"))))
        form.addRow(_field("Data type"), self.kind)
        self.encoding = QComboBox()
        self.encoding.addItems(list(search.ENCODINGS))
        self.encoding.setCurrentText(last.get("encoding", "ANSI"))
        form.addRow(_field("Text encoding"), self.encoding)
        self.case = QCheckBox("Match case")
        self.case.setChecked(last.get("case", False))
        form.addRow("", self.case)
        self.size = QComboBox()
        self.size.addItems(list(search.INT_SIZES))
        self.size.setCurrentText(last.get("size_text", "32 bit"))
        form.addRow(_field("Integer size"), self.size)
        self.fsize = QComboBox()
        self.fsize.addItem("Float (32 bit)", "4")
        self.fsize.addItem("Double (64 bit)", "8")
        self.fsize.setCurrentIndex(0 if last.get("fsize", 4) == 4 else 1)
        form.addRow(_field("Floating point"), self.fsize)
        row = QHBoxLayout()
        self.order = _radios(self, row, [("little", "Little endian"), ("big", "Big endian")],
                             last.get("order", "little"))
        row.addStretch(1)
        w = QWidget()
        w.setLayout(row)
        form.addRow(_field("Byte order"), w)
        row = QHBoxLayout()
        self.direction = _radios(self, row, [("all", "All (from the start)"), ("forward", "Forward"),
                                             ("backward", "Backward")], last.get("direction", "forward"))
        row.addStretch(1)
        w = QWidget()
        w.setLayout(row)
        form.addRow(_field("Search direction"), w)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        if replace:
            b = buttons.addButton("REPLACE ALL", QDialogButtonBox.ButtonRole.AcceptRole)
            b.clicked.connect(lambda: self._go("replace_all"))
        b = buttons.addButton("FIND ALL" if not replace else "FIND", QDialogButtonBox.ButtonRole.AcceptRole)
        b.clicked.connect(lambda: self._go("find_all" if not replace else "find"))
        ok = buttons.addButton("FIND NEXT", QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setDefault(True)
        ok.clicked.connect(lambda: self._go("find"))
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.kind.currentIndexChanged.connect(lambda _: self._sync())
        self._sync()

    def _sync(self):
        k = self.kind.currentData()
        self.encoding.setEnabled(k == "text")
        self.case.setEnabled(k == "text")
        self.size.setEnabled(k == "int")
        self.fsize.setEnabled(k == "float")
        for b in self.order.values():
            b.setEnabled(k in ("int", "float"))

    def _go(self, action: str):
        self.action = action
        self.accept()

    def values(self) -> dict:
        k = self.kind.currentData()
        size = search.INT_SIZES[self.size.currentText()] if k == "int" else int(self.fsize.currentData())
        return {"kind": k, "text": self.text.text(), "repl": self.repl.text(), "encoding": self.encoding.currentText(),
                "case": self.case.isChecked(), "size": size, "size_text": self.size.currentText(),
                "fsize": int(self.fsize.currentData()),
                "order": _chosen(self.order), "direction": _chosen(self.direction), "action": self.action}


class GoToDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Go To")
        form = QFormLayout()
        self.offset = QLineEdit()
        self.offset.setPlaceholderText("Offset")
        form.addRow(_field("Offset"), self.offset)
        row = QHBoxLayout()
        self.base = _radios(self, row, [("hex", "Hex"), ("dec", "Decimal")], "hex")
        row.addStretch(1)
        w = QWidget()
        w.setLayout(row)
        form.addRow(_field("Number"), w)
        row = QHBoxLayout()
        self.origin = _radios(self, row, [("begin", "From the start"), ("current", "From the cursor"),
                                          ("end", "From the end (back)")], "begin")
        row.addStretch(1)
        w = QWidget()
        w.setLayout(row)
        form.addRow(_field("Counted"), w)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)

    def values(self) -> dict:
        return {"offset": self.offset.text(), "base": _chosen(self.base), "origin": _chosen(self.origin)}


def parse_offset(text: str, base: str = "hex") -> int:
    t = text.strip().replace(" ", "")
    if t.lower().startswith("0x"):
        return int(t, 16)
    return int(t, 16 if base == "hex" else 10)


class BlockDialog(QDialog):
    """Edit > Select Block: start, then an end offset or a length."""

    def __init__(self, parent=None, start: int = 0, end: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Select Block")
        form = QFormLayout()
        self.start = QLineEdit(f"{start:X}")
        self.end = QLineEdit(f"{max(start, end - 1):X}")
        form.addRow(_field("Start offset (hex)"), self.start)
        row = QHBoxLayout()
        self.mode = _radios(self, row, [("end", "End offset"), ("length", "Length")], "end")
        row.addStretch(1)
        w = QWidget()
        w.setLayout(row)
        form.addRow(_field("Then"), w)
        form.addRow(_field("End / length (hex)"), self.end)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)

    def values(self) -> dict:
        return {"start": self.start.text(), "end": self.end.text(), "mode": _chosen(self.mode)}


class OpenDiskDialog(QDialog):
    """File > Open Disk: Windows' drives and physical disks; always opened read-only first."""

    def __init__(self, parent=None, found: list | None = None):
        super().__init__(parent)
        self.setWindowTitle("Open Disk")
        self.setMinimumWidth(560)
        self.found = disks.list_disks() if found is None else found
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["DISK", "KIND", "SIZE", "SECTOR"])
        self.tree.setRootIsDecorated(False)
        from .pages import fmt_size
        for d in self.found:
            self.tree.addTopLevelItem(QTreeWidgetItem([d.label, d.kind, fmt_size(d.size) if d.size else "no access",
                                                       str(d.sector)]))
        if self.found:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        lay = QVBoxLayout(self)
        lay.addWidget(self.tree)
        note = QLabel("Disks open read-only. Writing to a disk can make it unreadable: turn Read-only off only when "
                      "you're sure (Edit > Read-only). Opening a disk needs administrator rights.")
        note.setWordWrap(True)
        note.setProperty("role", "dim")
        lay.addWidget(note)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)

    def chosen(self):
        i = self.tree.indexOfTopLevelItem(self.tree.currentItem()) if self.tree.currentItem() else -1
        return self.found[i] if 0 <= i < len(self.found) else None


class CompareDialog(QDialog):
    def __init__(self, parent=None, left: str = "", right: str = ""):
        super().__init__(parent)
        self.setWindowTitle("File Compare")
        self.setMinimumWidth(620)
        form = QFormLayout()
        self.edits = {}
        for side, value in (("first", left), ("second", right)):
            row = QHBoxLayout()
            e = QLineEdit(value)
            row.addWidget(e, 1)
            b = QPushButton("BROWSE…")
            b.clicked.connect(lambda _=False, e=e: self._browse(e))
            row.addWidget(b)
            w = QWidget()
            w.setLayout(row)
            form.addRow(_field(f"{side} file"), w)
            self.edits[side] = e
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        ok = b.addButton("COMPARE", QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setDefault(True)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)

    def _browse(self, edit):
        got, _ = QFileDialog.getOpenFileName(self, "Choose a file", os.path.dirname(edit.text()))
        if got:
            edit.setText(os.path.normpath(got))

    def values(self):
        return self.edits["first"].text().strip(), self.edits["second"].text().strip()


class OptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Options")
        form = QFormLayout()
        self.cols = QComboBox()
        for n in (8, 16, 32):
            self.cols.addItem(f"{n} bytes", str(n))
        self.cols.setCurrentIndex(max(0, self.cols.findData(str(settings.get_int("bytes_per_row", 16) or 16))))
        form.addRow(_field("Bytes per row"), self.cols)
        self.decimal = QCheckBox("Offsets in decimal")
        self.decimal.setChecked(settings.get_bool("decimal_offsets", False))
        form.addRow("", self.decimal)
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(6, 32)
        self.font_size.setSingleStep(0.5)
        self.font_size.setSuffix(" pt")
        self.font_size.setValue(settings.get_float("font_size", 10.0))
        form.addRow(_field("Text size"), self.font_size)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)

    def save(self):
        settings.set("bytes_per_row", int(self.cols.currentData()))
        settings.set("decimal_offsets", self.decimal.isChecked())
        settings.set("font_size", self.font_size.value())
