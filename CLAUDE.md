# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this repo is

A catalog of Toniebox NFC dumps plus a CLI that writes one of them to a magic SLIX-L
tag using a Proxmark3. `data/tonies/` mirrors
[nortakales/flipper-zero-tonies](https://github.com/nortakales/flipper-zero-tonies)
nightly; `TONIES.md` and `data/tonies.json` are rendered from it.

## The task you will usually be asked to do

> "Write <some Tonie> to the tag."

That is one command. Do not write Python, do not call `pm3` yourself:

```sh
./tonie write "Zuma"
```

Resolve ambiguity first rather than guessing — several Tonies share a name across
languages:

```sh
./tonie --json search "zuma"        # ranked matches with scores
./tonie write "Zuma" --language German
./tonie write "Zuma" --pick 1
```

If the query matches nothing, `search` prints suggestions; ask the user which one they
meant instead of picking for them. `write` prompts for confirmation before touching the
tag — let that prompt reach the user; only pass `--yes` when they have already confirmed
the exact Tonie in the conversation.

Preview without touching hardware: `./tonie write "Zuma" --dry-run`.

## Hard rules — violating these destroys hardware

1. **Never run `hf 15 csetuid`, with or without `--v2`.** The `--v2` path sends the Gen2
   layout command `02 E0 09 47 …`, which **permanently bricks magic SLIX-L tags**. The
   UID is written with two raw frames instead; `tonie_writer/proxmark.py` already does
   this correctly. See "Why this repo never calls `csetuid`" in `docs/HARDWARE.md`.
2. **Data blocks are written before the UID.** Once the tag carries a foreign UID the
   blocks may no longer be writable. Do not reorder.
3. **Block writes are non-addressed** (`hf 15 wrbl --ua`, flags `0x02`, retry with `-o`
   = `0x42`). `-*` means "scan, then write addressed" and is not the verified sequence.
4. **Never write SLIX passwords or enable privacy mode** (`slixwritepwd`,
   `passprotectafi`, `passprotecteas`). These are irreversible and are not needed —
   genuine Tonie dumps have `Privacy Mode: false`.

If a change seems to require breaking one of these, stop and ask.

## Commands

| Command | Purpose |
|---------|---------|
| `./tonie write "<name>"` | write a Tonie to the tag on the reader |
| `./tonie search "<query>"` | ranked matches (add global `--json` before the subcommand) |
| `./tonie info "<query>"` | UID, series, language, all 8 blocks |
| `./tonie read` | read the tag on the reader and identify it |
| `./tonie doctor` | environment + hardware check; `--probe-magic` tests UID writability |
| `./tonie list --language German` | browse the catalog |
| `./tonie index` | regenerate `data/tonies.json` + `TONIES.md` |

Exit codes: `0` ok · `2` resolution · `3` missing tooling · `4` no tag · `5` UID write
failed · `6` verification failed.

## Generated files — never hand-edit

`data/tonies/**`, `data/tonies.json`, `data/UPSTREAM.json`, `TONIES.md`. They are
rebuilt by `scripts/sync_upstream.sh` + `scripts/build_index.py` in the nightly
workflow. To change how they look, edit the generator and run `./tonie index`.

## Development

```sh
python3 -m unittest discover -s tests      # 57 tests, no hardware or network needed
```

Python standard library only — do not add dependencies. The tool must work on a fresh
`git clone` with nothing but macOS system Python.

## Hardware context

Stock (unmodified) Toniebox, Proxmark3 Easy "512M" with Iceman firmware on macOS ARM,
and magic SLIX-L tags with changeable UID from rfidfriend.com. Plain SLIX, ICODE SLI,
SLIX2 and TAG-it tags cannot drive a stock box — see `docs/HARDWARE.md` before
suggesting the user buy anything.
