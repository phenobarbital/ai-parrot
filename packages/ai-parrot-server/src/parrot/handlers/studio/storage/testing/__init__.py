"""In-memory Studio repositories with the same invariants and signals as Postgres (spec §2.5). Tests only.

Enforces UNIQUE(tenant, name) (tenant NULL included), the CHECKs, version bumps (child writes included) and the write
guards; absent rows give None/False/[]. Concurrency is only tested on Postgres.
"""


from __future__ import annotations

from typing import Any

from ._agents import _Agents, _Assets, _Tooling
from ._catalog import _Drafts, _Skills
from ._common import _MemoryPool


class InMemoryStudioRepositories:
    """Same method set as the five repositories; usable wherever a ``StudioRepositories`` is."""

    def __init__(self) -> None:
        self._state: dict[str, Any] = {"agents": {}, "assets": {}, "tooling": {}, "drafts": {}, "skills": {}}
        self.pool = _MemoryPool(self)
        self.agents = _Agents(self)
        self.assets = _Assets(self)
        self.tooling = _Tooling(self)
        self.drafts = _Drafts(self)
        self.skills = _Skills(self)


__all__ = ["InMemoryStudioRepositories"]
