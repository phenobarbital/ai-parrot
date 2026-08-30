"""``A2UIRuntime.dispatch`` overhead benchmark (FEAT-469 TASK-2576, spec §5
Acceptance Criteria: "dispatch de un callAgentFunction añade < 5 ms de
overhead sobre execute_tool").

Measured directly with ``time.perf_counter`` over a bounded number of
repetitions, comparing MEDIANS (matching the established precedent —
``tests/outputs/a2ui/conformance/test_benchmark.py``'s "20-50 runs, take the
median" instruction; a mean over a handful of runs is CI noise).
"""

from __future__ import annotations

import statistics
import time

import pytest
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, FunctionDefinition
from parrot.outputs.a2ui.runtime.dispatch import A2UIRuntime
from parrot.outputs.a2ui.runtime.models import A2UICallContext
from parrot.tools.abstract import ToolResult

pytestmark = pytest.mark.asyncio

#: Number of timed repetitions; the assertion is against the MEDIAN (p50).
_REPETITIONS = 50

#: Acceptance threshold (spec §5): dispatch overhead over a no-op executor < 5 ms.
_OVERHEAD_BUDGET_SECONDS = 0.005


class _NoopExecutor:
    """A `FunctionExecutor` whose `call()` does nothing but return success."""

    def __init__(self):
        self.calls = 0

    async def call(self, name, args, ctx):
        self.calls += 1
        return ToolResult(success=True, status="success", result=None)

    def list_functions(self):
        return [FunctionDefinition(name="noop", catalog_id=DEFAULT_CATALOG_ID, allowed_callers="rendererOrAgent")]


class _NoopStore:
    async def get(self, session_id, surface_id):
        return None

    async def put(self, session_id, state):
        pass

    async def delete(self, session_id, surface_id):
        pass

    async def add(self, session_id, record):
        pass

    async def resolve(self, session_id, function_call_id, value, error):
        return None


def _call_agent_function_envelope():
    return {
        "version": "v1.0",
        "callAgentFunction": {
            "surfaceId": "s-1",
            "functionCallId": "fc-1",
            "callFunction": {"call": "noop", "args": {}, "catalogId": DEFAULT_CATALOG_ID},
        },
    }


@pytest.fixture
def noop_runtime():
    executor = _NoopExecutor()
    store = _NoopStore()
    return A2UIRuntime(executor=executor, surfaces=store, pending=store), executor


@pytest.fixture
def a2ui_call_ctx():
    return A2UICallContext(agent_id="a", session_id="s", transport="http", permission_context=None)


async def test_dispatch_overhead_under_5ms(noop_runtime, a2ui_call_ctx):
    """Compare MEDIANS over many iterations — a mean over a few is CI noise."""
    runtime, executor = noop_runtime
    envelope = _call_agent_function_envelope()

    # Baseline: calling the no-op executor directly (the floor `dispatch`
    # cannot go below — it must resolve the catalog, validate the envelope,
    # and map the ToolResult on top of this).
    baseline_durations = []
    for _ in range(_REPETITIONS):
        start = time.perf_counter()
        await executor.call("noop", {}, a2ui_call_ctx)
        baseline_durations.append(time.perf_counter() - start)
    baseline_p50 = statistics.median(baseline_durations)

    dispatch_durations = []
    for _ in range(_REPETITIONS):
        start = time.perf_counter()
        await runtime.dispatch(envelope, a2ui_call_ctx)
        dispatch_durations.append(time.perf_counter() - start)
    dispatch_p50 = statistics.median(dispatch_durations)

    overhead = dispatch_p50 - baseline_p50
    assert overhead < _OVERHEAD_BUDGET_SECONDS, (
        f"A2UIRuntime.dispatch p50 overhead over a no-op execute_tool call was "
        f"{overhead * 1000:.3f} ms over {_REPETITIONS} runs "
        f"(dispatch p50={dispatch_p50 * 1000:.3f} ms, baseline p50={baseline_p50 * 1000:.3f} ms), "
        f"budget is {_OVERHEAD_BUDGET_SECONDS * 1000:.0f} ms"
    )
