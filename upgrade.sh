#!/usr/bin/env bash
# BLAXCY upgrade. Re-installs the package in place, preserving user data.
#
#   ./upgrade.sh [--root DIR] [--dry-run]
#
# User data (.runtime/, .build-state/, logs/) is NEVER touched by an upgrade.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${BLAXCY_ROOT:-$SCRIPT_DIR}"
DRY_RUN=0

usage() { sed -n '2,6p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "upgrade.sh: unknown option: $1" >&2; usage 2 ;;
  esac
done

if [ ! -f "$ROOT/pyproject.toml" ]; then
  echo "ERROR: no pyproject.toml at $ROOT (not a BLAXCY root)" >&2
  exit 1
fi

version() { sed -n 's/^version *= *"\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1; }

echo "BLAXCY upgrade → $ROOT (version $(version))"
for keep in ".runtime" ".build-state" "logs"; do
  [ -e "$ROOT/$keep" ] && echo "  preserving $keep"
done

VENV="$ROOT/.venv"
if [ "$DRY_RUN" = "1" ]; then
  echo "  [dry-run] (cd $ROOT && ${VENV}/bin/python -m pip install --upgrade -e '.[control,ui,dev]')"
  echo "Dry run complete. Nothing was changed."
  exit 0
fi

if [ -x "$VENV/bin/python" ]; then
  (cd "$ROOT" && "$VENV/bin/python" -m pip install --upgrade -e '.[control,ui,dev]')
elif command -v python3 >/dev/null 2>&1; then
  echo "  no .venv found; running the installer first"
  "$ROOT/install.sh" --root "$ROOT"
else
  echo "ERROR: no .venv and no python3 available" >&2
  exit 1
fi

echo "Upgrade complete. Try: blaxcy doctor"
