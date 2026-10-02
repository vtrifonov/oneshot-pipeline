#!/usr/bin/env bash
# Symlink every item in this repo into the live Claude Code config.
#
# One symlink per item, never a symlink over a whole directory: the real
# ~/.claude/agents and ~/.agents/skills keep holding machine-local
# (employer-specific) items alongside the ones linked from here.
#
# Idempotent. Refuses to replace a real file or directory.

set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
config_root=${CLAUDE_CONFIG_DIR:-"${HOME}/.claude"}

# ~/.claude/skills is itself a symlink to ~/.agents/skills on this machine;
# resolve it so links land on the real directory either way.
skills_target=$(cd -- "${config_root}/skills" 2>/dev/null && pwd -P || echo "${config_root}/skills")
agents_target="${config_root}/agents"
bin_target="${config_root}/bin"
hooks_target="${config_root}/hooks"

linked=0
skipped=0

link_one() {
  local src=$1 dest=$2

  if [ -L "$dest" ]; then
    local current
    current=$(readlink "$dest")
    if [ "$current" = "$src" ]; then
      return 0
    fi
    ln -sfn "$src" "$dest"
    printf 'relinked %s\n' "$dest"
    linked=$((linked + 1))
    return 0
  fi

  if [ -e "$dest" ]; then
    printf 'SKIP    %s (real file or directory already there)\n' "$dest" >&2
    skipped=$((skipped + 1))
    return 0
  fi

  ln -s "$src" "$dest"
  printf 'linked  %s\n' "$dest"
  linked=$((linked + 1))
}

link_dir_of() {
  local subdir=$1 target=$2 pattern=$3

  [ -d "${repo_root}/${subdir}" ] || return 0
  mkdir -p "$target"

  local src
  for src in "${repo_root}/${subdir}"/${pattern}; do
    [ -e "$src" ] || continue
    if [ "$subdir" = skills ] && [ ! -f "$src/SKILL.md" ]; then
      continue
    fi
    case "$(basename -- "$src")" in
      .gitkeep) continue ;;
    esac
    link_one "$src" "${target}/$(basename -- "$src")"
  done
}

link_dir_of skills   "$skills_target"   '*'
link_dir_of agents   "$agents_target"   '*.md'
link_dir_of bin      "$bin_target"      '*'
mkdir -p "$hooks_target"
link_one "${repo_root}/bin/block-full-suite.sh" "${hooks_target}/block-full-suite.sh"

printf '\n%d linked, %d skipped\n' "$linked" "$skipped"
printf 'Restart Claude Code to load skills and pr-shepherd. Optional hook registration: skills/oneshot-pipeline/reference/distribution.md\n'
