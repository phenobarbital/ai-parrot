---
id: FG-006
query_id: Q065
type: git_log
intent: "Recent activity on dev_flow (declarative stage topology)."
executed_at: 2026-10-30T16:41:30Z
duration_ms: 300
parent_id: null
depth: 0
---

# FG-006 — flows/dev_flow/: 10 commits in 90 days, last on 2026-09-19; stable declarative topology whose subagent briefs are shipped as _subagent_data/*.md

## Summary

10 commits (Jesus, Jesus Lara, Claude) between 2026-09-01 and 2026-09-19, none since. Themes: per-run model plan (TASK-2687, resumed runs keep seats; two fixes), research-partner client fix, PEP-420 client enum hard-cut (TASK-2845/2846), narrative console/thinking/changeset per-seat summary, Slack `--base` threading (TASK-3196), and TASK-3465 which made `/sdd-spec` carry `projects/tags` and `sdd-ideation` fill them — that commit shows the dev-flow ships its subagent persona briefs as data files under `flows/dev_flow/_subagent_data/sdd-ideation.md`, mirrored in `.claude/agents/`, `.agent/agents/`, `.agents/agents/`. So a "persona as markdown data consumed by a flow node" precedent exists, but in 4 hand-synced copies.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md`
  lines: n/a
  symbol: subagent brief (data file)
  excerpt: |
    d6508203e4 2026-09-19 Jesus feat(sdd-spec-changes): TASK-3465 — sdd-spec carries projects/tags forward; sdd-ideation fills them
     .agent/agents/sdd-ideation/agent.md | .agents/agents/sdd-ideation/agent.md | .claude/agents/sdd-ideation.md
     .../src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md | 8 ++++++++
     .agent/workflows/sdd-spec.md | .claude/commands/sdd-spec.md | .agents/skills/sdd-spec/SKILL.md

- path: `packages/ai-parrot/src/parrot/flows/dev_flow/`
  lines: n/a
  symbol: commits
  excerpt: |
    13c91cfbf7 2026-09-12 Claude feat(dev-loop): narrative console, thinking, changeset and per-seat summary
    c3e9905501 2026-09-12 Jesus feat(dev-loop-slack): TASK-3196 — thread --base into the dev-flow ideation document
    d1cb6b3adb 2026-09-02 Jesus Lara fix(dev-flow): open the research partner's client — complementary research degraded on every run
    00b6dd7314 2026-09-01 Jesus Lara feat(per-run-model-plan): TASK-2687 — resumed run keeps original seats
    a846edad4b 2026-09-01 fix(per-run-model-plan): resumed runs must not adopt a newly submitted per-run override

## Notes

- "Seats" (per-run model plan) is the existing tier→model projection mechanism in flows: a stage's model is a seat chosen per run, not hard-coded. Relevant to the `tier` open question.
- [cross-lane: type=read, intent=dev_flow/definition.py — how nodes/stages declare their subagent brief and gates; whether a model seat is declared per node]
