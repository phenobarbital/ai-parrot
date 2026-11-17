---
id: F012
query_id: Q012
type: read
intent: "Which shipped agent prompt fails outright in a repository without Python tooling?"
executed_at: 2026-11-04T22:33:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F012 — The shipped `sdd-qa` agent runs `ruff check .` and `mypy` unconditionally and gates on both

## Summary

The dev-loop QA agent's step 3 runs `ruff check .` and `mypy --no-incremental .` with
only a parenthetical "or the project's configured equivalents", and defines
`lint_passed` as both returning 0. The top-level `passed` requires `lint_passed`. In a
repository without ruff or mypy the QA verdict is always a failure.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-qa.md`
  lines: 57-60
  symbol: null
  excerpt: |
    3. Run lint: ``ruff check .`` and ``mypy --no-incremental .`` (or the
       project's configured equivalents). Capture combined output as
       ``lint_output``; ``lint_passed`` = both ruff and mypy returned 0.
    4. ``passed`` (top-level) = every ``criterion_results[*].passed`` is

## Notes

Contrast with `qa-runner.md:84-89`, which is already guarded (F014). The twins under
`_assets/agents/agents/sdd-qa/agent.md` carry the same text (lane report).
