# Decision Log

One log per project (a parent issue or a multi-PR initiative), not one per run. Every run reads it at start and writes to it through its owner. It is the only channel through which a decision becomes binding.

The header names one owner session for the project, not per run. Every other session, including concurrent runs, sends rows to the owner. An owner change is itself a row (`owner: A → B`). When the owner session ends, the human names the next owner; until then rows queue in the sender's brief as pending, not as decisions. There is no second file: briefs, sub-issues and notes cite log ids and hold no decided rows. Evidence from a 2026 pilot: decision ids lived on a parent issue while rows went into a brief, and the two drifted apart.

## Location

Use the first that exists:
1. A path the repository names (e.g. `docs/decisions/<project>.md`), committed with the T0 docs PR.
2. A single pinned comment on the parent GitHub issue, edited in place.
3. `git rev-parse --git-path feature-workflow/_decisions/<project>.md` for local-only work.

## Format

```markdown
# Decisions: <project>   (parent: <issue>; owner: <session>)

| id | date | decision (one line) | by | scope | supersedes |
|----|------|---------------------|----|-------|------------|
| P3 | 2026-01-12 | One meter per vendor, priced per unit at best published rate | human | all vendors | P1 |
| A7 | 2026-01-13 | Override allowlist: only q, limit, lang reach the vendor | agent (vetoable) | vendor A | — |

## Escapes
| date | bug | should have been caught by | fix to process |
```

- `by`: `human`, `human (direct, <worker>)` with `reported-by: <worker>` for an answer given inside a worker session, or `agent (vetoable)`. An agent decision becomes binding when the human approves the brief or packet that lists it.
- `scope` determines inheritance: a run inherits every decision whose scope covers it and lists the ids in its brief's "Inherited" section. This prevents losses like the capability-list decision (`services += <new capability>`) that the pilot spec never carried forward.
- Supersede with a new row; never edit a decided row's meaning.

## Writers

- Only the owner writes the log; other sessions and workers send it rows.
- A decision heard through a relay (a peer session, a forwarded summary) is confirmed with the human before anyone acts on it, and is not acted on until its row exists. The confirmation counts toward the ≤3-question cap.
- When the human answers a worker directly, about a decision scoped to that worker's sub-issue, the worker sends the row with the answer verbatim and where it was given; the owner appends it tagged `reported-by: <worker>` and the next digest lists it as vetoable. See `orchestration.md`.
- Before asking the human anything, search the log. If the answer is there, cite the id instead of asking.
