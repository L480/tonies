# Implementation Plan: Tonie → NFC Tag Writer

**Status:** ready to implement
**Target executor:** Claude Sonnet (or any coding agent) — this document is written to be executed top-to-bottom without further research.
**Repository:** `l480/tonies`
**Working branch:** `claude/tonie-nfc-deployment-plan-0p2nto`

---

## 1. Goal

Build a repository that:

1. **Nightly** mirrors all Tonie `.nfc` dumps from
   [`nortakales/flipper-zero-tonies`](https://github.com/nortakales/flipper-zero-tonies) into this repo via GitHub Actions.
2. **Nightly** renders a browsable list of every available Tonie (`TONIES.md`) plus a
   machine-readable index (`data/tonies.json`).
3. Provides a **local CLI tool** so that after `git clone`, a user can run
   `./tonie write "Zuma"` and the selected Tonie is written to a blank NFC tag
   via a Proxmark3.

**Everything in the repo — code, comments, docs, commit messages — is in English.**

### Target environment

| Item | Value |
|------|-------|
| Host OS | macOS on Apple Silicon (ARM64) |
| Reader/Writer | "Proxmark3 512M" from AliExpress — a **Proxmark3 Easy clone** with a 512 KB ARM MCU. Runs the Iceman (RfidResearchGroup) firmware, built with `PLATFORM=PM3GENERIC`. |
| Toniebox | **Stock / unmodified** (no TeddyCloud, no HackieboxNG) → cloning a real Tonie UID is the only viable path |
| Tags | **Magic SLIX-L with changeable UID** (see §2.3). The AliExpress "SLIX 15693 Dia 30 mm … programmable RFID sticker" the user already owns is expected *not* to work — see §2.4. |
| Python | `python3` from Xcode Command Line Tools (3.9+). **Standard library only** — no `pip install` step for the end user. |

---

## 2. Hardware reality check — READ BEFORE WRITING CODE

This section does **not** change what we build, but it determines whether the hardware
the user already bought will work. The CLI must surface these facts to the user instead
of failing cryptically.

### 2.1 What a Toniebox actually checks

* Tonie figures use **NXP ICODE SLIX-L** chips (ISO 15693 / NFC-V).
* The Toniebox validates the **first three UID bytes: `E0 04 03`**
  (`E0` = ISO 15693, `04` = NXP, `03` = ICODE SLIX-L).
  If they do not match, the box does *nothing at all* — no sound, no LED, no error.
* The Tonie identity is carried by the **UID**. The 32 bytes of user memory
  (8 blocks × 4 bytes) are part of the dump and are cloned for fidelity.
* Every `.nfc` file in the upstream repo therefore contains a UID starting with
  `E0 04 03` plus a 32-byte `Data Content`.

### 2.2 Target box: **stock / unmodified Toniebox** (confirmed)

This changes nothing about the software, but it fixes the requirement:
on an unmodified box the only way to make a tag play something is to **clone the UID
of a real Tonie** the box (or the cloud) already knows. Assigning custom content to a
tag's own UID requires a modified box (TeddyCloud / HackieboxNG) and is out of scope
(§12).

### 2.3 Which tags actually work — and which do not

* On a **genuine** NXP tag the UID is laser-programmed at the factory and is
  **permanently read-only**. No reader can change it, Proxmark3 included.
* A genuine **ICODE SLIX** (not SLIX-L) reports `E0 04 02` and additionally lacks the
  privacy-password support the box expects. Stock firmware rejects it; only patched
  firmware ("allow tags without privacy password support, e.g. SLIX") accepts it.
* Historically no UID-changeable SLIX-**L** existed — all magic ISO 15693 tags were
  SLI/SLIX class, which is why "cloning a Tonie" was long considered impossible.
* That has changed: **magic SLIX-L tags are now sold** (e.g. RFIDFriend). Upstream
  issue [nortakales/flipper-zero-tonies#170](https://github.com/nortakales/flipper-zero-tonies/issues/170)
  reports them working on **original, unmodified Toniebox 1 and 2**.

**Buying guidance for `docs/HARDWARE.md` — be specific, this is where money gets wasted:**

| Tag | Stock box | Verdict |
|-----|-----------|---------|
| Magic **SLIX-L**, changeable UID | ✅ | **This is what you need.** |
| Generic "magic ISO15693 / ICODE SLI / SLIX, UID changeable" | ❌ likely | UID can be set to `E00403…`, but the chip is SLI/SLIX class and fails the box's privacy-password step. |
| Genuine SLIX-L, fixed UID | ❌ | UID is unknown to the cloud → box ignores it. Only useful on a modified box. |
| Genuine SLIX (the AliExpress stickers, see below) | ❌ | Wrong UID prefix *and* no privacy support. |

### 2.4 The tags the user already owns

AliExpress "Echtes SLIX 15693 Dia 30 mm … programmierbarer RFID-Aufkleber".
"Programmable" refers to the **memory**, not the UID. The listing's reviews are the
tell — every positive report describes a **patched** box:

> "Funktioniert perfekt mit meiner Toniebox (CC3200), die den benutzerdefinierten Bootloader HackieboxNG verwendet."
> "Funktioniert mit Toniebox/Teddycloud mit aktivierten Patches."

The patch in question is exactly the HackieboxNG OFW patch that allows tags *without*
privacy-password support (i.e. plain SLIX). Needing that patch is strong evidence the
stickers are genuine SLIX with a fixed `E0 04 02…` UID — not magic, not SLIX-L.
No review claims a stock box works.

**Expected outcome: these stickers will not work for this project.** Say so in the
README, do not let the user discover it after 30 failed writes. They remain usable if
the box is ever modified.

### 2.5 The 2-minute verification the user runs first

`./tonie doctor [--probe-magic]` reports the tag's UID prefix and whether
`hf 15 csetuid` takes. Document the three outcomes plainly:

| Outcome | Meaning | What to do |
|---------|---------|------------|
| `csetuid` ok, UID becomes `E0 04 03…`, chip behaves as SLIX-L | Magic SLIX-L ✅ | Everything in this repo works as designed. |
| `csetuid` ok, but the tag is SLI/SLIX class | Magic, wrong class ⚠️ | Write succeeds, stock box will most likely still ignore the tag. Try it, but expect failure. |
| `csetuid` fails / UID unchanged | Fixed-UID tag ❌ | Cloning is physically impossible with these. Buy magic SLIX-L tags. |

**Residual risk to flag in `docs/HARDWARE.md`:** the upstream success report used a
**Flipper Zero** with the [SLI-Writer](https://github.com/Julienbxl/SLI-Writer) app, not
a Proxmark3. Whether a given magic SLIX-L batch answers the gen1 or the gen2 magic
command is vendor-specific — hence `--gen2` and the automatic gen1→gen2 retry in §8.5
step 6. If neither works, the fallback is Flipper Zero + SLI-Writer with the very same
`.nfc` files from `data/tonies/` (they are Flipper-native — mention this, it costs one
sentence and saves the project).

Document all of §2 in `docs/HARDWARE.md` and link it from the README's first section.
Do **not** hide it in a footnote — it is the single most likely reason the project
"doesn't work" for the user.

### 2.6 Legal / scope note (one short paragraph in the README)

This tooling clones identifiers of Tonie figures for personal use with figures and
content the user owns (e.g. replacing a lost or damaged figure with a sticker on a
DIY figure). The `.nfc` dumps come from a public third-party repository. Do not
redistribute cloned tags. No audio content is copied — the audio lives on the
Toniebox/cloud, not on the tag.

---

## 3. Upstream facts (verified — do not re-research)

Repository: `https://github.com/nortakales/flipper-zero-tonies`, default branch **`master`**.

```
flipper-zero-tonies/
├── English/<Series>/<Tonie>.nfc      (some series nested one level deeper)
├── French/<Series>/<Tonie>.nfc
├── German/<Series>/<Tonie>.nfc
├── scripts/{validate_files.sh,build_directories.sh,figures_name_tool.pyw,requirements.txt}
├── .github/workflows/
└── README.md                          (+ per-language README.md, auto-generated)
```

* ~755 `.nfc` files at time of writing; 3 languages; files are at least 2 directories deep.
* Allowed filename characters upstream: `A-Za-z0-9().,!%&+ -` (note: **spaces**, and
  German umlauts are transliterated, e.g. `Kruemelmonsters Mitmampfspass`).
* Upstream has **no LICENSE file** → attribute clearly, mirror as-is, link back.

### 3.1 Exact `.nfc` file format (Flipper Zero NFC v4, SLIX)

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

Lines starting with `#` are comments and must be ignored. Key/value separator is `: `.

* `UID` — 8 bytes, **display order** (`E0` first). This is exactly the order
  `hf 15 csetuid -u …` expects.
* `Data Content` — 32 bytes = 8 blocks × 4 bytes, block 0 = first 4 bytes.
* `Privacy Mode: false` → we never need to disable privacy before writing.
* `Password Privacy: 7F FD 6E 5B` is the well-known Tonies privacy password. **Do not
  write passwords by default** — `hf 15 slixwritepwd` / `passprotect*` can permanently
  lock a tag. Mention it only as an expert-mode footnote in `docs/HARDWARE.md`.

---

## 4. Proxmark3 reference (verified against Iceman `master` — do not re-research)

### 4.1 Install on macOS ARM

```sh
xcode-select --install
brew tap RfidResearchGroup/proxmark3
brew install --with-generic proxmark3          # --with-generic = PM3GENERIC, i.e. PM3 Easy / "512M"
# if that fails:
brew install --HEAD --with-generic proxmark3
```

Flashing (unplug PM3, hold its button while plugging in, release when 2 of 4 LEDs stay on):

```sh
pm3-flash-all
```

Notes:
* Firmware and client must always be the same version — after `brew upgrade proxmark3`, re-run `pm3-flash-all`.
* MCU size (256/512 KB) is auto-detected while flashing. 512 KB needs no `SKIP_*` trimming.
* Serial device appears as `/dev/tty.usbmodemiceman1` (older firmware: `/dev/tty.usbmodem881`).
* Since v4.19552 Rosetta 2 is no longer required on Apple Silicon.

### 4.2 Client invocation (non-interactive)

```sh
pm3 -c "hf 15 info"                      # auto-detect port, run one command, exit
pm3 -c "cmd1;cmd2;cmd3"                  # several commands, ';' separated
pm3 -p /dev/tty.usbmodemiceman1 -c "..." # explicit port
proxmark3 -s cmds.txt                    # one command per line
```

The CLI shells out to `pm3` (fall back to `proxmark3` if `pm3` is not on `PATH`).

### 4.3 The `hf 15` commands we use

| Command | Purpose |
|---------|---------|
| `hf 15 info` | tag present? shows UID, chip type |
| `hf 15 csetuid -u E00403502030361D` | set UID on a **magic** tag (gen1 command) |
| `hf 15 csetuid -u E00403502030361D --v2` | same, gen2 magic command |
| `hf 15 wrbl -* -b <0-7> -d AABBCCDD` | write one 4-byte block, unaddressed mode |
| `hf 15 rdbl -* -b <0-7>` | read one block back (verification) |
| `hf 15 dump --ns` | read all blocks, don't save to file |

Verified behaviour of `csetuid`: the UID argument is 8 hex bytes in display order and
**must start with `E0`**; the command finds the tag, writes, re-reads and prints
`Setting new UID ( ok )` or `( fail )` — i.e. it self-verifies. Exit code alone is not
reliable across versions, so parse stdout too.

Do **not** use `hf 15 restore -f …`: it requires a full `iso15_tag_t` binary struct dump
whose layout changes between releases. `csetuid` + 8× `wrbl` is stable and explicit.

---

## 5. Target repository layout

```
tonies/
├── .github/workflows/
│   └── sync-tonies.yml            # nightly: mirror upstream + rebuild index + commit
├── data/
│   ├── tonies/                    # MIRROR — generated, never edit by hand
│   │   ├── English/<Series>/<Tonie>.nfc
│   │   ├── French/…
│   │   └── German/…
│   ├── tonies.json                # generated index (search metadata)
│   └── UPSTREAM.json              # generated provenance: upstream repo, commit SHA, sync timestamp, file count
├── scripts/
│   ├── sync_upstream.sh           # clone upstream, rsync .nfc files into data/tonies
│   └── build_index.py             # data/tonies/** -> data/tonies.json + TONIES.md
├── tonie_writer/                  # Python package (stdlib only)
│   ├── __init__.py
│   ├── cli.py                     # argparse entry point, subcommands
│   ├── catalog.py                 # load index, normalize, fuzzy match
│   ├── nfcfile.py                 # parse .nfc -> TonieTag dataclass
│   ├── proxmark.py                # locate + invoke pm3, parse output
│   └── writer.py                  # orchestrate write + verify
├── docs/
│   ├── HARDWARE.md                # PM3 setup, tag requirements, magic-vs-genuine, troubleshooting
│   └── WORKFLOW.md                # how the nightly sync works, how to run it locally
├── tonie                          # executable shim: #!/usr/bin/env python3 -> tonie_writer.cli
├── TONIES.md                      # generated full list
├── README.md                      # quickstart
├── .gitattributes
└── plan.md                        # this file
```

`.gitattributes`:

```
data/tonies/** linguist-generated=true
data/tonies.json linguist-generated=true
TONIES.md linguist-generated=true
```

---

## 6. Phase 1 — Nightly sync

### 6.1 `scripts/sync_upstream.sh`

Bash, `set -euo pipefail`. Steps:

1. `UPSTREAM_URL=https://github.com/nortakales/flipper-zero-tonies.git`, `UPSTREAM_BRANCH=master`.
2. Clone shallow into a temp dir (`mktemp -d`, trap cleanup).
3. Capture `git -C "$tmp" rev-parse HEAD` and the commit date.
4. `mkdir -p data/tonies`, then mirror **only** `.nfc` files, deleting removed ones:
   ```sh
   rsync -a --delete --prune-empty-dirs \
     --include='*/' --include='*.nfc' --exclude='*' \
     "$tmp"/English "$tmp"/French "$tmp"/German data/tonies/
   ```
   (If a new language directory appears upstream, the script should pick it up
   automatically: enumerate top-level dirs of the clone excluding `scripts`, `.git`,
   `.github`, and pass those to rsync.)
5. Write `data/UPSTREAM.json`:
   ```json
   {
     "repository": "https://github.com/nortakales/flipper-zero-tonies",
     "branch": "master",
     "commit": "<sha>",
     "commit_date": "<iso8601>",
     "synced_at": "<iso8601 UTC>",
     "file_count": 755
   }
   ```
6. Print a one-line summary (added / removed / total).

Must be runnable locally on macOS too (`rsync` ships with macOS; avoid GNU-only flags —
the ones above are BSD-rsync compatible).

### 6.2 `.github/workflows/sync-tonies.yml`

```yaml
name: Sync Tonies

on:
  schedule:
    - cron: "27 2 * * *"     # 02:27 UTC nightly
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: sync-tonies
  cancel-in-progress: false

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Sync upstream .nfc files
        run: ./scripts/sync_upstream.sh
      - name: Rebuild index
        run: python3 scripts/build_index.py
      - name: Commit changes
        run: |
          if git diff --quiet; then
            echo "No changes."
            exit 0
          fi
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data TONIES.md
          git commit -m "chore: sync tonies from upstream ($(python3 -c '...print commit sha...'))"
          git push
```

Details for the executor:
* Pin action versions as shown.
* The commit message should include the upstream short SHA and the total file count —
  read them from `data/UPSTREAM.json` with a small `python3 -c` snippet.
* Push to the repository's **default branch** (the workflow runs on it after merge).
* Add a `workflow_dispatch` input `dry_run` (boolean, default false) that skips the
  commit step — handy for testing.
* Keep the job under 5 minutes; a shallow clone of ~755 small files is seconds.

---

## 7. Phase 2 — Index rendering

### 7.1 `scripts/build_index.py`

Stdlib only. Walks `data/tonies/**/*.nfc`, parses each file with `tonie_writer.nfcfile`
(import it — one parser, one source of truth), and emits:

**`data/tonies.json`**

```json
{
  "generated_at": "2026-08-02T02:27:11Z",
  "upstream_commit": "abc1234",
  "count": 755,
  "tonies": [
    {
      "id": "english/paw-patrol/zuma",
      "name": "Zuma",
      "series": "Paw Patrol",
      "language": "English",
      "path": "data/tonies/English/Paw Patrol/Zuma.nfc",
      "uid": "E00403502030361D",
      "search": "english paw patrol zuma"
    }
  ]
}
```

* `id` — slug: `<language>/<series path>/<name>`, lowercased, spaces → `-`, unsafe chars dropped. Must be stable and unique (append `-2`, `-3` on collision).
* `series` — path between the language dir and the file, joined with `/` if nested.
* `uid` — hex, no spaces, uppercase.
* `search` — precomputed normalized haystack (see §8.3).
* Sort by `language`, then `series`, then `name` so diffs stay minimal.
* Write with `indent=2`, `ensure_ascii=False`, trailing newline.

**`TONIES.md`**

```markdown
# Available Tonies

*This file is generated by `scripts/build_index.py` — do not edit manually.*

Upstream: [nortakales/flipper-zero-tonies](…) @ `abc1234` · synced 2026-08-02 · **755 Tonies**

| Language | Count |
|---|---|
| English | 61 |
| French | 12 |
| German | 682 |

## German

### Sesamstrasse

| Tonie | UID | File |
|---|---|---|
| Elmos Mitmachmusik | `E00403…` | [.nfc](data/tonies/German/Sesamstrasse/Elmos%20Mitmachmusik.nfc) |
```

* Group by language → series; series headings sorted alphabetically.
* URL-encode spaces (`%20`) in links.
* Add a "How to write one of these" line at the top pointing at `./tonie write "<name>"`.

**Duplicate-UID detection:** if two `.nfc` files share a UID, list them in a
`## Duplicate UIDs` section at the bottom of `TONIES.md` (informational only, never fail).

**Validation:** the script warns (stderr, non-fatal) about files that do not match the
expected SLIX shape (missing UID, `Block Count` ≠ 8, `Data Content` ≠ 32 bytes) and
**excludes** them from the index. Exit code stays 0 unless the whole tree is unreadable.

---

## 8. Phase 3 — The CLI

### 8.1 Entry point

`./tonie` (chmod +x):

```python
#!/usr/bin/env python3
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from tonie_writer.cli import main
raise SystemExit(main())
```

Also expose `python3 -m tonie_writer` for the same result.

### 8.2 Commands

| Command | Behaviour |
|---------|-----------|
| `tonie list [--language DE\|German] [--series X] [--limit N]` | print catalog table |
| `tonie search <query>` | ranked matches with scores |
| `tonie info <query>` | resolved Tonie: name, series, language, UID, path, all 8 blocks |
| `tonie write <query> [flags]` | the main event — see §8.5 |
| `tonie read` | read the tag on the reader, print UID + blocks, and identify it against the catalog ("This is *Zuma* (English / Paw Patrol)") |
| `tonie doctor` | environment + hardware check — see §8.6 |
| `tonie index` | regenerate `data/tonies.json` + `TONIES.md` locally (calls `scripts/build_index.py`) |

Global flags: `--port <dev>`, `--json` (machine-readable output where meaningful), `--verbose`.

### 8.3 Matching (`catalog.py`)

Normalization for both query and catalog entries:
1. Unicode NFKD, strip combining marks.
2. German transliteration **before** stripping: `ä→ae ö→oe ü→ue ß→ss` (upstream filenames
   already use this convention, users will type either form — normalize both ways and
   index both variants in the haystack).
3. Lowercase; replace any non-alphanumeric run with a single space; strip.

Ranking, highest first:
1. exact match on normalized `name`
2. exact match on normalized `series/name` or `id`
3. `name` startswith query
4. all query tokens present in `search` haystack
5. `difflib.SequenceMatcher` ratio ≥ 0.72 against `name` (tie-break by ratio)

Resolution rules:
* 0 results → error, plus "did you mean" suggestions from the best 5 difflib hits, exit 2.
* 1 result → use it.
* n results → print a numbered list; interactively prompt for a number when stdin is a TTY;
  otherwise error with the list and exit 2. `--yes`/non-interactive never auto-picks
  an ambiguous match. `--pick N` selects from the printed list non-interactively.
* `--language` narrows before ranking; if the query matches in exactly one language,
  prefer that instead of asking.

### 8.4 `nfcfile.py`

```python
@dataclass(frozen=True)
class TonieTag:
    path: Path
    uid: str              # "E00403502030361D"
    uid_bytes: bytes
    blocks: list[str]     # 8 entries, "D93FEB0A" …
    block_count: int
    block_size: int
    device_type: str      # "SLIX"
    raw: dict[str, str]
```

`parse_nfc_file(path) -> TonieTag`, raising `NfcParseError` with the offending line on
malformed input. Rules: skip blank lines and `#` comments; split on the first `: `;
validate `Filetype: Flipper NFC device`, `Device type: SLIX`, UID length 8 bytes,
`Block Count: 8`, `Block Size: 04`, `Data Content` exactly 32 bytes.
Warn (don't fail) if `Privacy Mode` is `true`.

### 8.5 `tonie write` — exact flow

Flags: `--dry-run`, `--yes`, `--port`, `--gen2` (use `csetuid --v2`), `--uid-only`
(skip data blocks), `--blocks-only` (skip UID), `--no-verify`, `--retries N` (default 2).

1. **Resolve** the Tonie (§8.3) and parse its `.nfc` (§8.4).
2. **Locate `pm3`** (`shutil.which("pm3")` → `proxmark3`). Missing → actionable error
   pointing at `docs/HARDWARE.md` §install. Exit 3.
3. **Read the tag currently on the antenna:** `hf 15 info`.
   * No tag → "Place the tag on the Proxmark3 antenna and try again." Exit 4.
   * Tag found → capture its current UID.
4. **Show a confirmation summary** and require `y` unless `--yes`:
   ```
   Tonie   : Zuma  (English / Paw Patrol)
   Source  : data/tonies/English/Paw Patrol/Zuma.nfc
   New UID : E0 04 03 50 20 30 36 1D
   Blocks  : 8 × 4 bytes will be overwritten
   Tag now : E0 04 02 11 22 33 44 55   <- will be permanently replaced
   ```
   If the tag's current UID already equals the target, say so and offer to write only
   the data blocks.
   If the target UID does not start with `E00403`, warn loudly (should never happen
   with upstream data).
5. **`--dry-run`** prints the exact `pm3` command list and exits 0. Nothing is sent to
   the device. This is also what CI/tests exercise.
6. **Write UID:** `hf 15 csetuid -u <UID>` (or with `--v2` when `--gen2`).
   * Parse stdout for `Setting new UID ( ok )` / `( fail )` / `no tag found`.
   * On failure without `--gen2`, **automatically retry once with `--v2`** and say so.
   * If both fail → print the "fixed-UID vs. magic SLIX-L tag" explanation from §2.3/§2.5 verbatim
     (one short paragraph + link to `docs/HARDWARE.md`) and exit 5. This is the single
     most important error message in the tool.
7. **Write blocks:** for `b` in 0..7 → `hf 15 wrbl -* -b <b> -d <8 hex chars>`.
   Batch them into one `pm3 -c "c1;c2;…"` invocation to avoid 8 device reconnects, but
   fall back to one command per invocation when `--verbose` (clearer errors) or when a
   batch fails, so the failing block can be identified and retried (`--retries`).
8. **Verify** unless `--no-verify`: `hf 15 info` (UID) + `hf 15 rdbl -* -b <0..7>`,
   regex-extract the 4 bytes per block and compare against the expected values.
   * Output-parsing must be defensive: if a line cannot be parsed, report
     "verification inconclusive (unexpected pm3 output)" as a **warning**, not a
     mismatch, and print the raw output under `--verbose`.
9. **Report:**
   ```
   ✅ Wrote "Zuma" to tag  E0 04 03 50 20 30 36 1D
      UID    : ok
      Blocks : 8/8 ok
   ```
   Exit 0. Any mismatch → exit 6 with a per-block diff table.

Exit codes: `0` ok · `2` catalog/resolution · `3` missing tooling · `4` no tag ·
`5` UID write failed · `6` verification failed · `1` unexpected.

### 8.6 `tonie doctor`

Checks, each printed as `✅ / ⚠️ / ❌` with a fix hint:

1. `python3` version ≥ 3.9.
2. `pm3` / `proxmark3` on `PATH` (+ `pm3 --version`, and whether client and firmware
   versions match — warn if the client prints the firmware-mismatch banner).
3. Serial device present (`/dev/tty.usbmodem*`).
4. `hf 15 info` → tag present? UID? chip type? Flag whether the UID prefix is `E00403`
   (SLIX-L, Toniebox-compatible), `E00402` (plain SLIX), or something else.
5. **Magic-tag probe** — only with `--probe-magic`, because it overwrites the UID:
   write the harmless test UID `E0 04 03 00 00 00 00 01`, read it back, then restore the
   tag's original UID if it was readable in step 4. Report magic / not magic and whether
   gen1 or gen2 worked. Require an explicit confirmation prompt before running.
6. Catalog present and parseable (`data/tonies.json`, file count).

### 8.7 `proxmark.py`

* `run(commands: list[str], port: str|None, timeout=60) -> Pm3Result(stdout, stderr, returncode)`
  using `subprocess.run`, joining commands with `;`.
* Strip ANSI escape sequences from output before parsing (`re.sub(r"\x1b\[[0-9;]*m", "", s)`).
* Never pass user input into a shell string — build an argv list; the only interpolated
  values are hex strings and block numbers that we generate ourselves and validate with
  `re.fullmatch(r"[0-9A-F]{8}", …)` / `0 <= b <= 7`.
* Timeout → clear message ("Proxmark3 did not respond — is another pm3 session open?").
* All parsing helpers live here and are pure functions over strings so they can be
  unit-tested without hardware: `parse_info_uid()`, `parse_csetuid_result()`,
  `parse_rdbl_data()`.

---

## 9. Phase 4 — Documentation

### `README.md` (top-level, concise)

1. One-paragraph what/why.
2. **Compatibility warning box** (§2.3/§2.4 condensed, 4 lines): magic **SLIX-L** tags required,
   plain SLIX stickers do not work on a stock box. Link to `docs/HARDWARE.md`.
3. Quickstart:
   ```sh
   git clone https://github.com/l480/tonies.git && cd tonies
   brew tap RfidResearchGroup/proxmark3 && brew install --with-generic proxmark3
   pm3-flash-all                 # PM3 in bootloader mode
   ./tonie doctor
   ./tonie search "paw patrol"
   ./tonie write "Zuma" --dry-run
   ./tonie write "Zuma"
   ```
4. Command table (§8.2).
5. Link to `TONIES.md`, note that it and `data/` are regenerated nightly.
6. Credits: upstream repo + Proxmark3 Iceman fork; legal note (§2.6).

### `docs/HARDWARE.md`

Proxmark3 Easy "512M" specifics · macOS ARM install & flashing (incl. the button trick,
`/dev/tty.usbmodemiceman1`, client/firmware version match) · tag requirements and the
magic-vs-genuine explanation · the `hf 15` command reference from §4.3 · expert notes
(privacy password, `slixwritepwd`, why we don't use `hf 15 restore`) · troubleshooting
table (no tag found, antenna placement, `csetuid` fail, permission/port issues,
verification mismatch).

### `docs/WORKFLOW.md`

How the nightly job works, how to run `scripts/sync_upstream.sh` + `scripts/build_index.py`
locally, what is generated vs. hand-written, and how to trigger the workflow manually.

---

## 10. Tests

Lightweight, stdlib `unittest`, run via `python3 -m unittest discover -s tests`.
Add a `ci.yml` workflow (push + PR) that runs them plus a syntax check.

| Test | Covers |
|------|--------|
| `test_nfcfile.py` | parses a fixture `.nfc`; rejects truncated/short-UID/bad-block-count files |
| `test_catalog.py` | exact/fuzzy/umlaut matching (`"Krümelmonsters"` → `Kruemelmonsters…`), ambiguity handling, `--language` narrowing |
| `test_proxmark.py` | output parsers against captured `pm3` output fixtures (success + failure + garbage) |
| `test_writer.py` | `--dry-run` produces the exact expected command list for a fixture Tonie (this is the contract test) |
| `test_build_index.py` | builds an index from a tiny fixture tree; asserts JSON shape, sort order, duplicate-UID section |

Fixtures live in `tests/fixtures/`; include 2–3 real `.nfc` files copied from `data/tonies/`.
No test may require hardware or network.

---

## 11. Execution order & acceptance criteria

1. **Scaffold** — layout, `.gitattributes`, `README.md` stub. Commit.
2. **`tonie_writer/nfcfile.py` + tests.** Commit.
3. **`scripts/sync_upstream.sh`** — run it locally; `data/tonies/` fills up; `data/UPSTREAM.json` written. Commit the mirrored data (yes, commit the `.nfc` files — the repo is meant to be usable offline right after clone).
4. **`scripts/build_index.py` + tests** — `TONIES.md` and `data/tonies.json` generated and committed.
5. **`.github/workflows/sync-tonies.yml`** — commit, then trigger via `workflow_dispatch` and confirm a clean no-op run.
6. **`catalog.py`, `proxmark.py`, `writer.py`, `cli.py`, `./tonie`** + tests. Commit.
7. **Docs.** Commit.
8. Push to `claude/tonie-nfc-deployment-plan-0p2nto`.

**Done when:**

* [ ] `./tonie search "zuma"` finds the Tonie on a fresh clone with no `pip install`.
* [ ] `./tonie write "Zuma" --dry-run` prints exactly:
      `hf 15 csetuid -u E00403502030361D` followed by 8 `hf 15 wrbl -* -b N -d XXXXXXXX` lines
      with the block data from the `.nfc` file, and touches no hardware.
* [ ] `./tonie doctor` runs and degrades gracefully with no Proxmark3 attached.
* [ ] `python3 -m unittest discover -s tests` is green.
* [ ] `scripts/sync_upstream.sh && python3 scripts/build_index.py` is idempotent
      (second run produces zero diff).
* [ ] `TONIES.md` lists every Tonie, grouped by language and series, with working links.
* [ ] The nightly workflow runs on schedule, commits only when upstream changed, and
      never opens a PR.
* [ ] README states the magic-tag requirement above the fold.

---

## 12. Out of scope

* TeddyCloud / Toniebox firmware modification, custom audio upload.
* Writing to anything other than magic ISO 15693 tags (Flipper Zero emulation is
  upstream's use case, not ours).
* Setting SLIX passwords, privacy mode, EAS or page protection.
* A GUI. A Homebrew formula for `tonie` itself.
* Hosting the rendered list anywhere other than in the repo (`TONIES.md`).
