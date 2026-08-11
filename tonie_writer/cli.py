"""Command-line entry point for the Tonie -> NFC tag writer."""

from __future__ import annotations

import argparse
import json as jsonlib
import subprocess
import sys
from pathlib import Path

from tonie_writer import catalog, proxmark, writer
from tonie_writer.nfcfile import NfcParseError, parse_nfc_file

REPO_ROOT = Path(__file__).resolve().parent.parent

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_RESOLUTION = 2
EXIT_MISSING_TOOL = 3
EXIT_NO_TAG = 4
EXIT_UID_WRITE_FAILED = 5
EXIT_VERIFY_FAILED = 6

UID_WRITE_FAILURE_EXPLANATION = """\
The UID write did not take. This almost always means the tag is not a
magic SLIX-L with a changeable UID:
  - A genuine (fixed-UID) tag physically cannot have its UID changed by any
    reader, Proxmark3 included.
  - A generic "magic ISO 15693 / SLI / SLIX" tag accepts the UID write but
    is the wrong chip class and will not satisfy a stock Toniebox anyway.
You need a magic SLIX-L tag with changeable UID (e.g. from rfidfriend.com).
Run './tonie doctor --probe-magic' to check which kind of tag this is.
See docs/HARDWARE.md for details."""

UID_HALF_WRITTEN_EXPLANATION = """\
Only one half of the UID took — this IS a magic tag, the write was
interrupted. Each half is written by its own frame, and the tag drops the
pending half if the RF field goes down in between.
Retry the write; keep the tag flat on the antenna and don't move it.
If it keeps happening, run the two frames by hand in one pm3 session —
'./tonie write "<name>" --dry-run' prints them.
The tag is not damaged — it is simply carrying a half-finished UID until
the next successful write."""


def _load_catalog_or_exit() -> list[catalog.CatalogEntry]:
    try:
        return catalog.load_catalog()
    except catalog.CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_RESOLUTION)


def _format_candidate(entry: catalog.CatalogEntry) -> str:
    return f"{entry.name}  ({entry.language} / {entry.series})"


def _print_candidates(candidates: list[catalog.CatalogEntry], file=sys.stdout) -> None:
    for i, entry in enumerate(candidates, start=1):
        print(f"  {i}. {_format_candidate(entry)}", file=file)


def _resolve_or_exit(
    entries: list[catalog.CatalogEntry],
    query: str,
    language: str | None,
    pick: int | None,
    non_interactive: bool,
) -> catalog.CatalogEntry:
    result = catalog.resolve(entries, query, language=language, pick=pick)

    if result.outcome == "single":
        return result.entry

    if result.outcome == "none":
        print(f"error: no Tonie found matching {query!r}", file=sys.stderr)
        if result.suggestions:
            print("Did you mean:", file=sys.stderr)
            _print_candidates(result.suggestions, file=sys.stderr)
        raise SystemExit(EXIT_RESOLUTION)

    print(f"Multiple Tonies match {query!r}:", file=sys.stderr)
    _print_candidates(result.candidates, file=sys.stderr)

    if not non_interactive and sys.stdin.isatty():
        while True:
            try:
                choice = input(f"Pick 1-{len(result.candidates)}: ").strip()
            except EOFError:
                break
            if choice.isdigit() and 1 <= int(choice) <= len(result.candidates):
                return result.candidates[int(choice) - 1]
            print("Invalid selection.", file=sys.stderr)

    print("Use --pick N or a more specific query.", file=sys.stderr)
    raise SystemExit(EXIT_RESOLUTION)


def _format_uid(uid: str) -> str:
    return " ".join(uid[i : i + 2] for i in range(0, len(uid), 2))


def _entry_path(entry: catalog.CatalogEntry) -> Path:
    return REPO_ROOT / entry.path


# --------------------------------------------------------------------------
# tonie list
# --------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    entries = _load_catalog_or_exit()

    if args.language:
        from tonie_writer.normalize import normalize

        lang_norm = normalize(args.language)
        entries = [e for e in entries if normalize(e.language).startswith(lang_norm)]

    if args.series:
        needle = args.series.lower()
        entries = [e for e in entries if needle in e.series.lower()]

    entries.sort(key=lambda e: (e.language, e.series, e.name))

    if args.limit:
        entries = entries[: args.limit]

    if args.json:
        print(jsonlib.dumps([e.__dict__ for e in entries], indent=2, ensure_ascii=False))
        return EXIT_OK

    if not entries:
        print("No Tonies match the given filters.")
        return EXIT_OK

    for e in entries:
        print(f"{e.language:8} {e.series:40.40} {e.name:30.30} {_format_uid(e.uid)}")
    return EXIT_OK


# --------------------------------------------------------------------------
# tonie search
# --------------------------------------------------------------------------


def cmd_search(args: argparse.Namespace) -> int:
    entries = _load_catalog_or_exit()
    results = catalog.search(entries, args.query, language=args.language)

    if args.limit:
        results = results[: args.limit]

    if args.json:
        payload = [
            {"score": round(r.score, 3), "tier": r.tier, **r.entry.__dict__}
            for r in results
        ]
        print(jsonlib.dumps(payload, indent=2, ensure_ascii=False))
        return EXIT_OK

    if not results:
        print(f"No matches for {args.query!r}.")
        return EXIT_OK

    for r in results:
        print(f"[{r.score:.2f}] {_format_candidate(r.entry)}  {_format_uid(r.entry.uid)}")
    return EXIT_OK


# --------------------------------------------------------------------------
# tonie info
# --------------------------------------------------------------------------


def cmd_info(args: argparse.Namespace) -> int:
    entries = _load_catalog_or_exit()
    entry = _resolve_or_exit(entries, args.query, args.language, args.pick, args.yes)

    try:
        tag = parse_nfc_file(_entry_path(entry))
    except (NfcParseError, OSError) as exc:
        print(f"error: could not parse {entry.path}: {exc}", file=sys.stderr)
        return EXIT_UNEXPECTED

    if args.json:
        payload = {**entry.__dict__, "blocks": tag.blocks}
        print(jsonlib.dumps(payload, indent=2, ensure_ascii=False))
        return EXIT_OK

    print(f"Name    : {entry.name}")
    print(f"Series  : {entry.series}")
    print(f"Language: {entry.language}")
    print(f"UID     : {_format_uid(entry.uid)}")
    print(f"Path    : {entry.path}")
    print("Blocks  :")
    for i, block in enumerate(tag.blocks):
        print(f"  {i}: {block}")
    return EXIT_OK


# --------------------------------------------------------------------------
# tonie write
# --------------------------------------------------------------------------


def cmd_write(args: argparse.Namespace) -> int:
    entries = _load_catalog_or_exit()
    entry = _resolve_or_exit(entries, args.query, args.language, args.pick, args.yes)

    try:
        tag = parse_nfc_file(_entry_path(entry))
    except (NfcParseError, OSError) as exc:
        print(f"error: could not parse {entry.path}: {exc}", file=sys.stderr)
        return EXIT_UNEXPECTED

    options = writer.WriteOptions(
        uid_only=args.uid_only,
        blocks_only=args.blocks_only,
        no_verify=args.no_verify,
        retries=args.retries,
        port=args.port,
        verbose=args.verbose,
    )

    if args.dry_run:
        for cmd in writer.plan_write_commands(tag, options):
            print(cmd)
        return EXIT_OK

    pm3_bin = proxmark.locate_pm3()
    if not pm3_bin:
        print(
            "error: could not find 'pm3' or 'proxmark3' on PATH. "
            "See docs/HARDWARE.md for installation instructions.",
            file=sys.stderr,
        )
        return EXIT_MISSING_TOOL
    options.pm3_bin = pm3_bin

    current_uid = writer.read_tag_uid(options)
    if current_uid is None:
        print("error: no tag detected. Place the tag on the Proxmark3 antenna and try again.", file=sys.stderr)
        return EXIT_NO_TAG

    if current_uid == tag.uid and not options.uid_only:
        print(f"Tag already carries the target UID ({_format_uid(tag.uid)}); writing data blocks only.")
        options.blocks_only = True

    if not tag.uid.startswith("E00403"):
        print(f"WARNING: target UID {_format_uid(tag.uid)} does not start with E0 04 03 (unexpected for upstream data).")

    print(f"Tonie   : {entry.name}  ({entry.language} / {entry.series})")
    print(f"Source  : {entry.path}")
    if not options.blocks_only:
        print(f"New UID : {_format_uid(tag.uid)}")
    if not options.uid_only:
        print("Blocks  : 8 x 4 bytes will be overwritten")
    print(f"Tag now : {_format_uid(current_uid)}" + ("   <- will be permanently replaced" if current_uid != tag.uid else ""))

    if not args.yes:
        try:
            answer = input("Proceed? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer != "y":
            print("Aborted.")
            return EXIT_UNEXPECTED

    report = writer.write_tag(tag, options)

    if report.uid_result is not None and not report.uid_result.ok:
        reason = writer.classify_uid_failure(
            tag.uid, report.uid_result.read_back_uid, current_uid
        )
        if report.uid_result.read_back_uid:
            print(
                f"Tag reads : {_format_uid(report.uid_result.read_back_uid)} "
                f"(expected {_format_uid(tag.uid)})",
                file=sys.stderr,
            )
        if reason.startswith("half-written"):
            print(UID_HALF_WRITTEN_EXPLANATION, file=sys.stderr)
        else:
            print(UID_WRITE_FAILURE_EXPLANATION, file=sys.stderr)
        return EXIT_UID_WRITE_FAILED

    if not report.verified_ok:
        print(f"MISMATCH writing {entry.name!r}:", file=sys.stderr)
        if report.verify_result and report.verify_result.uid_ok is False:
            print(f"  UID    : mismatch (expected {_format_uid(tag.uid)})", file=sys.stderr)
        if report.verify_result:
            for block, ok in report.verify_result.block_ok.items():
                if ok is False:
                    print(f"  block {block}: mismatch (expected {tag.blocks[block]})", file=sys.stderr)
        return EXIT_VERIFY_FAILED

    print(f"✅ Wrote {entry.name!r} to tag {_format_uid(tag.uid)}")
    if report.verify_result is not None:
        uid_status = "ok" if report.verify_result.uid_ok else "inconclusive"
        block_matches = sum(1 for v in report.verify_result.block_ok.values() if v)
        block_inconclusive = sum(1 for v in report.verify_result.block_ok.values() if v is None)
        print(f"  UID    : {uid_status}")
        suffix = f" ({block_inconclusive} inconclusive)" if block_inconclusive else ""
        print(f"  Blocks : {block_matches}/8 ok{suffix}")
    return EXIT_OK


# --------------------------------------------------------------------------
# tonie read
# --------------------------------------------------------------------------


def cmd_read(args: argparse.Namespace) -> int:
    pm3_bin = proxmark.locate_pm3()
    if not pm3_bin:
        print("error: could not find 'pm3' or 'proxmark3' on PATH.", file=sys.stderr)
        return EXIT_MISSING_TOOL

    info = proxmark.run(["hf 15 info"], port=args.port, pm3_bin=pm3_bin)
    uid = proxmark.parse_info_uid(info.stdout)
    if uid is None:
        print("error: no tag detected. Place the tag on the Proxmark3 antenna and try again.", file=sys.stderr)
        return EXIT_NO_TAG

    blocks = {}
    for block in range(8):
        result = proxmark.run([proxmark.build_rdbl_command(block)], port=args.port, pm3_bin=pm3_bin)
        blocks[block] = proxmark.parse_rdbl_data(result.stdout, block)

    print(f"UID: {_format_uid(uid)}")
    for block in range(8):
        value = blocks[block] or "?"
        print(f"  {block}: {value}")

    entries = catalog.load_catalog() if catalog.DEFAULT_CATALOG_PATH.exists() else []
    matches = [e for e in entries if e.uid == uid]
    if matches:
        e = matches[0]
        print(f"This is {e.name!r} ({e.language} / {e.series})")
    else:
        print("This UID is not in the local catalog.")

    if args.json:
        print(jsonlib.dumps({"uid": uid, "blocks": blocks}, indent=2, ensure_ascii=False))
    return EXIT_OK


# --------------------------------------------------------------------------
# tonie doctor
# --------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    all_ok = True

    if sys.version_info >= (3, 9):
        print(f"✅ python3 {sys.version.split()[0]}")
    else:
        print(f"❌ python3 {sys.version.split()[0]} (need >= 3.9)")
        all_ok = False

    pm3_bin = proxmark.locate_pm3()
    if pm3_bin:
        print(f"✅ pm3 client found: {pm3_bin}")
    else:
        print("❌ pm3/proxmark3 not found on PATH — see docs/HARDWARE.md")
        all_ok = False

    if pm3_bin:
        try:
            version = subprocess.run([pm3_bin, "--version"], capture_output=True, text=True, timeout=15)
            first_line = (version.stdout or version.stderr or "").splitlines()[0] if (version.stdout or version.stderr) else ""
            print(f"✅ pm3 --version: {first_line.strip()}")
        except Exception as exc:  # subprocess/timeout errors: report, don't crash doctor
            print(f"⚠️  could not run 'pm3 --version': {exc}")

    try:
        info = proxmark.run(["hf 15 info"], port=args.port, pm3_bin=pm3_bin, timeout=15)
        uid = proxmark.parse_info_uid(info.stdout)
        if uid:
            prefix = uid[:6]
            if prefix == "E00403":
                print(f"✅ tag present, UID {_format_uid(uid)} (SLIX-L, Toniebox-compatible prefix)")
            elif prefix == "E00402":
                print(f"⚠️  tag present, UID {_format_uid(uid)} (plain SLIX — stock box will not accept this)")
            else:
                print(f"⚠️  tag present, UID {_format_uid(uid)} (unrecognized prefix)")
        else:
            print("⚠️  no tag detected on the antenna")
    except proxmark.ProxmarkError as exc:
        print(f"⚠️  could not query the tag: {exc}")
        uid = None

    if args.probe_magic:
        if not pm3_bin:
            print("❌ cannot probe: no pm3 client found")
            all_ok = False
        else:
            print(
                "About to write a test UID (E0 04 03 00 00 00 00 01) to the tag on the "
                "antenna to determine whether it is a magic tag."
            )
            if uid is None:
                print("⚠️  current UID could not be read — it may not be restorable after this probe.")
            try:
                confirm = input("Proceed with magic-UID probe? [y/N] ").strip().lower()
            except EOFError:
                confirm = ""
            if confirm == "y":
                test_uid = bytes.fromhex("E004030000000001")
                frames = list(proxmark.build_uid_frames(test_uid))
                proxmark.run(frames, port=args.port, pm3_bin=pm3_bin)
                check = proxmark.run(["hf 15 info"], port=args.port, pm3_bin=pm3_bin)
                new_uid = proxmark.parse_info_uid(check.stdout)
                if new_uid == test_uid.hex().upper():
                    print("✅ magic write succeeded — this is a magic tag.")
                    if uid:
                        orig = list(proxmark.build_uid_frames(bytes.fromhex(uid)))
                        proxmark.run(orig, port=args.port, pm3_bin=pm3_bin)
                        print(f"Restored original UID {_format_uid(uid)}.")
                else:
                    print("❌ UID unchanged — this tag's UID cannot be written (fixed-UID tag).")
            else:
                print("Probe skipped.")

    catalog_path = catalog.DEFAULT_CATALOG_PATH
    if catalog_path.exists():
        try:
            entries = catalog.load_catalog()
            print(f"✅ catalog present: {len(entries)} Tonies")
        except catalog.CatalogError as exc:
            print(f"❌ catalog present but unparseable: {exc}")
            all_ok = False
    else:
        print(f"❌ catalog not found at {catalog_path} — run './tonie index'")
        all_ok = False

    return EXIT_OK if all_ok else EXIT_UNEXPECTED


# --------------------------------------------------------------------------
# tonie index
# --------------------------------------------------------------------------


def cmd_index(args: argparse.Namespace) -> int:
    result = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "build_index.py")])
    return result.returncode


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tonie", description="Tonie -> NFC tag writer")
    parser.add_argument("--port", help="Proxmark3 serial device (default: auto-detect)")
    parser.add_argument("--json", action="store_true", help="machine-readable output where meaningful")
    parser.add_argument("--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="print the catalog")
    p_list.add_argument("--language")
    p_list.add_argument("--series")
    p_list.add_argument("--limit", type=int)
    p_list.set_defaults(func=cmd_list)

    p_search = sub.add_parser("search", help="ranked search over the catalog")
    p_search.add_argument("query")
    p_search.add_argument("--language")
    p_search.add_argument("--limit", type=int)
    p_search.set_defaults(func=cmd_search)

    p_info = sub.add_parser("info", help="show details for a resolved Tonie")
    p_info.add_argument("query")
    p_info.add_argument("--language")
    p_info.add_argument("--pick", type=int)
    p_info.add_argument("--yes", action="store_true")
    p_info.set_defaults(func=cmd_info)

    p_write = sub.add_parser("write", help="write a Tonie to the tag on the reader")
    p_write.add_argument("query")
    p_write.add_argument("--language")
    p_write.add_argument("--pick", type=int)
    p_write.add_argument("--dry-run", action="store_true")
    p_write.add_argument("--yes", action="store_true")
    p_write.add_argument("--uid-only", action="store_true")
    p_write.add_argument("--blocks-only", action="store_true")
    p_write.add_argument("--no-verify", action="store_true")
    p_write.add_argument("--retries", type=int, default=2)
    p_write.set_defaults(func=cmd_write)

    p_read = sub.add_parser("read", help="read the tag on the reader")
    p_read.set_defaults(func=cmd_read)

    p_doctor = sub.add_parser("doctor", help="environment + hardware check")
    p_doctor.add_argument("--probe-magic", action="store_true")
    p_doctor.set_defaults(func=cmd_doctor)

    p_index = sub.add_parser("index", help="regenerate data/tonies.json + TONIES.md")
    p_index.set_defaults(func=cmd_index)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        return EXIT_UNEXPECTED
    except proxmark.ProxmarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_MISSING_TOOL


if __name__ == "__main__":
    raise SystemExit(main())
