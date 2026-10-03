"""A real Studio agent behind the real ``StudioToolingService``, on the in-memory repositories.

The boundary a test does not own is the repository; everything above it (``AgentToolingStore._load_studio``, the
service, the gate, the tenant tooling policy and the tenant-caller guard) is production code. A tenant caller thus
reaches a *tenant Studio agent* exactly as in production — never a legacy row (PR #1564 F2).
"""

from __future__ import annotations

from types import SimpleNamespace

from aiohttp import web
from parrot.handlers.studio.storage.models import StudioAgentDefinition, StudioPartition
from parrot.handlers.studio.storage.repositories import studio_transaction
from parrot.handlers.studio.storage.services._common import StudioToolingGate
from parrot.handlers.studio.storage.services.tooling import StudioToolingService
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories


class StudioAgentWorld:
    """In-memory repositories, the real tooling service over them, and one agent per ``add_agent`` call."""

    def __init__(self, app: web.Application) -> None:
        self.repos = InMemoryStudioRepositories()
        self.service = StudioToolingService(self.repos, gate=StudioToolingGate(app))
        self.storage = SimpleNamespace(
            backend="database",
            services=SimpleNamespace(tooling=self.service, agents=SimpleNamespace(get=self._get)),
        )

    async def _get(self, part: StudioPartition, name: str):
        return await self.repos.agents.get(part, name)

    async def add_agent(self, tenant: str | None, name: str = "agent", owner: str = "42"):
        """Insert a private Studio agent in the partition of ``tenant`` (``None``: the GLOBAL partition)."""
        async with studio_transaction(self.repos.pool) as conn:
            return await self.repos.agents.insert(
                conn, StudioPartition(tenant), name=name, owner=owner, definition=StudioAgentDefinition(),
                visibility="private", allowed_groups=(),
            )

    async def tooling(self, tenant: str | None, name: str = "agent"):
        """The normalised tooling currently stored for the agent."""
        return (await self.service.load(StudioPartition(tenant), name)).tooling

    async def version(self, tenant: str | None, name: str = "agent") -> int:
        """The agent's version: it moves on every committed tooling write."""
        return (await self.service.load(StudioPartition(tenant), name)).record.version

    def wire(self, handler, tenant: str | None):
        """Point a handler at this world: its storage and partition are the only things the test supplies."""
        handler._studio_storage = lambda: self.storage
        handler._studio_partition = _partition(tenant)
        return handler


def _partition(tenant: str | None):
    async def _resolve() -> StudioPartition:
        return StudioPartition(tenant)

    return _resolve
