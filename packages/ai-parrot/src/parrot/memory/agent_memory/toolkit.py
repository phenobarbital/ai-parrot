"""Explicitly configured core memory toolkit with lazy resource ownership."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.project import find_shared_root
from parrot.memory.dynamics.feedback import import_feedback
from parrot.memory.dynamics.models import ReviewSignal
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.user.models import UserKnowledgeCommand
from parrot.tools.toolkit import AbstractToolkit

from .factory import create_memory_manager
from .models import AgentMemoryConfig, MemoryRequestScope


class AgentMemoryToolkit(AbstractToolkit):
    """Expose scoped memory operations over the same stores as agents."""

    auto_open = True
    read_tools = frozenset({"memory_status", "memory_recall"})
    tenant_bound = True

    def __init__(self, config: dict[str, Any], namespace: dict[str, Any], **kwargs: Any) -> None:
        """Validate trusted serializable configuration without opening resources.

        Args:
            config: Explicit agent-memory configuration from trusted YAML.
            namespace: Trusted tenant and agent scope from trusted YAML.
            **kwargs: Common toolkit configuration.
        """
        unknown_namespace_fields = set(namespace) - set(MemoryNamespace.model_fields)
        if unknown_namespace_fields:
            fields = ", ".join(sorted(unknown_namespace_fields))
            raise ValueError(f"unknown memory namespace fields: {fields}")
        validated_config = AgentMemoryConfig.model_validate(config)
        validated_namespace = MemoryNamespace.model_validate(namespace)
        if not validated_namespace.tenant_id.strip() or not validated_namespace.agent_id.strip():
            raise ValueError("memory namespace tenant_id and agent_id must be non-blank")
        super().__init__(config=config, namespace=namespace, **kwargs)
        self._config = validated_config
        self._namespace = validated_namespace
        self._manager: Any | None = None
        # memory_cite/memory_review accept caller-chosen exposure ids and review signals, so they are
        # operator-only (CLI calls the methods directly) and never part of the LLM/MCP tool surface.
        operator_only = ("memory_cite", "memory_review")
        self.exclude_tools = operator_only if validated_config.enable_user_memory else (*operator_only, "memory_forget")

    async def _open(self) -> None:
        """Construct configured stores; unwind partially acquired resources on failure."""
        if self._manager is not None:
            return
        manager = await create_memory_manager(self._config, namespace=self._namespace)
        self._manager = manager

    async def _close(self) -> None:
        """Drain and close owned resources, then allow a later lazy reopen."""
        manager = self._manager
        self._manager = None
        try:
            if manager is not None:
                cleanup_task = asyncio.create_task(manager.cleanup())
                try:
                    await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:
                    await asyncio.shield(cleanup_task)
                    raise
        finally:
            await super()._close()

    async def memory_status(self) -> dict[str, Any]:
        """Report enabled capabilities, durable pending reviews and degraded state."""
        manager = await self._opened_manager()
        vector_status: dict[str, Any] = {"status": "disabled"}
        if manager.episodic is not None:
            status = getattr(manager.episodic._backend, "vector_status", None)
            if callable(status):
                vector_status = await status(self._namespace.build_filter())
            else:
                vector_status = {"status": "unavailable"}
        return {
            "namespace": self._namespace.model_dump(mode="json"),
            "capabilities": {
                "episodic": manager.episodic is not None,
                "user_memory": manager.user_memory_store is not None,
                "dynamics": self._config.memory_dynamics,
                "brain": self._config.enable_brain,
            },
            "durable_pending_reviews": 0,
            "vector": vector_status,
        }

    async def memory_recall(self, query: str, limit: int = 5) -> dict[str, list[dict[str, Any]]]:
        """Recall episodic and explicitly enabled user memory in the configured scope.

        Args:
            query: Literal query text.
            limit: Maximum results returned by each enabled memory plane.

        Returns:
            Serialized, source-separated results for the trusted namespace.
        """
        if not query.strip():
            raise ValueError("query must be non-blank")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        manager = await self._opened_manager()
        episodic: list[dict[str, Any]] = []
        user: list[dict[str, Any]] = []
        if manager.episodic is not None:
            rows = await manager.episodic.recall_similar(
                query=query,
                namespace=self._namespace,
                top_k=limit,
                include_failures_only=False,
            )
            episodic = [row.model_dump(mode="json") for row in rows]
        if manager.user_memory_store is not None:
            rows = await manager.user_memory_store.recall(query, scope=self._request_scope(), limit=limit)
            user = [row.model_dump(mode="json") for row in rows]
        return {"episodic": episodic, "user": user}

    async def memory_cite(self, memory_ids: list[str], exposure_id: str) -> dict[str, Any]:
        """Cite delivered episodic references without assigning a review grade.

        Args:
            memory_ids: Delivered episode identifiers.
            exposure_id: Runtime-minted final-delivery exposure identifier.

        Returns:
            The validated structured citation.
        """
        manager = await self._opened_manager()
        if manager.episodic is None:
            raise ValueError("episodic memory is not enabled")
        citation = await manager.episodic.cite(
            memory_ids,
            namespace=self._namespace,
            exposure_id=exposure_id,
        )
        return citation.model_dump(mode="json")

    async def memory_review(
        self,
        memory_ids: list[str],
        signal: dict[str, Any],
        exposure_id: str,
    ) -> list[dict[str, Any]]:
        """Apply trusted outcome evidence to previously cited episodic references.

        Args:
            memory_ids: Episode identifiers already cited for the exposure.
            signal: A validated trusted-evidence signal; caller-supplied grades are forbidden.
            exposure_id: Runtime-minted final-delivery exposure identifier.

        Returns:
            Durable review receipts, including explicit ignored or unavailable states.
        """
        manager = await self._opened_manager()
        if manager.episodic is None:
            raise ValueError("episodic memory is not enabled")
        if not self._config.memory_dynamics:
            raise ValueError("memory dynamics is not enabled")
        trusted_signal = ReviewSignal.model_validate(signal)
        self._require_signal_scope(trusted_signal)
        receipts = await manager.episodic.review(
            memory_ids,
            trusted_signal,
            namespace=self._namespace,
            exposure_id=exposure_id,
        )
        return [receipt.model_dump(mode="json") for receipt in receipts]

    async def memory_forget(self, command: dict[str, Any]) -> dict[str, Any]:
        """Forget one user fact through the authorized scoped suppression service.

        Args:
            command: Revision-checked forget command. Scope is never accepted from this payload.

        Returns:
            The durable user-memory receipt.
        """
        manager = await self._opened_manager()
        if manager.user_memory_store is None:
            raise ValueError("user memory is not explicitly enabled")
        trusted_command = UserKnowledgeCommand.model_validate(command)
        if trusted_command.operation != "forget":
            raise ValueError("memory_forget accepts only forget commands")
        receipt = await manager.user_memory_store.forget(trusted_command, scope=self._request_scope())
        return receipt.model_dump(mode="json")

    async def memory_sync(self) -> dict[str, Any]:
        """Report the durable replay state without reapplying committed reviews.

        Returns:
            A synchronization receipt. The selected transactional backend has no
            uncommitted replay queue, so committed reviews are never applied twice.
        """
        status = await self.memory_status()
        return {
            "status": "synchronized",
            "replayed": 0,
            "durable_pending_reviews": status["durable_pending_reviews"],
        }

    async def memory_import_feedback(self) -> dict[str, int]:
        """Import shared coder feedback idempotently from the main checkout ledger.

        Returns:
            Counts of imported, skipped and newly retracted feedback records.
        """
        manager = await self._opened_manager()
        if manager.episodic is None:
            raise ValueError("episodic memory is not enabled")
        shared_root = find_shared_root(Path.cwd())
        if shared_root is None:
            raise ValueError("shared repository root is unavailable")
        return await import_feedback(shared_root, store=manager.episodic, namespace=self._namespace)

    async def _opened_manager(self) -> Any:
        """Return the manager after passing through the idempotent lazy-open gate."""
        await self._ensure_open()
        if self._manager is None:
            raise RuntimeError("memory manager failed to open")
        return self._manager

    def _request_scope(self) -> MemoryRequestScope:
        """Derive operation scope only from the trusted configured namespace."""
        return MemoryRequestScope(
            tenant_id=self._namespace.tenant_id,
            agent_id=self._namespace.agent_id,
            user_id=self._namespace.user_id,
            session_id=self._namespace.session_id,
            room_id=self._namespace.room_id,
            crew_id=self._namespace.crew_id,
            model_id=self._namespace.model_id,
            turn_id="agent-memory-toolkit",
            identity_provenance="server_resolved",
        )

    def _require_signal_scope(self, signal: ReviewSignal) -> None:
        """Reject evidence bound to any principal outside the configured namespace."""
        expected = self._request_scope()
        dimensions = ("tenant_id", "agent_id", "user_id", "session_id", "room_id", "crew_id", "model_id")
        if any(getattr(signal.scope, field) != getattr(expected, field) for field in dimensions):
            raise ValueError("review signal scope does not match the configured namespace")
