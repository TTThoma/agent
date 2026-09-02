# PR Comprehension Skills

Portable Agent Skills for understanding complicated pull requests in Codex CLI and Claude Code.

## Included skills

- `understand-pr` reconstructs an unfamiliar PR from its code and diff before reading the author's rationale.
- `reviewer-map` turns a final PR into a human-first reading order with execution paths, semantic and mechanical diff groups, and complexity hotspots.

The canonical packages live in `skills/`. The checked-in `.agents/skills/` and `.claude/skills/` links make them available when either tool is launched inside this repository.

## Install for your user account

Clone the repository and run:

```sh
./install.sh
```

The installer creates non-destructive symlinks in:

- `~/.agents/skills/` for Codex CLI
- `~/.claude/skills/` for Claude Code

It refuses to replace an existing file, directory, or different symlink with the same skill name. Restart an already-running CLI if the new skills do not appear immediately.

## Invoke

In Codex CLI:

```text
$understand-pr
$reviewer-map
```

In Claude Code:

```text
/understand-pr
/reviewer-map
```

Both tools may also select a skill automatically when the request matches its description.

## Update

Run `git pull` in the cloned repository. Because installation uses symlinks, both tools see the updated skill content without reinstalling.

## Uninstall

Remove only the four symlinks created by the installer:

```sh
rm ~/.agents/skills/understand-pr
rm ~/.agents/skills/reviewer-map
rm ~/.claude/skills/understand-pr
rm ~/.claude/skills/reviewer-map
```
