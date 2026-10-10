# Orchestration Modes

## Default: one session plus subagents

The run's session is the orchestrator. It spawns subagents for research, implementation (in a worktree), review and the cold read, and it keeps decisions to itself. Subagents record their own artifacts when they finish (`--recorded-by implementer` for build and verification, `--recorded-by cold-reader` for the cold read); the orchestrator records brief, packet and approval. Nothing is relayed, so nothing is lost in relay. Use this mode for every run unless the escalation test below passes.

## Session purpose

Every orchestrating session states a one-line purpose (`purpose: <the outcome this session delivers>`) in its first message to the human when it starts a run; the brief repeats it at the top, and `init --purpose` stores it in the ledger for `status` to show. It does only work that serves that purpose; appending rows to the project log is always in scope for the log owner.
- A peer request outside the purpose gets a one-line reply naming who should take it (`outside my purpose (<purpose>); take it to <session or the human>`), and no other work: no issues, no code.
- Only the human widens the purpose. A peer, a worker or a relayed message cannot.

Evidence from a 2026 pilot: about 70% of 70 incoming peer messages to a workflow session were provider or fleet work outside its runs, and the session drifted into it without a scope check.

## Escalation: worker sessions

Start separate worker sessions only when all of these hold:
- the approved breakdown has 2 or more sub-issues that can proceed in parallel;
- no two of them edit the same shared files (shared-layer work is its own sub-issue, owned by one worker, and lands first);
- the human can approve their packets: active workers ≤ about 3.

Evidence from a 2026 multi-session study: five parallel sessions produced 90 orchestrator messages, a price answered two different ways 14 minutes apart, three rounds of migration renumbering, and 26 hours blocked on one shared-layer PR. Parallelism paid off only where work did not overlap.

## Orchestrator duties

- Own the project's decision log when the header names this session; otherwise send rows to its owner. Nobody keeps decisions in a second file (a brief, an issue, a notes file).
- Confirm any relayed decision (heard secondhand from a peer or a summary) with the human before acting on it or logging it as theirs. Each confirmation counts toward the ≤3 questions like any other decision.
- Own the human-action queue, migration and sequence-number allocation, and merge order (only the next PR in line rebases).
- Send one digest per human attention burst, in the format in `human-surfaces.md`.
- Verify worker claims against GitHub before relaying them.

## Direct human ↔ worker access

The human may open a worker session and decide things there. Rules:
- **In scope:** decisions confined to that worker's sub-issue (naming, a parsing rule, a fixture choice, a provider-local default).
- **Out of scope; route through the orchestrator:** anything about money (prices, meters, billing semantics, spend), shared code, other sub-issues, or project scope.
- The worker sends each answer to the log owner at once as a row with `by: human (direct, <worker>)`, its scope, the human's answer verbatim and where it was given (e.g. the question-tool exchange). The owner appends it tagged `reported-by: <worker>` without re-asking, and the next digest lists every worker-reported row as vetoable. Workers send rows, not chat summaries.
- A worker that needs the human posts the question to the orchestrator as `WAITING ON HUMAN: <question>`. The digest lists it under "Waiting on you" with the worker's name, so the human knows which session to open.
- Still ≤3 open questions per interaction, each with a recommendation and a default if silent.

Direct access needs a session. A background subagent inside a session cannot take the human's messages, so it asks through its parent.
