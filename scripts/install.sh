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

# Astral's installer puts uv on ~/.local/bin. Do not print the environment.
export PATH="${HOME:-}/.local/bin:${PATH:-}"

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

run_cmd uv tool install "$SPEC"
export PATH="${HOME:-}/.local/bin:${PATH:-}"

if [ "$ASSUME_YES" = 1 ]; then
  run_cmd swag setup --auto --yes
else
  run_cmd swag setup --auto
fi

if [ $# -gt 0 ]; then
  run_cmd swag "$@"
fi
