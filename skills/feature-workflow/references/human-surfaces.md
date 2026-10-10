# Human Surfaces

The human reads three things: the brief, the review packet and the digest. Each has a hard cap. If content does not fit, it is not for the human: put it in an agent-internal file and link it as a footnote.

Evidence from a 2026 multi-session study: the maintainer approved every gate from a ≤40-line chat summary or a reviewer map. They never opened spec.md or ledger files, and GitHub shows 0 reviews. Single concrete questions were answered in 4–90 s; abstract option lists were approved fast and later reversed.

## Brief (≤100 lines, assembled over shaping rounds)

Each shaping round is a short message with ≤3 questions. The assembled brief is the approval object. Post it in chat, or as a comment on the source issue. Sections in this order:

```markdown
# <run>: brief                                  tier: T1|T2   est. PRs: N
purpose: <one line: the outcome this session delivers; only the human widens it>

## Outcome (≤5 lines)
What a caller can do after this ships, what it costs them, what it costs us.

## Scope (≤6 lines)
In: …   Out (non-goals): …

## Shape (≤15 lines, a diagram if it helps)
Before → after in one picture: which modules or layers are added or changed, and who owns any shared layer.

## Decide now (≤3)
D1. <question in plain words>
    Shows: <rows / $ table / sample output, ≤8 lines>
    Recommend: <option> because <fleet precedent or rule>
    If silent by next burst: <what the agent does>
D2. …

## Decided by agent (vetoable, one line each, ≤15)
A1. <decision> — <one-clause reason>   (log id)

## Inherited (from the decision log, ≤8 lines)
The ids and one-liners of parent decisions this run must honour.

## Human-only actions (all of them, now)
- [ ] <key / account / payment / top-up / ToS check>: exact amount, where to put it, what it unblocks

## PR plan
| # | PR | tier | est. must-read lines | depends on |

## Proof plan (≤5 lines)
How we will know it works without you reading code: conformance, invariants, live calls (count, max spend).
```

Approval of the brief approves: the scope, the agent decisions not vetoed, the PR plan, and pre-authorized draft pushes and issue filing. It does not approve merge, deploy, spend beyond the stated cap, or installs.

## Review packet (≤60 lines, once per PR, posted as a PR comment)

They read where the PR is. Post the packet as a PR comment and give them a ≤5-line chat pointer.

```markdown
## Review packet: <tier> · patch <patch-id[:12]> · head <sha[:12]>

**What changed** (≤5 bullets, behaviour not files)

**Decisions in this PR** (log ids + any new agent decisions, one line each)

**Read these lines** (N)
| file:lines | why it matters | question to answer |

**Found and fixed by adversarial review** (material only, one line each)

**Evidence**
| check | result |
| unit tests | N → M passed |
| conformance (N adapters × M checks) | all pass / table link |
| invariants touched | <names> pass |
| live proof via the local service | N calls, $X, billing rows match (table below or linked) |
| tier floor / must-read budget | T2 ≥ floor · 312/400 |

**Deploy line**: merge auto-deploys to <env>? yes/no · ops prerequisites: <done / list> · hold required: yes/no

**Approve?** One question. Options: approve this patch / request change (say what) / split.
```

A T0 packet is 3 lines, the title line first (packet-check enforces it), with no question unless the project needs an approval status (`risk-tiers.md`):

```markdown
## Review packet: T0 · patch <patch-id[:12]> · head <sha[:12]>
<what changed, one line>
tests N passed · classifier T0 · deploy: <auto to env / none> · hold: no
```

### Batch approval (T1, and T0 where a status is needed)

One question may approve up to 5 packets. It counts as one of the ≤3 decisions. T2 is never batched. The batch is only the question: each PR still has its own packet, posted on its PR and recorded by its own run with `record --artifact packet --pr N`, so each passed packet-check and CI before it is listed.

```markdown
Approve these 3 T1 patches? (approving merges)        ← that note only under merge_mode: bot
- PR #N  patch <patch-id[:12]>  <one-line summary>  · evidence green · <packet link>
- PR #M  patch <patch-id[:12]>  <one-line summary>  · evidence green · <packet link>
Options: approve all / approve all except #N (say why) / hold all
```

Run `approve --pr` once per approved PR, in that PR's run. A PR whose patch changed or whose CI went red since the question is refused there and goes into the next question; a change requested on one PR leaves the others approved.

The reviewer-map skill output is the agent-internal input to "Read these lines". Do not paste the whole map.

### Packet grammar and `packet-check`

Every tier's packet starts with the title line. Two lines are machine-checked; the rest is free text.
- The title, the first non-blank line (text may follow the sha, e.g. `(rev 2)`): `## Review packet: <T0|T1|T2> · patch <patch-id> · head <sha>`, with the run's tier and at least 7 hex characters of `status`'s patch-id and HEAD.
- T2 only, a line starting `**Read these lines** (N)`: N is `status`'s counted must-read lines, a plain integer, and must fit the budget. A quoted, indented or fenced (inside a code block) marker does not count. Over budget, the form is `(M marked of N)`, accepted only when the ledger already holds a budget override for this patch with the same M and N (`record --artifact packet --marked-lines M --budget-override-reason ...`).

`workflow_state.py packet-check --slug S --packet FILE --pr N` lists every mismatch and refuses when the tier, head, patch-id or count differs from the worktree and ledger, when verification or (T2) cold-read is not current, when the PR head is not the local HEAD, or when the checks are not green. Checks come from the project's `checks` template (`landing.md`): every name in `required_checks` must report `pass` (a skipped required check refuses); with none named, no check may be pending, failing or cancelled. An unknown state or no checks at all refuses, unless the project config sets `checks` to `null`, meaning it has no CI. It never posts or records anything. `record --artifact packet` runs the same check on its `--path` file (and the PR checks when given `--pr`), records the hash of the bytes it checked, and refuses unless `--skip-packet-check REASON` is given; the reason is stored and shown by `status`, which also flags a packet recorded without `--pr` as `[PR/CI not checked]`. `approve` runs the same CI check after its first PR-head check and refuses while checks are pending, failing or missing (unless `checks` is `null`), and refuses a packet that skipped packet-check unless given `--allow-skipped-packet-check`, which the approval records.

## Digest (orchestrator, once per attention burst)

The orchestrator sends at most one digest per burst. If nothing needs the human, it sends nothing.

```markdown
## Decide (≤3, ranked)
1. <session>: <decision>: recommend X; if silent: Y. [unblocks: …]

## Do (human-only actions, checkbox per item)
- [ ] <session>: <action, exact amount/place>: unblocks <what>

## Waiting on you (workers you can open directly; scoped decisions only)
- <worker session>: <question in one line>; recommend X

## Approve (packets ready; each is one click after reading its packet)
- [ ] <session>: PR #N <title>: <tier>, <must-read lines>, evidence green? link

FYI: <one line: what moved since last digest>
```

Rules:
- Send it as two parts: first the information (FYI line, "Do" actions and "Approve" pointers as plain text, with no questions), then the "Decide" and "Waiting on you" items on their own through the question tool.
- Items 4+ wait for the next burst. Never pad with status.
- "Approve" items count toward the 3 when they are T2. T0 and T1 approvals are batched as one item, in the batch question format above.
- After a delegation window, the next digest's information part links its summary in one line ([delegation.md](delegation.md)).
- Workers send the orchestrator five headed lines: STAGE, BLOCKED BY, MAINTAINER ACTION, WAITING ON OTHER SESSIONS, NEXT. The orchestrator verifies claims against GitHub before relaying.
- When the human decides, the orchestrator writes it to the decision log first, then relays the log id, not a paraphrase.
