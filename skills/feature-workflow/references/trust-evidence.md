# Trust Evidence

When the human does not read the code, trust comes from evidence that an agent could not easily fake, and from records bound to the exact change. Build these once per repository. After that, every T1 change gets cheaper.

## Evidence ladder (strongest per minute of human attention first)

1. **Conformance suite.** One parametrized test over every registered adapter (or plugin, or route) that checks the shared contract: registration complete, meter priced, key vendor known, pinnable/visibility policy, error text redacted, empty/failed calls unbilled, timeout within deadline, fixtures parse into the declared schema. A new adapter that passes it is T1. The packet shows adapters × checks as one table.
2. **Invariant tests for rules that today only humans enforce.** Write each invariant as a test before relying on it. Examples: the price mirror equals the pricing service's manifest; billed quantity equals the vendor-charged quantity recorded by the probe; no vendor error text reaches callers or logs; every caller override key is fuzzed so that billed records equal served rows. Use property-based tests where a dependency is approved; otherwise use parametrized exhaustive cases.
3. **Live proof table.** For every new surface, at least one call through a locally running service (not straight to the vendor) with the real key, under a stated spend cap. Record status, a ≤1-line output excerpt, the billing row, and the negative cases (blocked → unbilled, over-limit → 4xx). Commit it as `evidence/<run>.md` or put it in the packet.
4. **Holdout scenarios.** A small human-owned set of end-to-end scenarios kept outside the implementer's context (e.g. a separate repo or directory the implementer brief excludes). Report the pass rate per PR. Implementers must not edit them, and any PR that deletes, skips or weakens a test is flagged in the packet.
5. **Adversarial cold read** (T2 only). An isolated reader reconstructs behaviour from the diff, then compares it with the brief. Only material discrepancies reach the packet. In a 2026 multi-session study it found real money bugs in 4 of 6 code runs and nothing material on wording-only runs, so skip it for T0/T1.
6. **Mutation check on money paths.** For billing or metering code, show that the key tests fail when the guarded line is reverted (manual "test fails without the fix"), or use a mutation tool if one is approved.

## CI is a precondition

Local test runs are claims; CI runs are evidence. If the repository has no CI that runs the test suite on PRs, the first T2 task is adding it. Until then, the packet must say "tests: local only".

## Recording approval

- Approval binds to the **patch id** of base..head (`git diff <base> <head> | git patch-id --stable`). A rebase that keeps the patch keeps the approval; one that changes only skip-read files, with byte-identical must-read hunks, keeps it through `carry`. Verification is bound to the exact head and must re-run after any rebase, before a carry.
- Record it outside chat with `approve --pr N --approver NAME [--evidence-url URL]`. It checks the PR head and runs the project's `approval_status` command, for example a commit status on the head or a review when the approver is not the PR author, and then records the approval ([landing.md](landing.md)). Use `record --artifact approval` by hand only where `approve` refuses by design, such as a patch that changes `.feature-workflow/`.
- Before merge, compare the approved patch id, local head, remote head and PR head, and run "what landed on base since approval". If anything that landed touches the same modules, re-run verification and say so in the deploy line.

## Calibration

- **Audit sample.** Roughly 1 in 10 T1 PRs gets a full T2 treatment (cold read + must-read lines) chosen at random. Log whether it found anything material; if it does, tighten the conformance suite or the tier rules, not just the PR.
- **Escapes.** When a bug reaches main, record which evidence layer should have caught it and add the missing test or rule. One line in the decision log under "escapes".
- **Runtime net.** Per-vendor spend caps, alerting on unpriced meters, and a deploy hold for changes whose ops prerequisites are pending.
