---
id: F014
query_id: Q014
type: grep
intent: "Inventory of Python assumptions in the shipped prompt and template assets"
executed_at: 2026-11-04T22:25:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F014 — Lint, format and type-check have no indirection in the shipped prompts; templates are Python-shaped

## Summary

Tests are already indirected (`test_command`, runner registry). Lint, format and
type-check are not: every concrete instruction names ruff, black, mypy or pylint. Where
a guard exists the step skips itself, so a TypeScript repository gets no lint or format
pass at all. The task/spec/brief templates carry `python` code fences, `from parrot…`
imports and pytest skeletons, and one prompt hard-codes ai-parrot's identity. The
seeded `sdd/CONVENTIONS.md` is language-neutral but no prompt reads its commands section.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md`
  lines: 165-182
  symbol: null
  excerpt: |
    `ruff check` and report; do not fix or commit. It runs only in a repository that
    configures ruff (`ruff.toml`, `.ruff.toml` or `[tool.ruff]` in `pyproject.toml`);
    anywhere else it is skipped and the report says "lint: ruff not configured".

- path: `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/qa-runner.md`
  lines: 84-89
  symbol: null
  excerpt: |
    ruff check <changed-files>      # only if the repo configures ruff (ruff.toml, .ruff.toml, [tool.ruff])
    mypy <changed-files>            # only if a mypy config exists in the repo
    A repository that configures neither gets no lint step; record "lint: not configured" in the report.

- path: `packages/ai-parrot/src/parrot/sdd/_assets/claude/hooks/sdd-worker-format.sh`
  lines: 69-93
  symbol: null
  excerpt: |
    | grep -E '\.py$' \
    command -v "$BLACK" >/dev/null 2>&1 || { note "black not found — skipping."; exit 0; }

- path: `packages/ai-parrot/src/parrot/sdd/_assets/sdd/sdd_templates/task.md`
  lines: 53-281
  symbol: null
  excerpt: |
    from parrot.module import ClassName  # verified: parrot/module/__init__.py:NN
    - [ ] All tests pass: `pytest <test_path> -v`
    - [ ] Imports work: `from parrot.<module> import <Component>`

- path: `packages/ai-parrot/src/parrot/sdd/_assets/sdd/sdd_templates/brief.md`
  lines: 37-37
  symbol: null
  excerpt: |
    <!-- File-level pytest only, e.g. `pytest path/to/test_file.py -q`. -->

- path: `packages/ai-parrot/src/parrot/sdd/_assets/sdd/sdd_templates/design_research.prompt.md`
  lines: 15-16
  symbol: null
  excerpt: |
    You are an independent design reviewer for **ai-parrot**, an async-first Python
    framework for AI agents (aiohttp, Pydantic v2).

## Notes

The rest of this inventory comes from the assets audit lane and was NOT re-read line by
line (treat as medium confidence): `sdd-worker.md` L49-58 / `sdd-coder.md` L38-43
(`.venv` + `uv` shared-environment policy), `sdd-worker.md` L264-270 and L586-587
(`parrot.utils.types`, `.so`, maturin — ai-parrot specifics), `sdd-autopilot.md` L387 and
L575 ("ruff check + mypy" as fixed steps), `sdd-secondopinion.md` L53 and
`sdd-explain.md` L95 (ai-parrot conventions stated as the project's), `spec.md` L157,
L189-193, L243-244, L320-323 (pytest operands, `@pytest.fixture`, ai-parrot patterns),
`sdd-spec.md` L405-409 and `sdd-brainstorm.md` L134-135 ("checking `__init__.py`
exports"), `audit.py:27` `EXTERNAL_TOOLS` listing `black`/`pylint`.
Already neutral per the same lane: `sdd/CONVENTIONS.md` (30-line seed, `"seed": true`
in the manifest), `sdd-start.md`, `sdd-status.md`, `sdd-next.md`, `sdd-tojira.md`,
`remove-worktree.md`, `code-reviewer.md` L16-22, the runner-registry sections of
`sdd-task.md` L444-468 and `spec.md` L170-186.
Grep of the canonical `claude/` + `sdd/` asset tree for eslint, prettier, tsc and biome
found nothing (lane report).
