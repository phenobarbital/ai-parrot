"""LongTermMemoryMixin — opt-in unified long-term memory for any bot/agent.

Wires UnifiedMemoryManager into the agent lifecycle:
- ``_configure_long_term_memory()`` — call from the agent's ``configure()``
- ``get_memory_context()`` — call before LLM invocation to inject context
- ``_post_response_memory_hook()`` — call after response to record interaction
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from parrot.memory.episodic.models import MemoryNamespace

from .manager import UnifiedMemoryManager
from .models import MemoryConfig

logger = logging.getLogger(__name__)


class LongTermMemoryMixin:
    """Single opt-in mixin for long-term memory in any bot/agent.

    Provides unified episodic + skill + conversation memory without
    requiring the bot to manage individual subsystems.

    MRO note: place before ``AbstractBot`` (or ``Agent``) in the class
    definition so this mixin's methods take priority in the resolution order:

        class MyAgent(LongTermMemoryMixin, Agent):
            enable_long_term_memory = True

    Configuration attributes (override in the subclass or via kwargs):
        enable_long_term_memory: Master toggle — all methods are no-ops when False.
        episodic_inject_warnings: Retrieve past failure warnings.
        episodic_auto_record: Record interactions to episodic memory.
        episodic_max_warnings: Maximum failure warnings per context.
        skill_inject_context: Retrieve relevant skills into context.
        skill_auto_extract: Auto-extract skills from successful interactions.
        skill_expose_tools: Register skill tools with the agent's tool manager.
        skill_max_context: Maximum skills per context.
        memory_max_context_tokens: Total token budget for assembled context.
    """

    # --- Configuration flags ---
    enable_long_term_memory: bool = False
    episodic_inject_warnings: bool = True
    episodic_auto_record: bool = True
    episodic_max_warnings: int = 3
    skill_inject_context: bool = True
    skill_auto_extract: bool = False
    skill_expose_tools: bool = True
    skill_max_context: int = 3
    memory_max_context_tokens: int = 2000

    # --- Runtime state ---
    _memory_manager: Optional[UnifiedMemoryManager] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _configure_long_term_memory(self) -> None:
        """Create and configure the UnifiedMemoryManager.

        Call this from the agent's ``configure()`` method.  When
        ``enable_long_term_memory`` is ``False`` this is a no-op.
        Construction failures are logged at WARNING and the manager is
        left as ``None`` so the agent can continue without memory.
        """
        if not self.enable_long_term_memory:
            return

        try:
            config = MemoryConfig(
                max_context_tokens=self.memory_max_context_tokens,
                episodic_max_warnings=self.episodic_max_warnings,
                skill_max_context=self.skill_max_context,
                skill_auto_extract=self.skill_auto_extract,
            )

            episodic_store = None
            if self.episodic_inject_warnings or self.episodic_auto_record:
                episodic_store = await self._create_episodic_store()

            skill_registry = None
            if self.skill_inject_context or self.skill_expose_tools:
                skill_registry = await self._create_skill_registry()

            conversation_memory = getattr(self, "conversation_memory", None)

            ns = self._create_namespace()

            manager = UnifiedMemoryManager(
                namespace=ns,
                conversation_memory=conversation_memory,
                episodic_store=episodic_store,
                skill_registry=skill_registry,
                config=config,
            )
            await manager.configure()
            self._memory_manager = manager

            logger.info(
                "LongTermMemoryMixin configured: episodic=%s, skills=%s, conv=%s",
                episodic_store is not None,
                skill_registry is not None,
                conversation_memory is not None,
            )

        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to configure long-term memory: %s", exc)
            self._memory_manager = None

    # ------------------------------------------------------------------
    # Context retrieval
    # ------------------------------------------------------------------

    async def get_memory_context(
        self,
        query: str,
        user_id: str,
        session_id: str,
    ) -> str:
        """Return assembled memory context as an injectable prompt string.

        Args:
            query: Current user query for semantic retrieval.
            user_id: User identifier for conversation history.
            session_id: Session identifier for conversation history.

        Returns:
            Formatted multi-section string ready for system prompt injection,
            or empty string when memory is disabled or not configured.
        """
        if not self.enable_long_term_memory or self._memory_manager is None:
            return ""

        try:
            ctx = await self._memory_manager.get_context_for_query(
                query=query,
                user_id=user_id,
                session_id=session_id,
            )
            return ctx.to_prompt_string()
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_memory_context failed: %s", exc)
            return ""

    # ------------------------------------------------------------------
    # Interaction recording
    # ------------------------------------------------------------------

    async def _post_response_memory_hook(
        self,
        query: str,
        response: Any,
        user_id: str,
        session_id: str,
    ) -> None:
        """Record a completed interaction to long-term memory (fire-and-forget).

        This method never raises — all exceptions are caught and logged.
        It is intended to be called after a response is delivered to the user.

        Args:
            query: The user's original query.
            response: The agent's response (str or object with .content).
            user_id: User identifier.
            session_id: Session identifier.
        """
        if not self.enable_long_term_memory or self._memory_manager is None:
            return

        try:
            await self._memory_manager.record_interaction(
                query=query,
                response=response,
                tool_calls=[],
                user_id=user_id,
                session_id=session_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("_post_response_memory_hook failed: %s", exc)

    # ------------------------------------------------------------------
    # Namespace helpers
    # ------------------------------------------------------------------

    def _create_namespace(self) -> MemoryNamespace:
        """Build a MemoryNamespace from agent attributes.

        Uses ``self.name`` as ``agent_id`` (falls back to ``"unknown_agent"``).
        Uses ``self.tenant_id`` when available (falls back to ``"default"``).

        Returns:
            Populated ``MemoryNamespace`` instance.
        """
        agent_id: str = getattr(self, "name", "unknown_agent") or "unknown_agent"
        tenant_id: str = getattr(self, "tenant_id", "default") or "default"
        return MemoryNamespace(tenant_id=tenant_id, agent_id=agent_id)

    # ------------------------------------------------------------------
    # Private subsystem factory helpers
    # ------------------------------------------------------------------

    async def _create_episodic_store(self) -> Any:
        """Create an EpisodicMemoryStore from agent configuration.

        Uses the same backend selection logic as ``EpisodicMemoryMixin``.
        Returns ``None`` on failure (logged at WARNING).
        """
        try:
            from parrot.memory.episodic.embedding import EpisodeEmbeddingProvider
            from parrot.memory.episodic.reflection import ReflectionEngine
            from parrot.memory.episodic.store import EpisodicMemoryStore

            embedding = EpisodeEmbeddingProvider()

            llm_client = getattr(self, "_llm", None)
            reflection = ReflectionEngine(
                llm_client=llm_client,
                fallback_to_heuristic=True,
            )

            backend: str = getattr(self, "episodic_backend", "faiss")
            dsn: str | None = getattr(self, "episodic_dsn", None)
            schema: str = getattr(self, "episodic_schema", "parrot_memory")
            faiss_path: str | None = getattr(self, "episodic_faiss_path", None)

            redis_client = getattr(self, "redis", None)
            cache = None
            if redis_client is not None:
                from parrot.memory.episodic.cache import EpisodeRedisCache
                cache = EpisodeRedisCache(redis_client=redis_client)

            if backend == "pgvector" and dsn:
                return await EpisodicMemoryStore.create_pgvector(
                    dsn=dsn,
                    schema=schema,
                    embedding_provider=embedding,
                    reflection_engine=reflection,
                    redis_cache=cache,
                )
            return await EpisodicMemoryStore.create_faiss(
                persistence_path=faiss_path,
                embedding_provider=embedding,
                reflection_engine=reflection,
                redis_cache=cache,
            )

        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not create episodic store: %s", exc)
            return None

    async def _create_skill_registry(self) -> Any:
        """Create a SkillRegistry from agent configuration.

        Returns ``None`` when the skills module is unavailable or on error.
        """
        try:
            from parrot.memory.skills.store import SkillRegistry  # type: ignore[import]

            registry = SkillRegistry()
            return registry

        except (ImportError, ModuleNotFoundError):
            logger.debug("Skill registry module not available — skipping")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not create skill registry: %s", exc)
            return None
