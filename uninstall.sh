#!/usr/bin/env bash
# BLAXCY uninstall. Removes install artifacts but keeps your data by default.
#
#   ./uninstall.sh [--root DIR] [--dry-run] [--yes] [--purge]
#
# --purge   also delete user data (.runtime/, .build-state/, logs/).
# --yes     confirm real deletion (without it, nothing is removed).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${BLAXCY_ROOT:-$SCRIPT_DIR}"
DRY_RUN=0
ASSUME_YES=0
PURGE=0

usage() { sed -n '2,7p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    --purge) PURGE=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "uninstall.sh: unknown option: $1" >&2; usage 2 ;;
  esac
done

remove() {
  local target="$1"
  [ -e "$target" ] || return 0
  if [ "$DRY_RUN" = "1" ]; then
    echo "  [dry-run] rm -rf $target"
  else
    echo "  rm -rf $target"
    rm -rf "$target"
  fi
}

PREVIEW=0
if [ "$DRY_RUN" != "1" ] && [ "$ASSUME_YES" != "1" ]; then
  echo "No --yes given: showing what would be removed (nothing will be deleted)."
  DRY_RUN=1
  PREVIEW=1
fi

echo "BLAXCY uninstall → $ROOT"
echo "  removing install artifacts"
remove "$ROOT/.venv"
remove "$ROOT/build"
remove "$ROOT/dist"
find "$ROOT" -maxdepth 2 -name '*.egg-info' -type d 2>/dev/null | while read -r egg; do
  remove "$egg"
done
find "$ROOT/blaxcy" -name '__pycache__' -type d 2>/dev/null | while read -r pyc; do
  remove "$pyc"
done

if [ "$PURGE" = "1" ]; then
  echo "  --purge: removing user data"
  remove "$ROOT/.runtime"
  remove "$ROOT/.build-state"
  remove "$ROOT/logs"
else
  echo "  keeping user data (.runtime, .build-state, logs) — use --purge to remove"
fi

if [ "$DRY_RUN" = "1" ]; then
  echo "Dry run complete. Nothing was changed."
  [ "$PREVIEW" = "1" ] && exit 3 || exit 0
fi
echo "Uninstall complete."
