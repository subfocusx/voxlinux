#!/usr/bin/env bash
#
# build.sh — single entry point for the VoxLinux build.
#
# Usage: build.sh [--out DIR] [--skip-tests] [--no-pyinstaller] [--with-model]
#
set -uo pipefail

SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SRC_DIR"

OUT_DIR="$SRC_DIR/dist"
SKIP_TESTS=0
NO_PYINSTALLER=0
WITH_MODEL=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --out) OUT_DIR="$2"; shift 2 ;;
        --out=*) OUT_DIR="${1#*=}"; shift ;;
        --skip-tests) SKIP_TESTS=1; shift ;;
        --no-pyinstaller) NO_PYINSTALLER=1; shift ;;
        --with-model) WITH_MODEL=1; shift ;;
        -h|--help) echo "usage: build.sh [--out DIR] [--skip-tests] [--no-pyinstaller] [--with-model]"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLU=$'\033[36m'; DIM=$'\033[2m'; RST=$'\033[0m'
if [[ ! -t 1 ]]; then RED=""; GRN=""; YEL=""; BLU=""; DIM=""; RST=""; fi
step() { printf '\n%s== %s ==%s\n' "$DIM" "$*" "$RST"; }
ok()   { printf '  %s[ OK ]%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '  %s[WARN]%s %s\n' "$YEL" "$RST" "$*"; }
bad()  { printf '  %s[FAIL]%s %s\n' "$RED" "$RST" "$*"; }
info() { printf '  %s[INFO]%s %s\n' "$BLU" "$RST" "$*"; }

PY="${SRC_DIR}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
    if command -v python3 >/dev/null; then PY="$(command -v python3)"; else PY="python3"; fi
fi

VERSION="$(cat "$SRC_DIR/VERSION" | tr -d '[:space:]')"
ARCH="$(uname -m)"
BUNDLE_NAME="voxlinux-${VERSION}-linux-${ARCH}"
TARBALL_NAME="voxlinux-${VERSION}.src.tar.gz"
TARBALL_PATH="$OUT_DIR/$TARBALL_NAME"

printf '%sVoxLinux build%s  version=%s  out=%s\n' "$BLU" "$RST" "$VERSION" "$OUT_DIR"

# ---------------------------------------------------------------------------
# a. Resolve versions
# ---------------------------------------------------------------------------
step "a. Resolve versions"
SHERPA_VERSION="$("$PY" -c 'import sherpa_onnx; print(sherpa_onnx.__version__)' 2>/dev/null || echo 'unknown')"
info "sherpa_onnx: $SHERPA_VERSION"
PYTHON_VERSION="$("$PY" --version 2>&1)"
info "python: $PYTHON_VERSION"
GIT_COMMIT="$(git -C "$SRC_DIR" rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
info "git commit: $GIT_COMMIT"
ONNXRUNTIME_VERSION="$("$PY" -c 'import onnxruntime; print(onnxruntime.__version__)' 2>/dev/null || echo 'not installed')"

# ---------------------------------------------------------------------------
# b. Gate: unit tests
# ---------------------------------------------------------------------------
if (( SKIP_TESTS == 0 )); then
    step "b. Unit tests (gate)"
    if "$PY" -m unittest discover -s tests -t .; then
        ok "unit tests passed"
    else
        bad "unit tests FAILED — aborting build"
        exit 1
    fi
else
    step "b. Unit tests (skipped via --skip-tests)"
fi

# ---------------------------------------------------------------------------
# c. compileall
# ---------------------------------------------------------------------------
step "c. compileall"
COMPILE_TARGETS=(voxapp)
for f in scripts/voxlinux scripts/vox-ptt scripts/voxtray scripts/test_platform.py scripts/test_transcribe.py scripts/bench_models.py; do
    [[ -f "$SRC_DIR/$f" ]] && COMPILE_TARGETS+=("$f")
done
if "$PY" -m compileall -q "${COMPILE_TARGETS[@]}"; then
    ok "compileall ok"
else
    bad "compileall failed — aborting"
    exit 1
fi

# ---------------------------------------------------------------------------
# d. Source distribution
# ---------------------------------------------------------------------------
step "d. Source distribution"
if bash "$SRC_DIR/scripts/make_dist.sh" "$OUT_DIR" "$VERSION"; then
    ok "source tarball created"
else
    bad "source tarball failed — aborting"
    exit 1
fi

# tarball SHA-256 -> dist/SHA256SUMS
TARBALL_SHA="$(sha256sum "$TARBALL_PATH" | awk '{print $1}')"
printf '%s  %s\n' "$TARBALL_SHA" "$TARBALL_NAME" > "$OUT_DIR/SHA256SUMS"
ok "wrote $OUT_DIR/SHA256SUMS"

# ---------------------------------------------------------------------------
# e. PyInstaller bundle
# ---------------------------------------------------------------------------
PYINSTALLER_OK=0
PYINSTALLER_VERSION="not built"
BUNDLE_DIR="$OUT_DIR/$BUNDLE_NAME"

if (( NO_PYINSTALLER == 0 )); then
    step "e. PyInstaller bundle"

    # Isolated build venv.
    BUILD_VENV="${BUILD_VENV:-$SRC_DIR/.build-venv}"
    BUILD_PY="$BUILD_VENV/bin/python"
    if [[ ! -x "$BUILD_PY" ]]; then
        info "creating isolated build venv at $BUILD_VENV"
        python3 -m venv "$BUILD_VENV" || { bad "venv creation failed"; BUILD_PY=""; }
    fi
    if [[ -n "${BUILD_PY:-}" && -x "$BUILD_PY" ]]; then
        if ! "$BUILD_PY" -c 'import PyInstaller' 2>/dev/null; then
            info "installing PyInstaller + runtime deps into build venv"
            "$BUILD_PY" -m pip install --quiet pyinstaller sherpa-onnx numpy sounddevice 2>&1 | tail -5
        fi
    fi

    if [[ -z "${BUILD_PY:-}" || ! -x "$BUILD_PY" ]]; then
        warn "no build python available — skipping PyInstaller"
    elif ! "$BUILD_PY" -c 'import PyInstaller' 2>/dev/null; then
        warn "PyInstaller not available in build venv — skipping"
    else
        PYINSTALLER_VERSION="$("$BUILD_PY" -c 'import PyInstaller; print(PyInstaller.__version__)' 2>/dev/null || echo 'unknown')"
        info "PyInstaller $PYINSTALLER_VERSION"
        WORK_DIR="$(mktemp -d /tmp/opencode/pyi-work.XXXXXX)"
        rm -rf "$BUNDLE_DIR"
        if PYTHONPATH="$SRC_DIR" "$BUILD_PY" -m PyInstaller \
            --noconfirm --clean \
            --distpath "$OUT_DIR" \
            --workpath "$WORK_DIR" \
            "$SRC_DIR/voxlinux.spec"; then
            # PyInstaller may have created bundle dir; verify.
            if [[ -d "$BUNDLE_DIR" ]]; then
                PYINSTALLER_OK=1
                ok "bundle created: $BUNDLE_DIR"
            else
                # find produced dir
                FOUND="$(find "$OUT_DIR" -maxdepth 1 -type d -name "voxlinux-*linux-*" | head -1)"
                if [[ -n "$FOUND" ]]; then
                    BUNDLE_DIR="$FOUND"
                    BUNDLE_NAME="$(basename "$FOUND")"
                    PYINSTALLER_OK=1
                    ok "bundle created: $BUNDLE_DIR"
                else
                    bad "PyInstaller ran but bundle dir not found"
                fi
            fi
        else
            bad "PyInstaller build FAILED"
        fi
        rm -rf "$WORK_DIR"
    fi
fi

# Post-process bundle if produced.
MODEL_ID=""
MODEL_URL=""
MODEL_EXTRACTED_DIR=""
MODEL_INSTALLED=0
MODEL_FILES_SHA=""
if (( PYINSTALLER_OK == 1 )); then
    step "e2. Bundle post-processing"
    # rec_overlay.py as plain script
    if [[ -f "$SRC_DIR/voxapp/rec_overlay.py" ]]; then
        cp "$SRC_DIR/voxapp/rec_overlay.py" "$BUNDLE_DIR/rec_overlay.py"
        ok "copied rec_overlay.py (frozen=False)"
    fi

    # systemd templates rendered
    mkdir -p "$BUNDLE_DIR/systemd"
    for u in voxlinux.service voxtray.service; do
        if [[ -f "$SRC_DIR/systemd/$u" ]]; then
            sed -e "s|%h|\$HOME|g" -e "s|%t|\${XDG_RUNTIME_DIR:-/run/user/\$(id -u)}|g" \
                "$SRC_DIR/systemd/$u" > "$BUNDLE_DIR/systemd/$u"
        fi
    done
    ok "rendered systemd templates"

    # bundle-local install.sh
    cat > "$BUNDLE_DIR/install.sh" <<'INSTALL_EOF'
#!/usr/bin/env bash
set -euo pipefail
BUNDLE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${VOX_BIN_DIR:-$HOME/.local/bin}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$BIN_DIR" "$UNIT_DIR"

cat > "$BIN_DIR/voxlinux" <<EOF
#!/usr/bin/env bash
exec "$BUNDLE_DIR/voxlinux" "\$@"
EOF
chmod +x "$BIN_DIR/voxlinux"

cat > "$BIN_DIR/vox-ptt" <<EOF
#!/usr/bin/env bash
exec "$BUNDLE_DIR/vox-ptt" "\$@"
EOF
chmod +x "$BIN_DIR/vox-ptt"

# render + install systemd user unit
if [[ -f "$BUNDLE_DIR/systemd/voxlinux.service" ]]; then
    sed -e "s|%h|$HOME|g" -e "s|%t|${XDG_RUNTIME_DIR:-/run/user/$(id -u)}|g" \
        "$BUNDLE_DIR/systemd/voxlinux.service" > "$UNIT_DIR/voxlinux.service"
fi
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload 2>/dev/null || true
fi
echo "Installed VoxLinux bundle from $BUNDLE_DIR"
echo "  launchers: $BIN_DIR/voxlinux, $BIN_DIR/vox-ptt"
echo "  unit:      $UNIT_DIR/voxlinux.service"
echo "Enable with: systemctl --user enable --now voxlinux.service"
INSTALL_EOF
    chmod +x "$BUNDLE_DIR/install.sh"
    ok "wrote bundle install.sh"

    # README-bundle.md
    cat > "$BUNDLE_DIR/README-bundle.md" <<'README_EOF'
# VoxLinux bundle

Self-contained bundle (no venv required). Run the daemon directly:

    ./voxlinux            # foreground
    ./voxlinux --list-models

Control CLI:

    ./vox-ptt ping

Overlay (needs SYSTEM python with Gtk/cairo — not frozen):

    python3 rec_overlay.py

Install into ~/.local/bin + systemd user unit:

    ./install.sh

## Model

The speech model is NOT bundled by default. It is downloaded to
~/.local/share/voxlinux/models/ on first run / via install.sh.

With --with-model, the currently installed model is copied into ./models/
and its SHA-256 is recorded in BUILD-INFO.txt.
README_EOF
    ok "wrote README-bundle.md"

    # --with-model
    if (( WITH_MODEL == 1 )); then
        # resolve installed model via project python
        MODEL_ID="$("$PY" - "$SRC_DIR" <<'PY' 2>/dev/null
import sys, os
sys.path.insert(0, sys.argv[1])
from voxapp.registry import DEFAULT_MODEL_ID, RECOMMENDED_MODEL_ID, MODELS
print(RECOMMENDED_MODEL_ID or DEFAULT_MODEL_ID)
PY
)"
        if [[ -n "$MODEL_ID" ]]; then
            MODEL_EXTRACTED_DIR="$("$PY" - "$SRC_DIR" "$MODEL_ID" <<'PY' 2>/dev/null
import sys, os
sys.path.insert(0, sys.argv[1])
from voxapp.registry import MODELS
print(MODELS[sys.argv[2]]["extracted_dir"])
PY
)"
            MODEL_URL="$("$PY" - "$SRC_DIR" "$MODEL_ID" <<'PY' 2>/dev/null
import sys, os
sys.path.insert(0, sys.argv[1])
from voxapp.registry import MODELS
print(MODELS[sys.argv[2]]["url"])
PY
)"
            MODELS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/voxlinux/models"
            if [[ -d "$MODELS_DIR/$MODEL_EXTRACTED_DIR" ]]; then
                mkdir -p "$BUNDLE_DIR/models"
                cp -a "$MODELS_DIR/$MODEL_EXTRACTED_DIR" "$BUNDLE_DIR/models/"
                MODEL_INSTALLED=1
                # per-file sha256
                MODEL_FILES_SHA="$(cd "$MODELS_DIR/$MODEL_EXTRACTED_DIR" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sed 's| \./|  |')"
                ok "copied model $MODEL_ID into bundle"
            else
                warn "model $MODEL_ID not installed at $MODELS_DIR/$MODEL_EXTRACTED_DIR"
            fi
        fi
    fi
fi

# ---------------------------------------------------------------------------
# f. BUILD-INFO.txt
# ---------------------------------------------------------------------------
step "f. BUILD-INFO.txt"
BUILD_INFO="$OUT_DIR/BUILD-INFO.txt"
{
    echo "VoxLinux BUILD-INFO"
    echo "version: $VERSION"
    echo "date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "git_commit: $GIT_COMMIT"
    echo "python_version: $PYTHON_VERSION"
    echo "sherpa_onnx_version: $SHERPA_VERSION"
    echo "onnxruntime_version: $ONNXRUNTIME_VERSION"
    echo "pyinstaller_version: $PYINSTALLER_VERSION"
    if [[ -n "$MODEL_ID" ]]; then
        echo "model_id: $MODEL_ID"
        echo "model_url: $MODEL_URL"
        echo "model_installed: $([[ $MODEL_INSTALLED -eq 1 ]] && echo yes || echo no)"
        if [[ $MODEL_INSTALLED -eq 1 ]]; then
            echo "model_extracted_dir: $MODEL_EXTRACTED_DIR"
            echo "model_files_sha256:"
            echo "$MODEL_FILES_SHA" | sed 's/^/  /'
        fi
    else
        echo "model_id: (none recorded; use --with-model)"
    fi
    echo ""
    echo "artifacts:"
    # list files in dist
    for f in "$OUT_DIR"/*; do
        [[ -e "$f" ]] || continue
        name="$(basename "$f")"
        [[ "$name" == "BUILD-INFO.txt" ]] && continue
        if [[ -f "$f" ]]; then
            sz="$(stat -c %s "$f" 2>/dev/null || echo 0)"
            sh="$(sha256sum "$f" | awk '{print $1}')"
            echo "  $name  size=$sz  sha256=$sh"
        elif [[ -d "$f" ]]; then
            sz="$(du -sb "$f" 2>/dev/null | awk '{print $1}')"
            echo "  $name/  size=$sz  (directory)"
        fi
    done
} > "$BUILD_INFO"
ok "wrote $BUILD_INFO"

# ---------------------------------------------------------------------------
# g. Summary table
# ---------------------------------------------------------------------------
step "g. Artifact summary"
printf '  %-46s %12s  %s\n' "artifact" "size(bytes)" "sha256"
for f in "$OUT_DIR"/*; do
    [[ -e "$f" ]] || continue
    name="$(basename "$f")"
    if [[ -f "$f" ]]; then
        sz="$(stat -c %s "$f" 2>/dev/null || echo 0)"
        sh="$(sha256sum "$f" | awk '{print $1}')"
        printf '  %-46s %12s  %s\n' "$name" "$sz" "$sh"
    elif [[ -d "$f" ]]; then
        sz="$(du -sb "$f" 2>/dev/null | awk '{print $1}')"
        printf '  %-46s %12s  %s\n' "$name/" "$sz" "(directory)"
    fi
done

if (( NO_PYINSTALLER == 0 && PYINSTALLER_OK == 0 )); then
    warn "PyInstaller bundle was NOT produced (see above). Exiting nonzero."
    exit 1
fi
exit 0
