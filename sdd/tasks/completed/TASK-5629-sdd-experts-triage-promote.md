# TASK-5629: `parrot sdd experts triage` and `promote` (inferred ADR)

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-5628
**Assigned-to**: unassigned

---

## Context

Spec §2.6–2.7 / Module 10, AC15.

---

## Scope

- `triage <contribution> <finding-id> confirm|reject|escalate --reason`: update the finding status + reason.
- `promote <contribution> <finding-id>`: only for `confirm`ed findings; create an inferred decision via `DecisionService` (read service.py to find how `generate` persists `origin="inferred"`; if `generate(target)` cannot carry a provided statement, add NOTHING to DecisionService — instead write the ADR markdown file in the decisions directory with origin inferred / review unreviewed and run `sync`; decide after reading).
- Create `parrot/experts/promotion.py` for the promote logic.
- Tests.

**NOT in scope**: Reviewing decisions (existing `DecisionService.review`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/experts_cli.py` | MODIFY | triage + promote commands |
| `packages/ai-parrot/src/parrot/experts/promotion.py` | CREATE | promotion |
| `packages/ai-parrot/tests/sdd/test_experts_triage_promote.py` | CREATE | tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.experts.contributions import load_contribution, save_contribution  # TASK-5628
```

### Existing Signatures to Use
```python
class DecisionService  # knowledge/wiki/decisions/service.py:96
    async def generate(self, target: str) -> GenerationResult  # :389 (creates origin="inferred" ~:443)
    review(request: ReviewRequest) -> DecisionRecord  # ~:473
# models: origin Literal["documented","inferred"]; review_status Literal["unreviewed","accepted","rejected"]
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.
- ~~`DecisionService.propose` / `.record`~~.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/experts_cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/experts/promotion.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_experts_triage_promote.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Conventions: `.claude/rules/codebase-conventions.md` (Pydantic v2, Google docstrings, `self.logger`, async I/O, no print).
- Worktree tests need `PYTHONPATH=packages/ai-parrot/src` (plus `packages/ai-parrot-integrations/src` / `packages/ai-parrot-tools/src` when touched).

---

## Implementation Blueprint

### Steps (in order)
1. Read decisions/service.py 380–480 and the decisions models.
2. Implement.
3. Tests.

### Blocks

```python
# packages/ai-parrot/src/parrot/experts/promotion.py  (CREATE)
"""Finding → inferred decision (FEAT-890 M10)."""
from __future__ import annotations

async def promote_finding(contribution_path: "Path", finding_id: str, *, repo_root: "Path") -> str:
    """Return the created decision id; raises ValueError unless the finding is confirmed."""
    # FILL IN — see Scope bullet 2 for the decision
```

### FILL IN checklist
- [ ] promotion mechanism
- [ ] tests

---

## Acceptance Criteria

- [ ] AC15.

## Validation Commands
- `pytest packages/ai-parrot/tests/sdd/test_experts_triage_promote.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5629 expert-stages-and-delegation verified`.

---

## Completion Note


- Task: TASK-5629
- Feature: expert-stages-and-delegation
- Implementation SHA: da506d454408f72be2a2e0fd492868cb840c8e6c
- Closed at (UTC): 2026-11-13T23:30:54+00:00
- Fix commits: 7955e73b68a208c7fd870de3115c445461d494b2

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| seat_summary | Seat: qwen · Backend: nova · Model: qwen.qwen3-coder-480b-a35b-instruct · Attempts: 3 (glm failed x2, qwen completed) · Duration: ~641s · Tokens: n/a |
