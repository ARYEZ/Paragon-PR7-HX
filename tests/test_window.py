import hashlib
import os
import struct
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pr7hx import disks, settings, theme


def make(tmp_path, data=bytes(range(256)), name="a.bin"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def find_args(**kw):
    a = {"kind": "hex", "text": "", "repl": "", "encoding": "ANSI", "case": True, "size": 4, "order": "little",
         "direction": "forward", "action": "find"}
    a.update(kw)
    return a


def test_open_type_and_save(window, tmp_path):
    p = make(tmp_path)
    page = window.open_files([p])
    v = page.view
    assert window.tabs.tabText(0) == "a.bin" and window.status.text() == "Offset(h): 0"
    QTest.keyClicks(v, "ab")                                  # overwrite: one byte, AB
    assert page.buf.read(0, 2) == b"\xab\x01" and window.tabs.tabText(0) == "a.bin *"
    assert "1 byte changed, unsaved" in window.mode.text()
    window.acts["undo"].trigger()
    assert page.buf.read(0, 1) == b"\x00"                     # both digits undone together
    window.acts["redo"].trigger()
    v.area = "text"
    QTest.keyClicks(v, "Hi")
    assert page.buf.read(1, 2) == b"Hi"
    window.acts["save"].trigger()
    assert open(p, "rb").read()[:3] == b"\xabHi" and window.tabs.tabText(0) == "a.bin"


def test_insert_mode_backspace_and_delete(window, tmp_path):
    p = make(tmp_path, b"ABCDEF")
    page = window.open_files([p])
    v = page.view
    QTest.keyClick(v, Qt.Key.Key_Insert)
    assert v.insert_mode and window.acts["insert_mode"].isChecked() and "Insert" in window.mode.text()
    v.go(2)
    v.area = "text"
    QTest.keyClicks(v, "xy")
    assert page.buf.read(0, 10) == b"ABxyCDEF"
    QTest.keyClick(v, Qt.Key.Key_Backspace)
    assert page.buf.read(0, 10) == b"ABxCDEF"
    v.select(0, 2)
    QTest.keyClick(v, Qt.Key.Key_Delete)
    assert page.buf.read(0, 10) == b"xCDEF" and len(page.buf) == 5
    window.save()
    assert open(p, "rb").read() == b"xCDEF"


def test_keys_move_and_select(window, tmp_path):
    page = window.open_files([make(tmp_path)])
    v = page.view
    QTest.keyClick(v, Qt.Key.Key_Down)
    QTest.keyClick(v, Qt.Key.Key_Right)
    assert v.cursor == 17
    QTest.keyClick(v, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(v, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert v.selection() == (17, 19) and window.status.text() == "Offset(h): 13   ·   Block(h): 11-12   ·   Length(h): 2"
    QTest.keyClick(v, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
    assert v.cursor == 256 and not v.has_selection()
    QTest.keyClick(v, Qt.Key.Key_Home)
    assert v.cursor == 256 - 256 % 16


def test_copy_and_paste(window, tmp_path):
    p = make(tmp_path, b"0123456789")
    page = window.open_files([p])
    v = page.view
    v.select(2, 5)
    assert window.copy() and QApplication.clipboard().text() == "32 33 34"
    v.go(0)
    window.acts["paste"].trigger()                            # insert
    assert page.buf.read(0, 20) == b"2340123456789" and v.selection() == (0, 3)
    v.go(10)
    window.acts["paste_write"].trigger()                      # write over
    assert page.buf.read(0, 20) == b"2340123456234"
    QApplication.clipboard().setText("41 42")
    v.go(0)
    v.area = "hex"
    window.paste()
    assert page.buf.read(0, 2) == b"AB"
    assert window.copy_as("c") and "0x41, 0x42" in QApplication.clipboard().text()
    window.save()
    assert open(p, "rb").read() == b"AB2340123456234"


def test_find_replace_and_go_to(window, tmp_path):
    data = b"..NTFS....ntfs...." + struct.pack("<I", 1280)
    p = make(tmp_path, data)
    page = window.open_files([p])
    window.answers["find"] = find_args(kind="text", text="ntfs", case=False, direction="all")
    assert window.find() == (2, 4) and page.view.selection() == (2, 6)
    assert window.find_again(False) == (10, 4)
    assert window.find_again(True) == (2, 4)
    window.answers["find"] = find_args(kind="int", text="1280", action="find_all")
    assert window.find() == [(18, 4)]
    window.answers["find"] = find_args(kind="text", text="NTFS", case=False, repl="FAT!", action="replace_all")
    assert window.find(replace=True) == 2
    assert page.buf.read(0, 18) == b"..FAT!....FAT!...."
    window.answers["goto"] = {"offset": "10", "base": "hex", "origin": "begin"}
    assert window.go_to() and page.view.cursor == 16
    window.answers["goto"] = {"offset": "4", "base": "dec", "origin": "end"}
    assert window.go_to() and page.view.cursor == len(data) - 4
    window.answers["goto"] = {"offset": "999", "base": "hex", "origin": "begin"}
    assert not window.go_to()


def test_select_block_and_fill(window, tmp_path):
    p = make(tmp_path)
    page = window.open_files([p])
    window.answers["block"] = {"start": "10", "end": "8", "mode": "length"}
    assert window.select_block() and page.view.selection() == (16, 24)
    window.answers["fill"] = "DE AD"
    assert window.fill_selection()
    assert page.buf.read(16, 8) == bytes.fromhex("DEADDEADDEADDEAD") and len(page.buf) == 256


def test_inspector_shows_and_edits(window, tmp_path):
    p = make(tmp_path, struct.pack("<I", 1280) + b"\0" * 12)
    page = window.open_files([p])
    assert page.inspector_value("UInt32") == "1280"
    page.order_buttons["big"].setChecked(True)
    assert page.inspector_value("UInt32") == str(struct.unpack(">I", struct.pack("<I", 1280))[0])
    assert settings.get("byte_order") == "big"
    page.order_buttons["little"].setChecked(True)
    window.answers["value"] = lambda args: "640"
    assert page.edit_value("UInt16")
    assert page.buf.read(0, 4) == struct.pack("<HH", 640, 0)
    window.answers["value"] = lambda args: "70000"
    assert not page.edit_value("UInt16") and window.said[-1][0] == "warning"


def test_bookmarks(window, tmp_path):
    page = window.open_files([make(tmp_path)])
    page.view.select(16, 20)
    assert page.add_bookmark("Header")
    page.view.go(100)
    assert page.add_bookmark("One byte")
    assert [m["name"] for m in page.bookmarks] == ["Header", "One byte"] and page.view.marks == [(16, 20), (100, 101)]
    page.view.go(0)
    assert window.step_bookmark(1) and page.view.selection() == (16, 20)
    assert window.step_bookmark(1) and page.view.selection() == (100, 101)
    assert page.remove_bookmark(0) and page.view.marks == [(100, 101)]


def test_checksums(window, tmp_path):
    data = os.urandom(5000)
    page = window.open_files([make(tmp_path, data)])
    got = window.checksums()
    assert got["SHA-256"] == hashlib.sha256(data).hexdigest().upper()
    page.view.select(10, 20)
    window.checksums()
    assert page.results["MD5"] == hashlib.md5(data[10:20]).hexdigest().upper()
    assert page.sum_list.topLevelItemCount() == 5


def test_compare(window, tmp_path):
    a = make(tmp_path, b"abcdefgh", "a.dat")
    b = make(tmp_path, b"abXdefYYzz", "b.dat")
    window.answers["compare"] = (a, b)
    page = window.compare_dialog()
    assert page.runs == [(2, 3), (6, 10)] and window.status.text().startswith("Difference 1 of 2")
    window.acts["next_diff"].trigger()
    assert page.cur == 1 and page.views[1].cursor == 6
    window.acts["prev_diff"].trigger()
    assert page.cur == 0
    assert not page.views[0].editable
    window.answers["compare"] = (a, a)
    window.compare_dialog()
    assert ("info", "The files are identical.") in window.said


def test_a_disk_image_is_read_only_until_confirmed(window, tmp_path):
    img = make(tmp_path, bytes(2048), "stick.img")
    page = window.open_buffer(disks.open_image(img))
    v = page.view
    assert page.buf.read_only and "Read-only" in window.mode.text() and window.status.text().startswith("sector 0 of 4")
    QTest.keyClicks(v, "ff")
    assert page.buf.read(0, 1) == b"\0" and "read-only" in window.said[-1][1].lower()
    window.answers["confirm"] = False
    window.toggle_read_only()
    assert page.buf.read_only
    window.answers["confirm"] = True
    window.toggle_read_only()
    assert not page.buf.read_only
    QTest.keyClick(v, Qt.Key.Key_Insert)
    assert not v.insert_mode                                  # a disk can't grow
    QTest.keyClicks(v, "ff")
    window.answers["confirm"] = False
    assert not window.save() and open(img, "rb").read(1) == b"\0"   # Save asks first
    window.answers["confirm"] = True
    assert window.save() and open(img, "rb").read(1) == b"\xff" and os.path.getsize(img) == 2048


def test_closing_with_unsaved_changes(window, tmp_path):
    p = make(tmp_path, b"abc")
    page = window.open_files([p])
    page.view.type_text("0")
    window.answers["save_changes"] = "cancel"
    assert not window.close_tab(0) and window.tabs.count() == 1
    window.answers["save_changes"] = "save"
    assert window.close_tab(0) and open(p, "rb").read() == b"\x01bc"


def test_new_and_save_as(window, tmp_path):
    page = window.new_file()
    page.view.type_text("CAFE")
    target = str(tmp_path / "new.bin")
    window.answers["save_as"] = target
    assert window.save() and open(target, "rb").read() == b"\xca\xfe" and page.name() == "new.bin"


def test_reload_when_changed_elsewhere(window, tmp_path):
    p = make(tmp_path, b"one")
    page = window.open_files([p])
    with open(p, "wb") as f:
        f.write(b"other text")
    window.answers["reload"] = True
    assert window.check_disk(page) and page.buf.read(0, 20) == b"other text"


def test_bytes_per_row_and_finish(window, tmp_path):
    page = window.open_files([make(tmp_path)])
    window.set_cols(32)
    assert page.view.cols == 32 and settings.get_int("bytes_per_row") == 32
    window.set_cols(16)
    window.set_finish("aurora")
    assert theme.FINISH == "aurora"
    window.set_finish("obsidian")


def test_the_same_file_opens_once(window, tmp_path):
    p = make(tmp_path)
    window.open_files([p])
    window.open_files([p])
    assert window.tabs.count() == 1


@pytest.mark.skipif(sys.platform == "win32", reason="elsewhere the Explorer menu can't be set")
def test_explorer_menu_is_windows_only(window):
    assert not window.acts["explorer_menu"].isEnabled()


def test_version():
    import pr7hx
    assert pr7hx.__version__.count(".") == 2
