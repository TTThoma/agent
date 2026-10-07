# Skill and Host Routing

Use what the host can invoke. Missing skills are not permission to install them; use the fallback.

| Stage | Preferred | Fallback |
|---|---|---|
| `shape` research | parallel research subagents (read-only, word-capped returns) | direct research in the main thread |
| `shape` questions | `think` or `spec` for the agent-internal spec; the brief template for the human surface | brief template only |
| `build` | implementer subagent with `isolation: "worktree"`; reviewer subagents that report only | follow repository rules directly |
| `verification` | repository commands + `check` | repository commands |
| `cold-read` | `understand-pr` in an isolated, resumable subagent | none; disclose that independence is not guaranteed |
| `packet` | `reviewer-map` as input, condensed into the packet template | build the packet directly from the diff and evidence |
| `published` | host Git/GitHub CLI after explicit consent | — |

## Claude Code

- Invoke as `/feature-workflow`.
- Cold reader: an Agent call of type `general-purpose`, not a fork. Record its id and resume it with SendMessage for the comparison.
- Human decisions: one AskUserQuestion call with up to 3 questions. Each question has a "(Recommended)" first option and shows its concrete consequence in the option preview.

## Codex

- Invoke as `$feature-workflow`.
- Cold reader: a subagent with `fork_turns=none`.

## Permission boundary

Approval of a brief pre-authorizes filing its sub-issues, draft pushes, packet comments and follow-up issues. It never authorizes merge, deploy, spend beyond the brief's cap, dependency installs, branch deletion or force-pushes to shared branches.
