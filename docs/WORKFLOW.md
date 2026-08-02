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
