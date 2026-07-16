# TASK-1793: End-to-end integration tests, FEAT-177 benchmark evidence, documentation

**Feature**: FEAT-310 — Unified EventBus v2 — queue-based dispatch, severity, ingress channels, and notifications
**Spec**: `sdd/specs/eventbus-v2.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1786, TASK-1787, TASK-1788, TASK-1789
**Assigned-to**: unassigned

---

## Context

Closing task for FEAT-310 Phase 1+2: the cross-module integration tests from
spec §4, the emitter-overhead benchmark required by spec §5 (FEAT-177 budget:
< 0.1% of LLM call latency, evidence in `artifacts/logs/`), and the
documentation acceptance criterion (bus architecture, config reference,
migration notes, "typed hot path vs app-wide fabric" doctrine).

---

## Scope

- Integration tests (spec §4):
  - `test_end_to_end_memory_mode` — emit → workers → severity-filtered
    subscriber → notification rule fires (mocked async-notify).
  - `test_end_to_end_streams_mode` — two consumers in a group vs real/fake
    Redis: at-least-once, no double-processing with dedup
    (`@pytest.mark.integration` if real Redis required).
  - `test_lifecycle_dual_emit_through_facade` — `EventRegistry.forward_to_bus`
    → envelope arrives; FEAT-177 fire-and-forget preserved.
  - `test_graceful_shutdown_drain` — pending queue drained within deadline;
    no lost DLQ writes.
- Benchmark: micro-benchmark of `emit()` overhead (ns/op, p99) vs the
  FEAT-177 budget; script + output saved to `artifacts/logs/feat-310-bench-*`;
  assert-style check documented (not a flaky CI gate — mark it
  `@pytest.mark.benchmark` or a standalone script).
- Documentation in `docs/`:
  - Bus architecture page (layers diagram from spec §2).
  - Config reference: `[bus]` and `[[bus.alerts]]` with defaults table.
  - Migration notes (legacy `EventBus` semantics changes: async delivery,
    return-count meaning).
  - Doctrine section: "typed hot path (EventRegistry) vs app-wide fabric
    (topic bus)" — two subscription systems coexist BY DESIGN (spec §7).
- Full-suite pass: `pytest packages/ai-parrot/tests/ -v` including the
  unmodified guard-rail tests.

**NOT in scope**: new features, Phase 3 modules (they may land after; docs
mention them as available/optional), CI pipeline changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/core/events/bus/test_integration.py` | CREATE | four e2e tests |
| `scripts/bench/feat310_emit_overhead.py` | CREATE | benchmark script |
| `artifacts/logs/feat-310-bench-<date>.txt` | CREATE | benchmark evidence |
| `docs/events/eventbus-v2.md` | CREATE | architecture + doctrine |
| `docs/events/eventbus-config.md` | CREATE | `[bus]` / `[[bus.alerts]]` reference |
| `docs/events/eventbus-migration.md` | CREATE | migration notes |

*(Adjust doc paths to the existing `docs/` layout — verify structure first.)*

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` 2026-07-16 (commit b7226186d).

### Verified Imports
```python
from parrot.core.events import EventBus, Event, EventPriority, EventSubscription  # facade
from parrot.core.events.bus import BusCore, EventEnvelope, Severity, DLQHandler   # TASK-1783/84/88
from parrot.core.events.lifecycle.registry import EventRegistry                    # registry.py:90
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py:121
def subscribe(self, event_type, callback, *, where=None, forward_to_bus=False) -> str
# registry.py:283 — dual-emit: asyncio.create_task(self._event_bus.emit(...))
```

### Does NOT Exist
- ~~An existing benchmark harness for events~~ — check `scripts/` and FEAT-177 artifacts first; if none, the standalone script pattern above is the deliverable.
- ~~`docs/events/` directory~~ — verify docs layout (`ls docs/`) and place pages per the existing structure instead of inventing a new tree if one fits better.
- ~~A CI perf gate~~ — do not wire the benchmark into CI as a hard gate.

---

## Implementation Notes

### Key Constraints
- Guard-rail tests (`test_eventbus_imports.py`,
  `test_hookmanager_eventbus.py`) must be UNMODIFIED and passing.
- Benchmark methodology: measure `await bus.emit(...)` wall time with a
  registered slow handler to prove enqueue-only cost; compare against a
  representative LLM call latency (document the reference figure used, per
  FEAT-177).
- Docs follow the repo's existing docs conventions (check `docs/` for
  format/front-matter).
- Save benchmark evidence BEFORE marking done (spec §5 explicitly requires
  `artifacts/logs/` evidence).

### References in Codebase
- `sdd/specs/eventbus-v2.spec.md` §4–§5 — the exact test/AC list this task closes
- FEAT-177 spec/artifacts — latency-budget precedent (grep `sdd/specs/` for FEAT-177)

---

## Acceptance Criteria

- [ ] All four integration tests implemented and passing.
- [ ] Benchmark evidence file exists in `artifacts/logs/` showing emitter overhead within the FEAT-177 budget.
- [ ] Docs published: architecture, config reference (`[bus]`, `[[bus.alerts]]` defaults), migration notes, coexistence doctrine.
- [ ] Full test suite green: `pytest packages/ai-parrot/tests/ -v` (integration-marked tests may need Redis; document how to run).
- [ ] Guard-rail tests unmodified.
- [ ] `ruff check` clean on all new files.

---

## Test Specification

```python
# packages/ai-parrot/tests/core/events/bus/test_integration.py
import pytest

async def test_end_to_end_memory_mode(mock_notify): ...

@pytest.mark.integration
async def test_end_to_end_streams_mode(): ...

async def test_lifecycle_dual_emit_through_facade(): ...
async def test_graceful_shutdown_drain(mock_asyncdb): ...
```

---

## Agent Instructions

1. Verify TASK-1786/1787/1788/1789 are ALL in `sdd/tasks/completed/`.
2. Read spec §4 and §5 line-by-line — this task closes the remaining ACs.
3. Verify docs layout before creating pages.
4. Update `sdd/tasks/index/eventbus-v2.json` status transitions.
5. Move this file to `sdd/tasks/completed/` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
