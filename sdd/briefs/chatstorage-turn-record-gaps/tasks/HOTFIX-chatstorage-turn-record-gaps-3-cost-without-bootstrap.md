# HOTFIX-chatstorage-turn-record-gaps-3: The client computes cost without the observability bootstrap

**Feature**: chatstorage-turn-record-gaps — close the turn-record gaps between conversation history and ChatStorage
**Spec**: `sdd/briefs/chatstorage-turn-record-gaps.brief.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`AbstractClient._compute_call_cost` returns `None` when no shared `CostCalculator` is installed.
Only the observability bootstrap installs one, so a standalone bot stores `cost_usd: null` and
`usage.estimated_cost: null` even for a model with a bundled price (brief, Problem 3). Decision 2
of the brief: fix it in the client layer. The owner approved editing `clients/base.py` for this
task; keep the change to the lines named below.

## Scope

In `packages/ai-parrot/src/parrot/clients/base.py`:

- In `_compute_call_cost`, when `get_shared_cost_calculator()` returns `None`, obtain one with
  `ensure_shared_cost_calculator()` (it builds from the bundled pricing tables or
  `PARROT_PRICING_PATH`, and caches the instance process-wide).
- The method must still never raise: the `ensure_shared_cost_calculator()` call goes inside the
  existing `try` so a failure to build a calculator logs at DEBUG and returns `None`.
- Extend the existing import on line 89 with `ensure_shared_cost_calculator`.

**NOT in scope**: any other method of `clients/base.py`, the calculator, pricing tables, the bot-layer
`backfill_estimated_cost`, event emission.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | Lazy calculator in `_compute_call_cost`; one import |
| `packages/ai-parrot/tests/unit/observability/test_cost_without_bootstrap.py` | CREATE | Regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev @ 80cc849fac, 2026-11-17)

- `packages/ai-parrot/src/parrot/clients/base.py:89` — `from parrot.observability.cost import get_shared_cost_calculator, last_call_cost`
- `packages/ai-parrot/src/parrot/clients/base.py:854` — `def _compute_call_cost(`
- `packages/ai-parrot/src/parrot/clients/base.py:865` — `calc = get_shared_cost_calculator()`
- `packages/ai-parrot/src/parrot/observability/cost/__init__.py:45` — `def get_shared_cost_calculator() -> "Optional[CostCalculator]":`
- `packages/ai-parrot/src/parrot/observability/cost/__init__.py:50` — `def set_shared_cost_calculator(calc: "Optional[CostCalculator]") -> None:`
- `packages/ai-parrot/src/parrot/observability/cost/__init__.py:57` — `def ensure_shared_cost_calculator() -> "CostCalculator":`
- `packages/ai-parrot/src/parrot/observability/cost/pricing/google.json` has an entry for `gemini-3-flash-preview`.
- Existing tests to keep green: `packages/ai-parrot/tests/unit/observability/test_cost_computed_once.py`,
  `packages/ai-parrot/tests/unit/observability/test_shared_cost_calculator.py`.

### Does NOT Exist

- No per-client calculator and no `AbstractClient.cost_calculator` attribute.

## Acceptance Criteria

- [ ] **AC-1**: With `set_shared_cost_calculator(None)` (no bootstrap), `_compute_call_cost` for
      provider google / model `gemini-3-flash-preview` with non-zero tokens returns a float `> 0`.
- [ ] **AC-2**: When `ensure_shared_cost_calculator` raises, `_compute_call_cost` returns `None` and
      does not raise.
- [ ] **AC-3**: A calculator already installed by the bootstrap is used as-is (no second instance is built).
- [ ] **AC-4**: `test_cost_computed_once.py` and `test_shared_cost_calculator.py` still pass. If one
      of them asserts `None` for the no-calculator case, update that assertion and say so in the
      Completion Note.
- [ ] **AC-5**: Every test restores the shared calculator it changed (`set_shared_cost_calculator` in a fixture teardown).

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/unit/observability/test_cost_without_bootstrap.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/unit/observability/test_cost_computed_once.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/unit/observability/test_shared_cost_calculator.py -q`

## Agent Instructions

1. Work in this worktree only; verify every anchor above before editing.
2. Touch only `_compute_call_cost` and the import on line 89 in `clients/base.py`.
3. `ruff check --fix` and `black -l 120` on the listed files; run the validation commands.
4. Commit only the listed files: `fix(chatstorage-turn-record-gaps): HOTFIX-chatstorage-turn-record-gaps-3 — cost without bootstrap`.

## Completion Note

Pending.
