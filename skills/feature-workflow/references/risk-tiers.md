# Risk Tiers and Split Rules

The tier decides which stages run and what the human reads. The run's tier is never lower than the **path floor**, the highest tier of any changed file under the run's tier rules (see `tiers.json` below).

| Tier | Typical content | Human reads | Gate |
|---|---|---|---|
| **T0 mechanical** | docs, recorded fixtures, pure moves/renames, fan-out rows of an approved template | nothing; packet is FYI | verification green + classifier confirms T0 |
| **T1 pattern** | new adapter/site/meter row following an existing, conformance-tested pattern; price rows that follow a recorded pricing rule | packet only, no code (text/tests: the full diff, ≤40 lines) | code: conformance + invariants + live proof green; text/tests: tests green; human approves packet |
| **T2 core** | shared layers, billing/metering semantics, keys/auth/secrets, routing/failover, migrations, global caps or request policies, anything that changes behaviour of every provider | packet + ≤400 must-read lines | cold-read done, must-read within budget, human approves patch |

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

The count leaves out lines nobody needs to re-read, and reports them as `must-read: N counted, M excluded (moved X, whitespace Y)`:
- **moved:** lines git marks as moved (`--color-moved=zebra --color-moved-ws=allow-indentation-change`, blocks of ≥20 alphanumerics) between must-read files only. One line per moved block on the added side still counts, because where a block lands can change behaviour. A block moved out of a skip-read or t1 file counts in full, as does a file renamed into a must-read path.
- **whitespace:** a change block whose lines are equal once trailing whitespace and blank lines are dropped. Outside moved blocks, indentation and spacing inside a line still count: they change meaning in Python, YAML and string literals.
- **format** (optional): with `"formatter": {"command": "ruff format --no-cache --stdin-filename {path} -", "globs": ["**/*.py"]}` in the rules, a matching file counts the diff between the formatted old and new blobs when that is smaller. The command reads stdin, writes stdout and must not change semantics. Name a trusted binary by path, never `uv run`, `npx` or `poetry run`, which install from the branch's lockfile. It runs only from a rules file outside the worktree, so a branch cannot name its own command, and the rules pin covers it.
A changed line is never excluded, and any doubt in parsing git's output leaves the raw count.

## Split rules

When must-read lines exceed the budget, or a PR mixes tiers, cut it into a stack in this order:

1. **Shared-layer change** (T2), owned by the layer owner. One PR, no vendor code.
2. **Vendor layer + one pilot site** (T2 for the first vendor of its kind, otherwise T1).
3. **Mechanical fan-out** (T1/T0): remaining sites as table rows or near-identical modules, proven by conformance.
4. **Fixtures** (T0): trimmed to the fields the tests assert. Provenance (probe date, call count, spend) goes in the packet instead of being read.
5. **Docs/spec** (T0): may land first.

Never stack on another session's unmerged branch. Wait for its merge, or ask the orchestrator to sequence the work.

Measured in a 2026 multi-session study: must-read lines were 585–1,046 per PR even with fixtures skipped, mostly because shared-layer edits rode inside vendor PRs. Fixtures were 34–78% of added lines. One vendor's fan-out alone would have been about 11 and 70 lines.
