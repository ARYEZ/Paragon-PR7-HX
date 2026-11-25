"""Check a real install of PR7-HX-Setup.exe (CI, Windows): verify_install.py installed|uninstalled

`installed`: the files, the Start menu entry, the uninstall entry, "Edit with PR7-HX" in Explorer's menu starting the
installed exe, and the installed exe's --selftest: a file edited and saved byte for byte, found, checksummed, compared,
a disk image refused while read-only and written once allowed. `uninstalled`: all of it gone, the menu entry too."""
import json
import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

HKCU = winreg.HKEY_CURRENT_USER
APP = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "PR7-HX"
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Paragon PR7-HX.lnk"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{C612D234-7CDF-4811-BA78-1965A73D44AA}_is1"
MENU = r"Software\Classes\*\shell\PR7HX.Edit"


def value(root, path, name=""):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def check(ok, what, p):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        p.append(what)


def installed():
    p = []
    exe = APP / "PR7-HX.exe"
    for f in (exe, APP / "unins000.exe", APP / "_internal" / "pr7hx" / "fonts" / "Inter-Regular.ttf"):
        check(f.is_file(), f"file {f}", p)
    check(SHORTCUT.is_file(), "Start menu shortcut", p)
    check(value(HKCU, UNINSTALL, "DisplayName") == "Paragon PR7-HX", "Installed apps entry", p)
    cmd = value(HKCU, MENU + r"\command") or ""
    check(str(exe).lower() in cmd.lower() and cmd.endswith('"%1"'), f"Explorer menu starts the installed exe ({cmd})", p)
    check(value(HKCU, MENU) == "Edit with PR7-HX", "Explorer menu text", p)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.json"
        try:
            subprocess.run([str(exe), "--selftest", str(out)], timeout=600, check=False)
        except subprocess.TimeoutExpired:
            pass
        got = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        check(got.get("ok") is True and got.get("fonts") is True,
              f"the installed exe edits, saves, finds, checksums, compares, guards a disk ({got})", p)
    return p


def uninstalled():
    deadline = time.time() + 60
    while True:
        p = []
        check(not (APP / "PR7-HX.exe").exists(), "program files removed", p)
        check(not SHORTCUT.exists(), "Start menu shortcut removed", p)
        check(value(HKCU, UNINSTALL, "DisplayName") is None, "Installed apps entry removed", p)
        check(value(HKCU, MENU + r"\command") is None, "Explorer menu entry removed", p)
        if not p or time.time() > deadline:
            return p
        print("... waiting for the uninstaller to finish")
        time.sleep(3)


if __name__ == "__main__":
    problems = {"installed": installed, "uninstalled": uninstalled}[sys.argv[1]]()
    print("\nALL OK" if not problems else f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
