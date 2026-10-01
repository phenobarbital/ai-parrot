"""Shared helpers of the in-memory Studio repositories."""

from __future__ import annotations

import copy
import re
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..models import (
    StudioAgentHead,
    StudioNameConflict,
    StudioStaleAuthorization,
    StudioStorageError,
    StudioVersionConflict,
    StudioWriteGuard,
)

if TYPE_CHECKING:  # pragma: no cover - typing only; the package __init__ imports this module
    from . import InMemoryStudioRepositories


_NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_VISIBILITY = ("private", "tenant", "groups")
_ASSET_HARD_CAP = 1048576


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _check_shared(tenant: str | None, name: str | None, visibility: str, *, slug_name: bool = True) -> None:
    """The CHECK constraints every Studio table shares."""
    if visibility not in _VISIBILITY:
        raise StudioStorageError(f"visibility {visibility!r} violates check constraint")
    if tenant is not None and not _TENANT_RE.match(tenant):
        raise StudioStorageError(f"tenant {tenant!r} violates check constraint")
    if tenant is None and visibility != "private":
        raise StudioStorageError("shared visibility needs a tenant (check constraint)")
    if slug_name and name is not None and not _NAME_RE.match(name):
        raise StudioStorageError(f"name {name!r} violates check constraint")


class _MemoryConn:
    """Satisfies ``studio_transaction``: ``transaction()`` snapshots the state, ``rollback()`` restores it."""

    def __init__(self, store: "InMemoryStudioRepositories") -> None:
        self._store = store
        self._saved: Any = None

    async def transaction(self) -> "_MemoryConn":
        self._saved = copy.deepcopy(self._store._state)
        return self

    async def commit(self) -> None:
        self._saved = None

    async def rollback(self) -> None:
        if self._saved is not None:
            self._store._state = self._saved
            self._saved = None


class _MemoryPool:
    """Pool double: ``acquire()`` yields a connection bound to the store."""

    def __init__(self, store: "InMemoryStudioRepositories") -> None:
        self._store = store

    @asynccontextmanager
    async def acquire(self):
        yield _MemoryConn(self._store)


class _Repo:
    def __init__(self, store: "InMemoryStudioRepositories") -> None:
        self._store = store

    @property
    def _s(self) -> dict[str, Any]:
        return self._store._state

    def _find(self, table: str, tenant: str | None, name: str) -> Any:
        return next((r for r in self._s[table].values() if r.tenant == tenant and r.name == name), None)

    def _bump(self, table: str, rec: Any, **changes: Any) -> Any:
        new = replace(rec, version=rec.version + 1, updated_at=_now(), **changes)
        self._s[table][getattr(rec, _ID[table])] = new
        return new

    def _unique(self, table: str, tenant: str | None, name: str, *, skip: Any = None) -> None:
        other = self._find(table, tenant, name)
        if other is not None and getattr(other, _ID[table]) != skip:
            raise StudioNameConflict(f"{table}: {name!r} already exists in partition {tenant!r}")


_ID = {"agents": "agent_id", "drafts": "draft_id", "skills": "skill_id"}


def _guard(head: StudioAgentHead, name: str, guard: StudioWriteGuard) -> StudioAgentHead:
    if guard.expected_version is not None and guard.expected_version != head.version:
        raise StudioVersionConflict(f"{name}: expected {guard.expected_version}, found {head.version}")
    if guard.authorized_version is not None and guard.authorized_version != head.version:
        raise StudioStaleAuthorization(f"{name}: authorized {guard.authorized_version}, found {head.version}")
    return head
