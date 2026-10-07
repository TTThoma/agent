# Artifact and State Contracts

## Location

The ledger resolves the run directory with `git rev-parse --git-path feature-workflow/<slug>`. That is worktree-local Git metadata and does not dirty the candidate. Human surfaces are published elsewhere (chat, PR comment); the ledger keeps the canonical copy for hashing.

## Header

Every Markdown artifact begins with:

```yaml
---
workflow: feature-workflow/v2
run: <slug>
artifact: <name>
tier: <t0|t1|t2>
source: <issue or idea id>
base_sha: <full SHA or null>
head_sha: <full SHA or null>
patch_id: <stable patch id or null>
generated_at: <ISO-8601 UTC>
result: <draft|approved|pass|fail|accepted|rejected>
---
```

## Binding

| Artifact | Bound to | Stale when |
|---|---|---|
| brief | hash of the run's copy `brief.<revision>.md` (source path kept for reference) | the copy is edited |
| build, verification | exact base + head, clean worktree | any commit, rebase or dirty tree |
| cold-read, packet, approval, published | patch id of base..head, clean worktree | the patch changes; an identical-patch rebase leaves them current with a note |

Patch ids use `git patch-id --verbatim` when git supports it (2.40+), else `--stable`, which ignores whitespace; crossing that git version makes patch-bound artifacts stale once. Once the branch is merged into its base (merge-base == HEAD), artifacts are judged against the base recorded at build, and `published` needs `--remote-sha <merge commit>` on the base's first-parent line whose first-parent diff carries the approved patch id (HEAD itself after a fast-forward). A squash commit on that line with one parent and the approved patch id also publishes; its parent must descend from the build base, a checked-out branch must still carry the approved patch, and the run is then judged at the build's base and head and closed to further records. Merging the base into the branch before landing needs a fresh `build`.

Changing an artifact invalidates every consumer that recorded its earlier revision. Missing files and changed hashes are stale, never implicitly accepted. Invalidation marks state but never deletes evidence.

## Dependency graph

```text
shape→brief ─ build ─┬─ verification ─┐
                     └─ cold-read (T2)┴─ packet ─ approval (T1/T2) ─ published
```

## Tier record

`state.json` stores the tier and every tier change (`from`, `to`, `reason`, `at`). Lowering needs a reason, and the floor from `tiers.json` always wins. `rules_pin` holds the rules path and sha256 from `init`; each re-pin (`set-rules`, `--rules-override-reason`) appends `{from_sha, to_sha, path, reason, at}` to `rules_changes`.

## Approval record

`approval.md` holds the approver, UTC time, tier, patch id, head, outcome, accepted risks or conditions, and the external record URL. Chat text alone is insufficient.

## Publication record

Record the merge commit, the remote head's patch id compared with the approved patch id, deploy environment and status, and the ops prerequisites with their state.
