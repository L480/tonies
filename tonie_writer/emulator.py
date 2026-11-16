"""Convert Tonie dumps to Proxmark3 emulator images and start tag simulation."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from tonie_writer import proxmark
from tonie_writer.nfcfile import TonieTag


def build_image(tag: TonieTag) -> dict:
    """Use PM3's portable ISO15693 v4 JSON format, rather than a packed struct.

    v4 supports these eight-block tags on both older clients and clients that
    upgrade v4 to v5. The stored UID is in transmission order (LSB first).
    """
    def hex_field(name: str, default: str, size: int) -> str:
        value = bytes.fromhex(tag.raw.get(name, default))
        if len(value) != size:
            raise ValueError(f"{name} must contain {size} bytes")
        return value.hex().upper()

    def lock_field(name: str) -> str:
        value = tag.raw.get(name, "false")
        if value not in ("true", "false"):
            raise ValueError(f"{name} must be true or false")
        return "01" if value == "true" else "00"

    if tag.raw.get("Privacy Mode", "false") != "false":
        raise ValueError("Emulation requires a dump with Privacy Mode: false")

    return {
        "Created": "tonie",
        "FileType": "15693 v4",
        "Card": {
            "uid": tag.uid_bytes[::-1].hex().upper(),
            "dsfid": hex_field("DSFID", "00", 1),
            "dsfidlock": lock_field("Lock DSFID"),
            "afi": hex_field("AFI", "00", 1),
            "afilock": lock_field("Lock AFI"),
            "bytesperpage": "04",
            "pagescount": "08",
            "ic": hex_field("IC Reference", "03", 1),
            "locks": hex_field("Security Status", "00 " * 8, 8),
            "random": "0000",
            "privacypasswd": hex_field("Password Privacy", "0F 0F 0F 0F", 4),
            "state": "00",
        },
        "blocks": {str(i): block for i, block in enumerate(tag.blocks)},
    }


def load_command(path: Path) -> str:
    # PM3 parses a second command language inside argv's -c value. Shell
    # escaping alone would not protect its semicolon-separated commands.
    value = str(path)
    if any(c in value for c in ('"', ';', '\n', '\r', '\\')):
        raise ValueError("Emulator image path contains unsupported command characters")
    return f'hf 15 eload -f "{value}"'


def emulate(tag: TonieTag, port: str | None = None, verbose: bool = False) -> None:
    image = build_image(tag)
    binary = proxmark.locate_pm3()
    if not binary:
        raise proxmark.ProxmarkNotFoundError("Could not find 'pm3' or 'proxmark3' on PATH.")

    with tempfile.TemporaryDirectory(prefix="tonie-emulate-") as directory:
        path = Path(directory) / "tag.json"
        path.write_text(json.dumps(image), encoding="utf-8")
        result = proxmark.run([load_command(path)], port=port, pm3_bin=binary)
        if verbose:
            print(result.stdout, end="")
            print(result.stderr, end="")
        # Some PM3 clients exit zero even when the command failed. Do not
        # simulate stale emulator memory unless the upload was confirmed.
        if result.returncode or not re.search(
            r"uploaded\s+\d+\s+bytes to emulator memory", result.stdout, re.IGNORECASE
        ):
            detail = (result.stdout + result.stderr).strip()
            raise proxmark.ProxmarkError(f"Emulator upload was not confirmed.\n{detail}")

    print("Image loaded. Place the Proxmark3 HF antenna against the Toniebox reader.", flush=True)
    print("Press the Proxmark3 hardware button to stop emulation.", flush=True)
    result = proxmark.run_live(["hf 15 sim"], port=port, pm3_bin=binary)
    if result.returncode or "Done!" not in result.stdout:
        raise proxmark.ProxmarkError("Proxmark3 did not confirm completion of tag emulation.")
