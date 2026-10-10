# Delegation Mode (opt-in)

By default only the human approves. In delegation mode the orchestrator approves PRs on the human's behalf for a stated window, under a fixed rubric. It is off unless the human turns it on.

## The grant

- The human gives it in their own message: an end time and whether it includes merging ("approve low-risk PRs until 09:00, merges included"). A relayed or summarised grant does not count (SKILL.md rule 2).
- The orchestrator writes it to the decision log as one row: grant, the message time, end time (at most 12 h after the message), merges yes/no, where it was said. That row is the trust anchor.
- The mode ends at the end time or when the human says stop. A grant cannot be extended; the human gives a new one, which is a new row.
- The grant is the explicit consent rules 8 and 9 require, for the PRs the rubric admits during the window: approving, and merging only when the grant says so. It never covers deploy prerequisites, spending, installs or anything else on rule 9's list.

## Rubric (all must hold, or the PR waits for the human)

1. **No caller-visible output or billing change**, proven by a byte-identical output, request or billing snapshot; or the change is scripts, tests or logs only.
2. **Cold read done** (T2) with every MATERIAL item fixed, and no open question that needs the human. A T2 PR with a MATERIAL finding left open or accepted as a risk is never delegated.
3. **CI green**: `packet-check --pr` passes, and `approve` re-checks CI itself; a delegated approve never skips packet-check.
4. **≤150 changed lines in all**, every tier counted (`git diff --shortstat base...head`). Splitting work to get under the limit is not allowed: the PR plan from the brief decides the PRs.
5. **No policy decision embedded** (money, privacy, retention, data handling, keys, auth, routing, permissions) beyond one already in the decision log.
6. **No live runs, no infra**: the agent runs nothing against live data or paid services during approval; live proof recorded during build is fine. The PR touches no infra, deploy config or tier rules.
7. **Deploy line: none, no hold**: the packet's deploy line lists no ops prerequisites and no manual-merge hold.

When in doubt, hold. A held PR keeps its packet, and its question goes into the next digest.

## Recording

`approve --pr N --grant ROW --grant-at <message time> --grant-until <end> [--grant-merges] --expect-patch <id>`:
- records the approver as `delegated:<session>` (from `FEATURE_WORKFLOW_SESSION`, else the host name) and refuses `--approver`;
- refuses outside the window, a window over 12 h, `--allow-skipped-packet-check`, an `approval_status` template without `{approver}` (the status must read delegated), and, under `merge_mode: bot`, a missing `--grant-merges`;
- pins the grant repo-wide on first use (`<git-common-dir>/feature-workflow/grants.json`): every later use must name the same times and merge flag;
- stores the grant in the approval, and `status` shows it. `carry` of a delegated approval refuses once the window has closed.

Without `--grant`, `approve` refuses an approver that starts with `delegated` or holds `delegated:`, and any non-ASCII name.

Each delegated approval is also a row in the same decision log (PR, patch id, grant row, which rubric items held, evidence), never a separate file. The next digest's FYI line lists each grant row with the approval rows made under it; the human may veto any of them, and a veto of a merged PR becomes a revert PR.

Code cannot catch an agent that approves under a human's name instead. The audit trail is the decision-log rows and the human's own approval-question history.
