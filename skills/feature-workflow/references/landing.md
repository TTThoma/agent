# Landing

The land stage runs from approval to merge: record the approval, wait for required checks, get through rebases and outages, and merge. It is mechanical, so the ledger runs its commands as argv lists through subprocess, never through a shell, and nobody retypes a head check or a status command.

## Project config: `.feature-workflow/project.json`

Project-specific commands live with the project, not in the skill. The ledger looks for them in this order:
1. `--project <path>`;
2. the first ancestor `.feature-workflow/<origin-name>.project.json` outside the main checkout, next to `<origin-name>.tiers.json`;
3. the in-tree `.feature-workflow/project.json` as of the base commit, never the worktree copy, which the branch controls (it may be untracked behind a `.gitignore`). It is refused if it is not a regular file there.

The branch under review controls everything in the tree, so `approve` and `carry` refuse while the patch adds, changes or deletes any path under `.feature-workflow/`. Land such a change on its own and record its approval by hand (`record --artifact approval`).

Every key is optional. A missing file or key takes the default, and JSON `null` switches a command off. The `gh` defaults suit GitHub; a project config overrides them for anything else.

| Key | Default | Meaning |
|---|---|---|
| `pr_head` | `gh pr view {pr} --json headRefOid -q .headRefOid` | read-only command that prints the PR head SHA |
| `mark_ready` | `gh pr ready {pr}` | takes the PR out of draft |
| `approval_status` | none | sets the approval record the merge bot or reviewer reads, e.g. `gh api repos/<o>/<r>/statuses/{sha} -f state=success -f context=maintainer-approval -f "description=patch {patch_id} approved by {approver}"` |
| `required_checks` | `[]` | check names that must pass before merge; `packet-check --pr` and `approve` refuse unless each one passed (when none are named, while any check is pending or failing). Recorded with each approval and carry |
| `checks` | `gh pr checks {pr} --json name,bucket` | read-only; prints a JSON list of `{name, bucket}` for `packet-check` (`bucket`: pass, fail, pending, skipping or cancel). `null` means the project has no CI |
| `retrigger` | none | re-requests a required check for the current head, e.g. a rerun of a dispatch workflow for `{head_ref}` `{sha}` |
| `merge_mode` | none | `bot` (a merge bot lands it once checks and status are green) or `manual` (the human merges). Recorded with each approval and carry |

Placeholders, each with a fixed character set. A value outside its set is refused before anything runs, but only when a template that will run uses it:
- `{pr}`: digits;
- `{sha}` (local HEAD) and `{patch_id}`: hex;
- `{approver}`: ASCII letters, digits, space and `. _ - ( ) ' :`, starting with a letter, digit, `_` or `(`; `approve` checks it on every call (`delegated:<session>` only under `--grant`, [delegation.md](delegation.md));
- `{head_ref}` (current branch): `A-Z a-z 0-9 . _ / -`;
- `{date}`: UTC timestamp.

A template is split with `shlex` first and then filled per argument, so no value can add or split arguments. Any other `{word}` is refused as a typo; braces with spaces or colons, as in a jq filter, pass through unchanged. Never wrap a template in a shell. A template that runs `sh`, `bash`, `zsh`, `dash` or `ksh` with `-c` is refused, but that denylist is a convenience; the value sets are the guard. Keys starting with `_` are comments; other unknown keys are refused.

## Commands

- **`workflow_state.py approve --slug S --pr N (--approver NAME | --grant ROW --grant-at T --grant-until T [--grant-merges]) [--expect-patch ID] [--evidence-url URL] [--dry-run]`**
  - Works for every tier; a T0 run needs only build, verification and packet current.
  - `--approver` is ASCII, and a name starting with `delegated` or holding `delegated:` is refused. `--expect-patch` refuses unless the current patch id starts with the id the human was shown.
  - `--grant` records a delegated approval as `delegated:<session>`; it needs `--expect-patch`, refuses over 150 changed lines, and is checked against the grant's window and pinned repo-wide ([delegation.md](delegation.md)).
  - Refuses unless the run is open, the patch is not empty, every artifact before approval is current, no gate blocks approval, the worktree is clean, the patch leaves `.feature-workflow/` alone, and `pr_head` equals the local HEAD.
  - Runs `mark_ready`, checks `pr_head` again, and then takes the ledger lock. Under the lock it re-loads and re-evaluates the run, refusing if approval is no longer allowed on the same head and patch. Only then does it run `approval_status` and record `approval`, with the approver, patch id, PR, project config, `merge_mode`, `required_checks`, and each command's argv and output.
  - On a failure before `approval_status`, no approval status is left behind. If `approval_status` itself fails, nothing is recorded except an `approval_attempts` entry, which never counts as an approval.
- **`workflow_state.py carry --slug S --pr N [--dry-run]`**, after a rebase (rule 7):
  - Refuses unless the approval was recorded by `approve` for the same PR. A delegated approval also refuses once its grant window has closed (`re-approval needed: delegation window closed`).
  - Compares each file's hunks in the approved patch with the current patch, ignoring index lines and hunk line numbers. The approval carries only when every must-read file (t2, not `skip_read`) has byte-identical hunks and every changed file matches a `skip_read` rule. A t1 file without `skip_read` is neither, so it fails closed.
  - Build and verification must already be re-recorded on the new head, so carry never skips them.
  - It checks `pr_head`, re-evaluates under the lock, re-runs `approval_status` on the new head, and records a `carry` artifact with the same landing fields as `approve`; `status` lists every carry.
  - It prints `carried approval for PR N to <sha>: only <files> changed`, plus `; this will merge` under `merge_mode: bot`. Anything else is refused with `re-approval needed: must-read changed in <files>`, or with the changed files that are not skip-read.
  - Run it after an identical-patch rebase too: the ledger keeps that approval, but the new head has no approval status yet.
- **`--dry-run`** runs no command at all, `pr_head` included, and prints the exact argv of each one and the project config path. It changes nothing.
- Every ledger write (`init`, `record`, `set-tier`, `set-rules`, `invalidate`, `approve`, `carry`) holds an exclusive lock on `state.lock` beside `state.json`.

## Telling the human

Carry notices, flake notes and outage notes go into the next digest (a human-action or FYI line, batched) or onto the PR as a comment. They are never separate chat messages.

## Watching checks

- Run one watcher per run. Poll every 90 s or more, back off (90 → 180 → 300 s), and stop on merge, close or a failed required check. Never run a tight loop.
- Write multi-step loops as a script and run it with `bash script.sh`, never inline in an interactive shell.

## When something goes wrong

| Situation | Do | Don't |
|---|---|---|
| A required check fails on a known flake | rerun it once; if it fails again, file a follow-up issue for the flake fix (pre-authorized) and note it in the digest | loop reruns |
| A required check fails for real | return to `build`; the patch change voids approval | rerun hoping it passes |
| Infrastructure outage (rate limit, registry, runner pool) | wait, check once an hour, note it once in the digest | rerun: reruns extend rate limits |
| Conflict after approval | rebase, re-record build and verification, then `carry`; if carry refuses, re-ask approval with the changed must-read files | resolve and merge without the ledger |
| A required check needs re-requesting | run the project's `retrigger` for the current head; a run that was skipped (not failed) needs a fresh PR event, such as a new push | push empty commits in a loop |

## Merge

- **`merge_mode: bot`:** `approve` and `carry` can trigger the merge (rule 8).
  - The approval question says "approving merges", and the answer counts as merge consent.
  - A carried patch may merge without a new question only because its must-read hunks are identical to what was approved.
  - Landing ends when the bot merges; record `published` with the merge commit.
- **`manual`:** ask the human to merge (merging always needs explicit consent), with the deploy line.

Either way, check before merge that the approved (or carried) patch id still matches the PR head.
