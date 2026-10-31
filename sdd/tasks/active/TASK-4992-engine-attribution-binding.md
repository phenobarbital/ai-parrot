# TASK-4992: sdd-coder engine builds and binds UsageAttribution; registers the durable sink

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4983, TASK-4990, TASK-4991
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (binding half), G1, AC-10 (end to end). The engine already owns every
identifier: `feature_id` from the per-spec index, `execution_id` from the caller,
`attempt_uid` minted per attempt. This task builds one `UsageAttribution` per attempt and
binds it around `dispatcher.dispatch(...)`. It also makes sure dispatcher usage events
actually reach a `UsageRecordingSubscriber` holding a `SpecUsageRecorder`.

**Discovered at task time**: the sdd-coder engine never calls `set_event_registry_resolver`
on the dispatchers it builds. Only `runner.py:465` and `nodes/development.py:1292,1723` do. So
`claude.py::_emit_usage_event` returns early (claude.py:1007) and **no usage event is emitted
for sdd-coder attempts today**. Wiring it is in scope.

**Out of scope, gated by spike S1** (spec §8): interactive Claude Code / Codex OTLP
ingestion. Do NOT add it here; it stays opt-in and config-gated in a later task once S1 passes.

---

## Scope

- In `_run_attempt`, wrap the `dispatcher.dispatch(...)` call (engine.py:3582) in `usage_attribution(job_id, seat=..., attribution=UsageAttribution(...))` with `feat_id=ctx.feature_id`, `task_id=task.task_id`, `attempt_uid`, `execution_id`, `dispatch_kind` (`"sdk"` for the claude backend, `"cli"` for codex, `"in-process"` otherwise), `roster_seat=seat.label` and `accounting_seat=f"development.sdd-coder-{seat.label}"`.
- Wire the event-registry resolver on the dispatcher when it exposes `set_event_registry_resolver`, so emitted events reach the global registry.
- Lazily create **one** engine-scoped `UsageRecordingSubscriber(recorders=[SpecUsageRecorder(...)])` registered on the global registry, guarded by `DEV_LOOP_CODER_TELEMETRY` (the same gate as `CoderTelemetrySink`). Close it with the engine.
- Pass the attempt's spec rows into `build_attempt_row(..., spec_rows=...)` (TASK-4991 seam).
- An integration test: a fake dispatcher that emits an `AfterClientCallEvent` inside dispatch produces a durable row with the full attribution (AC-10, spec §4 Integration).

**NOT in scope**: the S1-gated interactive ingestion; `coder_end_execution` totals (open defect `issue:cc372f700a47`, spec §7: do not use it as a settlement signal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Bind attribution, wire resolver, own the sink subscriber |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_usage_attribution.py` | CREATE | Integration test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.attribution import UsageAttribution                     # TASK-4983
from parrot.observability.context import usage_attribution                        # context.py:162 (widened by TASK-4983)
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber    # subscriber.py:47
from parrot.observability.recorders.spec_usage import SpecUsageRecorder, read_spec_usage  # TASK-4990
from parrot.core.events.lifecycle import get_global_registry                      # used by observability/bootstrap.py:212-216
```

### Existing Signatures to Use
```python
# sdd_coder/engine.py — NO observability import exists today
    async def begin_execution(self, feature: str, worktree: str, execution_id: str) -> "ExecutionPoolView"  # :623
    def _labels_for(self, task: PlannedTask, seat: RosterSeat, attempt: int) -> DispatchLabels   # :3388
    async def _run_attempt(...)                                                                    # :3400
        binder = getattr(dispatcher, "set_validation_runner", None)   # :3578 (1 occurrence) — anchor
        output = await dispatcher.dispatch(brief=..., run_id=job_id, node_id=f"development.sdd-coder-{seat.label}", ...)  # :3582
# DispatchLabels(task_id=..., seat=f"sdd-coder.{seat.label}", agent=seat.backend or "native", model=..., attempt=...)
# RosterSeat: .label, .backend, .model
# dispatchers/claude.py
    def set_event_registry_resolver(self, resolver: Callable[[str], Optional[EventRegistry]]) -> None   # :183
    # _emit_usage_event: registry = resolver(run_id); await registry.emit(event); registry.forward_to_global(event)   (:1009-1020)
# observability/bootstrap.py:212-216 — get_global_registry().add_provider(subscriber) -> ids
```

### Does NOT Exist
- ~~`SddCoderEngine` resolver wiring~~ — not wired today; this task adds it
- ~~`sdd/state/<FEAT-ID>/state.json` `attempt_uid`~~ — not in the schema; never infer attribution from state files or cwd
- ~~`DispatchLabels.feat_id`~~ — labels carry no feature id; take it from `ctx.feature_id`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_usage_attribution.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_attempt",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._labels_for",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py#ClaudeCodeDispatcher.set_event_registry_resolver"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `engine.py` is the package's hottest file, with open encapsulation defects at `begin_execution` (`issue:700660c7f663`). Keep the diff to: imports, one helper method, one `with` wrap, one resolver wiring, sink lifecycle, and the `spec_rows` pass-through.
- **Double-delivery check**: if the resolver returns the global registry itself, `claude.py` calls `registry.emit(event)` and then `registry.forward_to_global(event)` on the same registry, so the event could be handled twice and the cost double-counted. Prefer a private per-engine `EventRegistry` whose `forward_to_global` delivers to the global registry once. Verify with a test that asserts exactly one durable row per emitted event.
- Every new step is fail-open. A telemetry error must never change a dispatch or merge outcome (FEAT-554 AC-11 posture).
- Telemetry fails closed only on the root check: if `SpecUsageRecorder` raises `ValueError`, log once and run without the sink.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_usage_attribution_for(ctx, task, seat, attempt_uid, execution_id) -> UsageAttribution` next to `_labels_for`, so attribution is built in exactly one place.
2. Add `_ensure_usage_sink()`: a lazy, idempotent, telemetry-gated subscriber registration. Unregister and `aclose` it in the engine's existing close path (FILL IN: locate it with `grep -n 'async def close\|async def aclose' engine.py`).
3. Wire the resolver right after the existing `set_validation_runner` binder.
4. Wrap the dispatch in `usage_attribution(...)`.
5. Pass `spec_rows=read_spec_usage(...)` at the `build_attempt_row` call (FILL IN: locate with `grep -n 'build_attempt_row(' engine.py`; run `read_spec_usage` via `asyncio.to_thread` because it reads a file).
6. Integration test.

### `engine.py` (MODIFY)
```python
# NEW method after _labels_for (ends engine.py:~3398)
    def _usage_attribution_for(
        self, ctx: Any, task: PlannedTask, seat: RosterSeat, *, attempt_uid: str, execution_id: str
    ) -> UsageAttribution:
        """FEAT-783 M7: the one place an attempt's SDD attribution is built (never inferred from cwd)."""
        backend = (seat.backend or "").lower()
        dispatch_kind = "sdk" if backend == "claude" else "cli" if backend == "codex" else "in-process"
        return UsageAttribution(
            feat_id=ctx.feature_id,
            task_id=task.task_id,
            attempt_uid=attempt_uid or None,
            execution_id=execution_id or None,
            dispatch_kind=dispatch_kind,
            roster_seat=seat.label,
            accounting_seat=f"development.sdd-coder-{seat.label}",
        )
```
```python
# occurrences: 1 (verified: grep -c 'binder = getattr(dispatcher, "set_validation_runner", None)' engine.py)
# AFTER — insert below the 2-line binder block at engine.py:3578-3580
            resolver_setter = getattr(dispatcher, "set_event_registry_resolver", None)
            if callable(resolver_setter):
                # FILL IN: wire the per-engine registry (see Key Constraints: double delivery) and call
                # self._ensure_usage_sink() — bounded by "exactly one durable row per event"
                ...
```
```python
# occurrences: 1 (verified: grep -c '                output = await dispatcher.dispatch(' engine.py), :3582
# Wrap the existing call (keep every argument verbatim):
                with usage_attribution(
                    job_id,
                    seat=f"development.sdd-coder-{seat.label}",
                    attribution=self._usage_attribution_for(
                        ctx, task, seat, attempt_uid=attempt_uid, execution_id=execution_id or ""
                    ),
                ):
                    output = await dispatcher.dispatch(
                        ...  # unchanged arguments
                    )
```
**Why**: dispatchers re-enter `usage_attribution(run_id, seat=...)` without `attribution`. TASK-4983 made that preserve the outer attribution, so every event built during this dispatch carries it.

### `test_engine_usage_attribution.py` (CREATE)
```python
"""FEAT-783 TASK-4992 — engine attribution end to end (AC-10, spec §4 Integration)."""
import pytest


@pytest.mark.asyncio
async def test_attempt_produces_attributed_durable_row(tmp_path, monkeypatch) -> None:
    # FILL IN: build the engine the way tests/flows/dev_loop/sdd_coder/ tests do (hermetic evidence root —
    # see the sdd-coder evidence-store fixture), fake dispatcher whose dispatch() constructs+emits an
    # AfterClientCallEvent via the wired resolver; assert exactly ONE row in read_spec_usage(root, feat)
    # with feat_id/task_id/attempt_uid/execution_id/roster_seat set
    ...


@pytest.mark.asyncio
async def test_telemetry_disabled_registers_no_sink(tmp_path, monkeypatch) -> None:
    # FILL IN: DEV_LOOP_CODER_TELEMETRY off -> no subscriber added to the global registry
    ...
```

### FILL IN checklist
- [ ] Resolver/registry wiring without double delivery
- [ ] `_ensure_usage_sink` + close path
- [ ] `spec_rows` pass-through off the loop
- [ ] Integration tests (hermetic root)

---

## Acceptance Criteria

- [ ] Every dispatcher event during an attempt carries the attempt's full `UsageAttribution` (G1).
- [ ] An sdd-coder attempt end to end produces exactly one durable row per call, readable by a second process (AC-10).
- [ ] With the telemetry gate off, no sink is registered and dispatch behaviour is unchanged.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_usage_attribution.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py -q`

## Test Specification
See blueprint.

## Agent Instructions
Two files only. `PYTHONPATH=packages/ai-parrot/src`. Do not touch `begin_execution` beyond what the blueprint says; the spec's "binds at begin_execution" is satisfied by building at the attempt boundary, where `attempt_uid` exists.

## Completion Note
_(filled at close)_
