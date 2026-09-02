# Skill and Host Routing

Inspect what the current host can actually invoke. Do not install or upgrade a dependency merely because it is preferred.

| Stage | Preferred skill | Fallback |
|---|---|---|
| `spec` | Waza `think` | Ask focused product, boundary, behavior, and acceptance questions; write the approved spec contract. |
| `plan-review` | gstack `plan-eng-review` | Perform an interactive engineering review covering architecture, data flow, failure modes, test strategy, rollout, and operational risks. |
| `implementation` | Project/domain skills plus the coding agent | Follow repository instructions and the approved plan directly. |
| `verification` | Waza `check` plus repository commands | Run repository-authoritative checks and produce the same evidence report. `check` does not replace actual test/build commands. |
| `reconstruction` | `understand-pr` in an isolated subagent | No in-context fallback. Report that independence cannot be guaranteed. |
| `intent-comparison` | Resume the same `understand-pr` subagent | If resumption is unavailable, a new isolated subagent may compare the fixed reconstruction and spec, but disclose the weaker continuity guarantee. |
| `deep-review` | claude-code-kit `deepening-review` | Narrow read-only hotspot analysis using the reconstruction vocabulary; never expand to a broad redesign. |
| `reviewer-map` | `reviewer-map` | Produce the artifact contract directly from the final diff and evidence. |
| `published` | Host Git/GitHub/GitLab skill or CLI | Use ordinary non-force Git and host APIs only after explicit authorization. |

## Codex

Invoke the orchestrator as `$feature-workflow`. For the cold reader, use a subagent with `fork_turns=none`; give it the `understand-pr` skill path and only base/head evidence. Persist the returned content in the parent. Send the second-pass intent comparison to that same agent when continuation is supported.

## Claude Code

Invoke the orchestrator as `/feature-workflow`. Skills are slash commands. For the cold reader, ask the Agent tool for a new non-forked `general-purpose` or custom subagent with `understand-pr` preloaded. Record its agent ID. Resume that ID for intent comparison. Do not use `/subtask` or a forked agent because a fork inherits the planning conversation; do not use Explore when the second pass must resume the same agent.

## Skill names

Some installations namespace third-party skills. Match by declared skill name and description rather than assuming a directory name. Examples include `plan-eng-review` versus `gstack-plan-eng-review`.

## Permission boundary

Planning and read-only analysis do not authorize:

- dependency installation;
- branch creation or switching;
- commits or pushes;
- issue, PR, review-comment, or merge mutations;
- deployment or release;
- destructive cleanup.

Ask at the point the action becomes necessary unless the user's current request already authorizes that exact class of action.
