# Agent Workflow Skills

Portable Agent Skills for taking a feature from intent through implementation and making complicated pull requests easier to understand in Codex CLI and Claude Code.

## Included skills

- `understand-pr` reconstructs an unfamiliar PR from its code and diff before reading the author's rationale.
- `reviewer-map` turns a final PR into a human-first reading order with execution paths, semantic and mechanical diff groups, and complexity hotspots.
- `feature-workflow` orchestrates issue/idea shaping, plan review, implementation, verification, isolated reconstruction, intent comparison, reviewer mapping, human approval, and SHA-verified publication.

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
$feature-workflow start <issue URL or feature idea>
$understand-pr
$reviewer-map
```

In Claude Code:

```text
/feature-workflow start <issue URL or feature idea>
/understand-pr
/reviewer-map
```

Both tools may also select a skill automatically when the request matches its description.

The orchestrator prefers Waza `think` and `check`, gstack `plan-eng-review`, and claude-code-kit `deepening-review` when installed. They are optional adapters, not vendored runtime dependencies. The bundled `understand-pr` and `reviewer-map` skills provide the required comprehension stages.

## Update

Run `git pull` in the cloned repository. Because installation uses symlinks, both tools see the updated skill content without reinstalling.

## Uninstall

Remove only the six symlinks created by the installer:

```sh
rm ~/.agents/skills/feature-workflow
rm ~/.agents/skills/understand-pr
rm ~/.agents/skills/reviewer-map
rm ~/.claude/skills/feature-workflow
rm ~/.claude/skills/understand-pr
rm ~/.claude/skills/reviewer-map
```
