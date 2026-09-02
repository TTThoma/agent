# Stage Contracts

Execute the first incomplete or stale required stage. `deep-review` is conditional; all other stages are ordered gates.

| Artifact | Agent goal | Inputs | Expected output | Exit gate |
|---|---|---|---|---|
| `spec` | Make the request decision-complete. | Issue or idea, repository constraints, user answers. | `spec.md`, or interactive questions while still draft. | Problem, users, behavior, scope, non-goals, acceptance criteria, and verification are approved. |
| `plan-review` | Pressure-test execution before coding. | Approved spec and repository evidence. | `plan-review.md` plus any approved spec revisions. | Architecture, data flow, edge cases, rollout, and test strategy have no unresolved blocking decisions. |
| `implementation` | Implement only the approved behavior. | Approved spec, reviewed plan, repository rules, base commit. | A clean committed HEAD containing code, tests, docs, migrations, and generated artifacts as applicable. | Implementation is coherent and any plan-breaking discovery has been resolved interactively. |
| `verification` | Establish deterministic implementation health. | Exact implementation HEAD and repository-authoritative commands. | `verification.md` containing commands, exit status, relevant counts, failures, and environment limitations. | Required tests, types, lint, build, schema, and generated-artifact checks pass. |
| `reconstruction` | Explain what the code actually does without intent contamination. | Repository, base SHA, HEAD SHA, `understand-pr`; no rationale. | `reconstruction.md`. | Observed behavior, before/after architecture, execution paths, state ownership, and unknowns are evidence-backed. |
| `intent-comparison` | Compare observed code with approved intent. | Fixed reconstruction, spec, source issue or idea. | `intent-comparison.md`. | Missing, accidental, contradictory, and unjustified behavior is resolved or explicitly accepted. |
| `deep-review` | Resolve one hard-to-explain architecture hotspot. | User-selected hotspot and reconstruction evidence. | `deep-review.md` with keep/change decision and rationale, or interactive questions. | The selected hotspot is accepted or routed back to implementation. |
| `candidate` | Freeze the exact review candidate. | Current verification and intent comparison, optional deep review, clean committed HEAD. | Ledger record binding base/head and upstream artifact revisions. | No upstream artifact is missing or stale. |
| `reviewer-map` | Minimize human review cost. | Exact candidate diff, reconstruction, verification, and accepted exceptions. | `reviewer-map.md`. | Reading order, execution paths, semantic/mechanical split, hotspots, and test map describe the candidate SHA. |
| `approval` | Make the accountable correctness decision. | Issue, spec, exact diff, evidence, reconstruction, comparison, reviewer map. | `approval.md` or explicit change requests. | A named human approves the exact candidate SHA; otherwise route to implementation. |
| `published` | Publish exactly what was approved. | Approved SHA, green CI, authorization, host state. | PR/merge/release URL and verified remote commit identity. | External result points to the approved SHA. |

## Stage behavior

### Shape

Planning is interactive. Do not manufacture answers to product or architecture choices that materially change scope. Capture approved decisions in the spec rather than leaving them only in chat.

### Build

Implementation may proceed autonomously inside the approved plan. Stop when repository evidence creates a new product decision, irreversible migration choice, security boundary, or meaningful scope change. Commit authorization remains separate from code-edit authorization.

Verification uses commands declared by repository instructions, CI, package scripts, or established project conventions. Do not substitute a generic command when the repository names an authoritative one. A skipped check must include the reason and resulting uncertainty; it is not a pass.

### Understand

The cold reader is read-only and isolated. The first pass ends before intent is revealed. The comparison is a distinct second artifact so the observed model cannot be silently rewritten to match the plan.

Run deep review only when a concrete hotspot remains difficult to explain or test. The user chooses the hotspot. If `deepening-review` requires project context that is absent, record the unmet prerequisite and either use a narrow read-only fallback or skip the optional stage.

### Review and delivery

Record the candidate before reviewer mapping. A draft PR may be opened after the reviewer map when authorized; it is the review vehicle, not proof of approval. Any code change, rebase, or conflict resolution returns the run to implementation.

Publication and merge are separate from approval. Verify all commit identities immediately before the external mutation.
