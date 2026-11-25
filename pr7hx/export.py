"""Edit > Copy As (no Qt): a block as hex text, a C or Python array, Base64; and reading hex back for Paste."""

from __future__ import annotations

import base64

FORMATS = {"hex": "Hex values", "c": "C array", "python": "Python bytes", "base64": "Base64"}


def as_text(data: bytes, fmt: str, per_line: int = 16) -> str:
    if fmt == "hex":
        return " ".join(f"{b:02X}" for b in data)
    if fmt == "base64":
        return base64.b64encode(data).decode("ascii")
    if fmt == "c":
        lines = [", ".join(f"0x{b:02X}" for b in data[i:i + per_line]) for i in range(0, len(data), per_line)]
        body = ",\n    ".join(lines)
        return f"unsigned char data[{len(data)}] = {{\n    {body}\n}};"
    if fmt == "python":
        lines = ['    b"' + "".join(f"\\x{b:02x}" for b in data[i:i + per_line]) + '"'
                 for i in range(0, len(data), per_line)]
        return "data = (\n" + "\n".join(lines) + "\n)" if lines else 'data = b""'
    raise ValueError(fmt)
