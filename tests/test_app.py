import json
import os
import subprocess
import sys
import time

from pr7hx import app


def test_a_second_launch_hands_over(window, tmp_path, qapp):
    """A second PR7-HX (its own process, as Explorer starts it) opens its file in this window."""
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    assert app.listen(window) is not None
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from PySide6.QtCore import QCoreApplication; "
            "q = QCoreApplication([]); from pr7hx import app; "
            "sys.exit(0 if app.hand_over({'files': sys.argv[2:]}, 3000) else 1)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.Popen([sys.executable, "-c", code, root, str(f)])
    deadline = time.time() + 20
    while (not window.tabs.count() or proc.poll() is None) and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert proc.wait(5) == 0
    assert window.editor().buf.path == str(f)
    window.instance_server.close()


def test_selftest(tmp_path):
    out = tmp_path / "out.json"
    assert app.selftest(str(out)) == 0
    r = json.loads(out.read_text())
    assert r["ok"] and r["disk_refused_while_read_only"] and r["differences"] >= 1
