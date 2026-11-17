---
kind: inline
jira_key: null
fetched_at: 2026-11-11T22:32:22Z
summary_oneline: "Rewrite FEAT-713 accounting-metrics-layer on top of the ai-parrot-semantic package that exists on dev; resolve what FEAT-880 needs (DuckDB/Arrow)"
---

# Source — FEAT-713 revision (inline, translated from Spanish)

> Re-write FEAT-713 `accounting-metrics-layer` (`sdd/specs/accounting-metrics-layer.spec.md`, draft of
> 2026-10-21, never decomposed into tasks) on the basis of the `ai-parrot-semantic` package that already
> exists on `dev` after FEAT-704 merged (PR #1821). The original spec assumed FEAT-704 was paused and
> created the satellite skeleton itself (M1, AC2 and Q10 are obsolete). The new proposal must start from
> `packages/ai-parrot-semantic/src/parrot/semantic/` as it is today, keep the accepted brainstorm
> decisions (`sdd/proposals/accounting-metrics-layer.brainstorm.md`, Option B) that still hold, and
> resolve what FEAT-880 `datasetmanager-semantic-source`
> (`sdd/proposals/datasetmanager-semantic-source.proposal.md`) needs, including DuckDB/Arrow execution
> (AC10, AC17).

Owner statement that triggered the run: "the ideal is to re-write it again (sdd-proposal) based on what
`ai-parrot-semantic` already has, since the new spec on the DatasetManager semantic source needs it
resolved."

## Inputs this revision supersedes or depends on

- `sdd/specs/accounting-metrics-layer.spec.md` — FEAT-713 spec, `Status: draft`, 1099 lines, single commit
  `15d77efe4d` (2026-10-21). No per-spec index, no task files, no branch, no PR.
- `sdd/proposals/accounting-metrics-layer.brainstorm.md` — accepted 2026-10-21, Option B.
- `sdd/proposals/datasetmanager-semantic-source.proposal.md` — FEAT-880, `status: review`. Its U4 moved the
  DuckDB-backed dataset store out of FEAT-880 "into a revision of FEAT-713".
- `sdd/state/FEAT-713/design_research/` — design-research artifacts from the original spec run.

## Id

The revision keeps the reserved id **FEAT-713**; no new FEAT id is allocated.
