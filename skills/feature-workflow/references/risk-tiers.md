# Risk Tiers and Split Rules

The tier decides which stages run and what the human reads. The run's tier is never lower than the **path floor**, the highest tier of any changed file under the run's tier rules (see `tiers.json` below).

| Tier | Typical content | Human reads | Gate |
|---|---|---|---|
| **T0 mechanical** | docs, recorded fixtures, pure moves/renames, fan-out rows of an approved template | a packet of ≤3 lines, FYI | verification green + classifier confirms T0; no approval stage, unless the merge mechanism requires an approval status: then one click |
| **T1 pattern** | new adapter/site/meter row following an existing, conformance-tested pattern; price rows that follow a recorded pricing rule | packet only, no code (text/tests: the full diff, ≤40 lines) | code: conformance + invariants + live proof green; text/tests: tests green; human approves packet, up to 5 per batch question |
| **T2 core** | shared layers, billing/metering semantics, keys/auth/secrets, routing/failover, migrations, global caps or request policies, anything that changes behaviour of every provider | packet + ≤400 must-read lines | cold-read done, must-read within budget, human approves patch, or a delegated approval under a logged grant ([delegation.md](delegation.md)) |

Generated mirrors of prices or permissions are T2: the row is the change. A lockfile-only change floors T2 with nothing to read, so its packet lists every version change instead.

Line counting follows renames (`git diff -M`): a pure move counts 0 lines, an edited move counts its edits, a move into must-read counts the whole file, and every move floors at the higher tier of its old and new paths. T2 lines are additions plus deletions; a T2 file git shows as binary counts its whole old and new content.

Escalate to T2 regardless of paths when the change:
- changes what is billed or how much (quantity, meter, unbilled conditions);
- lets caller input reach a vendor request in a new way (overrides, allowlists);
- stores or logs vendor responses, errors, or keys;
- cannot be covered by the conformance suite;
- is text or tests only but over 40 changed lines;
- removes or weakens a test assertion (deleted asserts, loosened tolerances, added skips): tests cannot vouch for their own weakening.

## tiers.json

The rules file is local and untracked, outside every checkout: `.feature-workflow/<repo>.tiers.json` in a parent directory, where `<repo>` is the last component of `git remote get-url origin` without `.git` (e.g. `~/repos/example-org/.feature-workflow/backend.tiers.json`). Edits to it are permission-gated outside the script; worker agents cannot change it.

Lookup, first hit wins: the run's `--rules` (sticky; switching needs `--rules-override-reason`); then each ancestor of the worktree root, nearest first, skipping the main checkout's own tree; then the in-tree fallback `<repo>/.feature-workflow/tiers.json`. Every worktree of a clone resolves to the same file. If nothing is found the run fails closed: floor T2, every changed file is must-read, and the packet carries the gate `no rules file found`.

`init` pins the resolved path and its sha256. Any later change of path or hash, including deletion, raises the blocking gate `rules changed since run start` (packet, approval, published); `set-rules --reason` re-pins (never to no rules), logs the change in `rules_changes`, and re-opens the packet.

```json
{
  "default_tier": "t1",
  "must_read_budget": 400,
  "rules": [
    {"glob": "tests/fixtures/**", "tier": "t0", "skip_read": true},
    {"glob": "docs/**", "tier": "t0", "skip_read": true},
    {"glob": "tests/**", "tier": "t1", "skip_read": true},
    {"glob": "src/shared/**", "tier": "t2"},
    {"glob": "src/billing/**", "tier": "t2"},
    {"glob": "migrations/**", "tier": "t2"},
    {"glob": ".feature-workflow/**", "tier": "t2"}
  ]
}
```

Tiers are per file, so when a file mixes registration rows with policy, mark it by its most dangerous content. A false T2 costs the human a few extra lines; a false T1 hides a rule from them. Observed case: vendor PRs add 2–3 registration lines to the provider registry, but one vendor PR also put a fleet-wide override rule in the same file. The cure is structural: derive registration from the adapter specs so vendor PRs stop editing shared files, then move the registry to T1.

The first matching rule wins. The ledger's `classify` command prints per-file tiers, the floor and the must-read line count; `record --artifact packet` refuses when the tier is below the floor or a T2 run is over budget. A maintainer-approved override, `--marked-lines N --budget-override-reason`, lets one packet revision count the lines it marks as must-read (N ≤ budget); it is logged in `budget_overrides` and never touches the floor. Changing the in-tree fallback is itself a T2 change: it moves the trust boundary.

Must-read may exclude only lines that cannot change behaviour, so every changed line counts, with one exception: an unchanged block of ≥5 lines moved from one must-read file to another counts one anchor line on each side instead of all its lines. `status` reports `must-read: N counted, M excluded (moved M)`. In detail:
- a run of ≥5 consecutive lines that git marks as moved (`--color-moved=zebra --color-moved-ws=no`: blocks of ≥20 alphanumerics, with no whitespace allowance, so any re-indent is a change), removed from one must-read file and added, byte-identical, to a different must-read file;
- each excluded block keeps one counted anchor line on both sides, so the reader sees where the code left and where it arrived;
- a move within one file (a reorder, such as moving a check after the code it guards) counts in full, as do shorter moves, edited lines inside a moved block, and blocks moved out of or into a skip-read or lower-tier file;
- a file renamed into a must-read path from a lower tier or a skip-read path counts in full, even unchanged: nobody read it at that tier. A rename between must-read paths counts only its changed lines.

Whitespace-only and formatting changes are not excluded: a trailing space after a shell `\`, a blank line in a triple-quoted string or a YAML `|` block, and a space in a SQL literal all change behaviour. Any doubt in parsing git's output leaves the raw count. A budget override recorded before this rule stores the old count, so it no longer matches; overrides are per run, so an in-flight run re-records its packet.

## Approval per tier

- **T0:** a packet of ≤3 lines: the title line, what changed with an evidence link, and the deploy line (`human-surfaces.md`). The ledger requires no approval. Run `approve` only when the project's merge mechanism needs an approval status (`approval_status` or `merge_mode: bot` in `project.json`); it accepts a T0 run with build, verification and packet current, and refuses until CI is green. Under `manual` or no merge mode, merging still needs the human's consent (SKILL.md rule 9); the same one click can give it when the question says so.
- **T1:** one question may approve up to 5 packets, each listed with its patch id ([human-surfaces.md](human-surfaces.md)). Each PR still gets its own `approve --pr N --expect-patch <listed id>`, which refuses a patch other than the one listed.
- **T2:** one question per PR, never batched. Only a delegated approval under a logged grant replaces it ([delegation.md](delegation.md)).

### T1 site pattern (evidence-approved)

A provider's own module (one per site, endpoint or integration) that follows an existing, conformance-tested pattern is T1 already: SKILL.md rule 5 approves T1 code on conformance + invariants + live proof, and T1 has no cold read and no must-read lines. No extra tier is needed. The approval reads the live-proof table and the usage-metering evidence (each call's billed quantity next to the quantity the external provider charged), not the diff. It holds only when:
- the money, key and routing values each module uses are pinned in a shared T2 file that the conformance suite checks every module against, so a module cannot change them unseen;
- the conformance suite and its fixtures are T2 and read, never T1 or skip-read: they are what vouches for the T1 files;
- the path rules list only the modules as T1 and keep every shared file T2, including shared helpers inside a provider's own folder. First match wins, so the T2 rules come first:

```json
{"glob": "tests/conformance/**", "tier": "t2"},
{"glob": "tests/fixtures/conformance/**", "tier": "t2"},
{"glob": "src/providers/shared/**", "tier": "t2"},
{"glob": "src/providers/*/sites/_*.py", "tier": "t2"},
{"glob": "src/providers/*/sites/base.py", "tier": "t2"},
{"glob": "src/providers/*/sites/common*", "tier": "t2"},
{"glob": "src/providers/<name>/sites/special.py", "tier": "t2"},
{"glob": "src/providers/*/sites/**", "tier": "t1"}
```

These go before any broader `tests/**` or `tests/fixtures/**` rule. `src/providers/shared/**` is the shared layer (pin table, billing, privacy, registry); `_*.py` covers `__init__.py`; the `<name>` rule pins a module that sets its own billing rule. A site PR that needs a shared-file change (a pin row, a registration) follows SKILL.md rule 3: the layer owner lands it as a separate T2 PR, and the site PR waits for it. The escalation list above still applies to every module.

## Split rules

When must-read lines exceed the budget, or a PR mixes tiers, cut it into a stack in this order:

1. **Shared-layer change** (T2), owned by the layer owner. One PR, no vendor code.
2. **Vendor layer + one pilot site** (T2 for the first vendor of its kind, otherwise T1).
3. **Mechanical fan-out** (T1/T0): remaining sites as table rows or near-identical modules, proven by conformance.
4. **Fixtures** (T0): trimmed to the fields the tests assert. Provenance (probe date, call count, spend) goes in the packet instead of being read.
5. **Docs/spec** (T0): may land first.

Never stack on another session's unmerged branch. Wait for its merge, or ask the orchestrator to sequence the work.

Measured in a 2026 multi-session study: must-read lines were 585–1,046 per PR even with fixtures skipped, mostly because shared-layer edits rode inside vendor PRs. Fixtures were 34–78% of added lines. One vendor's fan-out alone would have been about 11 and 70 lines.
