# Workflow: how the catalog stays up to date

## What's generated vs. hand-written

| Path | Generated? | Notes |
|---|:---:|---|
| `data/tonies/**/*.nfc` | ✅ | Mirrored 1:1 from upstream. Never edit by hand — the nightly sync deletes anything not present upstream. |
| `data/UPSTREAM.json` | ✅ | Provenance: upstream repo, branch, commit SHA, commit date, sync timestamp, file count. |
| `data/tonies.json` | ✅ | Search index built from `data/tonies/`. |
| `TONIES.md` | ✅ | Human-readable catalog built from the same data. |
| Everything else (`tonie_writer/`, `scripts/`, `docs/`, `./tonie`, `tests/`) | ❌ | Hand-written. |

All generated paths are marked `linguist-generated=true` in
`.gitattributes` so they collapse in GitHub diffs by default.

## The `.nfc` file format

The mirrored dumps are Flipper Zero NFC device files (v4, `Device type: SLIX`).
`tonie_writer/nfcfile.py` parses them; one file looks like this:

```
Filetype: Flipper NFC device
Version: 4
Device type: SLIX
UID: E0 04 03 50 20 30 36 1D
DSFID: 00
AFI: 00
IC Reference: 03
Lock DSFID: false
Lock AFI: false
Block Count: 8
Block Size: 04
Data Content: D9 3F EB 0A DB 3D 44 47 8B E4 85 49 DB 4E 04 E1 93 9A 22 6B 2F B3 91 1D 98 2C 1C 55 00 F2 00 64
Security Status: 00 00 00 00 00 00 00 00
Capabilities: Default
Password Privacy: 7F FD 6E 5B
Password Destroy: 0F 0F 0F 0F
Password EAS: 00 00 00 00
Privacy Mode: false
Lock EAS: false
```

Lines starting with `#` are comments and are ignored; the key/value separator
is `: `. The fields that matter for writing a tag:

* **`UID`** — 8 bytes in display order (`E0` first). That is exactly the order
  the magic UID frames expect; they reverse each half themselves (see
  [HARDWARE.md](HARDWARE.md#-why-this-repo-never-calls-csetuid)).
* **`Data Content`** — 32 bytes = 8 blocks × 4 bytes; block 0 is the first
  4 bytes.
* **`Privacy Mode: false`** — true for every upstream file, so the write flow
  never has to disable privacy mode first.
* **`Password Privacy: 7F FD 6E 5B`** — the well-known Tonies privacy
  password. This repo never writes passwords; see the expert notes in
  [HARDWARE.md](HARDWARE.md).

A file is rejected by the parser if it is not `Device type: SLIX`, the UID is
not 8 bytes, `Block Count` is not 8, `Block Size` is not `04`, or
`Data Content` is not exactly 32 bytes. `scripts/build_index.py` warns about
and skips such files instead of failing the whole build.

## The nightly job

[`.github/workflows/sync-tonies.yml`](../.github/workflows/sync-tonies.yml)
runs on a schedule (02:27 UTC nightly) and can also be triggered manually:

1. Checks out the repo.
2. Runs `./scripts/sync_upstream.sh`, which shallow-clones
   [nortakales/flipper-zero-tonies](https://github.com/nortakales/flipper-zero-tonies)
   and mirrors only `*.nfc` files into `data/tonies/` via `rsync -a --delete`,
   then writes `data/UPSTREAM.json`.
3. Runs `python3 scripts/build_index.py` to rebuild `data/tonies.json` and
   `TONIES.md` from the freshly mirrored files.
4. Stages `data/` and `TONIES.md`. If nothing changed, it stops there — no
   commit, no PR, ever. If something changed, it commits as
   `github-actions[bot]` with a message naming the upstream short SHA and
   file count, and pushes directly to the branch the workflow runs on.

"Nothing changed" is meant literally, which takes some care with timestamps:

* `sync_upstream.sh` leaves `data/UPSTREAM.json` untouched when the upstream
  commit it just fetched matches the one already recorded. Rewriting
  `synced_at` on every run would make the file differ every night even when
  the mirror is identical.
* `build_index.py` takes `generated_at` from that `synced_at` rather than
  from the current clock, so `data/tonies.json` and `TONIES.md` inherit the
  same property.

Together this means a night with no upstream activity produces a genuinely
empty diff and therefore no commit. `tests/test_build_index.py` guards the
second half of this.

Triggering it manually (e.g. from the Actions tab, "Run workflow") accepts a
`dry_run` input: when true, the sync and index rebuild still run, but the
commit step only prints what it *would* commit (`git diff --cached --stat`)
instead of actually committing and pushing.

## Running it locally

```sh
./scripts/sync_upstream.sh
python3 scripts/build_index.py
```

Both are idempotent: running them again with nothing changed upstream
produces zero diff (aside from the `synced_at`/`generated_at` timestamps
inside the JSON files, which always update). `./tonie index` is a shortcut
for just the second step, useful after hand-editing a test fixture.

`scripts/sync_upstream.sh` only depends on `git`, `rsync`, and `python3` —
all of which ship with macOS — so it works the same on a contributor's
laptop as it does in CI (BSD-rsync-compatible flags only, no GNU-only
options).

## CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on every push
and pull request: a syntax check (`py_compile` over every tracked `.py`
file) plus the full test suite (`python3 -m unittest discover -s tests`).
It never touches the network or upstream data — all tests run against
fixtures committed under `tests/fixtures/`.
