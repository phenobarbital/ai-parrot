"""Tests for TASK-2283: single-flight lock keyed on `(page_id, section_kind)`.

Spec: sdd/specs/graphindex-retriever.spec.md §6.2, §6.3.
"""

import asyncio

import pytest
from parrot.knowledge.retrieval.sections import SectionKind
from parrot.knowledge.retrieval.single_flight import SingleFlight


@pytest.mark.asyncio
async def test_different_sections_same_page_do_not_serialize() -> None:
    sf = SingleFlight()
    started: list[str] = []
    release = asyncio.Event()

    async def _factory(name: str):
        started.append(name)
        await release.wait()
        return name

    task_a = asyncio.ensure_future(
        sf.run_once("page-1", SectionKind.CONTRACTS, lambda: _factory("contracts"))
    )
    task_b = asyncio.ensure_future(
        sf.run_once("page-1", SectionKind.RATIONALE, lambda: _factory("rationale"))
    )
    await asyncio.sleep(0.01)
    # Both must have started — different sections of the same page do not
    # wait on each other.
    assert set(started) == {"contracts", "rationale"}

    release.set()
    results = await asyncio.gather(task_a, task_b)
    assert set(results) == {"contracts", "rationale"}


@pytest.mark.asyncio
async def test_same_section_serializes_to_one_regeneration() -> None:
    sf = SingleFlight()
    call_count = {"n": 0}

    async def _factory():
        call_count["n"] += 1
        await asyncio.sleep(0.02)
        return "result"

    results = await asyncio.gather(
        sf.run_once("page-1", SectionKind.CONTRACTS, _factory),
        sf.run_once("page-1", SectionKind.CONTRACTS, _factory),
        sf.run_once("page-1", SectionKind.CONTRACTS, _factory),
    )
    assert call_count["n"] == 1
    assert results == ["result", "result", "result"]


@pytest.mark.asyncio
async def test_falls_back_to_in_process_lock_without_redis(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        sf = SingleFlight(redis=None)
    assert sf.redis is None
    assert any("no Redis client configured" in record.message for record in caplog.records)

    result = await sf.run_once("page-1", SectionKind.CONTRACTS, lambda: _identity("ok"))
    assert result == "ok"


async def _identity(value: str) -> str:
    return value


@pytest.mark.asyncio
async def test_uses_redis_lock_when_configured() -> None:
    calls: list[str] = []

    class _FakeLock:
        async def acquire(self) -> bool:
            calls.append("acquire")
            return True

        async def release(self) -> None:
            calls.append("release")

    class _FakeRedis:
        def lock(self, key: str, timeout: float):
            calls.append(f"lock:{key}")
            return _FakeLock()

    sf = SingleFlight(redis=_FakeRedis())
    result = await sf.run_once("page-1", SectionKind.CONTRACTS, lambda: _identity("ok"))
    assert result == "ok"
    assert calls[0].startswith("lock:wiki-single-flight:page-1:contracts")
    assert "acquire" in calls
    assert "release" in calls


@pytest.mark.asyncio
async def test_propagates_exception_to_all_joiners() -> None:
    sf = SingleFlight()

    async def _failing():
        await asyncio.sleep(0.01)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await asyncio.gather(
            sf.run_once("page-1", SectionKind.CONTRACTS, _failing),
            sf.run_once("page-1", SectionKind.CONTRACTS, _failing),
        )
