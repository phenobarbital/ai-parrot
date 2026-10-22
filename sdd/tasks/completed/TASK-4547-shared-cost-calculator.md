# TASK-4547: Process-wide shared CostCalculator + resolve_event_cost helper

**Feature**: FEAT-710 — Parrot telemetry event fan-out
**Spec**: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4546
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 and Module 6 (Goal G5). Cost must be computed once per LLM call, at the origin, with one calculator shared by the process. This task adds the holder, installs it from both bootstrap paths, and adds the `resolve_event_cost` helper the subscribers will use (TASK-4550).

---

## Scope

- In `observability/cost/__init__.py`: add `get_shared_cost_calculator()`, `set_shared_cost_calculator(calc)` and `resolve_event_cost(event, fallback)`.
- `bootstrap.py`: after `cost_calc = CostCalculator(...)` (:115) call `set_shared_cost_calculator(cost_calc)`; clear it in `shutdown_usage_recording()`.
- `setup.py`: after `cost_calc = CostCalculator(override_path=override)` (:245) call `set_shared_cost_calculator(cost_calc)`.
- Add `ensure_shared_cost_calculator()` that builds one honoring `PARROT_PRICING_PATH` when none is installed (used by the fan-out when observability is off, design research S3).
- Write tests.

**NOT in scope**: changing the subscribers (TASK-4550); computing cost in clients (TASK-4548).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/cost/__init__.py` | MODIFY | Holder + resolve_event_cost + ensure_shared_cost_calculator |
| `packages/ai-parrot/src/parrot/observability/bootstrap.py` | MODIFY | Install/clear shared calculator |
| `packages/ai-parrot/src/parrot/observability/setup.py` | MODIFY | Install shared calculator on the OTel path |
| `packages/ai-parrot/tests/unit/observability/test_shared_cost_calculator.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against `origin/dev` @ `cf1888270` (2026-10-21). Re-run every `grep -c` before editing.

### Verified Imports
```python
from parrot.observability.cost.calculator import CostCalculator  # verified: observability/bootstrap.py:113
from parrot.observability.attributes import resolve_gen_ai_system  # verified: used in recorders/subscriber.py:96
from parrot.core.events.lifecycle.events import AfterClientCallEvent  # verified: yaml_loader.py:33-47
```

### Existing Signatures to Use
```python
# observability/cost/calculator.py:135
class CostCalculator:
    def __init__(self, *, override_path=None, stale_warn_days=...)  # FILL IN: confirm kwargs at :135-189
    def cost_usd(self, *, provider: str, model: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> Optional[float]  # :190
# observability/bootstrap.py
cost_calc = CostCalculator(override_path=config.pricing_override_path)   # :115 (lightweight path only; OTel path returns earlier)
def shutdown_usage_recording() -> None                                     # :186
# observability/setup.py
cost_calc = CostCalculator(override_path=override)                        # :245
```

### Does NOT Exist
- ~~`get_shared_cost_calculator`~~, ~~`set_shared_cost_calculator`~~, ~~`resolve_event_cost`~~, ~~`ensure_shared_cost_calculator`~~ — created here
- ~~`CostCalculator.instance()`~~ / ~~singleton classmethod~~ — does not exist

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/observability/cost/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/observability/bootstrap.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/observability/setup.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/observability/test_shared_cost_calculator.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/cost/calculator.py#CostCalculator",
    "sym:packages/ai-parrot/src/parrot/observability/bootstrap.py#shutdown_usage_recording"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async-first; never block the event loop; `self.logger`, never `print`.
- Telemetry must never raise into the request path.
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Implement the holder and helpers in `cost/__init__.py` — *why*: a tiny module-level holder is the least invasive way to share one instance.
2. Install it from both bootstrap paths and clear it on shutdown — *why*: the OTel path returns before `bootstrap.py:115` (spec §7), so both must install.
3. Write tests.

### `packages/ai-parrot/src/parrot/observability/cost/__init__.py` (MODIFY)
```python
# AFTER the module docstring (file has no other code)
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from parrot.core.events.lifecycle.events import AfterClientCallEvent
    from parrot.observability.cost.calculator import CostCalculator

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()
_SHARED: "Optional[CostCalculator]" = None


def get_shared_cost_calculator() -> "Optional[CostCalculator]":
    """Return the process-wide CostCalculator installed by observability bootstrap, or None."""
    return _SHARED


def set_shared_cost_calculator(calc: "Optional[CostCalculator]") -> None:
    """Install (or clear with None) the process-wide CostCalculator."""
    global _SHARED  # noqa: PLW0603
    with _LOCK:
        _SHARED = calc


def ensure_shared_cost_calculator() -> "CostCalculator":
    """Return the shared calculator, building one from PARROT_PRICING_PATH if none is installed."""
    # FILL IN: double-checked under _LOCK; read PARROT_PRICING_PATH via navconfig exactly like setup.py:228-244 — AC-3
    raise NotImplementedError


def resolve_event_cost(event: "AfterClientCallEvent", fallback: "Optional[CostCalculator]") -> Optional[float]:
    """Return the call's USD cost, computing it only when the origin did not.

    ``event.cost_usd`` wins when not None. Otherwise compute with the shared calculator, else ``fallback``
    (emitters that bypass AbstractClient, or tests that inject a calculator). Never raises.
    """
    if event.cost_usd is not None:
        return event.cost_usd
    calc = _SHARED or fallback
    if calc is None:
        return None
    from parrot.observability.attributes import resolve_gen_ai_system  # noqa: PLC0415

    try:
        return calc.cost_usd(
            provider=resolve_gen_ai_system(event.client_name),
            model=event.model,
            input_tokens=event.input_tokens or 0,
            output_tokens=event.output_tokens or 0,
        )
    except Exception:  # noqa: BLE001 — cost must never break telemetry
        logger.debug("resolve_event_cost failed", exc_info=True)
        return None
```
**Why**: the `cost_usd is not None` rule (not "trust the origin blindly") keeps the dev-loop dispatcher events priced (design research S9).

### `packages/ai-parrot/src/parrot/observability/bootstrap.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'cost_calc = CostCalculator(override_path=config.pricing_override_path)' bootstrap.py)
# AFTER — insert below that line (verified: :115)
        from parrot.observability.cost import set_shared_cost_calculator  # noqa: PLC0415

        set_shared_cost_calculator(cost_calc)
```
```python
# In shutdown_usage_recording() (verified: :186), before `_SUBSCRIBER = None`:
    from parrot.observability.cost import set_shared_cost_calculator  # noqa: PLC0415

    set_shared_cost_calculator(None)
```

### `packages/ai-parrot/src/parrot/observability/setup.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'cost_calc = CostCalculator(override_path=override)' setup.py)
# AFTER — insert below that line (verified: :245), same indentation
            from parrot.observability.cost import set_shared_cost_calculator  # noqa: PLC0415

            set_shared_cost_calculator(cost_calc)
```
`# FILL IN: also clear it in shutdown_telemetry()` — bounded by AC-2.

### `packages/ai-parrot/tests/unit/observability/test_shared_cost_calculator.py` (CREATE)
```python
"""FEAT-710 TASK-4547 — shared CostCalculator + resolve_event_cost."""
from parrot.core.events.lifecycle.events import AfterClientCallEvent
from parrot.observability.cost import (
    get_shared_cost_calculator, resolve_event_cost, set_shared_cost_calculator,
)


def test_event_cost_wins_without_recompute() -> None:
    class _Spy:
        calls = 0

        def cost_usd(self, **_):
            _Spy.calls += 1
            return 9.9

    set_shared_cost_calculator(_Spy())
    try:
        assert resolve_event_cost(AfterClientCallEvent(cost_usd=0.5), None) == 0.5
        assert _Spy.calls == 0
    finally:
        set_shared_cost_calculator(None)


def test_missing_cost_uses_shared_then_fallback() -> None:
    # FILL IN: cost_usd=None → shared calc used; no shared → fallback used; raising calc → None — AC-1
    raise NotImplementedError


def test_holder_roundtrip() -> None:
    assert get_shared_cost_calculator() is None
```

### FILL IN checklist
- [ ] `ensure_shared_cost_calculator` — AC-3
- [ ] Clear on `shutdown_telemetry` — AC-2
- [ ] Test body — AC-1

---

## Acceptance Criteria

- [ ] `resolve_event_cost` returns `event.cost_usd` without calling any calculator when it is set; otherwise shared → fallback; never raises.
- [ ] Both bootstrap paths install the same instance the subscribers receive; shutdown clears it.
- [ ] `ensure_shared_cost_calculator()` honors `PARROT_PRICING_PATH`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/observability/test_shared_cost_calculator.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_bootstrap.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_setup.py -q`

---

## Test Specification

See the test-file block in the Implementation Blueprint; every `FILL IN` test must pass.

---

## Agent Instructions

1. Work in the feature worktree, never on `dev`:
   `python -m scripts.sdd.ensure_worktree --slug parrot-telemetry-event-fanout --feature-id FEAT-710`
2. Read the spec `sdd/specs/parrot-telemetry-event-fanout.spec.md` (rev 0.4) for context.
3. Check that every `Depends-on` task is `done` in `sdd/tasks/index/parrot-telemetry-event-fanout.json`.
4. Verify the Codebase Contract before writing code (re-run `grep -c` on every anchor); fix the contract first if it drifted.
5. Set this task `in-progress` in the index and commit only that file.
6. Implement from the Blueprint, completing every `# FILL IN:`; never change a fixed signature or path.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
8. Commit only the files listed in this task.
9. Close with `scripts/sdd/close_task.sh TASK-4547 parrot-telemetry-event-fanout verified`.
10. Fill in the Completion Note and commit the staged SDD state.

---

## Completion Note



**Completed by**: sdd-worker orchestrator (coder: codex/gpt-5.6-sol)
**Date**: 2026-10-22
**Notes**: Delivered, merged, tests green; pre-existing unrelated failure test_attributes (jev/meta) noted.

**Deviations from spec**: none
