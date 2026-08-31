# TASK-2620: End-to-end integration tests

**Feature**: FEAT-479 — Dev-Flow / Dev-Loop Telemetry Accounting on the Lifecycle Bus
**Spec**: `sdd/specs/devflow-telemetry-accounting.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2611, TASK-2616, TASK-2617, TASK-2619
**Assigned-to**: unassigned

---

## Context

Implements spec §4 Integration Tests.

Every unit test in this feature verifies one seam. These four verify the
**whole chain** — builder → adapter → dispatcher → event → subscriber →
ledger → report — for the four defects the feature exists to fix. Each of the
spec's verified findings gets exactly one end-to-end proof:

| Test | Proves |
|---|---|
| `test_dev_flow_run_produces_usage_report` | Finding 1 — dev-flow emitted nothing at all |
| `test_retry_cycle_totals_are_cumulative` | Finding 2 — retries overwrote |
| `test_pool_run_attributes_every_worker` | Finding 3 — pool workers were dropped |
| `test_failed_node_reported_with_usage` | the failure-reporting goal |

A unit test can pass while the chain is broken at a seam none of them cover;
these close that gap.

---

## Scope

- Write the four integration tests below against a fake dispatcher, with no
  network, no Redis and no real LLM call.
- Assert on the **rendered report**, not just internal state — that is what
  the user sees.

**NOT in scope**: changing any implementation. If a test fails, the defect
belongs to the owning task — fix it there and note it here, rather than
loosening the assertion.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/test_telemetry_integration.py` | CREATE | The four tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/flows/dev_flow/flow.py:68
from parrot.flows.dev_flow.flow import build_dev_flow
# verified: packages/ai-parrot/src/parrot/flows/dev_flow/runner.py:37
from parrot.flows.dev_flow.runner import DevFlowRunner
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/flow.py:285
from parrot.flows.dev_loop.flow import build_dev_loop_flow
# from this feature:
from parrot.observability.recorders.run_ledger import RunLedgerRecorder
from parrot.flows.dev_loop.usage_report import build_usage_report, render_usage_markdown
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_flow/runner.py
class DevFlowRunner(DevLoopRunner):                        # line 37
    async def run(self, brief: DevRequestBrief | FeatureBrief, *,
                  run_id: str | None = None, initial_task: str = "",
                  extra_shared: dict | None = None) -> FlowResult: ...  # line 55
    # Inherits _close_host from DevLoopRunner (runner.py:1460) — which is why
    # dev-flow already gets the run bundle and usage report for free, and why
    # its missing lifecycle adapter (Finding 1) was the only thing stopping it.

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py
#   line 149: worker_id = f"development.w{i}"   <-- the seat scheme under test
```

### Does NOT Exist

- ~~A shared end-to-end dev-flow fixture~~ — verify what
  `packages/ai-parrot/tests/flows/dev_flow/` already provides (e.g.
  `test_flow_parity.py`, `test_ideation_node.py`) and reuse it. Do not build a
  new harness before checking.
- ~~A real dispatcher usable in tests~~ — every dispatcher shells out or calls
  a provider. Use a fake.
- ~~`pytest.mark.integration`~~ — verify the project's marker registry in
  `pyproject.toml` / `pytest.ini` before adding a marker; an unregistered
  marker warns or errors under strict settings.

---

## Implementation Notes

### Keep them hermetic

Pass `publish_flow_events=False` so no Redis connection is attempted. Use an
`EventRegistry(forward_to_global=False)` so the process-wide singleton is never
touched and tests cannot leak into each other — spec §4's `isolated_registry`
fixture exists for exactly this.

### Assert on the rendered output

```python
report = build_usage_report(ledger, run_id=rid)
md = render_usage_markdown(report)
assert "development.w1" in md
```

Internal state can be right while rendering silently drops a row. The rendered
report is the deliverable.

### Exactness, not sleeps

Do **not** paper over a race with `await asyncio.sleep(...)`. If the ledger
isn't populated when the run returns, the wiring is wrong (TASK-2616) — report
it rather than hiding it. Node events are separately bounded by
`AgentsFlow._drain_event_tasks` (`flow.py:452`), awaited at `flow.py:2074`
before `run_flow` returns.

### Key Constraints

- No network, no Redis, no real LLM call, no subprocess.
- Deterministic — no wall-clock or ordering dependence.
- Each test asserts one finding, so a failure names its own cause.
- If a test cannot be written without changing production code, that is a
  finding: record it in the Completion Note.

### References in Codebase

- `packages/ai-parrot/tests/flows/dev_flow/` — existing dev-flow fixtures
- `packages/ai-parrot/tests/flows/dev_loop/test_dispatch_telemetry.py` — fake-dispatch precedent
- `examples/dev_loop/e2e_demo.py` — a self-contained end-to-end wiring reference

---

## Acceptance Criteria

- [ ] All four integration tests exist and pass.
- [ ] No test uses `sleep` to make an assertion pass.
- [ ] No test requires network, Redis, a subprocess or a real LLM call.
- [ ] Tests use an isolated registry and never mutate the global one.
- [ ] Each test asserts on the **rendered** report, not only internal state.
- [ ] `pytest packages/ai-parrot/tests/flows/ -v` passes in full.
- [ ] `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_telemetry_integration.py
import pytest


async def test_dev_flow_run_produces_usage_report(dev_flow_runner, dev_request_brief):
    """Finding 1: dev-flow attached no FlowLifecycleAdapter, so it emitted
    zero lifecycle events and its usage report was always empty."""
    await dev_flow_runner.run(dev_request_brief)
    report = _report_for(dev_flow_runner, run_id=...)
    assert report.agents, "dev-flow produced no usage records at all"
    assert "## Usage" in render_usage_markdown(report)


async def test_retry_cycle_totals_are_cumulative(dev_loop_runner, brief_forcing_one_retry):
    """Finding 2: session state overwrote per-node tokens on each retry, so a
    3-cycle run reported roughly a third of its true usage."""
    await dev_loop_runner.run(brief_forcing_one_retry)
    dev = _seat(_report_for(dev_loop_runner, ...), "development")
    assert len(dev.cycles) == 2
    assert dev.input_tokens == sum(c.input_tokens for c in dev.cycles)


async def test_pool_run_attributes_every_worker(dev_loop_runner, brief_with_pool_of_2):
    """Finding 3: 'development.w1' cannot validate against the closed NodeId
    Literal, so _apply_to_session_host swallowed it and fan-out reported zero."""
    await dev_loop_runner.run(brief_with_pool_of_2)
    md = render_usage_markdown(_report_for(dev_loop_runner, ...))
    assert "development.w1" in md and "development.w2" in md


async def test_failed_node_reported_with_usage(dev_loop_runner, brief_failing_in_qa):
    """A failed cycle must report its error AND the tokens it burned."""
    await dev_loop_runner.run(brief_failing_in_qa)
    report = _report_for(dev_loop_runner, ...)
    qa = _seat(report, "qa")
    assert qa.failures >= 1
    md = render_usage_markdown(report)
    assert "Failures" in md
```

**Fake dispatcher**: it must be scriptable per call — returning a chosen
`(input_tokens, output_tokens, model)` per invocation — so a test can drive two
different cycles and assert the sum. Check whether
`packages/ai-parrot/tests/flows/dev_loop/` already has one before writing it.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §4 Integration Tests, and §1 for what each finding was
2. **Check dependencies** — TASK-2611, 2616, 2617, 2619 must all be in
   `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — survey existing fixtures before writing new ones
4. **Update status** in `sdd/tasks/index/devflow-telemetry-accounting.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2620-integration-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Defects found in earlier tasks** *(if any — with the task id that owns each)*:

**Deviations from spec**: none | describe if any
