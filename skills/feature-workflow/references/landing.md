# Landing

The land stage runs from approval to merge: record the approval, wait for required checks, survive rebases and outages, and merge. It is mechanical, so the ledger runs its commands as argv lists through subprocess, never through a shell, and nobody retypes a head check or a status command.

## Project config: `.feature-workflow/project.json`

Project-specific commands live with the project, not in the skill. The ledger looks for `--project <path>`, then the first ancestor `.feature-workflow/<origin-name>.project.json` outside the main checkout (next to `<origin-name>.tiers.json`), then the in-tree `<repo>/.feature-workflow/project.json`. The in-tree copy is controlled by the branch under review, and its commands run on approval, so it stays t2 must-read unless the tiers file says otherwise. `approve` and `carry` print the file they loaded.

Every key is optional. A missing file or key takes the default, and JSON `null` switches a command off.

| Key | Default | Meaning |
|---|---|---|
| `pr_head` | `gh pr view {pr} --json headRefOid -q .headRefOid` | read-only command that prints the PR head SHA |
| `approval_status` | none | sets the approval record the merge bot or reviewer reads, e.g. `gh api repos/<o>/<r>/statuses/{sha} -f state=success -f context=maintainer-approval -f "description=patch {patch_id} approved by {approver}"` |
| `mark_ready` | `gh pr ready {pr}` | takes the PR out of draft |
| `required_checks` | `[]` | check names that must pass before merge; the watcher waits on these |
| `retrigger` | none | re-requests a required check for the current head, e.g. a rerun of a dispatch workflow for `{head_ref}` `{sha}` |
| `merge_mode` | none | `bot` (a merge bot lands it once checks and status are green) or `manual` (the human merges) |

Placeholders are `{pr}`, `{sha}` (local HEAD), `{patch_id}`, `{approver}`, `{date}` (UTC) and `{head_ref}` (current branch). A template is split with `shlex` first and then filled per argument, so a value with spaces or `;` stays one argument. Any other `{word}` is refused as a typo; braces with spaces or colons, as in a jq filter, pass through unchanged. Keys starting with `_` are comments; other unknown keys are refused.

## Commands

- `workflow_state.py approve --slug S --pr N --approver NAME [--evidence-url URL] [--dry-run]` refuses unless every artifact before approval is current, no gate blocks approval, the worktree is clean and `pr_head` equals the local HEAD. It then runs `approval_status` and `mark_ready` in that order, stopping at the first failure without recording, and records `approval` with the approver, patch id, PR and each command's argv and output.
- `workflow_state.py carry --slug S --pr N [--dry-run]` is for after a rebase (rule 7, decision D2). It compares each file's hunks in the approved patch with the current patch, ignoring index lines and hunk line numbers. The approval carries only when every must-read file (t2, not `skip_read`) has byte-identical hunks and every changed file matches a `skip_read` rule. Then it re-runs `approval_status` on the new head, records a `carry` artifact, and prints one line for the human: `carried approval for PR N to <sha>: only <files> changed`. Anything else is refused, with `re-approval needed: must-read changed in <files>` or with the changed files that are not skip-read (a t1 file without `skip_read` is neither, so it fails closed). Build and verification must already be re-recorded on the new head, so carry never skips them. Run it after an identical-patch rebase too: the ledger keeps that approval, but the new head has no status yet.
- `--dry-run` runs only the read-only `pr_head` check and prints the exact argv of every other command; it changes nothing.

## Watching checks

- Run one watcher per run. Poll every 90 s or more, back off (90 → 180 → 300 s), and stop on merge, close or a failed required check. Never run a tight loop: parallel fast watchers exhausted the GitHub rate limit in the pilot.
- Write multi-step loops as a script and run it with `bash script.sh`, never inline in an interactive shell (zsh does not word-split `$var`, which broke loops 4 times in the pilot).

## When something goes wrong

| Situation | Do | Don't |
|---|---|---|
| A required check fails on a known flake | rerun it once; if it fails again, file a flake-fix PR and tell the human in one line | loop reruns |
| A required check fails for real | return to `build`; the patch change voids approval | rerun hoping it passes |
| Infrastructure outage (rate limit, registry, runner pool) | wait, and check once an hour; report the outage once | rerun: reruns extend rate limits |
| Conflict after approval | rebase, re-record build and verification, then `carry`; if carry refuses, re-ask approval with the changed must-read files | resolve and merge without the ledger |
| A required check needs re-requesting | run the project's `retrigger` for the current head; a run that was skipped (not failed) needs a fresh PR event, such as a new push | push empty commits in a loop |

## Merge

With `merge_mode: bot`, landing ends when the bot merges; record `published` with the merge commit. With `manual`, ask the human to merge (merging always needs explicit consent) and include the deploy line. Either way, check before merge that the approved (or carried) patch id still matches the PR head.
