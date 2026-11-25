import hashlib
import os
import struct
import zlib

import pytest

from pr7hx import buffer, checksums, disks, export, hexcompare, inspect, search
from pr7hx.buffer import Buffer


def make(tmp_path, data, name="f.bin"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_read_and_edit(tmp_path):
    p = make(tmp_path, bytes(range(256)))
    b = Buffer.open(p)
    assert len(b) == 256 and b.read(250, 10) == bytes(range(250, 256))
    b.overwrite(1, b"\xAA\xBB")
    b.insert(0, b"HEAD")
    b.delete(10, 4)
    want = bytearray(range(256))
    want[1:3] = b"\xAA\xBB"
    want[0:0] = b"HEAD"
    del want[10:14]
    assert b.read(0, len(b)) == bytes(want) and len(b) == 256
    assert b.changed_ranges(0, 20) == [(0, 4), (5, 7)] and b.modified
    assert open(p, "rb").read() == bytes(range(256))         # nothing written until Save
    b.save()
    assert open(p, "rb").read() == bytes(want) and not b.modified and b.changed_ranges(0, 300) == []
    b.close()


def test_undo_redo_and_groups(tmp_path):
    b = Buffer.open(make(tmp_path, b"abcdef"))
    b.overwrite(0, b"X")
    b.insert(6, b"!")
    assert b.read(0, 10) == b"Xbcdef!"
    assert b.undo() and b.read(0, 10) == b"Xbcdef"
    assert b.undo() and b.read(0, 10) == b"abcdef" and not b.modified
    assert b.redo() and b.read(0, 10) == b"Xbcdef"
    with b.group():
        b.overwrite(1, b"Y")
        b.overwrite(2, b"Z")
    assert b.read(0, 3) == b"XYZ" and b.undo() and b.read(0, 3) == b"Xbc"
    b.close()


def test_a_big_file_is_never_read_whole(tmp_path, monkeypatch):
    p = tmp_path / "big.bin"
    with open(p, "wb") as f:
        f.seek(300 * 1024 * 1024 - 4)
        f.write(b"TAIL")                                          # a sparse 300 MB file
    b = Buffer.open(str(p))
    reads = []
    real = b.source.read
    monkeypatch.setattr(b.source, "read", lambda o, n: reads.append(n) or real(o, n))
    assert b.read(len(b) - 4, 4) == b"TAIL"
    b.insert(10, b"x")
    assert b.read(len(b) - 4, 4) == b"TAIL" and max(reads) < 1 << 21
    b.close()


def test_save_as_and_failures(tmp_path):
    p = make(tmp_path, b"hello")
    b = Buffer.open(p)
    b.overwrite(0, b"J")
    other = str(tmp_path / "copy.bin")
    assert b.save(other) == other
    assert open(other, "rb").read() == b"Jello" and open(p, "rb").read() == b"hello" and b.path == other
    ro = Buffer.open(p, read_only=True)
    with pytest.raises(PermissionError):
        ro.overwrite(0, b"x")
    assert not [n for n in os.listdir(tmp_path) if n.startswith(".pr7hx-")]   # no temp files left behind
    b.close()
    ro.close()


def test_changed_on_disk(tmp_path):
    p = make(tmp_path, b"one")
    b = Buffer.open(p)
    assert not b.changed_on_disk()
    with open(p, "ab") as f:
        f.write(b" two")
    assert b.changed_on_disk()
    b.close()


def test_a_disk_image_writes_only_its_changed_sectors(tmp_path):
    data = bytearray(4096)
    data[510:512] = b"\x55\xAA"
    p = make(tmp_path, bytes(data), "disk.img")
    b = disks.open_image(p, 512)
    assert b.read_only and not b.resizable and b.read(510, 2) == b"\x55\xAA"
    with pytest.raises(PermissionError):
        b.overwrite(0, b"\xEB")
    b.read_only = False
    with pytest.raises(ValueError):
        b.insert(0, b"x")                                         # a disk can't grow
    b.overwrite(1000, b"PR7")
    b.save()
    got = open(p, "rb").read()
    assert got[1000:1003] == b"PR7" and len(got) == 4096 and got[510:512] == b"\x55\xAA"
    assert not b.modified
    b.close()


def test_hex_and_text_search(tmp_path):
    data = b"\x00" * (buffer.CHUNK - 2) + b"NTFS" + b"\x00" * 50 + b"ntfs" + b"\x00" * 10
    b = Buffer.open(make(tmp_path, data))
    pat = search.make("hex", "4E 54 46 53")
    assert search.find(b, pat) == (buffer.CHUNK - 2, 4)                    # across the chunk border
    pat = search.make("text", "ntfs", case=False)
    assert search.find_all(b, pat) == [(buffer.CHUNK - 2, 4), (buffer.CHUNK + 52, 4)]
    assert search.find(b, pat, len(b), backwards=True) == (buffer.CHUNK + 52, 4)
    assert search.find(b, pat, buffer.CHUNK + 52, backwards=True) == (buffer.CHUNK - 2, 4)
    u = search.make("text", "Ab", encoding="UTF-16 LE")
    assert u.data == b"A\0b\0"
    with pytest.raises(ValueError):
        search.parse_hex("4E 5")
    b.close()


def test_number_search_and_replace_all(tmp_path):
    data = struct.pack("<I", 1280) + b"--" + struct.pack("<I", 1280) + struct.pack(">I", 1280)
    b = Buffer.open(make(tmp_path, data))
    pat = search.make("int", "1280", size=4)
    assert search.find_all(b, pat) == [(0, 4), (6, 4)]
    assert search.find_all(b, search.make("int", "1280", size=4, order="big")) == [(10, 4)]
    assert search.encode_number("int", "4294967295", 4) == b"\xff\xff\xff\xff"
    assert search.encode_number("int", "-1", 2) == b"\xff\xff"
    assert search.replace_all(b, pat, struct.pack("<I", 640)) == 2
    assert b.read(0, 4) == struct.pack("<I", 640) and b.read(6, 4) == struct.pack("<I", 640)
    assert b.undo() and b.read(0, 14) == data                                # one Undo step
    with pytest.raises(ValueError):
        search.encode_number("int", "70000", 2)
    b.close()


def test_inspector():
    data = struct.pack("<i", -2) + b"\0\0\0\0"
    rows = {name: v for name, v, _ in inspect.rows(data)}
    assert rows["Int32"] == "-2" and rows["UInt32"] == "4294967294" and rows["Int8"] == "-2"
    assert rows["Binary (8 bit)"] == "11111110"
    assert inspect.value("UInt32", struct.pack(">I", 1280), "big") == "1280"
    assert inspect.value("Unix time (32 bit)", struct.pack("<i", 0)) == "1970-01-01 00:00:00"
    assert inspect.value("FILETIME", struct.pack("<Q", 116444736000000000)) == "1970-01-01 00:00:00"
    assert inspect.value("Float (32 bit)", struct.pack("<f", 1.5)) == "1.5"
    assert inspect.value("Int64", b"\1\2") == ""                             # not enough bytes
    assert inspect.encode("UInt16", "0x1234") == b"\x34\x12"
    assert inspect.encode("Int16", "-1", "big") == b"\xff\xff"
    assert inspect.encode("Double (64 bit)", "2,5") == struct.pack("<d", 2.5)
    with pytest.raises(ValueError):
        inspect.encode("UInt8", "300")


def test_checksums(tmp_path):
    data = os.urandom(3 * 1024 * 1024 + 7)
    b = Buffer.open(make(tmp_path, data))
    got = checksums.compute(b)
    assert got["CRC-32"] == f"{zlib.crc32(data):08X}" and got["SHA-256"] == hashlib.sha256(data).hexdigest().upper()
    part = checksums.compute(b, 10, 20, ["MD5"])
    assert part == {"MD5": hashlib.md5(data[10:20]).hexdigest().upper()}
    with pytest.raises(checksums.Cancelled):
        checksums.compute(b, cancelled=lambda: True)
    b.close()


def test_compare(tmp_path):
    a = Buffer.open(make(tmp_path, b"abcdefgh", "a"))
    b = Buffer.open(make(tmp_path, b"abXdeYZh!!", "b"))
    runs = hexcompare.differences(a, b)
    assert runs == [(2, 3), (5, 7), (8, 10)] and hexcompare.differing_bytes(runs) == 5
    same = Buffer.open(make(tmp_path, b"abcdefgh", "c"))
    assert hexcompare.differences(a, same) == []
    for x in (a, b, same):
        x.close()


def test_copy_as():
    data = b"\x01\xAB"
    assert export.as_text(data, "hex") == "01 AB"
    assert export.as_text(data, "c") == "unsigned char data[2] = {\n    0x01, 0xAB\n};"
    assert export.as_text(data, "python") == 'data = (\n    b"\\x01\\xab"\n)'
    assert export.as_text(data, "base64") == "Aas="
