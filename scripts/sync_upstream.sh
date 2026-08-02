#!/usr/bin/env bash
# Mirror the .nfc dumps from the upstream flipper-zero-tonies repository into
# data/tonies/ and record provenance in data/UPSTREAM.json.
#
# Usable both from CI and locally on macOS (BSD rsync/date compatible).
set -euo pipefail

UPSTREAM_URL="https://github.com/nortakales/flipper-zero-tonies.git"
UPSTREAM_BRANCH="master"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="$REPO_ROOT/data/tonies"
UPSTREAM_JSON="$REPO_ROOT/data/UPSTREAM.json"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "Cloning $UPSTREAM_URL (branch $UPSTREAM_BRANCH)..." >&2
git clone --depth 1 --branch "$UPSTREAM_BRANCH" "$UPSTREAM_URL" "$TMP_DIR" >&2

COMMIT_SHA="$(git -C "$TMP_DIR" rev-parse HEAD)"
COMMIT_DATE="$(git -C "$TMP_DIR" log -1 --format=%cI)"
SYNCED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

BEFORE_COUNT=0
if [ -d "$DEST_DIR" ]; then
  BEFORE_COUNT="$(find "$DEST_DIR" -name '*.nfc' | wc -l | tr -d ' ')"
fi

mkdir -p "$DEST_DIR"

# Discover top-level language directories automatically, excluding upstream's
# own tooling/metadata directories, so a new language is picked up without
# changes to this script.
LANG_DIRS=()
for entry in "$TMP_DIR"/*; do
  name="$(basename "$entry")"
  case "$name" in
    scripts|.git|.github) continue ;;
  esac
  if [ -d "$entry" ]; then
    LANG_DIRS+=("$entry")
  fi
done

if [ "${#LANG_DIRS[@]}" -eq 0 ]; then
  echo "error: no language directories found upstream" >&2
  exit 1
fi

rsync -a --delete --prune-empty-dirs \
  --include='*/' --include='*.nfc' --exclude='*' \
  "${LANG_DIRS[@]}" "$DEST_DIR/"

AFTER_COUNT="$(find "$DEST_DIR" -name '*.nfc' | wc -l | tr -d ' ')"

python3 - "$UPSTREAM_JSON" "$UPSTREAM_URL" "$UPSTREAM_BRANCH" "$COMMIT_SHA" "$COMMIT_DATE" "$SYNCED_AT" "$AFTER_COUNT" <<'PYEOF'
import json
import os
import sys

out_path, repository, branch, commit, commit_date, synced_at, file_count = sys.argv[1:8]

data = {
    "repository": repository.removesuffix(".git"),
    "branch": branch,
    "commit": commit,
    "commit_date": commit_date,
    "synced_at": synced_at,
    "file_count": int(file_count),
}

# Only rewrite the file when the mirror actually moved. "synced_at" changes on
# every run by definition, so writing it unconditionally would produce a
# timestamp-only diff -- and therefore a pointless commit -- every night.
# Everything else in the record is derived from the upstream commit, so an
# unchanged SHA means an unchanged mirror.
if os.path.exists(out_path):
    try:
        with open(out_path, encoding="utf-8") as f:
            previous = json.load(f)
    except (json.JSONDecodeError, OSError):
        previous = None

    if previous is not None:
        comparable = {k: v for k, v in data.items() if k != "synced_at"}
        if all(previous.get(k) == v for k, v in comparable.items()):
            print("Upstream unchanged, keeping existing UPSTREAM.json", file=sys.stderr)
            sys.exit(0)

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
PYEOF

DELTA=$((AFTER_COUNT - BEFORE_COUNT))
echo "Synced: $AFTER_COUNT .nfc files total (was $BEFORE_COUNT, delta $DELTA) @ $COMMIT_SHA" >&2
