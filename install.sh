#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
destination_home=${1:-"$HOME"}

link_skill() {
  source_path=$1
  target_path=$2

  if [ -L "$target_path" ]; then
    current_target=$(readlink "$target_path")
    if [ "$current_target" = "$source_path" ]; then
      printf 'Already installed: %s\n' "$target_path"
      return
    fi
    printf 'Refusing to replace existing symlink: %s -> %s\n' "$target_path" "$current_target" >&2
    exit 1
  fi

  if [ -e "$target_path" ]; then
    printf 'Refusing to replace existing path: %s\n' "$target_path" >&2
    exit 1
  fi

  ln -s "$source_path" "$target_path"
  printf 'Installed: %s -> %s\n' "$target_path" "$source_path"
}

mkdir -p "$destination_home/.agents/skills" "$destination_home/.claude/skills"

for skill_dir in "$repository_dir"/skills/*; do
  [ -f "$skill_dir/SKILL.md" ] || continue
  skill_name=$(basename "$skill_dir")
  link_skill "$skill_dir" "$destination_home/.agents/skills/$skill_name"
  link_skill "$skill_dir" "$destination_home/.claude/skills/$skill_name"
done

printf '\nSkills are ready for Codex CLI and Claude Code.\n'
