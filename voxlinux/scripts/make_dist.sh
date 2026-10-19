#!/usr/bin/env bash
#
# make_dist.sh — source-tarball half of the VoxLinux build.
#
# Usage: make_dist.sh <out-dir> <version>
#
# Produces $out_dir/voxlinux-<version>.src.tar.gz containing the source tree,
# with a SHA256SUMS file inside. Deterministic-ish: sorted file list, fixed
# mtimes, normalised ownership.

set -euo pipefail

OUT_DIR="${1:?usage: make_dist.sh <out-dir> <version>}"
VERSION="${2:?usage: make_dist.sh <out-dir> <version>}"

SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$OUT_DIR"

STAGE="$(mktemp -d /tmp/opencode/make-dist.XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT

STAGE_TREE="$STAGE/tree"
mkdir -p "$STAGE_TREE"

# Build the inclusion list (paths relative to SRC_DIR).
LIST="$STAGE/files.txt"
{
    if [[ -d "$SRC_DIR/voxapp" ]]; then
        find voxapp -type f \
            ! -path '*/__pycache__/*' ! -name '*.pyc' ! -name '*.pyo' -print
    fi
    for d in scripts systemd tests; do
        if [[ -d "$SRC_DIR/$d" ]]; then
            find "$d" -type f \
                ! -path '*/__pycache__/*' ! -name '*.pyc' ! -name '*.pyo' -print
        fi
    done
    # eval/: metadata only — exclude audio files.
    if [[ -d "$SRC_DIR/eval" ]]; then
        find eval -type f \
            ! -name '*.wav' ! -name '*.mp3' ! -name '*.flac' ! -name '*.ogg' \
            ! -path '*/__pycache__/*' ! -name '*.pyc' -print
    fi
    for f in install.sh build.sh voxlinux.spec VERSION README.md PLAN.md requirements.txt; do
        [[ -f "$SRC_DIR/$f" ]] && printf '%s\n' "$f"
    done
    # LICENSE-ish notices.
    find . -maxdepth 3 -type f \
        \( -iname 'LICENSE*' -o -iname 'NOTICE*' -o -iname 'COPYING*' \) \
        -not -path './.venv/*' -not -path './dist/*' -not -path './.git/*' \
        -print 2>/dev/null | sed 's|^\./||' || true
} | sort -u > "$LIST"

# Stage files preserving structure.
while IFS= read -r rel; do
    [[ -n "$rel" ]] || continue
    mkdir -p "$STAGE_TREE/$(dirname "$rel")"
    cp -a "$SRC_DIR/$rel" "$STAGE_TREE/$rel"
done < "$LIST"

# SHA256SUMS inside the tarball.
(
    cd "$STAGE_TREE"
    find . -type f ! -name SHA256SUMS -print0 | sort -z | \
        xargs -0 sha256sum | sed 's| \./|  |' > SHA256SUMS
)

TARBALL="$OUT_DIR/voxlinux-${VERSION}.src.tar.gz"
tar --sort=name \
    --mtime='2026-01-01 UTC' \
    --owner=0 --group=0 --numeric-owner \
    -C "$STAGE_TREE" -czf "$TARBALL" .

echo "created $TARBALL"
