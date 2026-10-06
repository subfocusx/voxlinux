#!/usr/bin/env bash
#
# VoxLinux installer — voice dictation for Wayland + Hyprland.
#
#   ./install.sh              # install everything (asks before the model download)
#   ./install.sh --check      # environment report only, changes nothing
#   ./install.sh --uninstall  # remove launchers, unit and model
#
# What it does:
#   * creates ./.venv and installs requirements.txt into it
#   * installs the vox-ptt / voxlinux launchers into ~/.local/bin
#   * installs the systemd *user* unit (rendered from systemd/voxlinux.service)
#   * optionally: adds the user to the `input` group or a udev rule for the
#     keyboard, so push-to-talk works without any compositor config
#   * optionally: downloads the GigaAM v3 model (~163 MB)
#   * prints the Hyprland Lua bind that wires the hotkey to vox-ptt
#
set -euo pipefail

SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SRC_DIR/.venv"
BIN_DIR="${VOX_BIN_DIR:-$HOME/.local/bin}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_SRC="$SRC_DIR/systemd/voxlinux.service"
UNIT_DST="$UNIT_DIR/voxlinux.service"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
MODELS_DIR="$DATA_HOME/voxlinux/models"
MODEL_ID="gigaam-v3"
MODEL_DIR_NAME="sherpa-onnx-nemo-ctc-giga-am-v3-russian-2025-12-16"

MODE="install"
ASSUME_YES=0
DO_DEPS=0
DO_MODEL=1
DO_INPUT_GROUP=0
UDEV_DEVICE=""
UDEV_RULE=""
DO_SERVICE=1
PURGE_MODEL=0

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLU=$'\033[36m'; DIM=$'\033[2m'; RST=$'\033[0m'
if [[ ! -t 1 ]]; then RED=""; GRN=""; YEL=""; BLU=""; DIM=""; RST=""; fi

FAILURES=0
WARNINGS=0

ok()   { printf '  %s[ OK ]%s %s\n' "$GRN" "$RST" "$*"; }
bad()  { printf '  %s[FAIL]%s %s\n' "$RED" "$RST" "$*"; FAILURES=$((FAILURES + 1)); }
warn() { printf '  %s[WARN]%s %s\n' "$YEL" "$RST" "$*"; WARNINGS=$((WARNINGS + 1)); }
info() { printf '  %s[INFO]%s %s\n' "$BLU" "$RST" "$*"; }
step() { printf '\n%s%s%s\n' "$DIM" "$*" "$RST"; }
die()  { printf '%serror:%s %s\n' "$RED" "$RST" "$*" >&2; exit 2; }

usage() {
  cat <<EOF
usage: install.sh [options]

  --check            only run environment checks and print a report
  --uninstall        remove launchers, systemd unit and the downloaded model
  --yes, -y          do not ask questions (non-interactive)
  --deps             install missing system packages with sudo (pacman/apt)
  --model[=ID]       download the speech model (default: $MODEL_ID)
  --no-model         skip the model download
  --input-group      sudo usermod -aG input \$USER  (evdev hotkey, no compositor config)
  --udev-rule PATH   install a udev rule for that keyboard (e.g. /dev/input/by-id/...)
  --skip-service     do not install the systemd user unit
  --purge-model      with --uninstall: also delete the downloaded model
  -h, --help         this text

Environment: VOX_BIN_DIR (default ~/.local/bin) overrides the launcher directory.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)      MODE="check" ;;
    --uninstall)  MODE="uninstall" ;;
    --yes|-y)     ASSUME_YES=1 ;;
    --deps)       DO_DEPS=1 ;;
    --model)      DO_MODEL=1 ;;
    --model=*)    DO_MODEL=1; MODEL_ID="${1#*=}" ;;
    --no-model)   DO_MODEL=0 ;;
    --input-group) DO_INPUT_GROUP=1 ;;
    --udev-rule)  UDEV_DEVICE="${2:-}"; [[ -n "$UDEV_DEVICE" ]] || { shift; UDEV_DEVICE="${1:-}"; }
                  [[ -n "$UDEV_DEVICE" ]] || die "--udev-rule needs a device path"; UDEV_RULE=1 ;;
    --purge-model)   PURGE_MODEL=1 ;;
    --skip-service) DO_SERVICE=0 ;;
    -h|--help)    usage; exit 0 ;;
    *)            usage >&2; die "unknown option: $1" ;;
  esac
  shift
done

confirm() {
  (( ASSUME_YES )) && return 0
  local reply
  read -r -p "  $1 [y/N] " reply </dev/tty || return 1
  [[ $reply =~ ^[YyДд] ]]
}

have() { command -v "$1" >/dev/null 2>&1; }

venv_py() { [[ -x "$VENV_DIR/bin/python" ]] && echo "$VENV_DIR/bin/python" || echo "$VENV_DIR/bin/python3"; }

# ---------------------------------------------------------------------------
# Environment checks (shared by --check and the install path)
# ---------------------------------------------------------------------------

check_python() {
  local py=""
  have python3 && py="$(command -v python3)"
  [[ -n "$py" ]] || { bad "python3 not found — install Python 3.10+"; return; }
  local ver
  ver="$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0.0)"
  if "$py" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)' 2>/dev/null; then
    ok "python3 $ver ($py)"
  else
    bad "python3 $ver is too old, need 3.10+ ($py)"
  fi
}

check_session() {
  if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] || have hyprctl; then
    ok "Hyprland session (WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-unset})"
  elif [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
    warn "Wayland, but no Hyprland found — vox-ptt binds will not work"
  else
    bad "not a Wayland session — text insertion via wtype will fail"
  fi
}

check_tools() {
  local t
  for t in wtype paplay notify-send; do
    if have "$t"; then ok "$t → $(command -v "$t")"; else bad "$t not found (see --deps / package hints below)"; fi
  done
  if have hyprctl; then ok "hyprctl → $(command -v hyprctl)"; else warn "hyprctl not found — hotkey poll and binds unavailable"; fi
  if have systemctl; then ok "systemctl → $(command -v systemctl)"; else warn "systemctl not found — no systemd user service"; fi
}

check_portaudio() {
  # The venv is authoritative: sounddevice >= 0.5 ships its own PortAudio.
  if [[ -x "$VENV_DIR/bin/python" ]] && "$VENV_DIR/bin/python" -c 'import sounddevice' 2>/dev/null; then
    ok "PortAudio available to sounddevice (venv import succeeded)"
    return
  fi
  # No early-exit grep here: under `set -o pipefail` `grep -q` makes ldconfig die
  # on SIGPIPE and the whole pipeline reports failure.
  if ldconfig -p 2>/dev/null | grep -c libportaudio >/dev/null; then
    ok "libportaudio present in ldconfig"
  else
    warn "no PortAudio found — install portaudio, or sounddevice will fail to load"
  fi
}

check_input_access() {
  if [[ ! -d /dev/input ]]; then
    warn "/dev/input absent — no evdev hotkey, use a Hyprland bind"
    return
  fi
  if compgen -G '/dev/input/event*' >/dev/null 2>&1; then
    local readable=0 node
    for node in /dev/input/event*; do [[ -r $node ]] && { readable=1; break; }; done
    if (( readable )); then
      ok "/dev/input/event* readable — evdev push-to-talk works"
    else
      warn "no read access to /dev/input/event* — use a Hyprland bind or --input-group"
    fi
  else
    warn "no /dev/input/event* nodes — use a Hyprland bind"
  fi
}

check_venv() {
  local py
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    ok "venv at $VENV_DIR"
    py="$(venv_py)"
    "$py" -c 'import numpy, sounddevice' 2>/dev/null \
      && ok "numpy + sounddevice importable" \
      || warn "venv incomplete — re-run: ./install.sh"
    "$py" -c 'import sherpa_onnx' 2>/dev/null \
      && ok "sherpa-onnx importable" \
      || warn "sherpa-onnx not importable — re-run: ./install.sh"
    "$py" -c 'import evdev' 2>/dev/null \
      && ok "evdev importable (python-evdev installed)" \
      || info "evdev not installed — only needed for the no-binds hotkey"
  else
    info "no venv at $VENV_DIR yet — run ./install.sh"
  fi
}

check_entrypoint() {
  if entrypoint_module >/dev/null; then
    ok "worker entrypoint: $(entrypoint_module)"
  else
    warn "worker entrypoint not present (voxapp/daemon.py) — voxlinux launcher and the systemd unit stay disabled"
  fi
}

check_launchers() {
  local n
  for n in vox-ptt voxlinux; do
    if [[ -x "$BIN_DIR/$n" ]]; then ok "$BIN_DIR/$n"; else info "$BIN_DIR/$n not installed"; fi
  done
}

check_service() {
  if [[ ! -f "$UNIT_DST" ]]; then
    info "systemd unit not installed"
    return
  fi
  ok "systemd unit at $UNIT_DST"
  if have systemctl; then
    local state
    state="$(systemctl --user is-enabled voxlinux.service 2>/dev/null || true)"
    case "$state" in
      enabled) ok "voxlinux.service enabled" ;;
      disabled) warn "voxlinux.service installed but disabled" ;;
      *) warn "systemctl --user cannot query the unit ($state) — is a user session running?" ;;
    esac
  fi
}

check_model() {
  if [[ -f "$MODELS_DIR/$MODEL_DIR_NAME/model.int8.onnx" ]]; then
    ok "model $MODEL_ID installed at $MODELS_DIR/$MODEL_DIR_NAME"
  elif [[ -d "$MODELS_DIR/$MODEL_DIR_NAME" ]]; then
    warn "model dir present but model.int8.onnx missing — re-run with --model"
  else
    info "model $MODEL_ID not downloaded (~163 MB) — run ./install.sh --model"
  fi
}

entrypoint_module() {
  local cand
  for cand in voxapp/daemon.py voxapp/worker.py voxapp/__main__.py vox.py; do
    [[ -f "$SRC_DIR/$cand" ]] && { echo "$cand"; return 0; }
  done
  return 1
}

package_hints() {
  cat <<EOF
  Arch / Omarchy : sudo pacman -S --needed wtype libnotify pipewire-pulse python portaudio
  Debian/Ubuntu  : sudo apt install wtype libnotify-bin pipewire pulseaudio-utils python3 python3-venv portaudio19-dev
EOF
}

run_checks() {
  printf '%sVoxLinux environment report%s\n' "$BLU" "$RST"
  step "Session"
  check_session
  step "External tools"
  check_tools
  step "Audio backend"
  check_portaudio
  step "Keyboard access"
  check_input_access
  step "Python environment"
  check_python
  check_venv
  step "Application"
  check_entrypoint
  check_launchers
  check_service
  check_model

  step "Summary"
  printf '  failures: %s%d%s   warnings: %s%d%s\n' \
    "$( ((FAILURES)) && printf '%s' "$RED" || printf '%s' "$GRN")" "$FAILURES" "$RST" \
    "$( ((WARNINGS)) && printf '%s' "$YEL" || printf '%s' "$GRN")" "$WARNINGS" "$RST"
  if (( FAILURES )); then
    printf '\n%sMissing packages%s\n' "$YEL" "$RST"
    package_hints
    printf '  or re-run with: %s./install.sh --deps%s\n' "$DIM" "$RST"
    return 1
  fi
  printf '  %senvironment is ready%s\n' "$GRN" "$RST"
  return 0
}

# ---------------------------------------------------------------------------
# Install steps
# ---------------------------------------------------------------------------

install_deps() {
  local missing=()
  have wtype || missing+=(wtype)
  have notify-send || missing+=(libnotify)
  have paplay || missing+=(pipewire-pulse)
  if (( ${#missing[@]} )); then
    step "System packages"
    info "missing: ${missing[*]}"
    if have pacman; then
      if confirm "install them with sudo pacman?"; then
        sudo pacman -S --needed --noconfirm "${missing[@]}"
      else
        warn "skipped — install manually:"; package_hints
      fi
    else
      warn "no pacman — install manually:"; package_hints
    fi
  fi
}

make_venv() {
  step "Virtualenv"
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    ok "reusing $VENV_DIR"
  else
    local py="python3"
    "$py" -m venv "$VENV_DIR" || {
      warn "python3 -m venv failed (install python3-venv); trying virtualenv"
      "$py" -m pip install --user virtualenv
      "$py" -m virtualenv "$VENV_DIR"
    }
    ok "created $VENV_DIR"
  fi
  local py; py="$(venv_py)"
  "$py" -m pip install --upgrade pip setuptools wheel
  "$py" -m pip install -r "$SRC_DIR/requirements.txt"
  # python-evdev is only needed on the evdev hotkey path, which the user opts
  # into explicitly (--input-group / --udev-rule). With Hyprland binds it is
  # dead weight, so it is not pulled in by default.
  if (( DO_INPUT_GROUP )) || [[ -n "$UDEV_RULE" ]]; then
    "$py" -m pip install evdev
    ok "python-evdev installed (evdev push-to-talk)"
  fi
  ok "dependencies installed"
}

install_launchers() {
  step "Launchers in $BIN_DIR"
  mkdir -p "$BIN_DIR"
  local py; py="$(venv_py)"

  cat > "$BIN_DIR/vox-ptt" <<EOF
#!/usr/bin/env bash
# Generated by voxlinux/install.sh — sends a push-to-talk command to the worker.
export PYTHONPATH="$SRC_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$py" "$SRC_DIR/scripts/vox-ptt" "\$@"
EOF
  chmod +x "$BIN_DIR/vox-ptt"
  ok "installed $BIN_DIR/vox-ptt"

  local module
  if module="$(entrypoint_module)"; then
    cat > "$BIN_DIR/voxlinux" <<EOF
#!/usr/bin/env bash
# Generated by voxlinux/install.sh — the dictation worker (systemd ExecStart).
export PYTHONPATH="$SRC_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$py" -m ${module%.py} "\$@"
EOF
    chmod +x "$BIN_DIR/voxlinux"
    ok "installed $BIN_DIR/voxlinux (entry: $module)"
  else
    rm -f "$BIN_DIR/voxlinux"
    warn "no worker entrypoint in the tree yet (expected voxapp/daemon.py) — $BIN_DIR/voxlinux not installed"
  fi
}

install_service() {
  step "systemd user unit"
  (( DO_SERVICE )) || { info "skipped (--skip-service)"; return; }
  [[ -f "$UNIT_SRC" ]] || { warn "missing $UNIT_SRC"; return; }
  mkdir -p "$UNIT_DIR"
  # %h/%t are systemd specifiers; render them so the file is readable on its own.
  sed -e "s|%h|$HOME|g" -e "s|%t|${XDG_RUNTIME_DIR:-/run/user/$(id -u)}|g" \
    "$UNIT_SRC" > "$UNIT_DST"
  ok "installed $UNIT_DST"
  if ! have systemctl; then warn "no systemctl — enable it manually"; return; fi
  systemctl --user daemon-reload
  if [[ -x "$BIN_DIR/voxlinux" ]]; then
    if confirm "enable and start voxlinux.service now?"; then
      systemctl --user enable --now voxlinux.service
      systemctl --user --no-pager status voxlinux.service || true
    else
      info "enable later: systemctl --user enable --now voxlinux.service"
    fi
  else
    warn "service left disabled — the worker entrypoint (voxapp/daemon.py) is missing"
  fi
}

setup_input() {
  step "Keyboard access (optional)"
  if (( DO_INPUT_GROUP )); then
    if id -nG | tr ' ' '\n' | grep -qx input; then
      ok "already in the input group (re-login to pick it up)"
    elif confirm "sudo usermod -aG input $USER ? (re-login required)"; then
      sudo usermod -aG input "$USER"
      warn "added to the input group — log out and back in"
    else
      info "skipped; Hyprland binds work without it"
    fi
  fi
  if [[ -n "$UDEV_DEVICE" ]]; then
    [[ -e "$UDEV_DEVICE" ]] || die "no such device: $UDEV_DEVICE"
    local kernel; kernel="$(basename "$(readlink -f "$UDEV_DEVICE")")"
    local rule=/etc/udev/rules.d/99-vox-input.rules
    if confirm "install $rule for $kernel (needs sudo)?"; then
      sudo tee "$rule" >/dev/null <<EOF
# Vox — seat access to the push-to-talk keyboard (no group membership needed).
KERNELS=="$kernel", SUBSYSTEM=="input", ENV{ID_INPUT}=="1", TAG+="uaccess", MODE="0660"
EOF
      sudo udevadm control --reload-rules && sudo udevadm trigger
      ok "udev rule installed — unplug/replug the keyboard"
    else
      info "skipped udev rule"
    fi
  fi
}

install_model() {
  step "Speech model"
  if [[ -d "$MODELS_DIR/$MODEL_DIR_NAME/model.int8.onnx" ]]; then
    ok "already installed: $MODELS_DIR/$MODEL_DIR_NAME"
    return
  fi
  (( DO_MODEL )) || { info "skipped (--no-model)"; return; }
  confirm "download $MODEL_ID (~163 MB)?" || { info "skipped"; return; }
  mkdir -p "$MODELS_DIR"
  PYTHONPATH="$SRC_DIR" "$(venv_py)" - "$MODEL_ID" <<'PY'
import sys
from voxapp.downloader import download_model
from voxapp.registry import MODELS

model_id = sys.argv[1]
state = {"last": -1}

def progress(done, total, stage):
    if total > 0:
        pct = int(done * 100 / total)
        if pct != state["last"]:
            state["last"] = pct
            print(f"\r  {stage}: {pct:3d}% ({done // (1 << 20)}/{total // (1 << 20)} MiB)", end="", flush=True)

print(f"  {MODELS[model_id]['name']} — {MODELS[model_id]['size_mb']} MB")
download_model(model_id, on_progress=progress, on_log=lambda m: print(f"  {m}"))
print()
PY
  ok "model installed in $MODELS_DIR/$MODEL_DIR_NAME"
}

print_bind_hint() {
  cat <<EOF

${BLU}Hyprland hotkey${RST}
  vox-ptt is on your PATH now. Add to ~/.config/hypr/bindings.lua (Hyprland 0.56 / Lua config):

      -- push-to-talk on right Ctrl (press + release)
      o.bind("Right",         "Vox: start", "vox-ptt start")
      o.bind("Right",         "Vox: stop",  "vox-ptt stop")

      -- or one line, if you prefer the hold command
      o.bind("Right",         "Vox: talk",  "vox-ptt hold Right")

      -- combo that does not clash with anything
      o.bind("SUPER SHIFT D", "Vox: toggle","vox-ptt toggle")

  Then: hyprctl reload   (and ${BIN_DIR} must be in your PATH)
  If you added $USER to the input group, drop the binds entirely — Vox
  reads KEY_RCTRL from the keyboard itself.
EOF
}

do_install() {
  printf '%sVoxLinux installer%s  (%s)\n' "$BLU" "$RST" "$SRC_DIR"
  (( DO_DEPS )) && install_deps
  make_venv
  install_launchers
  setup_input
  install_model
  install_service

  step "Verification"
  run_checks || true
  print_bind_hint
}

do_uninstall() {
  printf '%sVoxLinux uninstaller%s\n' "$BLU" "$RST"
  step "Files"
  for n in vox-ptt voxlinux; do
    if [[ -f "$BIN_DIR/$n" ]] && grep -q "voxlinux/install.sh" "$BIN_DIR/$n"; then
      rm -f "$BIN_DIR/$n"; ok "removed $BIN_DIR/$n"
    else
      info "$BIN_DIR/$n not installed by us — kept"
    fi
  done
  if [[ -f "$UNIT_DST" ]]; then
    have systemctl && systemctl --user disable --now voxlinux.service 2>/dev/null || true
    rm -f "$UNIT_DST"; ok "removed $UNIT_DST"
  else
    info "no systemd unit"
  fi
  # Deleting a re-downloadable 163 MB model is opt-in only: `--yes` must never
  # destroy it as a side effect of removing the launchers.
  if [[ -d "$MODELS_DIR/$MODEL_DIR_NAME" ]]; then
    if (( PURGE_MODEL )); then
      rm -rf "$MODELS_DIR/$MODEL_DIR_NAME"; ok "model $MODEL_ID removed"
    else
      info "model kept (~163 MB) — pass --purge-model to delete it"
    fi
  fi
  info "the .venv ($VENV_DIR) and ~/.local/share/voxlinux (db, config, logs) were kept — delete them by hand"
}

case "$MODE" in
  check)     run_checks ;;
  uninstall) do_uninstall ;;
  install)   do_install ;;
esac