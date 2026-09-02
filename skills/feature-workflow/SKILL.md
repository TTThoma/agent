---
name: feature-workflow
description: Orchestrate an issue or feature idea through decision-complete planning, implementation, verification, fresh-context reconstruction, intent comparison, reviewer mapping, human approval, and publication. Use when a change needs a reusable, evidence-backed workflow rather than a single coding pass.
---

# Feature Workflow

Coordinate the work; do not impersonate every specialist in one undifferentiated pass. Each stage has one goal, explicit inputs, an inspectable output, and an exit gate. Preserve user authority at interactive and externally mutating gates.

## Start or resume

Interpret the invocation as one of:

- **start** — a GitHub issue, local issue text, or feature idea begins a new run;
- **resume** — continue the named or only active run from its first incomplete or stale stage;
- **status** — report current, missing, and stale artifacts without changing code or external state.

Before starting, establish the repository root, base ref, current branch, clean/dirty state, and source request. Do not fetch, create an issue, create or switch branches, commit, push, open a PR, merge, deploy, or install dependencies unless the user has authorized that action. Prefer a dedicated branch or worktree so unrelated changes cannot contaminate the candidate.

Use `scripts/workflow_state.py` for the run ledger when Python and Git are available. It stores artifacts under the worktree's Git metadata by default, so analytical outputs do not change the commit they describe:

```text
python3 <skill-dir>/scripts/workflow_state.py init --slug <slug> --source <issue-or-idea> --base-ref <base>
python3 <skill-dir>/scripts/workflow_state.py status --slug <slug>
python3 <skill-dir>/scripts/workflow_state.py record --slug <slug> --artifact <name> [--path <file>]
```

Use `--state-dir <path>` only when the user or repository has chosen a different artifact location. If the helper is unavailable, maintain the same fields and invalidation rules manually using [references/artifact-contracts.md](references/artifact-contracts.md).

## Operating rules

1. Read [references/stage-contracts.md](references/stage-contracts.md) before executing or resuming a run. Execute stages in dependency order; a later stage never repairs an earlier failed gate by assumption.
2. Inspect available skills once. Use the adapters in [references/skill-routing.md](references/skill-routing.md). Missing third-party skills are not permission to install them; use the documented fallback or report the missing capability.
3. Interactive stages may end with questions instead of a file. Resume the same stage after the answers, and record its artifact only when the exit gate is met.
4. The orchestrator owns persistence and state. Specialist skills return content; the orchestrator writes the artifact, adds identity metadata, and records it in the ledger.
5. Keep planning intent away from the cold reader until reconstruction is complete. Fresh context is a process boundary, not a request to ignore visible conversation text.
6. Treat any implementation or worktree change after verification as invalidating verification and every downstream artifact. Re-run ledger status after edits, commits, rebases, or base updates.
7. A human approval applies only to the recorded candidate base/head. Never transfer approval to a different commit.

## Fresh-context boundary

For `reconstruction`, create a new non-forked, read-only subagent. Give it only the repository root, base SHA, head SHA, and the `understand-pr` instructions. Do not give it the issue, spec, PR body, planning transcript, commit messages, or author rationale.

- In Codex, dispatch with no inherited turns (`fork_turns=none`) when supported.
- In Claude Code, use a resumable `general-purpose` or custom subagent, not a conversation fork and not the one-shot Explore agent. Preload `understand-pr` when supported.

The parent records the returned reconstruction. Then resume the same subagent for `intent-comparison`, supplying the approved spec and source request only after the initial reconstruction is fixed. If the host cannot provide an isolated resumable agent, stop and disclose that the independence gate cannot be guaranteed; do not silently run the cold read in the main context.

## Candidate and review loop

The candidate gate requires a clean worktree and a committed HEAD. Record `candidate` only when verification and intent comparison are current and all material discrepancies are resolved or explicitly accepted.

Generate `reviewer-map` against that candidate. Open a draft PR only when authorized, then obtain human review. A requested code change routes back to implementation and invalidates `implementation` onward. Regenerate the downstream chain before asking for approval again.

Before publication or merge, compare:

- recorded candidate HEAD;
- local HEAD;
- remote branch HEAD;
- PR head SHA, when applicable;
- human-approved SHA.

Stop on any mismatch. Publish or merge only through a host-specific tool the user has authorized. Record `published` only after the external result and commit identity are verified.

## Completion report

Report the run slug, source, base/head, current stage, artifacts and paths, verification result, unresolved decisions, stale outputs, and any external URLs. Distinguish:

- **complete** — the authorized terminal action succeeded for the approved SHA;
- **waiting** — an interactive or human gate needs a response;
- **blocked** — a required capability or gate cannot be satisfied;
- **in progress** — safe work remains and no response is currently required.

Do not claim completion merely because code exists or a branch was pushed.
