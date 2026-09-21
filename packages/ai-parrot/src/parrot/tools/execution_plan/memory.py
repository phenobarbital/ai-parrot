"""Plan-scoped working-memory binding and exact-version recovery (FEAT-585 M2)."""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from parrot.interfaces.artifact_store import PayloadResult
from parrot.tools.working_memory.internals import CatalogEntry, EntryType, GenericEntry, VersionMetadata, WorkingMemoryCatalog
from parrot.tools.working_memory.task_memory.models import ArtifactAvailability, EvidenceRef

__all__ = ("PlanWorkingMemoryCatalog", "RestoreError")


class RestoreError(Exception):
    """A restoration was refused; ``code`` is one of the spec §2 stable codes."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize the stable error code and explanatory message."""
        super().__init__(message)
        self.code = code


class PlanWorkingMemoryCatalog(WorkingMemoryCatalog):
    """Catalog that restores exact artifact versions without backend mutation."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Bind like the base catalog and start with no pinned versions."""
        super().__init__(*args, **kwargs)
        self._pinned: dict[str, EvidenceRef] = {}
        self.logger = logging.getLogger(f"{__name__}.PlanWorkingMemoryCatalog")

    def _bind_version(self, key: str, ref: EvidenceRef) -> None:
        """Pin ``key`` to ``ref`` for this continuation.

        Args:
            key: Local catalog alias to bind.
            ref: Exact version that alias must resolve to.

        Raises:
            RestoreError: If ``key`` already identifies another exact version.
        """
        current = self._pinned.get(key)
        if current is not None and current != ref:
            raise RestoreError("artifact_alias_conflict", f"{key!r} is pinned to {current}, not {ref}")
        self._pinned[key] = ref

    async def restore_version(self, key: str, ref: EvidenceRef, *, max_bytes: int) -> None:
        """Authorize, load, and publish ``ref`` under ``key`` without writing a version.

        Args:
            key: Local catalog alias to publish.
            ref: Exact artifact version to restore.
            max_bytes: Hard materialization ceiling for this restoration.

        Raises:
            RestoreError: When scope is unavailable, the version cannot be loaded,
                the bounded read is refused, or an alias is already pinned elsewhere.
        """
        if self.scope is None:
            raise RestoreError("scope_mismatch", "restoration requires a trusted host scope")
        backend, scope = self._require_enabled("restore_version")
        self._bind_version(key, ref)
        descriptor = await backend.get_version(scope, ref, task_id=self.task_id)
        if (
            descriptor is None
            or descriptor.invalidated
            or descriptor.availability not in (ArtifactAvailability.MEMORY, ArtifactAvailability.PERSISTED)
        ):
            raise RestoreError("missing_or_expired", f"{ref} is not available in this scope")

        result: PayloadResult = await backend.load_payload(scope, ref, max_bytes=max_bytes)
        if result.refusal is not None:
            raise RestoreError("restore_budget_exceeded", f"{ref} refused under max_bytes={max_bytes}: {result.refusal}")
        if result.payload is None:
            raise RestoreError("missing_or_expired", f"{ref} has no readable payload")

        entry = self._entry_from_payload(key, result.payload, descriptor)
        async with self._lock:
            self._store[key] = entry
        self.logger.debug("restored %s as %r (%d bytes)", ref, key, result.returned_bytes or 0)

    def _entry_from_payload(self, key: str, payload: Any, descriptor: Any) -> CatalogEntry | GenericEntry:
        """Rebuild a local catalog entry from its descriptor and recovered payload.

        Args:
            key: Local alias for the recovered value.
            payload: Materialized backend payload.
            descriptor: Backend descriptor for the exact version.

        Returns:
            A versioned local catalog entry.
        """
        metadata = VersionMetadata.from_descriptor(descriptor)
        if descriptor.kind.value == "dataframe" and isinstance(payload, pd.DataFrame):
            return CatalogEntry(key=key, df=payload, session_id=self.session_id, version_metadata=metadata)
        return GenericEntry(
            key=key,
            data=payload,
            entry_type=EntryType(descriptor.kind.value),
            session_id=self.session_id,
            version_metadata=metadata,
        )

    async def aget(self, key: str) -> CatalogEntry | GenericEntry:
        """Read locally, lazily restoring a pinned exact version when necessary.

        Args:
            key: Local alias to retrieve.

        Returns:
            The existing or restored catalog entry.
        """
        async with self._lock:
            if key in self._store:
                return self._store[key]
        pinned = self._pinned.get(key)
        if pinned is None:
            return await super().aget(key)
        await self.restore_version(key, pinned, max_bytes=getattr(self, "_restore_budget", 2_000_000))
        async with self._lock:
            return self._store[key]
