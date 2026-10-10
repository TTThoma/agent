# Stage Contracts

Execute the first required stage (for the run's tier) that is absent or stale. A later stage never repairs an earlier failed gate by assumption.

| Stage | Tiers | Goal | Output | Exit gate |
|---|---|---|---|---|
| `shape` (records `brief`) | T1, T2 | Make the work decision-complete, ≤3 questions per round. | `brief.md` (the human surface) + agent-internal `spec.md` for T2 when an implementer contract needs more detail. | Human approved the brief; open decisions answered or defaulted; decisions written to the log; policy-settled check answered where required; human-only actions listed. |
| `build` | all | Implement only what the brief allows. | Clean committed HEAD in an isolated worktree. | Review rounds ended with a round finding nothing required (max 3); no shared-layer edits unless this run owns that layer. |
| `verification` | all | Prove health on this exact head. | `verification.md`: commands, exit codes, counts, conformance table, invariant results, live-proof table, skipped checks with reasons. | Required checks pass; `classify` floor ≤ tier; must-read within budget for T2. |
| `cold-read` | T2 | Independent reconstruction, then intent comparison. | `cold-read.md`: reconstruction, then a separate comparison section written after intent is revealed. | Material discrepancies fixed or listed for the human as accepted risks. |
| `packet` | all | Minimize human review cost. | `packet.md`, posted as a PR comment. | Within caps; every claim links to evidence; deploy line present. |
| `approval` | T1, T2 | Accountable human decision on the exact patch. | `approval.md` (approver, time, patch id, head, outcome, conditions) + external record URL. | Named human approved this patch id. |
| `published` | all | Ship exactly what was approved. | Merge commit and deploy status; ops prerequisites ticked. | Remote head's patch equals the approved patch; deploy gate satisfied. |

## Stage notes

### shape
- Each run records its own brief file. `record --artifact brief` keeps a snapshot per run, but never point several runs at one shared, mutable brief: the ledger warns when another open run recorded a brief from the same path. Evidence from a 2026 pilot: 46 of 48 runs shared one brief, and 42 of 48 recorded brief to packet within 3 minutes of the approval question.
- Input is a GitHub issue number or a few lines of idea. Restate it in ≤5 lines before asking anything.
- **Round 1, scope:** goals, non-goals and who it is for. Ask ≤3 questions, each with a recommended answer.
- **Round 2, facts:** run research in parallel subagents (vendor docs, pricing, **terms of service / resale**, repo precedent, a cheap live probe within a stated cap). Bring back only what changes a decision.
- **Round 3, breakdown:** derive the task and PR plan with the `risk-tiers.md` split rules, with tier and must-read estimate per item. Shared-layer work is its own task with one owner.
- **Policy-settled check:** a policy is a rule about what the product does with data, money or users that a later decision could reverse (privacy, retention, billing semantics and data handling are examples, not a closed list). A PR rests on it when reversing the policy would undo or rework that PR. Before the breakdown plans more than 2 PRs that rest on one policy, ask the human once whether it is settled for the life of the plan, showing the cost of a reversal: the number of planned PRs it would undo. The question counts toward the round's ≤3. Default if silent: treat the policy as unsettled, build only the first PR and hold the rest. The answer is a log row and is never re-asked; a later reversal is a new superseding row. Evidence from a 2026 pilot: one policy reversal neutralised about 10 merged PRs within 40 hours, and shaping had never asked.
- Rounds can merge when the work is small. Every round respects the ≤3-question cap. Record each answer in the decision log as it comes.
- On approval of the assembled brief: when the breakdown has 2 or more PRs, file each task as a sub-issue of the source issue (or of a new parent issue for an idea). Each sub-issue body holds the task, its owner, tier, must-read estimate, dependencies and inherited decision ids, in ≤20 lines. Filing sub-issues is pre-authorized by brief approval.
- Discoveries during build that change scope, money, security boundary or a shared layer return here as a new decision. Do not decide them silently.

### build
- Brief the implementer to comment sparingly and to stay within the brief.
- The implementer records `build`, and then `verification`, itself the moment each is done: `record --artifact build --recorded-by implementer`. The ledger is a gate, not paperwork filled in before the approval question. `status` shows who recorded each artifact and when.
- Reviewers report; they do not edit. Classify each finding as required or optional and keep only material ones for the packet.

### verification
- Use the repository's authoritative commands. A skipped check is not a pass.
- T1 code requires conformance + relevant invariants + live proof; T1 text or tests require passing tests and a diff of ≤40 changed lines, shown in full in the packet. If any is missing, raise the tier to T2 (`set-tier`).

### cold-read
- Spawn a new non-forked, read-only subagent. Give it only the repo root, base SHA and head SHA, plus `understand-pr`. Withhold the brief, spec, PR body and commit messages until its reconstruction is fixed. Then resume the same agent with the brief for the comparison.
- If an isolated resumable agent is unavailable, disclose that independence is not guaranteed.
- The cold reader records `cold-read --recorded-by cold-reader` when its comparison is written, not the orchestrator afterwards.

### packet
- Built from reviewer-map output, verification and cold-read. Use the template in `human-surfaces.md`.
- For T2, "Read these lines" totals ≤ budget. If it does not fit, go back and split.
- Run `packet-check --pr N` and post only when it passes (grammar in `human-surfaces.md`).

### approval
- Ask one question. Record the approval with `approve --pr N --approver NAME`, which checks the PR head, sets the project's approval status and marks the PR ready (`landing.md`).
- A requested change returns to `build`. The ledger invalidates packet and approval when the patch changes.

### published
- Land per `landing.md`: one slow watcher, a single rerun for a flake, no reruns during an outage, `carry` after a conflict-only rebase.
- Merging and deploying need explicit consent. Before merging, check heads, patch identity, what landed on base since approval, and ops prerequisites. Use a manual-merge hold when prerequisites are pending.
