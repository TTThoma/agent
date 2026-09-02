---
name: reviewer-map
description: Turn a final branch or pull-request diff into an evidence-backed reading guide for a human reviewer. Use when a PR is ready for review and the reviewer needs the best file order, core execution paths, semantic-versus-mechanical diff map, and complexity hotspots.
---

# Reviewer Map

Create a concise map that reduces the time needed to review a finished PR. Analyze only; do not edit the implementation, post comments, create or update a PR, or turn the task into a general code review unless the user separately requests that action.

## Establish the review surface

- Determine the base-to-head comparison and state it. Infer the base from reliable local metadata when possible; otherwise use the locally available default branch and disclose uncertainty.
- Inspect the complete diff before choosing a reading order.
- Follow changed entry points into unchanged code only far enough to explain control flow and contracts.
- Use tests to clarify behavior and intended edge cases, but do not let test-file order dictate the map.
- Do not fetch, switch branches, mutate the worktree, or contact external systems without user authorization.

## Optimize for human comprehension

Order files by explanatory value, not alphabetically or by diff size. Usually lead with the file that reveals the behavior or central decision, then the core implementation, boundary wiring, data/configuration changes, and tests. Group generated files, snapshots, formatting, bulk renames, and repetitive plumbing rather than listing each as a primary stop.

Distinguish:

- behavior-changing code;
- architectural or data-model changes;
- boundary and configuration wiring;
- compatibility or migration work;
- tests that encode important requirements;
- mechanical or generated changes safe to defer on a first pass.

Cite repository-relative paths and symbols for all important claims. Add stable line numbers when useful. Never claim a section is mechanical until the diff supports that classification.

## Deliverable

Produce `# Reviewer Map` with:

1. **What changed** — three to five behavior-focused bullets.
2. **Five-minute architecture** — before/after and the minimum concepts to retain.
3. **Main execution path** — concrete `file:symbol -> file:symbol` traces.
4. **Recommended review order** — numbered files or tightly related file groups, each with what question to answer there.
5. **New concepts** — what each represents and why existing concepts appear insufficient; flag when the diff does not justify one.
6. **Semantic diff** — changes that can alter behavior or contracts.
7. **Mechanical diff** — changes that can usually wait until a second pass.
8. **Complexity hotspots** — the areas deserving the most cognitive and correctness attention, with evidence.
9. **Tests and verification map** — which tests establish which behaviors, plus visible coverage gaps without expanding into a full audit.
10. **First-pass skip list** — files or groups safe to ignore initially and why.

Keep the map proportional to the PR. Do not reproduce a file-by-file changelog. If the branch is too entangled to yield a reliable reading order, make that the primary finding and identify the specific coupling that prevents one.
