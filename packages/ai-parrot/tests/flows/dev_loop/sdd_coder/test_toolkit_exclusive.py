"""State-changing `coder_*` tools are serialised; read-only ones are not (review finding P1)."""

from __future__ import annotations

import asyncio

import pytest

from parrot.flows.dev_loop.sdd_coder import toolkit as toolkit_mod
from parrot.flows.dev_loop.sdd_coder.models import ERROR_CODES
from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit


@pytest.fixture
def toolkit() -> SddCoderToolkit:
    return SddCoderToolkit(roster=[{"label": "a", "backend": "nova"}])


def test_engine_busy_is_a_declared_error_code() -> None:
    assert "engine_busy" in ERROR_CODES


@pytest.mark.asyncio
async def test_exclusive_calls_serialise_and_read_only_calls_interleave(toolkit: SddCoderToolkit) -> None:
    order: list[str] = []

    async def slow_mutation() -> dict:
        order.append("m1-start")
        await asyncio.sleep(0.3)
        order.append("m1-end")
        return {"ok": 1}

    async def second_mutation() -> dict:
        order.append("m2-start")
        return {"ok": 2}

    async def read_only() -> dict:
        order.append("ro")
        return {"ok": 3}

    results = await asyncio.gather(
        toolkit._run("coder_begin_execution", slow_mutation(), exclusive=True),
        toolkit._run("coder_run_chunk", second_mutation(), exclusive=True),
        toolkit._run("coder_status", read_only()),
    )
    assert [r.status for r in results] == ["ok", "ok", "ok"]
    assert order.index("ro") < order.index("m1-end"), "read-only call must not wait for the mutation"
    assert order.index("m2-start") > order.index("m1-end"), "second mutation must wait for the first"


@pytest.mark.asyncio
async def test_exclusive_wait_is_bounded_with_engine_busy(toolkit: SddCoderToolkit, monkeypatch) -> None:
    monkeypatch.setattr(toolkit_mod, "EXCLUSIVE_WAIT_S", 0.05)
    await toolkit._exclusive.acquire()  # a stuck state-changing call
    ran = False

    async def never() -> dict:
        nonlocal ran
        ran = True
        return {}

    result = await toolkit._run("coder_merge", never(), exclusive=True)
    assert result.status == "error"
    assert result.error is not None and result.error.code == "engine_busy"
    assert ran is False, "the queued call must not run after the wait expires"
    assert toolkit._exclusive.locked(), "the stuck holder keeps its slot"


@pytest.mark.asyncio
async def test_exclusive_slot_is_released_on_failure_and_cancellation(toolkit: SddCoderToolkit) -> None:
    async def boom() -> dict:
        raise RuntimeError("engine crashed")

    result = await toolkit._run("coder_plan", boom(), exclusive=True)
    assert result.status == "error" and result.error is not None and result.error.code == "internal_error"
    assert not toolkit._exclusive.locked()

    async def stuck() -> dict:
        await asyncio.sleep(30)
        return {}

    task = asyncio.create_task(toolkit._run("coder_merge", stuck(), exclusive=True))
    await asyncio.sleep(0.05)
    assert toolkit._exclusive.locked()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not toolkit._exclusive.locked()


def test_every_state_changing_tool_is_exclusive() -> None:
    import inspect

    src = inspect.getsource(SddCoderToolkit)
    read_only = {
        "coder_wait",
        "coder_status",
        "coder_read_artifact",
        "coder_task_context",
        "coder_delivery_report",
        "coder_feedback_report",
        "coder_bg_status",
        # Blocks on a handle's settlement; it changes nothing and must never
        # hold the engine's exclusive lock while it waits.
        "coder_bg_wait",
    }
    for name, member in inspect.getmembers(SddCoderToolkit, inspect.iscoroutinefunction):
        if not name.startswith("coder_"):
            continue
        body = inspect.getsource(member)
        assert ("exclusive=True" in body) == (name not in read_only), name
    assert "exclusive=True" in src
