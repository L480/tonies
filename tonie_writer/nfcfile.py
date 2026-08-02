"""Parser for Flipper Zero NFC device files (v4, SLIX) describing Tonie tags.

The format is documented in docs/WORKFLOW.md ("The `.nfc` file format").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

HEX_BYTE_RUN = re.compile(r"^[0-9A-Fa-f]{2}(?: [0-9A-Fa-f]{2})*$")


class NfcParseError(ValueError):
    """Raised when a .nfc file cannot be parsed or fails validation."""

    def __init__(self, message: str, line: str | None = None):
        self.line = line
        if line is not None:
            message = f"{message}: {line!r}"
        super().__init__(message)


@dataclass(frozen=True)
class TonieTag:
    path: Path
    uid: str  # "E00403502030361D" - hex, no spaces, uppercase
    uid_bytes: bytes
    blocks: list[str]  # 8 entries, e.g. "D93FEB0A"
    block_count: int
    block_size: int
    device_type: str  # "SLIX"
    raw: dict[str, str] = field(default_factory=dict)


def _parse_hex_bytes(value: str, field_name: str, line: str) -> bytes:
    if not HEX_BYTE_RUN.match(value):
        raise NfcParseError(f"Malformed hex byte list for {field_name}", line)
    try:
        return bytes.fromhex(value.replace(" ", ""))
    except ValueError as exc:
        raise NfcParseError(f"Malformed hex byte list for {field_name}", line) from exc


def parse_nfc_file(path: Path) -> TonieTag:
    """Parse a Flipper NFC device file into a TonieTag.

    Raises NfcParseError with the offending line on malformed or unexpected input.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    raw: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ": " not in stripped:
            raise NfcParseError("Expected 'Key: value' line", line)
        key, value = stripped.split(": ", 1)
        raw[key] = value

    def require(key: str) -> str:
        if key not in raw:
            raise NfcParseError(f"Missing required field {key!r}", key)
        return raw[key]

    filetype = require("Filetype")
    if filetype != "Flipper NFC device":
        raise NfcParseError("Unexpected Filetype", f"Filetype: {filetype}")

    device_type = require("Device type")
    if device_type != "SLIX":
        raise NfcParseError("Unsupported Device type (expected SLIX)", f"Device type: {device_type}")

    uid_line = require("UID")
    uid_bytes = _parse_hex_bytes(uid_line, "UID", f"UID: {uid_line}")
    if len(uid_bytes) != 8:
        raise NfcParseError("UID must be 8 bytes", f"UID: {uid_line}")

    block_count_str = require("Block Count")
    try:
        block_count = int(block_count_str)
    except ValueError as exc:
        raise NfcParseError("Block Count must be an integer", f"Block Count: {block_count_str}") from exc
    if block_count != 8:
        raise NfcParseError("Block Count must be 8", f"Block Count: {block_count_str}")

    block_size_str = require("Block Size")
    if block_size_str != "04":
        raise NfcParseError("Block Size must be 04", f"Block Size: {block_size_str}")
    block_size = int(block_size_str, 16)

    data_line = require("Data Content")
    data_bytes = _parse_hex_bytes(data_line, "Data Content", f"Data Content: {data_line}")
    if len(data_bytes) != 32:
        raise NfcParseError("Data Content must be 32 bytes", f"Data Content: {data_line}")

    blocks = [data_bytes[i : i + 4].hex().upper() for i in range(0, 32, 4)]

    privacy_mode = raw.get("Privacy Mode")
    if privacy_mode == "true":
        import sys

        print(f"warning: {path}: Privacy Mode is true", file=sys.stderr)

    return TonieTag(
        path=path,
        uid=uid_bytes.hex().upper(),
        uid_bytes=uid_bytes,
        blocks=blocks,
        block_count=block_count,
        block_size=block_size,
        device_type=device_type,
        raw=raw,
    )
