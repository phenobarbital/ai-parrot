"""Review fix — the write guard carries the version the access decision AUTHORIZED, and a stale one re-authorizes.

Between the caller's access decision and the guarded write the agent is deleted and re-created (another owner,
higher version). The write must not land on the new record: the re-read record is re-authorized and refused
(404/403), or the write conflicts (409). Real Postgres, real routes, real session; the hook is a view subclass
whose ``_studio_authorize`` (the access decision) performs the swap right after deciding.
"""
from __future__ import annotations

import pytest

from parrot.handlers.studio.agents import StudioAgentsHandler
from parrot.handlers.studio.files import StudioFilesHandler
from parrot.handlers.studio.storage.models import (
    StudioAgentDefinition,
    StudioAgentPatch,
    StudioPartition,
    StudioWriteGuard,
)

from .test_agents_db_mode import BASE, _app, _create, _offline, pool  # noqa: F401  (fixtures)

PART = StudioPartition.GLOBAL


async def _swap_owner(svc) -> None:
    """Delete ``alpha`` and re-create it for ``u2`` at a higher version (what the caller never authorized)."""
    assert await svc.delete(PART, "alpha", guard=StudioWriteGuard())
    await svc.create(PART, name="alpha", owner="u2", definition=StudioAgentDefinition(description="new"))
    await svc.patch(PART, "alpha", StudioAgentPatch(description="newer"), guard=StudioWriteGuard(), actor="u2")


class _SwapAfterDecision:
    """Mixin: the first access decision is followed by the delete + re-create."""

    swapped = False

    async def _swap_once(self) -> None:
        if not type(self).swapped:
            type(self).swapped = True
            await _swap_owner(self._studio_storage().services.agents)


class _SwappingAgents(_SwapAfterDecision, StudioAgentsHandler):
    async def _studio_authorize(self, rec, name, *, manage):
        denied = await super()._studio_authorize(rec, name, manage=manage)
        await self._swap_once()
        return denied


class _SwappingFiles(_SwapAfterDecision, StudioFilesHandler):
    async def _db_agent(self, storage, part, name, *, manage):
        decided = await super()._db_agent(storage, part, name, manage=manage)
        await self._swap_once()
        return decided


async def _client(aiohttp_client, pool, view):
    _SwappingAgents.swapped = _SwappingFiles.swapped = False
    app = _app(pool, view=view)
    app.router.add_view("/tenant/agents/{name}/files/{kind}/{filename}", _SwappingFiles)
    return await aiohttp_client(app)


async def _assert_untouched(client) -> None:
    rec = await client.app["studio_storage"].services.agents.get(PART, "alpha")
    assert rec.owner == "u2" and rec.version == 2 and rec.definition.description == "newer"


@pytest.mark.parametrize("verb", ["patch", "delete"])
async def test_agent_write_after_delete_recreate_is_refused(aiohttp_client, pool, verb):
    client = await _client(aiohttp_client, pool, _SwappingAgents)
    await _create(client, description="mine")
    kw = {"json": {"description": "hijack"}} if verb == "patch" else {}
    resp = await getattr(client, verb)("/tenant/agents/alpha", **kw)
    assert resp.status in (403, 404, 409), await resp.text()
    await _assert_untouched(client)


async def test_file_write_after_delete_recreate_is_refused(aiohttp_client, pool):
    client = await _client(aiohttp_client, pool, _SwappingFiles)
    await _create(client)
    resp = await client.put("/tenant/agents/alpha/files/kb/notes.md", json={"content": "hijack"})
    assert resp.status in (403, 404, 409), await resp.text()
    await _assert_untouched(client)
    assert await client.app["studio_storage"].services.assets.list(PART, "alpha", "kb") == []
