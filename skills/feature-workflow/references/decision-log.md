# Decision Log

One log per project (a parent issue or a multi-PR initiative), not one per run. Every run reads it at start and writes to it. It is the only channel through which a decision becomes binding.

## Location

Use the first that exists:
1. A path the repository names (e.g. `docs/decisions/<project>.md`), committed with the T0 docs PR.
2. A single pinned comment on the parent GitHub issue, edited in place.
3. `git rev-parse --git-path feature-workflow/_decisions/<project>.md` for local-only work.

## Format

```markdown
# Decisions: <project>   (parent: <issue>)

| id | date | decision (one line) | by | scope | supersedes |
|----|------|---------------------|----|-------|------------|
| P3 | 2026-01-12 | One meter per vendor, priced per unit at best published rate | human | all vendors | P1 |
| A7 | 2026-01-13 | Override allowlist: only q, limit, lang reach the vendor | agent (vetoable) | vendor A | — |

## Escapes
| date | bug | should have been caught by | fix to process |
```

- `by`: `human`, `human (direct, <worker>)` for an answer given inside a worker session, or `agent (vetoable)`. An agent decision becomes binding when the human approves the brief or packet that lists it.
- `scope` determines inheritance: a run inherits every decision whose scope covers it and lists the ids in its brief's "Inherited" section. This prevents losses like the capability-list decision (`services += <new capability>`) that the pilot spec never carried forward.
- Supersede with a new row; never edit a decided row's meaning.

## Writers

- In a single-session run, the run writes the log directly.
- With an orchestrator, workers propose rows and the orchestrator writes them. A decision heard through a relay is not acted on until its row exists.
- Exception: when the human answers a worker directly, about a decision scoped to that worker's sub-issue, the worker writes the row at once and tells the orchestrator. See `orchestration.md`.
- Before asking the human anything, search the log. If the answer is there, cite the id instead of asking.
