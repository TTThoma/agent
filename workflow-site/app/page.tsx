'use client';

import { useMemo, useState } from 'react';

type Step = {
  id: number;
  phase: 'Shape' | 'Build' | 'Understand' | 'Review';
  role: string;
  goal: string;
  input: string;
  output: string;
  skill: string;
  mode: 'Interactive' | 'Autonomous' | 'Conditional' | 'Human gate';
  gate: string;
};

const steps: Step[] = [
  {
    id: 1,
    phase: 'Shape',
    role: 'Planner',
    goal: 'Make the requested change decision-complete before implementation begins.',
    input: 'GitHub issue or feature idea, repository context, user constraints',
    output: 'Approved spec.md',
    skill: 'Waza /think',
    mode: 'Interactive',
    gate: 'Problem, scope, behavior, tests, and non-goals are explicit.',
  },
  {
    id: 2,
    phase: 'Shape',
    role: 'Plan reviewer',
    goal: 'Pressure-test architecture, data flow, edge cases, and delivery before coding.',
    input: 'spec.md and relevant repository evidence',
    output: 'plan-review.md and a revised approved spec.md',
    skill: 'gstack /plan-eng-review',
    mode: 'Interactive',
    gate: 'Engineering plan has no unresolved blocking decisions.',
  },
  {
    id: 3,
    phase: 'Build',
    role: 'Builder',
    goal: 'Implement only the approved behavior and surface any plan-breaking discovery.',
    input: 'Approved spec.md, repository rules, base commit',
    output: 'Code changes, tests, documentation, migrations or generated artifacts',
    skill: 'Project skills + coding agent',
    mode: 'Autonomous',
    gate: 'The change is coherent, scoped, and ready for deterministic checks.',
  },
  {
    id: 4,
    phase: 'Build',
    role: 'Verifier',
    goal: 'Establish deterministic implementation health with repository-authoritative checks.',
    input: 'Changed worktree, repository instructions, CI and package commands',
    output: 'verification.md with commands, results, and failures',
    skill: 'Waza /check or fallback contract',
    mode: 'Autonomous',
    gate: 'Required tests, types, lint, build, and artifact checks pass.',
  },
  {
    id: 5,
    phase: 'Understand',
    role: 'Cold reader',
    goal: 'Reconstruct what the branch actually implements without author intent.',
    input: 'Repository, base commit, HEAD; no issue, spec, or PR rationale',
    output: 'reconstruction.md bound to the observed base and HEAD',
    skill: 'understand-pr · fork_turns=none',
    mode: 'Autonomous',
    gate: 'Behavior, architecture, execution paths, and unknowns are evidenced.',
  },
  {
    id: 6,
    phase: 'Understand',
    role: 'Intent comparator',
    goal: 'Find differences between the independently observed code and approved intent.',
    input: 'reconstruction.md, approved spec.md, original issue',
    output: 'intent-comparison.md with missing, accidental, and unjustified behavior',
    skill: 'understand-pr · follow-up pass',
    mode: 'Autonomous',
    gate: 'Every material discrepancy is resolved or explicitly accepted.',
  },
  {
    id: 7,
    phase: 'Understand',
    role: 'Deep reviewer',
    goal: 'Resolve one architecture hotspot that remains difficult to explain.',
    input: 'Selected hotspot, code, and reconstruction evidence',
    output: 'Keep/change decision with rationale',
    skill: 'claude-code-kit /deepening-review',
    mode: 'Conditional',
    gate: 'The hotspot is accepted or routed back to the builder.',
  },
  {
    id: 8,
    phase: 'Review',
    role: 'Coordinator',
    goal: 'Freeze the exact candidate so every downstream artifact describes the same diff.',
    input: 'Passing gates and current base/HEAD identities',
    output: 'Immutable review-candidate record',
    skill: 'Proposed feature-workflow',
    mode: 'Autonomous',
    gate: 'The candidate commit is fixed and all upstream evidence is current.',
  },
  {
    id: 9,
    phase: 'Review',
    role: 'Review cartographer',
    goal: 'Minimize the cognitive cost of human review.',
    input: 'Final diff, reconstruction, and verification evidence',
    output: 'reviewer-map.md bound to base and HEAD',
    skill: 'reviewer-map',
    mode: 'Autonomous',
    gate: 'The reviewer has a reliable reading order and hotspot map.',
  },
  {
    id: 10,
    phase: 'Review',
    role: 'Human reviewer',
    goal: 'Decide whether the exact candidate is correct, safe, and maintainable.',
    input: 'Issue, spec, diff, reconstruction, reviewer map, verification evidence',
    output: 'Approval or actionable change requests',
    skill: 'Human accountability · no skill',
    mode: 'Human gate',
    gate: 'The reviewer approves the exact candidate commit.',
  },
  {
    id: 11,
    phase: 'Review',
    role: 'Shipper',
    goal: 'Publish exactly the approved candidate—never a later unreviewed commit.',
    input: 'Approved HEAD, green CI, required permissions',
    output: 'PR, merge, or release record',
    skill: 'Host-specific GitHub / ship integration',
    mode: 'Autonomous',
    gate: 'Published commit identity matches the approved candidate.',
  },
];

const phases = ['Shape', 'Build', 'Understand', 'Review'] as const;

function modeClass(mode: Step['mode']) {
  return 'mode mode-' + mode.toLowerCase().replace(' ', '-');
}

export default function Home() {
  const [selectedId, setSelectedId] = useState(1);
  const selected = useMemo(
    () => steps.find((step) => step.id === selectedId) ?? steps[0],
    [selectedId],
  );

  return (
    <main>
      <header className="site-header">
        <a className="brand" href="#top" aria-label="Agent workflow home">
          <span className="brand-mark">AW</span>
          <span>Agent workflow</span>
        </a>
        <nav aria-label="Page sections">
          <a href="#workflow">Workflow</a>
          <a href="#contracts">Contracts</a>
          <a href="#fresh-context">Fresh context</a>
        </nav>
      </header>

      <section className="hero" id="top">
        <div>
          <p className="eyebrow">A reusable engineering protocol</p>
          <h1>From rough idea to<br /><em>review-ready change.</em></h1>
        </div>
        <div className="hero-copy">
          <p>
            Eleven agents and gates, each with one goal, explicit inputs, and a durable output.
            Interactive work stays interactive until its contract is satisfied.
          </p>
          <div className="hero-stats" aria-label="Workflow summary">
            <span><strong>11</strong> steps</span>
            <span><strong>4</strong> phases</span>
            <span><strong>2</strong> bundled skills</span>
          </div>
        </div>
      </section>

      <section className="workflow-section" id="workflow">
        <div className="section-heading">
          <div>
            <p className="eyebrow">The contract map</p>
            <h2>Every handoff is inspectable.</h2>
          </div>
          <p>Select a step to inspect its complete agent contract.</p>
        </div>

        <div className="phase-grid">
          {phases.map((phase) => (
            <section className={'phase phase-' + phase.toLowerCase()} key={phase}>
              <header className="phase-header">
                <span>{String(phases.indexOf(phase) + 1).padStart(2, '0')}</span>
                <h3>{phase}</h3>
              </header>
              <div className="step-list">
                {steps.filter((step) => step.phase === phase).map((step) => (
                  <button
                    className={'step-card ' + (selectedId === step.id ? 'is-selected' : '')}
                    key={step.id}
                    type="button"
                    aria-pressed={selectedId === step.id}
                    onClick={() => setSelectedId(step.id)}
                  >
                    <span className="step-topline">
                      <span className="step-number">{String(step.id).padStart(2, '0')}</span>
                      <span className={modeClass(step.mode)}>{step.mode}</span>
                    </span>
                    <strong>{step.role}</strong>
                    <span className="step-goal">{step.goal}</span>
                    <span className="skill-label">{step.skill}</span>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>

        <article className="contract-panel" id="contracts" aria-live="polite">
          <div className="contract-title">
            <span className="contract-index">{String(selected.id).padStart(2, '0')}</span>
            <div>
              <p className="eyebrow">Selected agent contract</p>
              <h2>{selected.role}</h2>
            </div>
            <span className={modeClass(selected.mode)}>{selected.mode}</span>
          </div>

          <p className="contract-goal">{selected.goal}</p>

          <div className="contract-grid">
            <div>
              <span className="contract-label">Input</span>
              <p>{selected.input}</p>
            </div>
            <div>
              <span className="contract-label">Expected output</span>
              <p>{selected.output}</p>
            </div>
            <div>
              <span className="contract-label">Skill</span>
              <p className="mono">{selected.skill}</p>
            </div>
            <div>
              <span className="contract-label">Exit gate</span>
              <p>{selected.gate}</p>
            </div>
          </div>

          <div className="contract-nav">
            <button
              type="button"
              disabled={selected.id === 1}
              onClick={() => setSelectedId((id) => Math.max(1, id - 1))}
            >
              ← Previous
            </button>
            <span>{selected.id} of {steps.length}</span>
            <button
              type="button"
              disabled={selected.id === steps.length}
              onClick={() => setSelectedId((id) => Math.min(steps.length, id + 1))}
            >
              Next →
            </button>
          </div>
        </article>
      </section>

      <section className="fresh-section" id="fresh-context">
        <div className="fresh-copy">
          <p className="eyebrow">The independence boundary</p>
          <h2>Fresh context is a mechanism,<br />not a request to forget.</h2>
          <p>
            The cold reader runs in a separate subagent with no inherited conversation. It sees
            the repository and commit range, but not the issue, approved spec, PR description, or
            implementation rationale.
          </p>
        </div>
        <div className="context-diagram" role="img" aria-label="Parent agent sends only repository base and head to a context-free cold-reader subagent, which returns a reconstruction before receiving intent">
          <div className="context-node parent-node">
            <span>Parent context</span>
            <strong>Issue + spec + rationale</strong>
          </div>
          <div className="context-arrow">
            <span>base + HEAD only</span>
            <b>→</b>
          </div>
          <div className="context-node cold-node">
            <span>fork_turns=none</span>
            <strong>Cold reader</strong>
            <small>$understand-pr</small>
          </div>
          <div className="return-line">
            <b>←</b>
            <span>reconstruction.md first; intent comparison second</span>
          </div>
        </div>
      </section>

      <section className="artifact-section">
        <div className="section-heading compact">
          <div>
            <p className="eyebrow">Durable state</p>
            <h2>The artifact trail</h2>
          </div>
          <p>Every analytical artifact records the exact base and HEAD it describes.</p>
        </div>
        <ol className="artifact-track">
          {['spec.md', 'plan-review.md', 'code + tests', 'verification.md', 'reconstruction.md', 'intent-comparison.md', 'reviewer-map.md', 'approval'].map((artifact, index) => (
            <li key={artifact}>
              <span>{String(index + 1).padStart(2, '0')}</span>
              <strong>{artifact}</strong>
            </li>
          ))}
        </ol>
        <p className="stale-rule">
          <span>Invalidation rule</span>
          Any code change makes downstream reconstruction, comparison, and reviewer-map artifacts stale.
        </p>
      </section>

      <footer>
        <p>One goal per agent. One durable output per gate.</p>
        <a href="#top">Back to top ↑</a>
      </footer>
    </main>
  );
}
