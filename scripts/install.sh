#!/bin/sh
# One-command install for Swag Bot.
#
# Asks before installing uv. Never installs Ollama or a model by itself.
# `swag setup --auto` asks again before a model download unless you pass --yes.
#
# Keep PYPI_PUBLISHED and GIT_INSTALL_URL identical to
# src/swag_bot/onboarding/distribution.py. tests/onboarding/test_distribution.py
# fails when they drift.
set -eu

PYPI_PUBLISHED=0
GIT_INSTALL_URL="git+https://github.com/vishnu-Swagan/swag-bot"

DRY_RUN=0
ASSUME_YES=0

usage() {
  cat <<'EOF'
Usage: install.sh [--dry-run] [--yes] [--] [swag arguments]

Install uv after asking, install Swag Bot, run `swag setup --auto`, then
run `swag` with any remaining arguments.

  sh scripts/install.sh --yes -- run "Write hello.txt"

--dry-run prints the commands and does not install or download anything.
--yes skips the questions (uv install and the model pull).
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --yes | -y)
      ASSUME_YES=1
      shift
      ;;
    --help | -h)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

if [ "$PYPI_PUBLISHED" = 1 ]; then
  SPEC="swag-bot[mcp,models]"
else
  SPEC="swag-bot[mcp,models] @ ${GIT_INSTALL_URL}"
fi

# Optional git ref, for example SWAG_REF=v0.2.0 or a branch name.
# PEP 508 allows @ref only on a direct git URL.
if [ -n "${SWAG_REF:-}" ]; then
  case "$SPEC" in
    *git+*) SPEC="${SPEC}@${SWAG_REF}" ;;
  esac
fi

say() {
  printf '%s\n' "$1"
}

run_cmd() {
  if [ "$DRY_RUN" = 1 ]; then
    printf 'would run:'
    for arg in "$@"; do
      printf ' %s' "$arg"
    done
    printf '\n'
    return 0
  fi
  "$@"
}

ask() {
  question=$1
  if [ "$ASSUME_YES" = 1 ]; then
    return 0
  fi
  if [ ! -r /dev/tty ]; then
    echo "No terminal is available to ask: $question" >&2
    echo "Re-run with --yes if you want to continue without prompts." >&2
    return 1
  fi
  printf '%s [y/N] ' "$question" >/dev/tty
  read -r reply </dev/tty || return 1
  case "$reply" in
    y | Y | yes | YES) return 0 ;;
    *) return 1 ;;
  esac
}

# Astral's installer puts uv on ~/.local/bin. Remember the caller's PATH
# before this prepend. `uv tool update-shell` treats a directory that is
# already on PATH as persisted, so it must see the original PATH.
ORIGINAL_PATH="${PATH:-}"
export PATH="${HOME:-}/.local/bin:${ORIGINAL_PATH}"

if ! command -v uv >/dev/null 2>&1; then
  if [ "$DRY_RUN" = 1 ]; then
    say "would run: curl -LsSf https://astral.sh/uv/install.sh | sh"
  elif ask "Install uv from https://astral.sh/uv/install.sh ?"; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME:-}/.local/bin:${PATH:-}"
  else
    echo "uv is required. Install it from https://docs.astral.sh/uv/, then re-run this script." >&2
    exit 2
  fi
fi

say "Model choices (local and free cloud): https://github.com/vishnu-Swagan/swag-bot/blob/main/docs/MODELS.md"

run_cmd uv tool install --quiet "$SPEC"

BIN_DIR="${HOME:-}/.local/bin"
if [ "$DRY_RUN" = 1 ]; then
  say "would run: uv tool update-shell"
else
  UV_BIN=$(command -v uv || true)
  if [ -n "$UV_BIN" ]; then
    DISCOVERED=$("$UV_BIN" tool dir --bin 2>/dev/null || true)
    if [ -n "$DISCOVERED" ]; then
      BIN_DIR=$DISCOVERED
    fi
    # Invoke uv by path so PATH can be the caller's original value.
    PATH="${ORIGINAL_PATH}" "$UV_BIN" tool update-shell >/dev/null 2>&1 || true
  fi
fi
export PATH="${BIN_DIR}:${PATH:-}"
case ":${ORIGINAL_PATH}:" in
  *":${BIN_DIR}:"*) ;;
  *)
    say "swag is not on PATH for new shells yet. Open a new shell, or add it for this one:"
    say "  export PATH=\"${BIN_DIR}:\$PATH\""
    say "uv tool update-shell records that directory when it is missing from PATH."
    ;;
esac

SWAG_BIN="${BIN_DIR}/swag"
if [ "$ASSUME_YES" = 1 ]; then
  run_cmd "$SWAG_BIN" setup --auto --yes
else
  run_cmd "$SWAG_BIN" setup --auto
fi

if [ $# -gt 0 ]; then
  run_cmd "$SWAG_BIN" "$@"
fi
