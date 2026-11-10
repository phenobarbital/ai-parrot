"""FEAT-860 regression tests for crew HTTP storage failure handling."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.handlers.crew.definition_storage import CrewStorageConflict, CrewStorageUnavailable
from parrot.handlers.crew.handler import CrewHandler
from parrot.handlers.crew.models import AgentDefinition, CrewDefinition


def _definition(name: str = "crew", crew_id: str = "crew-id") -> CrewDefinition:
    """Build a minimal valid crew definition."""
    return CrewDefinition(
        name=name,
        crew_id=crew_id,
        tenant="tenant",
        agents=[AgentDefinition(agent_id="agent")],
    )


def _response(response: dict, status: int = 200) -> web.Response:
    """Return a concrete response without requiring a Navigator view."""
    return web.json_response(response, status=status)


def _handler(manager: MagicMock, *, body: dict | None = None, query: dict | None = None, crew_id: str | None = None):
    """Build the minimal handler contract used by the CRUD methods."""
    handler = MagicMock()
    handler.bot_manager = manager
    handler.logger = logging.getLogger("test.crew-storage-errors")
    handler.request = MagicMock()
    handler.request.json = AsyncMock(return_value=body or {})
    handler.match_parameters.return_value = {"id": crew_id} if crew_id else {}
    handler.get_arguments.return_value = query or {}
    handler.error.side_effect = _response
    handler.json_response.side_effect = _response
    handler._create_crew_from_definition = AsyncMock(return_value=MagicMock())
    return handler


@pytest.fixture(autouse=True)
def _tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests focused on storage mappings rather than session plumbing."""
    monkeypatch.setattr("parrot.handlers.crew.handler.resolve_session_tenant", AsyncMock(return_value="tenant"))


@pytest.mark.asyncio
async def test_storage_failure_is_503_not_404() -> None:
    """Storage errors remain 503 for GET, nested PUT, and direct PG DELETE."""
    secret = "postgres://user:password@db/crew"
    manager = MagicMock(crew_storage_backend="postgres")
    manager.get_crew = AsyncMock(side_effect=CrewStorageUnavailable(secret))
    get_handler = _handler(manager, query={"name": "crew"})

    get_response = await CrewHandler.get(get_handler)

    assert get_response.status == 503
    assert secret not in get_response.body.decode()

    manager.get_crew = AsyncMock(return_value=(MagicMock(), _definition()))
    manager.persist_crew_update = AsyncMock(side_effect=CrewStorageUnavailable(secret))
    put_handler = _handler(manager, body=_definition().model_dump(mode="json"), crew_id="crew")

    put_response = await CrewHandler.put(put_handler)

    assert put_response.status == 503
    assert secret not in put_response.body.decode()
    manager.remove_crew.assert_not_called()

    manager.get_crew = AsyncMock()
    manager.remove_crew = AsyncMock(side_effect=CrewStorageUnavailable(secret))
    delete_handler = _handler(manager, query={"name": "crew"})

    delete_response = await CrewHandler.delete(delete_handler)

    assert delete_response.status == 503
    assert secret not in delete_response.body.decode()
    manager.get_crew.assert_not_awaited()


@pytest.mark.asyncio
async def test_identity_conflict_is_409() -> None:
    """Typed conflicts map to 409 before generic handler catches."""
    secret = "duplicate crew-id=private"
    manager = MagicMock(crew_storage_backend="postgres")
    manager.get_crew = AsyncMock(side_effect=CrewStorageConflict(secret))
    get_handler = _handler(manager, query={"name": "crew"})

    get_response = await CrewHandler.get(get_handler)

    assert get_response.status == 409
    assert secret not in get_response.body.decode()

    manager.get_crew = AsyncMock(return_value=(MagicMock(), _definition()))
    put_handler = _handler(manager, body=_definition().model_dump(mode="json"), crew_id="crew")
    put_handler._create_crew_from_definition = AsyncMock(side_effect=CrewStorageConflict(secret))

    put_response = await CrewHandler.put(put_handler)

    assert put_response.status == 409
    assert secret not in put_response.body.decode()

    manager.remove_crew = AsyncMock(side_effect=CrewStorageConflict(secret))
    delete_handler = _handler(manager, query={"name": "crew"})

    delete_response = await CrewHandler.delete(delete_handler)

    assert delete_response.status == 409
    assert secret not in delete_response.body.decode()


@pytest.mark.asyncio
async def test_execution_endpoints_map_storage_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running or replaying a crew reports storage outages as 503 and identity conflicts as 409."""
    from parrot.handlers.crew.execution_handler import CrewExecutionHandler
    from parrot.handlers.crew.execution_history_handler import CrewExecutionHistoryHandler

    monkeypatch.setattr(
        "parrot.handlers.crew.execution_handler.resolve_session_tenant", AsyncMock(return_value="tenant")
    )
    secret = "postgres://user:password@db/crew"

    for error, expected in (
        (CrewStorageUnavailable(secret), 503),
        (CrewStorageConflict(secret), 409),
    ):
        manager = MagicMock(crew_storage_backend="postgres")
        manager.get_crew = AsyncMock(side_effect=error)
        run_handler = _handler(manager)

        run_response = await CrewExecutionHandler.execute_crew(run_handler, {"crew_id": "crew", "query": "hi"})

        assert run_response.status == expected
        assert secret not in run_response.body.decode()

        replay_handler = _handler(manager)
        replay_handler.service.replay_execution = AsyncMock(side_effect=error)

        replay_response = await CrewExecutionHistoryHandler._replay(replay_handler, "tenant", "user", "execution")

        assert replay_response.status == expected
        assert secret not in replay_response.body.decode()


@pytest.mark.asyncio
async def test_deleted_retry_succeeds_and_absent_is_404() -> None:
    """PostgreSQL deletes call the tombstone-aware manager without a cache precheck."""
    manager = MagicMock(crew_storage_backend="postgres")
    manager.remove_crew = AsyncMock(return_value=True)
    retry_handler = _handler(manager, query={"name": "crew"})

    retry_response = await CrewHandler.delete(retry_handler)

    assert retry_response.status == 200
    manager.remove_crew.assert_awaited_once_with("crew", tenant="tenant")
    manager.get_crew.assert_not_called()

    manager.remove_crew = AsyncMock(return_value=False)
    absent_handler = _handler(manager, query={"name": "crew"})

    absent_response = await CrewHandler.delete(absent_handler)

    assert absent_response.status == 404


@pytest.mark.asyncio
async def test_update_uses_single_persistence_and_rejects_rename() -> None:
    """PG updates preserve identity and leave the backing state unchanged on conflict."""
    original = _definition()
    original.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    stored = {"definition": original}
    manager = MagicMock(crew_storage_backend="postgres")
    manager.get_crew = AsyncMock(return_value=(MagicMock(), original))

    async def persist(identifier: str, crew: object, definition: CrewDefinition) -> None:
        """Mirror manager persistence enough to expose ordering and rename semantics."""
        assert identifier == "crew"
        if definition.name != stored["definition"].name:
            raise CrewStorageConflict("renames conflict with authoritative storage")
        stored["definition"] = definition

    manager.persist_crew_update = AsyncMock(side_effect=persist)
    update_handler = _handler(manager, body=_definition().model_dump(mode="json"), crew_id="crew")

    update_response = await CrewHandler.put(update_handler)

    assert update_response.status == 202
    manager.persist_crew_update.assert_awaited_once()
    persisted = manager.persist_crew_update.await_args.args[2]
    assert persisted.crew_id == original.crew_id
    assert persisted.created_at == original.created_at
    manager.remove_crew.assert_not_called()
    manager.add_crew.assert_not_called()

    before_rename = stored["definition"]
    rename_handler = _handler(manager, body=_definition(name="renamed").model_dump(mode="json"), crew_id="crew")

    rename_response = await CrewHandler.put(rename_handler)

    assert rename_response.status == 409
    assert stored["definition"] is before_rename
    assert manager.persist_crew_update.await_count == 2
