"""Orchestrate writing a TonieTag to a tag on the Proxmark3, and verifying it.

Every function that talks to the device takes a `run_fn` (defaulting to
proxmark.run) so the orchestration logic can be unit-tested without hardware.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from tonie_writer import proxmark
from tonie_writer.nfcfile import TonieTag

RunFn = Callable[..., proxmark.Pm3Result]


@dataclass
class WriteOptions:
    uid_only: bool = False
    blocks_only: bool = False
    no_verify: bool = False
    retries: int = 2
    port: str | None = None
    verbose: bool = False
    pm3_bin: str | None = None


@dataclass
class BlockWriteResult:
    block: int
    ok: bool
    attempts: int


@dataclass
class UidWriteResult:
    ok: bool
    read_back_uid: str | None
    attempts: int


@dataclass
class VerifyResult:
    uid_ok: bool | None  # None = inconclusive (unparseable pm3 output)
    block_ok: dict[int, bool | None]


@dataclass
class WriteReport:
    tag: TonieTag
    block_results: list[BlockWriteResult] = field(default_factory=list)
    uid_result: UidWriteResult | None = None
    verify_result: VerifyResult | None = None

    @property
    def blocks_ok(self) -> bool:
        return all(r.ok for r in self.block_results)

    @property
    def uid_ok(self) -> bool:
        return self.uid_result is None or self.uid_result.ok

    @property
    def verified_ok(self) -> bool:
        if self.verify_result is None:
            return True
        if self.verify_result.uid_ok is False:
            return False
        return all(v is not False for v in self.verify_result.block_ok.values())

    @property
    def ok(self) -> bool:
        return self.blocks_ok and self.uid_ok and self.verified_ok


def plan_write_commands(tag: TonieTag, options: WriteOptions) -> list[str]:
    """The exact, ordered pm3 command list a real write would send.

    Data blocks are written before the UID: once the tag carries a foreign
    UID, the blocks may no longer be writable. Never reorder this.
    """
    commands: list[str] = []
    if not options.uid_only:
        for block, data in enumerate(tag.blocks):
            commands.append(proxmark.build_wrbl_command(block, data))
    if not options.blocks_only:
        commands.extend(proxmark.build_uid_frames(tag.uid_bytes))
    return commands


def read_tag_uid(options: WriteOptions, run_fn: RunFn = proxmark.run) -> str | None:
    result = run_fn(["hf 15 info"], port=options.port, pm3_bin=options.pm3_bin)
    return proxmark.parse_info_uid(result.stdout)


def write_blocks(
    tag: TonieTag,
    options: WriteOptions,
    run_fn: RunFn = proxmark.run,
) -> list[BlockWriteResult]:
    """Write all 8 data blocks. Batched into one invocation first; on failure
    (or under --verbose) falls back to one command per block, retrying each
    with the OPTION flag (0x42) up to `options.retries` times."""
    commands = [proxmark.build_wrbl_command(b, tag.blocks[b]) for b in range(8)]
    batch_result = run_fn(commands, port=options.port, pm3_bin=options.pm3_bin)

    if batch_result.returncode == 0 and not options.verbose:
        return [BlockWriteResult(block=b, ok=True, attempts=1) for b in range(8)]

    results = []
    for block in range(8):
        ok = False
        attempts = 0
        for attempt in range(1, options.retries + 1):
            attempts = attempt
            cmd = proxmark.build_wrbl_command(block, tag.blocks[block], option=attempt > 1)
            result = run_fn([cmd], port=options.port, pm3_bin=options.pm3_bin)
            if result.returncode == 0:
                ok = True
                break
        results.append(BlockWriteResult(block=block, ok=ok, attempts=attempts))
    return results


def write_uid(
    tag: TonieTag,
    options: WriteOptions,
    run_fn: RunFn = proxmark.run,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> UidWriteResult:
    """Write the target UID using the two safe raw frames — never csetuid.
    Both frames go into a single pm3 session so the field stays up between
    them (`-k`); a power cycle in between can leave the UID half-written.
    Confirms via `hf 15 info` read-back, which is the only success signal
    these raw frames give. Retries up to 3 times with a short delay."""
    frames = list(proxmark.build_uid_frames(tag.uid_bytes))
    read_back: str | None = None
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        run_fn(frames, port=options.port, pm3_bin=options.pm3_bin)
        info = run_fn(["hf 15 info"], port=options.port, pm3_bin=options.pm3_bin)
        read_back = proxmark.parse_info_uid(info.stdout)
        if read_back == tag.uid:
            return UidWriteResult(ok=True, read_back_uid=read_back, attempts=attempt)
        if attempt < max_attempts:
            sleep_fn(0.5)
    return UidWriteResult(ok=False, read_back_uid=read_back, attempts=max_attempts)


def classify_uid_failure(
    target_uid: str,
    read_back: str | None,
    previous_uid: str | None = None,
) -> str:
    """Why did the UID write fail? The two halves are written by separate
    frames, so a half-written UID is a distinct — and very informative —
    outcome from a UID that never moved.

    `previous_uid` (what the tag read before the write) breaks a tie the
    halves alone cannot: every SLIX-L UID starts with `E0 04 03 50`, so a
    matching first half proves nothing on its own.

    Returns one of: "half-written-first", "half-written-last", "unchanged",
    "unknown" (nothing could be read back).
    """
    if read_back is None:
        return "unknown"
    target_uid = target_uid.upper()
    read_back = read_back.upper()
    if previous_uid and read_back == previous_uid.upper():
        return "unchanged"
    first_ok = read_back[:8] == target_uid[:8]
    last_ok = read_back[8:] == target_uid[8:]
    if last_ok and not first_ok:
        return "half-written-first"
    if first_ok and not last_ok:
        return "half-written-last"
    return "unchanged"


def verify(
    tag: TonieTag,
    options: WriteOptions,
    run_fn: RunFn = proxmark.run,
) -> VerifyResult:
    info = run_fn(["hf 15 info"], port=options.port, pm3_bin=options.pm3_bin)
    uid_read = proxmark.parse_info_uid(info.stdout)
    uid_ok = None if uid_read is None else (uid_read == tag.uid)

    block_ok: dict[int, bool | None] = {}
    for block in range(8):
        cmd = proxmark.build_rdbl_command(block)
        result = run_fn([cmd], port=options.port, pm3_bin=options.pm3_bin)
        value = proxmark.parse_rdbl_data(result.stdout, block)
        block_ok[block] = None if value is None else (value == tag.blocks[block])

    return VerifyResult(uid_ok=uid_ok, block_ok=block_ok)


def write_tag(
    tag: TonieTag,
    options: WriteOptions,
    run_fn: RunFn = proxmark.run,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> WriteReport:
    """Full write flow: blocks first, then UID, then verify (unless disabled)."""
    report = WriteReport(tag=tag)

    if not options.uid_only:
        report.block_results = write_blocks(tag, options, run_fn=run_fn)

    if not options.blocks_only:
        report.uid_result = write_uid(tag, options, run_fn=run_fn, sleep_fn=sleep_fn)

    if not options.no_verify and (report.uid_result is None or report.uid_result.ok):
        report.verify_result = verify(tag, options, run_fn=run_fn)

    return report
