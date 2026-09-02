---
name: understand-pr
description: Reconstruct an unfamiliar branch or pull request from its diff and code, producing an evidence-backed mental model before judging or changing it. Use when a maintainer needs to understand what a PR actually implements, especially in a fresh context without the author's design history.
---

# Understand PR

Act as a read-only implementation archaeologist. Explain the branch as it exists; do not edit code, propose a redesign, or perform a general correctness review unless the user separately asks for that work after the reconstruction.

## Preserve the fresh-context test

- Start with the base branch, current branch, diff, and repository code.
- Do not seek or read the original spec, implementation conversation, PR description, issue, or author rationale before completing the initial reconstruction.
- If that material is already present in the conversation, treat it only as intended behavior and keep it out of the initial inference. Clearly distinguish prior intent from facts observed in code.
- If the base is unspecified, infer it from local branch/upstream metadata when reliable. Otherwise use the repository's default branch if locally available; state the chosen comparison point and uncertainty.
- Do not fetch, switch branches, mutate the worktree, or contact external systems merely to improve the analysis unless the user authorizes it.

## Reconstruct from evidence

Inspect the base-to-head commit range and diff, then follow changed entry points into unchanged supporting code when needed. Use tests, schemas, migrations, configuration, and public interfaces as evidence; do not infer architecture from filenames alone.

Separate:

- externally observable behavior added, changed, or removed;
- architecture that existed at the base;
- architecture introduced or rewired by the branch;
- semantic changes from renames, formatting, generated output, and other mechanical changes;
- facts directly supported by code from plausible but unverified interpretations.

Trace the important execution paths end to end. For every significant new concept, identify its purpose, definition, consumers, state or configuration it owns, and why it appears to exist. Notice overlapping concepts, duplicated state, configuration threaded across layers, compatibility paths, and abstractions whose necessity the code does not reveal.

Cite repository-relative file paths and symbols for important claims. Add line numbers when stable and helpful. If evidence is incomplete, say so rather than filling gaps with a plausible story.

## Deliverable

Produce `# PR Reconstruction` with:

1. **Comparison scope** — base/head and important analysis limitations.
2. **Observed behavior change** — added, changed, and removed behavior.
3. **Architecture before / after** — a compact contrast, not two repository tours.
4. **Main execution paths** — concrete `file:symbol -> file:symbol` traces.
5. **New concepts** — purpose, ownership, consumers, evidence, and apparent necessity.
6. **State ownership and configuration flow** — sources of truth and layer crossings.
7. **Cross-cutting and mechanical changes** — separate these from the core behavior.
8. **Hard-to-understand areas** — where the code requires hidden context or excessive inference.
9. **Questions the code does not answer** — unresolved intent or ambiguous behavior.
10. **Five-minute mental model** — the smallest accurate model a maintainer needs.

End after reconstruction. If the user then supplies the spec, compare reconstruction with intent as a separate pass, identifying missing or accidental behavior and complexity not justified by the stated requirements. Do not silently rewrite the initial reconstruction to match the spec.
