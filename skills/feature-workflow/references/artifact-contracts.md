# Artifact and State Contracts

## Default location

The helper resolves the run directory with:

```text
git rev-parse --git-path feature-workflow/<slug>
```

This is worktree-local Git metadata and does not dirty the candidate. Use a repository path only when the project explicitly wants workflow evidence committed. Committing an analytical artifact changes HEAD, so regenerate or rebind all HEAD-bound artifacts afterward.

## Artifact header

Every Markdown artifact should begin with:

```yaml
---
workflow: feature-workflow/v1
run: <slug>
artifact: <artifact-name>
source: <issue URL, issue number, or concise idea identifier>
base_ref: <base ref>
base_sha: <full SHA or null before implementation>
head_sha: <full SHA or null before implementation>
generated_at: <ISO-8601 UTC timestamp>
result: <draft|approved|pass|fail|accepted|rejected>
---
```

Use full SHAs. Human-readable branch names are context, not identity.

## State file

`state.json` is the machine-readable ledger. Each recorded artifact contains:

- artifact name and optional absolute path;
- file SHA-256 when it has a file;
- monotonically increasing revision;
- base/head binding for implementation and later artifacts;
- revisions of upstream artifacts it consumed;
- explicit invalidation reason, when present.

Do not hand-edit the ledger when the helper is available.

## Invalidation graph

```text
spec
 └─ plan-review
     └─ implementation
         ├─ verification
         └─ reconstruction
             └─ intent-comparison
                 └─ deep-review (optional)

verification + intent-comparison (+ deep-review when run)
 └─ candidate
     └─ reviewer-map
         └─ approval
             └─ published
```

Changing an artifact invalidates every consumer that recorded its earlier revision. Any base/head mismatch or dirty worktree invalidates `implementation` and every HEAD-bound descendant. Missing files and changed file hashes are stale, never implicitly accepted.

Use explicit invalidation when the reason is known:

```text
python3 <skill-dir>/scripts/workflow_state.py invalidate \
  --slug <slug> --from implementation --reason "review changes requested"
```

Invalidation marks state; it does not delete evidence. Old artifacts remain inspectable but cannot satisfy a gate.

## Approval record

`approval.md` must identify the approver, UTC time, candidate base/head, outcome, and any accepted risks or conditions. A vague “looks good” copied from chat is insufficient unless it can be tied to the exact candidate SHA.

## Publication record

Record the external URL, action (`draft-pr`, `pr`, `merge`, or `release`), remote head SHA, approved SHA, and verification method. A pushed branch is not a merged or released change.
