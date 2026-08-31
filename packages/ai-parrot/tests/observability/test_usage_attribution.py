"""Unit tests for FEAT-479 Module 2 — seat/run attribution ContextVars.

``current_run_id`` / ``current_seat`` mirror the FEAT-228 ``current_agent_name``
precedent (`observability/context.py`): task-local carriers read at
event-construction time so events emitted deep inside ``AbstractClient`` can
be attributed back to the dev-loop / dev-flow run and seat that triggered
them, without widening ``NodeId``.
"""

from __future__ import annotations

import asyncio

import pytest
from parrot.observability import current_run_id, current_seat, usage_attribution


def test_binds_inside_block():
    assert current_run_id.get() is None
    with usage_attribution("run-1", "development.w1"):
        assert current_run_id.get() == "run-1"
        assert current_seat.get() == "development.w1"
    assert current_run_id.get() is None
    assert current_seat.get() is None


def test_nested_restores_outer_not_none():
    with usage_attribution("run-1", "development"):
        with usage_attribution("run-1", "development.w2"):
            assert current_seat.get() == "development.w2"
        assert current_seat.get() == "development"  # outer, not None


def test_restores_on_exception():
    with pytest.raises(RuntimeError), usage_attribution("run-1", "qa"):
        raise RuntimeError("boom")
    assert current_run_id.get() is None
    assert current_seat.get() is None


def test_seat_is_optional():
    with usage_attribution("run-1"):
        assert current_run_id.get() == "run-1"
        assert current_seat.get() is None


async def test_isolated_across_tasks():
    """ContextVars copy per asyncio.Task, so concurrent runs must not see
    each other's attribution."""
    seen = {}

    async def worker(run_id: str, seat: str):
        with usage_attribution(run_id, seat):
            await asyncio.sleep(0)
            seen[seat] = current_run_id.get()

    await asyncio.gather(
        worker("run-a", "development.w1"),
        worker("run-b", "development.w2"),
    )
    assert seen == {"development.w1": "run-a", "development.w2": "run-b"}
