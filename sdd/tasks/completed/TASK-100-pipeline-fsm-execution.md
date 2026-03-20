# TASK-100: Pipeline FSM & Execution Updates

**Feature**: MassiveToolkit Integration (FEAT-019)
**Spec**: `sdd/specs/massivetoolkit-integration.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-099
**Assigned-to**: antigravity-session

---

## Context

> Wires the `EnrichmentService` into the trading pipeline. Adds the `enriching` state
> to `PipelineStateMachine` and modifies `run_trading_pipeline()` to execute the
> enrichment phase with a 5-minute hard timeout. Implements Spec Section 3 (Module 2).

---

## Scope

- Add `enriching` state to `PipelineStateMachine` in `parrot/finance/fsm.py`.
- Add `start_enrichment` transition: `researching → enriching`.
- Modify `start_deliberation` to accept both `enriching → deliberating` and `researching → deliberating` (graceful degradation path).
- Update `run_trading_pipeline()` in `parrot/finance/execution.py`:
  - Accept new optional parameters: `massive_toolkit`, `options_analytics`, `quant_toolkit`.
  - If `massive_toolkit` is present and `MASSIVE_ENRICHMENT_ENABLED=true`, instantiate `EnrichmentService` and run `enrich_briefings()` wrapped in `asyncio.wait_for(timeout=300)`.
  - On timeout or exception, log warning and proceed with raw briefings.
- Write unit tests for FSM transitions and pipeline branching.

**NOT in scope**: `EnrichmentService` internals (TASK-099), analyst prompts (TASK-101).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/fsm.py` | MODIFY | Add `enriching` state + transitions |
| `parrot/finance/execution.py` | MODIFY | Wire enrichment phase into pipeline |
| `tests/unit/test_pipeline_enrichment.py` | CREATE | FSM + pipeline branching tests |

---

## Implementation Notes

### FSM Changes
```python
# New state
enriching = State("enriching")

# New transitions
start_enrichment = researching.to(enriching)
start_deliberation = (
    idle.to(deliberating)
    | researching.to(deliberating)   # Direct path (no Massive)
    | enriching.to(deliberating)     # Enriched path
)
```

### Pipeline Changes
```python
# In run_trading_pipeline():
if massive_toolkit:
    pipeline_fsm.start_enrichment()
    enrichment_service = EnrichmentService(...)
    try:
        briefings = await asyncio.wait_for(
            enrichment_service.enrich_briefings(briefings),
            timeout=300,
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"Enrichment failed: {e}. Proceeding with raw briefings.")

pipeline_fsm.start_deliberation()
```

### Key Constraints
- The `researching → deliberating` direct path MUST be preserved for graceful degradation.
- `MASSIVE_ENRICHMENT_ENABLED` env var acts as a kill switch.
- Hard timeout of 300s (configurable via `MASSIVE_ENRICHMENT_TIMEOUT`).

### References in Codebase
- `parrot/finance/fsm.py` — current `PipelineStateMachine`
- `parrot/finance/execution.py` — current `run_trading_pipeline()`

---

## Acceptance Criteria

- [ ] `enriching` state exists in FSM with correct transitions
- [ ] `researching → deliberating` direct path preserved
- [ ] Pipeline runs enrichment when `massive_toolkit` provided
- [ ] Pipeline skips enrichment when `massive_toolkit` is None
- [ ] Timeout (300s) triggers fallback to raw briefings
- [ ] Enrichment exceptions logged as warnings, pipeline continues
- [ ] All tests pass: `pytest tests/unit/test_pipeline_enrichment.py -v`
- [ ] No linting errors: `ruff check parrot/finance/fsm.py parrot/finance/execution.py`

---

## Test Specification

```python
# tests/unit/test_pipeline_enrichment.py
import pytest
from parrot.finance.fsm import PipelineStateMachine


class TestPipelineFSM:
    def test_enrichment_state_exists(self):
        """FSM has the enriching state."""
        fsm = PipelineStateMachine(pipeline_id="test")
        assert hasattr(fsm, "enriching")

    def test_researching_to_enriching(self):
        """Can transition from researching to enriching."""
        fsm = PipelineStateMachine(pipeline_id="test")
        fsm.start_research()
        fsm.start_enrichment()
        assert fsm.current_state.id == "enriching"

    def test_enriching_to_deliberating(self):
        """Can transition from enriching to deliberating."""
        fsm = PipelineStateMachine(pipeline_id="test")
        fsm.start_research()
        fsm.start_enrichment()
        fsm.start_deliberation()
        assert fsm.current_state.id == "deliberating"

    def test_direct_path_preserved(self):
        """Can go researching → deliberating without enrichment."""
        fsm = PipelineStateMachine(pipeline_id="test")
        fsm.start_research()
        fsm.start_deliberation()
        assert fsm.current_state.id == "deliberating"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-099 is in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-100-pipeline-fsm-execution.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: antigravity-session
**Date**: 2026-03-02
**Notes**: 
- Added `enriching` state to `PipelineStateMachine` in `fsm.py` with `start_enrichment` transition and updated `halt`/`fail` emergency paths.
- Preserved `researching → deliberating` direct path for graceful degradation.
- Wired enrichment phase into `run_trading_pipeline()` in `execution.py` with `MASSIVE_ENRICHMENT_ENABLED` kill switch and configurable timeout (`MASSIVE_ENRICHMENT_TIMEOUT`, default 300s).
- On timeout or exception, logs warning and proceeds with raw briefings.
- All 10 tests pass in `tests/unit/test_pipeline_enrichment.py`.

**Deviations from spec**: none
