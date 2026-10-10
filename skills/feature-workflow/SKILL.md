---
name: feature-workflow
description: Take an issue or feature idea from intent to merged code under a fixed human attention budget, with risk-tiered gates, a shared decision log, evidence instead of code reading for routine changes, and patch-bound approvals. Use when a change needs a trustworthy, reviewable delivery workflow rather than a single coding pass, especially when several agent sessions work in parallel.
---

# Feature Workflow (v2)

The scarce resource is the maintainer's attention, not agent time. Every stage exists either to (a) put a **decision** in front of the human in a form they can answer in under a minute, or (b) produce **evidence** that replaces reading code. Everything else is agent-internal and never shown.

## The attention contract

The human sees exactly three kinds of output. Templates and hard caps: [references/human-surfaces.md](references/human-surfaces.md).

| Surface | When | Cap |
|---|---|---|
| **Brief** | once per run, before building | ≤100 lines; ≤3 open decisions |
| **Review packet** | once per PR, posted on the PR | ≤60 lines (T0: ≤3 lines), plus ≤400 must-read code lines (T2 only) |
| **Digest** | orchestrator, once per attention burst | ≤3 decisions + human-only actions + one FYI line |

Rules for every message to the human:

1. **At most 3 open decisions.** Rank by impact × uncertainty. The agent decides everything else, logs each in one line in the decision log, and lists it as vetoable.
2. **Render concretely.** A decision shows its consequence: the actual rows, a calls → dollars table, a sample response, a diagram. An abstract option list gets rubber-stamped and reversed later.
3. **Recommendation plus default-if-silent.** Each decision states what the agent will do if there is no answer by the next burst.
4. **Long files are footnotes.** Never point at a file and expect it read.
5. **Information and decisions never share a message.** Send an information-only update first (what happened, links, no questions). Then send the decisions on their own, through the host's question tool when one exists (AskUserQuestion in Claude Code). Never ask a question at the end of a status message.

## Start, resume, status

- **start**: a GitHub issue number or a few lines of idea begins a run. Read the project decision log first ([references/decision-log.md](references/decision-log.md)), then shape the work with the human (below).
- **resume**: continue the first incomplete or stale stage of the named run.
- **status**: report current, missing and stale stages without changing anything.

The ledger records the shape stage's output as artifact `brief`.

Ledger: `python3 <skill-dir>/scripts/workflow_state.py {init|status|record|packet-check|approve|carry|classify|set-tier|invalidate|where} ...`. It stores state under the worktree's Git metadata. When `<repo>/.feature-workflow/tiers.json` exists, it also enforces the tier floor and the must-read budget.

## Stages

Execute in order and skip stages the run's tier does not require. Full contracts: [references/stage-contracts.md](references/stage-contracts.md). Tiers and split rules: [references/risk-tiers.md](references/risk-tiers.md).

| Stage | T0 | T1 | T2 | Human sees |
|---|---|---|---|---|
| `shape`: rounds of ≤3 questions (scope → facts → breakdown), human-only actions, sub-issues; produces the brief | – | ✓ | ✓ | each round, then the Brief |
| `build`: implementer in a worktree + ≤3 adversarial review rounds | ✓ | ✓ | ✓ | nothing |
| `verification`: tests, conformance, invariants, live proof | ✓ | ✓ | ✓ | evidence table (in packet) |
| `cold-read`: isolated reconstruction + intent comparison | – | – | ✓ | material findings, one line each (in packet) |
| `packet`: review packet posted on the PR | ✓ | ✓ | ✓ | Packet |
| `approval`: human approves the exact patch, or a delegated approval under a logged grant² | status only¹ | ✓ | ✓ | one question; T0/T1 batch up to 5 |
| `published`: land (checks, rebases, outages: [references/landing.md](references/landing.md)), then merge/deploy behind the deploy gate | ✓ | ✓ | ✓ | deploy line (in packet); carry notices in the digest |

¹ T0 runs `approve` only where the merge mechanism requires an approval status: one click. Merging still needs consent under rule 9 unless `merge_mode: bot`. Details: [references/risk-tiers.md](references/risk-tiers.md).
² Opt-in, for a window the human states: [references/delegation.md](references/delegation.md).

The default tier is **T2** until the ledger's path classification says otherwise. The agent may never set a tier below the path floor.

## Operating rules

1. **Human-only actions first.** In `shape`, list every key, payment method, top-up, account, legal/ToS check and spend cap the work needs, with exact amounts. Ask for all of them in the first message, not when blocked.
2. **One decision channel.** Decisions live in the project's one decision log, which has one named owner; not in chat, peer relays or a second file. Check the log before asking. Never re-ask a settled decision, and never act on a relayed decision until the human has confirmed it and its row is in the log.
3. **Shared code has one owner and its own PR.** A vendor or feature PR never modifies a shared layer. Shared-code changes go in a separate T2 PR owned by the layer owner; the others wait or build against a merged base. Never stack on a peer session's unmerged branch.
4. **Split before showing.** If `classify` reports must-read lines over budget, split the PR before writing the packet: shared change → vendor layer + one pilot → mechanical fan-out → fixtures.
5. **Evidence over reading.** A T1 code change is approvable only when the conformance suite and the relevant invariant tests pass and the live-proof table is filled. A T1 change to text or tests only is approvable when the tests pass and its diff, ≤40 changed lines, is shown in full in the packet. If that evidence cannot be produced, the change is T2.
6. **Review rounds stop early.** Run adversarial review rounds until one finds nothing required, max 3. Only material findings (money, keys, data exposure, cross-provider behaviour) reach the human, one line each with the fix.
7. **Approval binds to the patch, verification to the head.** A rebase that keeps the patch identical keeps the approval, but verification must re-run on the new head. Any other patch change invalidates approval, except a carry: after a rebase, `carry` keeps the approval when the must-read hunks are byte-identical and only skip-read files changed, with a one-line notice in the next digest or on the PR. Verification is still re-recorded on the new head first. Record approval outside chat with `approve` ([references/landing.md](references/landing.md), [references/trust-evidence.md](references/trust-evidence.md)).
8. **Deploy is a separate line.** Merging may auto-deploy. The packet's deploy line states the ops prerequisites and whether a manual-merge hold is required. The agent never relies on "approve" to imply "ship", except under a project's `merge_mode: bot`, where `approve` can trigger the merge: the approval question then says "approving merges", and the answer counts as merge consent. A carry under bot mode can merge the carried patch; that is allowed only because its must-read hunks are identical (rule 7), and the carry notice says "this will merge".
9. **Permissions.** Code edits inside the approved brief need no further consent. Once the brief is approved, filing its sub-issues, pushing to a draft PR, filing follow-up issues for work inside the session's purpose and posting packets are pre-authorized unless the user says otherwise. Marking a PR ready as part of `approve` is pre-authorized by that approval. Merging, deploying, spending money, installing dependencies, deleting branches and force-pushing shared branches always need explicit consent. A delegation grant, logged from the human's own message, is that consent only for approving the PRs its rubric admits during its window, and for merging them only when the grant says so ([references/delegation.md](references/delegation.md)).

## Shaping

The `shape` stage builds the brief with the human over short rounds, not written once and handed over. Each round asks ≤3 questions and shows concrete consequences. Typical order: scope, goals and non-goals → research and probe → task breakdown with tiers. When the approved breakdown has 2 or more PRs, file each task as a sub-issue of the source issue, recording its owner, tier, must-read estimate and inherited decision ids. Later changes go through the decision log, not by rewriting issues. Before planning more than 2 PRs that rest on a policy (a rule about data, money or users that a later decision could reverse), ask the human once whether it is settled for the life of the plan, showing what a reversal would cost in PRs undone; if silent, build only the first PR and hold the rest. Details: [references/stage-contracts.md](references/stage-contracts.md).

## Orchestration

Every orchestrating session states a one-line purpose in its first message to the human when it starts a run; the brief repeats it. A peer request outside that purpose gets a one-line reply naming who should take it, and no other work; only the human widens the purpose. The default mode is one session that orchestrates its own subagents (research, implementer, reviewer, cold reader). Use separate worker sessions only when the breakdown has 2 or more independent sub-issues with no shared files, and keep active workers at or below the packets the human can approve per sitting (about 3). With worker sessions, the orchestrator owns the decision log (or sends rows to its named owner), the human-action queue, migration and sequence numbers, merge order and the digest. The human may talk to a worker directly about decisions inside that worker's sub-issue; the worker sends each answer to the log owner at once. Details: [references/orchestration.md](references/orchestration.md).

## Completion report

Report the run, tier, base/head, patch id, current stage, packet URL, verification result, open decisions (≤3), and whether the deploy gate is open. **Complete** means the approved patch is merged and the deploy prerequisites are done. A pushed branch or an approval alone is not completion.
