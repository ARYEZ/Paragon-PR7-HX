"""Start PR7-HX.

    PR7-HX.exe [FILE ...]              the window, the files open in tabs (one window per user: a later start hands
                                       its files to the running window)
    PR7-HX.exe --register-menu         add "Edit with PR7-HX" to Explorer's menu (HKCU); --unregister removes it
    PR7-HX.exe --version
    PR7-HX.exe --selftest OUT.json     edit, save, search, checksum and compare real files and a disk image offscreen
                                       (CI runs the installed exe)
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import sys
import tempfile

TIMEOUT_MS = 1500


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "Paragon-PR7-HX-" + hashlib.sha1(user.encode()).hexdigest()[:12]


def hand_over(message: dict, wait_ms: int = 0) -> bool:
    """Give a message to the running window. With wait_ms, keep trying that long (it may still be starting)."""
    from PySide6.QtCore import QElapsedTimer, QThread
    from PySide6.QtNetwork import QLocalSocket
    clock = QElapsedTimer()
    clock.start()
    while True:
        s = QLocalSocket()
        s.connectToServer(server_name())
        if s.waitForConnected(TIMEOUT_MS):
            s.write(json.dumps(message).encode() + b"\n")
            s.flush()
            s.waitForBytesWritten(TIMEOUT_MS)
            if not s.waitForDisconnected(TIMEOUT_MS):
                s.disconnectFromServer()
            return True
        if clock.elapsed() >= wait_ms:
            return False
        QThread.msleep(100)


def listen(window):
    """Later starts hand their files over (PR7-R's hand-off, with its Windows fix: data already waiting when the
    connection is accepted is read at once)."""
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(window)
    QLocalServer.removeServer(server_name())
    if not server.listen(server_name()):
        return None

    def connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        buf = bytearray()

        def read():
            buf.extend(bytes(sock.readAll()))
            if b"\n" not in buf:
                return
            try:
                msg = json.loads(bytes(buf).split(b"\n", 1)[0])
            except ValueError:
                msg = {}
            sock.disconnectFromServer()
            receive(window, msg)
        sock.readyRead.connect(read)
        if sock.bytesAvailable():
            read()
    server.newConnection.connect(connection)
    window.instance_server = server
    return server


def receive(window, msg: dict):
    window.showNormal()
    window.raise_()
    window.activateWindow()
    files = [f for f in msg.get("files", []) if f]
    if files:
        window.open_files(files)


def selftest(out: str) -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
    app = QApplication.instance() or QApplication(sys.argv[:1])
    result: dict = {}
    try:
        from . import __version__, disks, theme
        from .main_window import MainWindow
        theme.load_fonts()
        d = tempfile.mkdtemp()
        f = os.path.join(d, "sample.bin")
        data = bytes(range(256)) * 64
        with open(f, "wb") as fh:
            fh.write(data)
        other = os.path.join(d, "other.bin")
        with open(other, "wb") as fh:
            fh.write(data[:100] + b"\xEE" + data[101:])
        img = os.path.join(d, "disk.img")
        with open(img, "wb") as fh:
            fh.write(bytes(4096))
        w = MainWindow(sync=True)
        w.answers.update({"say": lambda k, t: None, "confirm": True, "save_changes": "discard", "reload": True})
        w.show()
        page = w.open_files([f])
        page.view.type_text("CAFE")                         # overwrite two bytes
        page.view.insert_mode = True
        page.view.go(4)
        page.view.type_text("00")                           # insert one
        w.save()
        with open(f, "rb") as fh:
            saved = fh.read()
        edited = saved[:5] == b"\xca\xfe\x02\x03\x00" and len(saved) == len(data) + 1
        w.answers["find"] = {"kind": "hex", "text": "FE FF", "repl": "", "encoding": "ANSI", "case": True, "size": 4,
                             "order": "little", "direction": "all", "action": "find_all"}
        found = w.find()
        page.view.go(0)                                     # no selection: the whole file's checksums
        sums = w.checksums()
        sums_ok = sums["SHA-256"] == hashlib.sha256(saved).hexdigest().upper()
        w.answers["compare"] = (f, other)
        cmp_page = w.compare_dialog()
        disk = w.open_buffer(disks.open_image(img))
        disk.view.type_text("AA")                           # refused: read-only
        refused = open(img, "rb").read(1) == b"\0"
        w.tabs.setCurrentWidget(disk)
        w.toggle_read_only()
        disk.view.go(0)
        disk.view.type_text("AA")
        w.save()
        with open(img, "rb") as fh:
            disk_bytes = fh.read()
        disk_ok = disk_bytes[0] == 0xAA and len(disk_bytes) == 4096
        result = {"version": __version__, "edited": edited, "found": len(found or []), "checksums": sums_ok,
                  "differences": len(cmp_page.runs) if cmp_page else -1, "disk_refused_while_read_only": refused,
                  "disk_written": disk_ok, "fonts": "Inter" in QFontDatabase.families()}
        result["ok"] = edited and bool(found) and sums_ok and refused and disk_ok and cmp_page is not None
        w.close()
    except Exception as e:  # noqa: BLE001 - reported in the output
        import traceback
        result = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    app.clipboard().clear()
    return 0 if result.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or not argv[0].startswith("--"):
        return _window(argv)
    try:
        return _command(argv)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - reported, then a failing exit code
        import traceback
        if sys.stderr is not None:
            sys.stderr.write(traceback.format_exc())
        return 2


def _command(argv: list[str]) -> int:
    if argv[:1] == ["--version"]:
        from . import __version__
        print(__version__)
        return 0
    if argv[:1] == ["--selftest"] and len(argv) == 2:
        return selftest(argv[1])
    if argv[:1] == ["--register-menu"]:
        from . import shell
        shell.register(shell.exe_command())
        return 0
    if argv[:1] in (["--unregister"], ["--unregister-menu"]):
        from . import shell
        shell.unregister()
        return 0
    print(__doc__)
    return 1


def _lock():
    """The first PR7-HX of this user holds this lock while it starts the window; later ones hand over to it (Explorer
    starts one per selected file)."""
    from PySide6.QtCore import QLockFile
    lock = QLockFile(os.path.join(tempfile.gettempdir(), server_name() + ".lock"))
    lock.setStaleLockTime(0)
    return lock


def _window(argv: list[str]) -> int:
    from PySide6.QtWidgets import QApplication

    from . import settings, theme
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("Paragon")
    app.setApplicationName("PR7-HX")
    files = [os.path.abspath(a) for a in argv]
    lock = _lock()
    if not lock.tryLock(0):
        if hand_over({"files": files}, wait_ms=8000):
            return 0
        lock.removeStaleLockFile()
        lock.tryLock(0)
    elif hand_over({"files": files}):
        return 0
    from . import finish
    theme.set_finish(finish.start(settings.get("finish", "obsidian")))
    theme.load_fonts()
    app.setPalette(theme.palette())
    from PySide6.QtGui import QIcon
    icon = os.path.join(os.path.dirname(__file__), "icons", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    from .main_window import MainWindow
    w = MainWindow()
    from PySide6.QtCore import QTimer
    _follow = QTimer(w)                      # one finish for the family: follow another app's switch (finish.py)
    _follow.timeout.connect(lambda: finish.follow(theme.FINISH, w.set_finish))
    _follow.start(2000)
    listen(w)
    w.show()
    if files:
        QTimer.singleShot(0, lambda: w.open_files(files))
    from . import update_ui
    update_ui.start(w)
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
