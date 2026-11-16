"""Construct explicitly enabled memory resources with deterministic ownership."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.memory.unified.models import MemoryConfig
from parrot.memory.user.store import EvidenceTenantResolver, UserMemoryStore

from .models import AgentMemoryConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ManagedResource:
    """Associate a lifecycle resource with its ownership policy."""

    resource: Any
    owned: bool


class _OwnedEpisodicMemoryStore(EpisodicMemoryStore):
    """Close a backend only when this factory acquired it."""

    def __init__(self, backend: SQLiteEpisodeBackend, *, owns_backend: bool) -> None:
        """Build an episodic store with explicit backend ownership.

        Args:
            backend: SQLite backend used by this episodic store.
            owns_backend: Whether this store is responsible for closing the backend.
        """
        super().__init__(backend)
        self._owned_backend = backend if owns_backend else None

    async def close(self) -> None:
        """Release the backend only when this store owns its lifecycle."""
        if self._owned_backend is not None:
            await self._owned_backend.close()


def _configured_path(config: AgentMemoryConfig) -> Path:
    """Resolve the configured persistent storage path before resource acquisition.

    Args:
        config: Agent memory configuration containing the storage location.

    Returns:
        The configured SQLite database path.

    Raises:
        ValueError: If persistent memory was enabled without a storage path.
    """
    if not config.storage_path:
        raise ValueError("storage_path is required when persistent memory is enabled")
    return Path(config.storage_path)


def _warn_unsupported_knobs(config: AgentMemoryConfig) -> None:
    """Report options that have no consumer in the unified path instead of silently ignoring them.

    Args:
        config: Agent-level capability configuration.
    """
    defaults = AgentMemoryConfig()
    unsupported = [
        name
        for name in ("enable_reflection", "suppress_trivial_tools", "flush_on_startup", "user_memory_priority")
        if getattr(config, name) != getattr(defaults, name)
    ]
    if unsupported:
        logger.warning(
            "AgentMemoryConfig options have no effect in the unified memory path: %s", ", ".join(unsupported)
        )


def _manager_config(config: AgentMemoryConfig) -> MemoryConfig:
    """Translate agent capability flags into the unified-manager configuration.

    Args:
        config: Agent-level capability configuration.

    Returns:
        A manager configuration preserving independent capability enablement.
    """
    manager_config = MemoryConfig(
        enable_episodic=config.effective_episodic_memory,
        enable_skills=config.include_relevant_skills,
        enable_conversation=False,
        enable_user_memory=config.enable_user_memory,
        enable_brain=config.enable_brain,
        max_context_tokens=config.max_context_tokens,
        episodic_max_warnings=config.max_episodic_warnings,
    )
    # Per-source token knobs become relative weights; the assembler normalizes them across enabled sections.
    # They are assigned after construction because MemoryConfig's legacy sum-to-one check predates them.
    shares = {
        "episodic_weight": config.episodic_context_tokens,
        "skill_weight": config.skills_context_tokens,
        "brain_weight": config.brain_context_tokens,
        "user_weight": config.user_context_tokens,
    }
    total = sum(shares.values())
    if total > 0:
        for name, tokens in shares.items():
            setattr(manager_config, name, tokens / total)
    return manager_config


async def _close_owned_resources(resources: list[_ManagedResource]) -> None:
    """Close acquired resources in reverse order while preserving cancellation.

    Args:
        resources: Resources acquired so far, with their ownership policy.
    """
    for managed in reversed(resources):
        if not managed.owned:
            continue
        close = getattr(managed.resource, "close", None) or getattr(managed.resource, "cleanup", None)
        if not callable(close):
            continue
        result = close()
        if not inspect.isawaitable(result):
            continue
        close_task = asyncio.ensure_future(result)
        try:
            await asyncio.shield(close_task)
        except asyncio.CancelledError:
            await asyncio.shield(close_task)
            raise
        except Exception:  # noqa: BLE001
            logger.exception("memory resource cleanup failed")


async def create_memory_manager(
    config: AgentMemoryConfig,
    *,
    namespace: MemoryNamespace,
    evidence_tenant_resolver: EvidenceTenantResolver | None = None,
) -> UnifiedMemoryManager:
    """Build enabled resources and unwind any partial acquisition before propagating failure.

    Args:
        config: Explicit memory capability and persistent-storage configuration.
        namespace: Stable agent namespace used by episodic storage.
        evidence_tenant_resolver: Trusted metadata lookup for live ChatStorage evidence; missing lookup fails closed.

    Returns:
        A manager containing only the configured memory capabilities.

    Raises:
        ValueError: If enabled persistent memory lacks a configured storage path.
        BaseException: Any error raised while opening an enabled resource, after owned
            resources acquired earlier in this call are closed.
    """
    _warn_unsupported_knobs(config)
    if not config.effective_episodic_memory and not config.enable_user_memory:
        return UnifiedMemoryManager(namespace=namespace, config=_manager_config(config))

    path = _configured_path(config)
    resources: list[_ManagedResource] = []
    episodic_store: EpisodicMemoryStore | None = None
    user_memory_store: UserMemoryStore | None = None

    try:
        if config.effective_episodic_memory:
            backend = SQLiteEpisodeBackend(path)
            resources.append(_ManagedResource(resource=backend, owned=True))
            await backend.configure()
            episodic_store = _OwnedEpisodicMemoryStore(backend, owns_backend=True)

        if config.enable_user_memory:
            user_options: dict[str, Any] = {}
            if evidence_tenant_resolver is not None:
                user_options["evidence_tenant_resolver"] = evidence_tenant_resolver
            user_memory_store = UserMemoryStore(path, **user_options)
            resources.append(_ManagedResource(resource=user_memory_store, owned=True))
            await user_memory_store.configure()
    except BaseException:
        await _close_owned_resources(resources)
        raise

    return UnifiedMemoryManager(
        namespace=namespace,
        episodic_store=episodic_store,
        user_memory_store=user_memory_store,
        config=_manager_config(config),
    )
