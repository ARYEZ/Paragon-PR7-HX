"""The Explorer menu's "Edit with PR7-HX" (HKCU only), as HxD adds "Edit with HxD": a registry verb on every file
(`*`) that starts PR7-HX with the file; the running window opens it in a new tab (app.py's hand-over).

`base` is the Classes key under HKCU; tests on Windows CI pass a throwaway key so they never touch the real menu."""

from __future__ import annotations

import os
import sys

VERB = "PR7HX.Edit"
TEXT = "Edit with PR7-HX"
BASE = r"Software\Classes"


def exe_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" -m pr7hx'


def _icon() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.join(os.path.dirname(__file__), "icons", "app.ico")


def register(command: str, base: str = BASE) -> None:
    import winreg
    key = rf"{base}\*\shell\{VERB}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, TEXT)
        winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, _icon())
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, f'{command} "%1"')
    _changed()


def unregister(base: str = BASE) -> None:
    import winreg
    key = rf"{base}\*\shell\{VERB}"
    for sub in (key + r"\command", key):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
        except OSError:
            pass
    _changed()


def menu_registered(base: str = BASE) -> bool:
    return command_of(base) is not None if sys.platform == "win32" else False


def command_of(base: str = BASE) -> str | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{base}\*\shell\{VERB}\command") as k:
            return winreg.QueryValueEx(k, None)[0]
    except OSError:
        return None


def _changed() -> None:
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:  # noqa: BLE001 - only a refresh
        pass
