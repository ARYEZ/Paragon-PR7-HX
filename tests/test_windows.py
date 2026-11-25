"""Windows only (CI): the real registry under a throwaway key, and the runner's real drive C: read through Open Disk
(CI runs as administrator)."""
import sys
import uuid

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_explorer_menu_keys():
    import winreg

    from pr7hx import shell
    base = rf"Software\Paragon\PR7-HX-test-{uuid.uuid4().hex[:8]}\Classes"
    try:
        shell.register('"C:\\Apps\\PR7-HX.exe"', base)
        assert shell.menu_registered(base) and shell.command_of(base) == '"C:\\Apps\\PR7-HX.exe" "%1"'
        shell.unregister(base)
        assert not shell.menu_registered(base)
    finally:
        shell.unregister(base)
        root = base.rsplit("\\", 1)[0]
        for sub in (base + r"\*\shell", base + r"\*", base, root):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass


def test_the_real_drive_c_reads_read_only():
    from pr7hx import disks
    found = {d.path: d for d in disks.list_disks()}
    c = found.get("\\\\.\\C:")
    assert c is not None and c.size > 10 ** 9 and c.sector in (512, 4096)
    buf = disks.open_disk(c)
    try:
        assert buf.read_only and buf.read(3, 4) == b"NTFS" and buf.read(510, 2) == b"\x55\xaa"
        assert buf.read(c.size - 16, 16) is not None
        with pytest.raises(PermissionError):
            buf.overwrite(0, b"\0")
    finally:
        buf.close()
