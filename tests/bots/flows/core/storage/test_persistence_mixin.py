"""Unit tests for the rewritten PersistenceMixin (FEAT-147)."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.bots.flows.core.storage import PersistenceMixin
from parrot.bots.flows.core.storage.backends import ResultStorage


class _FakeStorage(ResultStorage):
    """Recording ResultStorage for tests."""

    def __init__(self) -> None:
        self.saves: list[tuple[str, dict]] = []
        self.closed = False

    async def save(self, collection: str, document: dict) -> None:
        self.saves.append((collection, document))

    async def close(self) -> None:
        self.closed = True


class _Host(PersistenceMixin):
    """Minimal host class that owns the four mixin attributes."""

    name = "TestCrew"

    def __init__(
        self,
        persist: bool = True,
        storage: "ResultStorage | None" = None,
    ) -> None:
        self._persist_results = persist
        self._result_storage_arg = storage
        self._result_storage: "ResultStorage | None" = (
            storage if isinstance(storage, ResultStorage) else None
        )
        self._persist_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]


# ──────────────────────────────────────────────────────────────────────────────
# _save_result behaviour
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_skips_when_disabled():
    """_save_result returns immediately when _persist_results=False."""
    fake = _FakeStorage()
    host = _Host(persist=False, storage=fake)
    await host._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    assert fake.saves == []


@pytest.mark.asyncio
async def test_save_lazy_resolves_storage(monkeypatch):
    """First _save_result lazily resolves backend; second call reuses it."""
    fake = _FakeStorage()
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.persistence.get_result_storage",
        lambda arg: fake,
    )
    host = _Host(persist=True, storage=None)

    await host._save_result(MagicMock(to_dict=lambda: {"x": 1}), "run_flow")
    await host._save_result(MagicMock(to_dict=lambda: {"x": 2}), "run_flow")

    assert len(fake.saves) == 2
    assert host._result_storage is fake  # cached after first call


@pytest.mark.asyncio
async def test_save_swallows_backend_exceptions(monkeypatch, caplog):
    """Exceptions from the backend are logged at WARNING and not propagated."""
    failing = MagicMock(spec=ResultStorage)
    failing.save = AsyncMock(side_effect=RuntimeError("boom"))
    failing.close = AsyncMock()
    host = _Host(persist=True, storage=failing)

    # Must not raise
    await host._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    assert "Failed to save result" in caplog.text


@pytest.mark.asyncio
async def test_save_uses_to_dict_when_available():
    """_save_result calls result.to_dict() and stores it under 'result'."""
    fake = _FakeStorage()
    host = _Host(persist=True, storage=fake)
    result_obj = MagicMock()
    result_obj.to_dict.return_value = {"agent": "x", "output": "ok"}

    await host._save_result(result_obj, "run_flow")

    assert len(fake.saves) == 1
    assert fake.saves[0][1]["result"] == {"agent": "x", "output": "ok"}


@pytest.mark.asyncio
async def test_save_falls_back_to_str_when_no_to_dict():
    """_save_result falls back to str(result) when to_dict is absent."""
    fake = _FakeStorage()
    host = _Host(persist=True, storage=fake)

    await host._save_result("plain string result", "run_flow")

    assert fake.saves[0][1]["result"] == "plain string result"


# ──────────────────────────────────────────────────────────────────────────────
# aclose() behaviour
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aclose_awaits_pending_tasks_and_closes_storage():
    """aclose() waits for in-flight persist tasks before calling storage.close()."""
    fake = _FakeStorage()
    host = _Host(persist=True, storage=fake)

    sentinel: list[int] = []

    async def slow_save() -> None:
        await asyncio.sleep(0.01)
        sentinel.append(1)

    t = asyncio.get_running_loop().create_task(slow_save())
    host._persist_tasks.add(t)

    await host.aclose()

    assert sentinel == [1], "aclose() must have waited for the slow task"
    assert fake.closed is True
    assert host._result_storage is None


@pytest.mark.asyncio
async def test_aclose_is_idempotent():
    """Calling aclose() twice (or before any save) does not raise."""
    fake = _FakeStorage()
    host = _Host(persist=True, storage=fake)

    await host.aclose()
    await host.aclose()  # second call — no-op


@pytest.mark.asyncio
async def test_aclose_on_never_persisted_host_is_noop():
    """aclose() on a host that never persisted anything is a no-op."""
    host = _Host(persist=True, storage=None)
    await host.aclose()  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# Async context-manager protocol
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_context_manager_calls_aclose():
    """async with host: calls aclose() on exit."""
    fake = _FakeStorage()
    host = _Host(persist=True, storage=fake)

    async with host:
        pass

    assert fake.closed is True
