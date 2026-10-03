#!/usr/bin/env bash
# BLAXCY installer — user-level, least-privilege, no root required.
#
# Local checkout:
#   ./install.sh [--root DIR] [--dry-run] [--no-venv] [--dev]
#
# One-line remote install (downloads the source, then installs it):
#   curl -fsSL https://raw.githubusercontent.com/alex3430143/blaxcyds/main/install.sh | bash
#
# The install never uses root, never writes outside --root/--prefix and
# ~/.local/bin, and never modifies any directory other than the one selected.
set -euo pipefail

DEFAULT_REPO="https://github.com/alex3430143/blaxcyds.git"
DEFAULT_REF="main"

SCRIPT_FILE="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""
if [ -n "$SCRIPT_FILE" ] && [ -f "$SCRIPT_FILE" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_FILE")" && pwd)"
fi

ROOT=""
PREFIX="${BLAXCY_HOME:-$HOME/.local/share/blaxcy}"
REPO="${BLAXCY_REPO:-$DEFAULT_REPO}"
REF="${BLAXCY_REF:-$DEFAULT_REF}"
DRY_RUN=0
NO_VENV=0
WITH_DEV=0
MINIMAL=0
WITH_LAUNCHER=1

usage() {
  cat <<'USAGE'
BLAXCY installer — user-level, least-privilege, no root required.

Local checkout:
  ./install.sh [--root DIR] [--dry-run] [--no-venv] [--dev]

One-line remote install:
  curl -fsSL https://raw.githubusercontent.com/alex3430143/blaxcyds/main/install.sh | bash

Options:
  --root DIR     install from DIR instead of this script's directory.
  --prefix DIR   where to download the source for a remote install
                 (default: $BLAXCY_HOME, else ~/.local/share/blaxcy).
  --repo URL     git remote to download from (default: the BLAXCY public repo).
  --ref REF      git branch/tag to download (default: main).
  --no-venv      install against the current interpreter instead of a local .venv.
  --minimal      install only the core package (skip optional extras).
  --dev          also install the development extras (pytest, ruff).
  --no-launcher  do not create ~/.local/bin/blaxcy.
  --dry-run      print exactly what would happen and change nothing.
  -h, --help     show this help.
USAGE
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --no-venv) NO_VENV=1; shift ;;
    --minimal) MINIMAL=1; shift ;;
    --dev) WITH_DEV=1; shift ;;
    --no-launcher) WITH_LAUNCHER=0; shift ;;
    -h|--help) usage 0 ;;
    *) echo "install.sh: unknown option: $1" >&2; usage 2 ;;
  esac
done

run() {
  if [ "$DRY_RUN" = "1" ]; then
    echo "  [dry-run] $*"
  else
    echo "  $*"
    "$@"
  fi
}

have() { command -v "$1" >/dev/null 2>&1; }

PY="${PYTHON:-python3}"
if ! have "$PY"; then
  echo "ERROR: python3 not found; BLAXCY needs Python 3.11+" >&2
  exit 1
fi

PY_MAJOR_MINOR="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo 0.0)"
PY_OK="$("$PY" -c 'import sys; print(1 if sys.version_info >= (3, 11) else 0)' 2>/dev/null || echo 0)"
if [ "$PY_OK" != "1" ]; then
  echo "ERROR: BLAXCY needs Python 3.11+ (found $PY_MAJOR_MINOR)" >&2
  exit 1
fi

is_checkout() { [ -f "$1/pyproject.toml" ] && [ -d "$1/blaxcy" ]; }

version() {
  [ -f "$ROOT/pyproject.toml" ] && \
    sed -n 's/^version *= *"\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1 || echo "unknown"
}

BOOTSTRAPPED=0
if [ -z "$ROOT" ]; then
  if [ -n "$SCRIPT_DIR" ] && is_checkout "$SCRIPT_DIR"; then
    ROOT="$SCRIPT_DIR"
  else
    # No checkout next to this script (e.g. `curl | bash`): download the source.
    ROOT="$PREFIX"
    BOOTSTRAPPED=1
  fi
fi

if [ "$BOOTSTRAPPED" = "1" ]; then
  echo "BLAXCY bootstrap → $ROOT"
  echo "  source: $REPO @ $REF"
  if [ -d "$ROOT/.git" ]; then
    run git -C "$ROOT" fetch --depth 1 origin "$REF"
    run git -C "$ROOT" checkout -q FETCH_HEAD
  elif have git; then
    if [ "$DRY_RUN" = "1" ]; then
      echo "  [dry-run] git clone --depth 1 --branch $REF $REPO $ROOT"
    else
      mkdir -p "$(dirname "$ROOT")"
      git clone --depth 1 --branch "$REF" "$REPO" "$ROOT"
    fi
  elif have curl; then
    tarball="${REPO%.git}/archive/refs/heads/$REF.tar.gz"
    if [ "$DRY_RUN" = "1" ]; then
      echo "  [dry-run] curl -fsSL $tarball | tar xz into $ROOT"
    else
      mkdir -p "$ROOT"
      curl -fsSL "$tarball" | tar xz -C "$ROOT" --strip-components=1
    fi
  else
    echo "ERROR: need git or curl to download BLAXCY" >&2
    exit 1
  fi
fi

if [ "$DRY_RUN" != "1" ] && ! is_checkout "$ROOT"; then
  echo "ERROR: $ROOT is not a BLAXCY checkout (no pyproject.toml + blaxcy/)" >&2
  exit 1
fi

# Optional feature groups, installed independently so that a wheel which will
# not build on this host never blocks the rest. Every feature degrades safely
# at runtime when its dependency is absent.
EXTRAS="control ui vision security browser"
[ "$MINIMAL" = "1" ] && EXTRAS=""
[ "$WITH_DEV" = "1" ] && EXTRAS="${EXTRAS:+$EXTRAS }dev"

pip_target() { if [ -n "$1" ]; then printf '%s' "${ROOT}[$1]"; else printf '%s' "$ROOT"; fi; }

pip_install_target() {
  local pip="$1" target="$2"
  if [ "$DRY_RUN" = "1" ]; then
    echo "  [dry-run] $pip -m pip install -e \"$target\""
    return 0
  fi
  echo "  $pip -m pip install -e \"$target\""
  "$pip" -m pip install -e "$target"
}

pip_install_all() {
  local pip="$1" group
  if ! pip_install_target "$pip" "$(pip_target "")"; then
    echo "ERROR: base package install failed" >&2
    return 1
  fi
  for group in $EXTRAS; do
    if ! pip_install_target "$pip" "$(pip_target "$group")"; then
      echo "  warning: extra '$group' failed to install; continuing without it" >&2
    fi
  done
  return 0
}

echo "BLAXCY install → $ROOT (version $(version))"

VENV="$ROOT/.venv"
if [ "$NO_VENV" = "1" ]; then
  echo "  --no-venv: using $PY (no virtual environment)"
  pip_install_all "$PY"
else
  if [ ! -d "$VENV" ]; then
    # --system-site-packages lets the Eye see the distro python3-gi / AT-SPI
    # bindings that are not installable from PyPI; the code degrades safely if
    # they are absent. Set BLAXCY_ISOLATED_VENV=1 to opt out.
    if [ "${BLAXCY_ISOLATED_VENV:-0}" = "1" ]; then
      run "$PY" -m venv "$VENV"
    else
      run "$PY" -m venv --system-site-packages "$VENV"
    fi
  else
    echo "  virtual environment already exists at $VENV"
  fi
  run "$VENV/bin/python" -m pip install --upgrade pip
  pip_install_all "$VENV/bin/python"
fi

run mkdir -p "$ROOT/.runtime" "$ROOT/logs"

if [ "$WITH_LAUNCHER" = "1" ] && [ "$NO_VENV" != "1" ]; then
  BIN_DIR="$HOME/.local/bin"
  LAUNCH_TARGET="$VENV/bin/blaxcy"
  run mkdir -p "$BIN_DIR"
  if [ "$DRY_RUN" = "1" ]; then
    echo "  [dry-run] ln -sf $LAUNCH_TARGET $BIN_DIR/blaxcy"
  else
    ln -sf "$LAUNCH_TARGET" "$BIN_DIR/blaxcy"
  fi
  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "  note: add $BIN_DIR to PATH to run 'blaxcy' from anywhere" ;;
  esac
fi

echo
if [ "$DRY_RUN" = "1" ]; then
  echo "Dry run complete. Nothing was changed."
else
  echo "Installed. Try:"
  if [ "$NO_VENV" != "1" ]; then
    echo "  source $VENV/bin/activate"
  fi
  echo "  blaxcy doctor"
  echo "  blaxcy ui        # control panel (needs PyQt6)"
  echo "  blaxcy run \"open a text editor and type hello\""
fi
