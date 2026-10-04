"""Plan-scoped working-memory binding and exact-version recovery (FEAT-585 M2)."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import TYPE_CHECKING, Any, Optional, Sequence

import pandas as pd

from parrot.bots.flows.plan import ArtifactRef
from parrot.interfaces.artifact_store import PayloadResult
from parrot.tools.working_memory.internals import (
    CatalogEntry,
    EntryType,
    GenericEntry,
    VersionMetadata,
    WorkingMemoryCatalog,
)
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig, TaskMemoryRuntime
from parrot.tools.working_memory.task_memory.models import ArtifactAvailability, EvidenceRef, TaskScope
from parrot.tools.working_memory.task_memory.tools import TaskMemory

if TYPE_CHECKING:
    from parrot.tools.working_memory.tool import WorkingMemoryToolkit

__all__ = ("PlanMemoryBinding", "PlanWorkingMemoryCatalog", "RestoreError", "synthesize_process_scope")


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
            raise RestoreError(
                "restore_budget_exceeded", f"{ref} refused under max_bytes={max_bytes}: {result.refusal}"
            )
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


def synthesize_process_scope(session_id: str) -> TaskScope:
    """Create a process-local namespace for legacy plan wiring.

    Args:
        session_id: Working-memory session identifier to preserve.

    Returns:
        A process-local task scope; it is not user authentication.
    """
    return TaskScope(
        chatbot_id="execution-plan",
        user_id=f"proc-{os.getpid()}-{uuid.uuid4().hex[:8]}",
        session_id=session_id,
    )


class PlanMemoryBinding:
    """Own plan-only memory preparation and borrowed/owned resource lifetimes."""

    def __init__(
        self,
        working_memory: "WorkingMemoryToolkit",
        *,
        runtime: Optional[TaskMemoryRuntime],
        scope: Optional[TaskScope],
        max_restore_bytes: int,
    ) -> None:
        """Prepare configuration without I/O; retain supplied scope and runtime.

        Args:
            working_memory: Toolkit receiving the prepared plan binding.
            runtime: Started host runtime to borrow, when supplied.
            scope: Trusted host scope for a supplied runtime.
            max_restore_bytes: Cumulative recovery read budget.

        Raises:
            ValueError: If a host runtime lacks its trusted scope.
        """
        if runtime is not None and scope is None and getattr(working_memory, "_task_memory", None) is None:
            raise ValueError("a host-supplied TaskMemoryRuntime requires a trusted TaskScope")
        self._wm = working_memory
        self._runtime = runtime
        self._owns_runtime = runtime is None and getattr(working_memory, "_task_memory", None) is None
        self._scope = scope
        self._max_restore_bytes = max_restore_bytes
        self._restored_bytes = 0
        self._lock = asyncio.Lock()
        self._task_memory: Optional[TaskMemory] = None
        self._catalog: Optional[PlanWorkingMemoryCatalog] = None
        self.logger = logging.getLogger(f"{__name__}.PlanMemoryBinding")

    @property
    def scope(self) -> Optional[TaskScope]:
        """Return the trusted scope in force after preparation."""
        return self._scope

    @property
    def artifact_mode(self) -> str:
        """Return ``durable`` only when the active configuration is durable."""
        config = getattr(self._task_memory, "config", None)
        return "durable" if getattr(config, "durable", False) else "memory"

    @property
    def resume_level_hint(self) -> str:
        """Return the recovery level supported by the current binding."""
        if self.artifact_mode == "durable" and not self._owns_runtime:
            return "cross_restart"
        return "process"

    async def prepare(self) -> TaskMemory:
        """Enable plan memory atomically while preserving legacy state on failure.

        Returns:
            The enabled task-memory composition root.
        """
        async with self._lock:
            if self._task_memory is not None:
                return self._task_memory

            existing = getattr(self._wm, "_task_memory", None)
            if existing is not None:
                self._task_memory = existing
                self._scope = existing.scope
                self._catalog = self._wm._catalog
                return existing

            if self._runtime is not None:
                task_memory = self._runtime.task_memory(self._scope)
            else:
                self._runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True, durable=False))
                await self._runtime.start(start_scheduler=False)
                scope = getattr(self._wm, "_plan_scope", None)
                if scope is None:
                    scope = synthesize_process_scope(self._wm._catalog.session_id)
                    self._wm._plan_scope = scope
                self._scope = scope
                task_memory = self._runtime.task_memory(scope)

            catalog = PlanWorkingMemoryCatalog(
                session_id=self._wm._catalog.session_id,
                backend=task_memory.artifacts,
                scope=self._scope,
                task_id=None,
            )
            for key, entry in self._wm._catalog._store.items():
                value = entry.df if isinstance(entry, CatalogEntry) else entry.data
                await catalog.aput_generic(
                    key,
                    value,
                    entry_type=getattr(entry, "entry_type", None),
                    description=getattr(entry, "description", ""),
                    metadata=getattr(entry, "metadata", None),
                    turn_id=getattr(entry, "turn_id", None),
                )

            await self._wm._enable_plan_memory(task_memory, catalog)
            self._task_memory = task_memory
            self._catalog = catalog
            return task_memory

    async def restore(self, refs: Sequence[ArtifactRef]) -> None:
        """Restore authorized exact versions within the configured cumulative budget.

        Args:
            refs: Checkpoint-published immutable artifact references.

        Raises:
            RestoreError: If preparation, checkpoint structure, or budget is invalid.
        """
        if self._catalog is None:
            raise RestoreError("artifacts_unavailable", "plan memory is not prepared")
        for ref in refs:
            if len(ref.keys) != len(ref.versions):
                raise RestoreError("checkpoint_invalid", f"node {ref.node_id!r}: keys/versions cardinality mismatch")
            for key, version in zip(ref.keys, ref.versions, strict=True):
                remaining = self._max_restore_bytes - self._restored_bytes
                if remaining <= 0:
                    raise RestoreError(
                        "restore_budget_exceeded", f"max_restore_bytes={self._max_restore_bytes} exhausted"
                    )
                await self._catalog.restore_version(key, EvidenceRef.parse(version), max_bytes=remaining)
                restored = await self._catalog.aget(key)
                self._restored_bytes += restored.version_metadata.byte_size or 0

    async def close(self) -> None:
        """Close only runtime resources created by this binding."""
        async with self._lock:
            if self._owns_runtime and self._runtime is not None:
                await self._runtime.stop()
