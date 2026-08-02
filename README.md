# tonies

Write a real Tonie figure onto a blank NFC tag using a Proxmark3, so a stock
Toniebox plays it. This repo nightly mirrors every `.nfc` dump from
[nortakales/flipper-zero-tonies](https://github.com/nortakales/flipper-zero-tonies),
builds a browsable index, and ships a local CLI (`./tonie`) that resolves a
Tonie by name, writes it to a tag, and verifies the result.

> **⚠️ Tag compatibility — read this first**
> You need a **magic ICODE SLIX-L tag with a changeable UID**, e.g. from
> [rfidfriend.com](http://rfidfriend.com) (order the *magic* variant, not the
> fixed-UID one). Plain "programmable" SLIX stickers, and generic magic
> ISO 15693 tags (SLI / SLIX2 / TAG-it), do **not** work on a stock,
> unmodified Toniebox — they either have the wrong UID prefix or fail the
> box's privacy-password check. See [`docs/HARDWARE.md`](docs/HARDWARE.md)
> for the full compatibility table and troubleshooting.

## Quickstart

```sh
git clone https://github.com/l480/tonies.git && cd tonies
brew tap RfidResearchGroup/proxmark3 && brew install --with-generic proxmark3
pm3-flash-all                 # put the PM3 in bootloader mode first
./tonie doctor
./tonie search "paw patrol"
./tonie write "Zuma" --dry-run
./tonie write "Zuma"
```

No `pip install` step: the CLI is Python standard library only.

## Commands

| Command | Behaviour |
|---------|-----------|
| `tonie list [--language DE\|German] [--series X] [--limit N]` | print the catalog |
| `tonie search <query>` | ranked matches with scores |
| `tonie info <query>` | resolved Tonie: name, series, language, UID, path, all 8 blocks |
| `tonie write <query> [flags]` | resolve, confirm, write, and verify a Tonie onto the tag on the reader |
| `tonie read` | read the tag on the reader and identify it against the catalog |
| `tonie doctor [--probe-magic]` | environment + hardware check |
| `tonie index` | regenerate `data/tonies.json` + `TONIES.md` locally |

Global flags: `--port <dev>`, `--json`, `--verbose`.

`tonie write` flags: `--dry-run`, `--yes`, `--uid-only`, `--blocks-only`,
`--no-verify`, `--retries N`, `--language`, `--pick N`. There is deliberately
no `--gen2` flag — see `docs/HARDWARE.md` for why.

## The catalog

[`TONIES.md`](TONIES.md) lists every available Tonie, grouped by language and
series. It and `data/` are regenerated nightly by
[`.github/workflows/sync-tonies.yml`](.github/workflows/sync-tonies.yml); see
[`docs/WORKFLOW.md`](docs/WORKFLOW.md) for how that works and how to run it
locally.

## Credits & legal

The `.nfc` dumps are mirrored from the community-maintained
[nortakales/flipper-zero-tonies](https://github.com/nortakales/flipper-zero-tonies)
repository. The write sequence is built against the
[Proxmark3 Iceman (RfidResearchGroup) firmware](https://github.com/RfidResearchGroup/proxmark3)
and reuses the safe magic-UID write frames documented by
[SLI-Writer](https://github.com/Julienbxl/SLI-Writer).

This tooling clones identifiers of Tonie figures for personal use with
figures and content you own — for example, replacing a lost or damaged
figure with a sticker on a DIY figure. Do not redistribute cloned tags. No
audio content is copied by any of this: the audio lives on the
Toniebox/cloud, never on the tag itself.
