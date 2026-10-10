# Delegation Mode (opt-in)

By default only the human approves. In delegation mode the orchestrator approves PRs on the human's behalf for a stated window, under a rubric. It is off unless the human turns it on.

## Turning it on

The human states it in their own message, with an end time: "approve low-risk PRs until 09:00". The orchestrator writes it to the decision log as one row (grant, window, who said it, where). A relayed grant does not count (SKILL.md rule 2). The mode ends at the stated time or when the human says stop, whichever is first.

The grant is the explicit consent that SKILL.md rules 8 and 9 require, for the PRs the rubric admits during the window. Under `merge_mode: bot` that includes the merge `approve` triggers. It never covers deploy prerequisites, spending, installs, infra or anything else on rule 9's list.

## Rubric (all must hold, or the PR waits for the human)

1. **No caller-visible output or billing change**, proven by a byte-identical output, request or billing snapshot; or the change is scripts, tests, logs or alarms only.
2. **Cold read done** (T2) with every MATERIAL item fixed, and no open question that needs the human. A T2 PR with a MATERIAL finding left open or accepted as a risk is never delegated.
3. **CI green**: `packet-check --pr` passes. A delegated `approve` runs the same CI check and refuses while checks are pending, failing or missing; never pass `--allow-skipped-packet-check` under delegation.
4. **≤150 counted must-read lines** (`status`).
5. **No policy decision embedded** (money, privacy, retention, data handling; `stage-contracts.md`) beyond one already in the decision log.
6. **No live-data runs and no infra**: the PR runs nothing against live data or paid vendors, and touches no infra apply, deploy config or tier rules.

When in doubt, hold. A held PR keeps its packet, and its question goes into the next digest.

## Recording

- Approve with `approve --pr N --approver "delegated:<session>"`. Where the project sets an approval status, its `approval_status` template must put `{approver}` in the description, so the status reads "delegated" and never passes as the human's own. Without that, delegation is unavailable for the project.
- Keep one summary file for the window: an "approved (delegated)" table (PR, what, why it passed each rubric item, evidence) and a "held" table (PR, which item failed). The next digest links it in its information part; the human may veto any delegated approval there, and a veto of a merged PR becomes a revert PR.

Evidence from a 2026 pilot: one overnight window approved and merged 5 PRs, all scripts, alarms or startup validation with closed cold reads, and held 3 (over 150 lines, caller-visible error text, served rows); the retrospective found all 8 calls right.
