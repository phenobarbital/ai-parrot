# `/sdd-proposal` v1.0 — Research-First Proposal Generator

Drop-in package for the AI-Parrot SDD pipeline. Implements a research-first
alternative to `/sdd-brainstorm` and `/sdd-fromjira`: takes a thin source
(typically a sparse Jira ticket), investigates the codebase, synthesizes
findings with confidence-graded reasoning, and produces a grounded proposal.

## What's in this package

```
.claude/
  commands/
    sdd-proposal.md            # The slash command (orchestrator)

sdd/
  templates/
    proposal.md                # Enriched proposal template
    state.schema.json          # State persistence schema (resumability + audit)
    research_plan.prompt.md    # Phase 1 prompt (planner)
    research_plan.schema.json  # Phase 1 output schema
    synthesis.prompt.md        # Phase 3 prompt (synthesis agent)
    finding.md                 # Per-query digest template
```

## Pipeline at a glance

```
/sdd-proposal <source>
  ├── Phase 0 — source resolution           (Jira | inline | file)
  ├── Phase 1 — research plan generation    [GATE: user approves]
  ├── Phase 2 — agentic codebase research   (budgeted; persists findings)
  ├── Phase 3 — synthesis                   (chain-of-thought, JSON)
  ├── Phase 4 — review gate                 [GATE: user validates synthesis]
  ├── Phase 5 — targeted Q&A                (only if material unknowns)
  ├── Phase 6 — proposal rendering          (sdd/proposals/<slug>.proposal.md)
  └── Phase 7 — commit + recommend next     (→ /sdd-spec or /sdd-brainstorm)
```

State is persisted to `sdd/state/<FEAT-ID>/` after each phase; runs are
resumable via `/sdd-proposal --resume <FEAT-ID>`.

## How to install

```bash
# From the package root:
cp -r .claude/commands/sdd-proposal.md   <repo>/.claude/commands/
cp -r sdd/templates/*                     <repo>/sdd/templates/
mkdir -p <repo>/sdd/state                 # state directory (gitignored or committed per policy)
```

If you want state to be auditable across the team (recommended), commit
`sdd/state/` to `dev`. If you want it ephemeral, add `sdd/state/` to
`.gitignore` — but then `--resume` only works on the same machine.

## How it differs from existing commands

| Aspect                  | `/sdd-brainstorm`          | `/sdd-fromjira`            | `/sdd-proposal` (this)            |
|-------------------------|----------------------------|----------------------------|-----------------------------------|
| Order                   | Q&A → research             | Jira → Q&A → research      | **Research → synthesis → Q&A**    |
| Best for                | Greenfield features        | Jira-seeded brainstorm     | Sparse tickets / bugs             |
| Output                  | Brainstorm w/ 3+ options   | Brainstorm w/ Jira context | Single-hypothesis grounded proposal |
| Hallucination defense   | Code Context section       | Code Context section       | **Lint + finding-ID grounding**   |
| Confidence reporting    | Implicit                   | Implicit                   | **Explicit confidence map**       |
| Resumability            | None                       | None                       | **Full state.json checkpoints**   |
| Budget control          | None                       | None                       | **Hard limits per profile**       |
| Routes to               | `/sdd-spec`                | `/sdd-spec`                | `/sdd-spec` OR `/sdd-brainstorm`  |

**When to pick which**:
- **`/sdd-proposal`** — the source is a thin Jira ticket, a bug report, or any
  request where the codebase has more context than the requester provided.
  This is the new default entry point for tickets.
- **`/sdd-brainstorm`** — truly greenfield features with no existing code to
  investigate.
- **`/sdd-fromjira`** — kept for backward compatibility; superseded by
  `/sdd-proposal NAV-XXXX` for most uses.

## Key design principles

1. **Codebase first, user second.** The repo is the primary source of truth.
   The user is consulted only for material unknowns the research couldn't
   resolve.

2. **Evidence-grounded synthesis.** Every claim in the proposal traces to a
   finding ID. The synthesis linter rejects fabrications.

3. **Honest confidence.** Claims are atomic and individually rated. The
   overall confidence is the *minimum* of contributing factors — never
   averaged up. Truncated research caps confidence at `medium`.

4. **Resumability.** State is checkpointed after every phase. Crashes or
   interruptions are recoverable via `--resume`.

5. **Budget-aware.** Research has hard limits (file reads, grep calls, wall
   time). When exhausted, the synthesis honestly reports `truncated: true`.

6. **Routes intelligently.** High-confidence proposals go to `/sdd-spec`.
   Medium-confidence ones with architectural forks go to `/sdd-brainstorm`.
   Trivial localized fixes can skip to `/sdd-task`.

## Recommended follow-ups (not in this package)

These are referenced in the design but require additional work:

- **`tools/sdd/synthesis_lint.py`** — a small validator that enforces the
  hard rules (paths cited in findings, confidence caps, etc.). Run as a
  gate before Phase 6.

- **Eval set in `sdd/evals/proposals/`** — 5-10 historical bugs/features
  with known answers. Replay the synthesis prompt against reconstructed
  digests and measure: localization recall, hypothesis precision, confidence
  calibration.

- **`sdd/WORKFLOW.md` update** — document when to pick `/sdd-proposal` vs.
  `/sdd-brainstorm` vs. `/sdd-fromjira`.

## Versioning

| Component                      | Version |
|--------------------------------|---------|
| Slash command                  | 1.0     |
| Proposal template              | 1.0     |
| State schema                   | 1.0     |
| Research-plan prompt + schema  | 1.0     |
| Synthesis prompt               | 1.0     |
| Finding template               | 1.0     |

Bump component versions independently. The proposal frontmatter records all
versions used to generate it (see Provenance section in the template).
