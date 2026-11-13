# TASK-5626: Expert tier → sdd-coder seat hint

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2.4 / Module 6, AC11. In dev-loop, an expert's tier informs seat eligibility; `RosterSeat` is unchanged, the map lives on `RosterConfig`.

---

## Scope

- Add `expert_tier_seats: dict[str, Literal["complex", "standard", "cheap"]]` to `RosterConfig` with default `{"judgment": "complex", "balanced": "standard", "templated": "cheap"}`.
- Add `eligible_seats_for_tier(tier, seats, policy, config)` in roster.py: `complex` → reuse `eligible_seats` with a synthetic complex assessment; `standard` → seats unchanged; `cheap` → seats ordered cheapest-first (decide ordering source).
- Tests.

**NOT in scope**: Wiring the hint into the dev-loop dispatcher for expert stages (no expert stage runs in dev-loop yet).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | RosterConfig field |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py` | MODIFY | tier helper |
| `packages/ai-parrot/tests/flows/dev_loop/test_tier_seat_hint.py` | CREATE | tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.complexity_models import ComplexityAssessment, ComplexityPolicy  # verified: complexity_models.py:254,103
```

### Existing Signatures to Use
```python
class RosterConfig(BaseModel)  # sdd_coder/models.py:294
def eligible_seats(assessment: ComplexityAssessment, seats: List[RosterSeat], policy: ComplexityPolicy) -> List[RosterSeat]  # roster.py:241
ComplexityAssessment.classification: Literal["standard", "complex", "unknown"]  # complexity_models.py:277
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.
- ~~`RosterSeat.tier`~~ — do not add.
- Do not import `parrot.experts` here (keep sdd_coder independent): tier is passed as a plain string.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_tier_seat_hint.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#eligible_seats"
  ]
}
```

---

## Implementation Notes

- Conventions: `.claude/rules/codebase-conventions.md` (Pydantic v2, Google docstrings, `self.logger`, async I/O, no print).
- Worktree tests need `PYTHONPATH=packages/ai-parrot/src` (plus `packages/ai-parrot-integrations/src` / `packages/ai-parrot-tools/src` when touched).

---

## Implementation Blueprint

### Steps (in order)
1. Read RosterConfig and eligible_seats fully; check existing Dict/Field imports.
2. Edit; tests.

### Blocks

```python
# sdd_coder/models.py (MODIFY) — inside `class RosterConfig(BaseModel):` (verified: models.py:294; occurrences: 1)
    expert_tier_seats: Dict[str, Literal["complex", "standard", "cheap"]] = Field(
        default_factory=lambda: {"judgment": "complex", "balanced": "standard", "templated": "cheap"}
    )
# roster.py (MODIFY) — AFTER the end of `def eligible_seats(` (verified: roster.py:241; occurrences: 1)
def eligible_seats_for_tier(tier: str, seats: List[RosterSeat], policy: ComplexityPolicy, config: RosterConfig) -> List[RosterSeat]:
    """Seat hint for an expert tier (FEAT-890 AC11); unknown tier → standard."""
    # FILL IN
```
**Why**: a plain-string tier avoids a dev-loop → experts import.

### FILL IN checklist
- [ ] synthetic assessment construction
- [ ] cheap ordering
- [ ] tests

---

## Acceptance Criteria

- [ ] AC11.
- [ ] Existing roster tests pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_tier_seat_hint.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5626 expert-stages-and-delegation verified`.

---

## Completion Note


- Task: TASK-5626
- Feature: expert-stages-and-delegation
- Implementation SHA: 7e4d0f8a3f9850cff4030e5520e3cb07fafb10bb
- Closed at (UTC): 2026-11-13T22:24:26+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a |
