# OpenAI Base Client Tech Debt — FEAT-662

```yaml
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [clients, openai, ruff, testing, tech-debt, ledger-fix]
```

## 1. Problem

Two tech-debt issues from the FEAT-579 adversarial code review:

1. **Ruff violations** (issue:8d1149254f88, major) — `openai_base.py` has 2
   pre-existing ruff errors: line 67 B039 (mutable `ContextVar` default) and
   line ~1715 B904 (`raise` without `from` in except-chain).

2. **Missing invoke() coverage** (issue:cfdc7e0cce94, minor) — No test
   exercised the budget-exhausted finalize path or the partial (bx2) path in
   `invoke()` before FEAT-579 incidentally added telemetry tests. The
   underlying budget-exhausted control flow (independent of telemetry) needs
   direct regression coverage.

## 2. Solution

### M1 — Fix ruff violations (openai_base.py)

- B039: Replace mutable `ContextVar` default with `default_factory` pattern
  (use `ContextVar("name")` with no default, or a factory).
- B904: Add `from exc` to the flagged `raise` in the except-chain.

### M2 — Add invoke() budget-exhausted tests

Add direct tests for the budget-exhausted finalize path and the partial (bx2)
path, independent of telemetry, covering the try/except dispatch-block at
~openai_base.py:1608-1677.

## 3. Files

| File | Module | Action |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | M1 | MODIFY |
| `packages/ai-parrot/tests/unit/clients/test_invoke_budget_exhausted.py` | M2 | CREATE |

## 4. Acceptance Criteria

- AC1: `ruff check packages/ai-parrot/src/parrot/clients/openai_base.py` passes (0 errors)
- AC2: Budget-exhausted finalize path is tested directly (not only via telemetry)
- AC3: Partial (bx2) path is tested directly
- AC4: Existing client tests pass
