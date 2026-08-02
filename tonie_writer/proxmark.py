"""Locate and invoke the Proxmark3 `pm3` client, and parse its text output.

All parsing helpers are pure functions over strings so they can be unit-tested
without hardware attached.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

BLOCK_HEX_RE = re.compile(r"^[0-9A-F]{8}$")
UID_HEX_RE = re.compile(r"^[0-9A-F]{16}$")


class ProxmarkError(RuntimeError):
    pass


class ProxmarkNotFoundError(ProxmarkError):
    pass


class ProxmarkTimeoutError(ProxmarkError):
    pass


def locate_pm3() -> str | None:
    """Return the path to the pm3 client, preferring `pm3` over `proxmark3`."""
    return shutil.which("pm3") or shutil.which("proxmark3")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


@dataclass(frozen=True)
class Pm3Result:
    stdout: str
    stderr: str
    returncode: int


def run(
    commands: list[str],
    port: str | None = None,
    timeout: float = 60,
    pm3_bin: str | None = None,
) -> Pm3Result:
    """Run one or more `hf 15 ...` commands in a single pm3 session.

    Never builds a shell string: argv is a list, and the only interpolated
    values (hex strings, block numbers) are generated and validated by the
    caller before reaching here.
    """
    binary = pm3_bin or locate_pm3()
    if not binary:
        raise ProxmarkNotFoundError(
            "Could not find 'pm3' or 'proxmark3' on PATH. "
            "See docs/HARDWARE.md for installation instructions."
        )

    argv = [binary]
    if port:
        argv += ["-p", port]
    argv += ["-c", ";".join(commands)]

    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ProxmarkTimeoutError(
            "Proxmark3 did not respond in time — is another pm3 session open, "
            "or is the device unplugged?"
        ) from exc
    except FileNotFoundError as exc:
        raise ProxmarkNotFoundError(f"Could not execute '{binary}': {exc}") from exc

    return Pm3Result(
        stdout=strip_ansi(proc.stdout or ""),
        stderr=strip_ansi(proc.stderr or ""),
        returncode=proc.returncode,
    )


def validate_block_hex(data_hex: str) -> str:
    """Uppercase and validate an 8-hex-char (4-byte) block value."""
    data_hex = data_hex.upper()
    if not BLOCK_HEX_RE.fullmatch(data_hex):
        raise ValueError(f"Invalid block data (expected 8 hex chars): {data_hex!r}")
    return data_hex


def validate_block_number(block: int) -> int:
    if not (0 <= block <= 7):
        raise ValueError(f"Invalid block number (expected 0-7): {block!r}")
    return block


def build_wrbl_command(block: int, data_hex: str, option: bool = False) -> str:
    """`hf 15 wrbl` for one 4-byte block. `option=True` sets the OPTION flag
    (0x42) retry variant used after a plain write (0x02) fails."""
    block = validate_block_number(block)
    data_hex = validate_block_hex(data_hex)
    flag = " -o" if option else ""
    return f"hf 15 wrbl --ua{flag} -b {block} -d {data_hex}"


def build_rdbl_command(block: int) -> str:
    block = validate_block_number(block)
    return f"hf 15 rdbl --ua -b {block}"


def build_uid_frames(uid_bytes: bytes) -> tuple[str, str]:
    """The two safe raw magic-UID frames from plan §4.4. Never `csetuid`.

    Each half is sent reversed (the card stores the UID LSB-first):
      high frame (0x40): uid[7] uid[6] uid[5] uid[4]
      low  frame (0x41): uid[3] uid[2] uid[1] uid[0]
    """
    if len(uid_bytes) != 8:
        raise ValueError(f"UID must be 8 bytes, got {len(uid_bytes)}")
    high = bytes([uid_bytes[7], uid_bytes[6], uid_bytes[5], uid_bytes[4]])
    low = bytes([uid_bytes[3], uid_bytes[2], uid_bytes[1], uid_bytes[0]])
    frame_high = "hf 15 raw -acw -d 02E00940" + high.hex().upper()
    frame_low = "hf 15 raw -acw -d 02E00941" + low.hex().upper()
    return frame_high, frame_low


def parse_info_uid(output: str) -> str | None:
    """Extract the UID (16 hex chars, no spaces, uppercase) from `hf 15 info`
    output. Returns None if no UID line is found."""
    output = strip_ansi(output)
    match = re.search(
        r"UID[^0-9A-Fa-f]*((?:[0-9A-Fa-f]{2}[\s:]*){8})",
        output,
    )
    if not match:
        return None
    hex_only = re.sub(r"[^0-9A-Fa-f]", "", match.group(1)).upper()
    if len(hex_only) != 16:
        return None
    return hex_only


def parse_rdbl_data(output: str, block: int) -> str | None:
    """Extract the 4-byte value (8 hex chars, uppercase) for `block` from
    `hf 15 rdbl` output. Returns None if the block's line can't be found or
    parsed — callers must treat that as inconclusive, not a mismatch."""
    output = strip_ansi(output)
    block = validate_block_number(block)
    pattern = re.compile(
        rf"(?m)^\s*(?:\[[=+!]\]\s*)?0*{block}\s*[:|]\s*((?:[0-9A-Fa-f]{{2}}[\s.]*){{4}})"
    )
    match = pattern.search(output)
    if not match:
        return None
    hex_only = re.sub(r"[^0-9A-Fa-f]", "", match.group(1)).upper()
    if len(hex_only) != 8:
        return None
    return hex_only


def parse_dump_blocks(output: str, block_count: int = 8) -> dict[int, str]:
    """Parse all blocks out of a multi-line dump/rdbl transcript. Blocks that
    can't be parsed are simply absent from the result (defensive, non-fatal)."""
    blocks: dict[int, str] = {}
    for block in range(block_count):
        value = parse_rdbl_data(output, block)
        if value is not None:
            blocks[block] = value
    return blocks
