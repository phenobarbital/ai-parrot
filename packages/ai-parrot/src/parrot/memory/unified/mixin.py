"""LongTermMemoryMixin — opt-in unified long-term memory for any bot/agent.

Wires UnifiedMemoryManager into the agent lifecycle:
- ``_configure_long_term_memory()`` — call from the agent's ``configure()``
- ``get_memory_context()`` — call before LLM invocation to inject context
- ``_post_response_memory_hook()`` — call after response to record interaction
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from parrot.memory.episodic.models import MemoryNamespace

from .manager import UnifiedMemoryManager
from .models import MemoryConfig

if TYPE_CHECKING:
    from parrot.memory.dream import BrainStore, DreamScheduler

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
        enable_brain: Master toggle for the dream cycle (FEAT-390) —
            episodic-to-wiki brain consolidation. All brain/dream objects
            are no-ops (never constructed) when False.
        dream_interval_hours: Hours between dream cycles.
        dream_importance_threshold: Minimum episode importance eligible
            for consolidation (episodes with a lesson are always eligible).
        brain_storage_dir: Directory for the agent's brain wiki; defaults
            to ``~/.parrot/brains/<agent_id>``.
        brain_promote_to_org: Also maintain an org-level brain wiki and
            promote reinforced pages into it.
        org_promotion_cycles: Distinct-cycle reinforcement threshold before
            a page is promoted to the org wiki.
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

    # --- Brain / dream-cycle flags (FEAT-390) ---
    enable_brain: bool = False
    dream_interval_hours: float = 24.0
    dream_importance_threshold: int = 5
    brain_storage_dir: str | None = None
    brain_promote_to_org: bool = False
    org_promotion_cycles: int = 3

    # --- Runtime state ---
    _memory_manager: UnifiedMemoryManager | None = None
    _dream_scheduler: DreamScheduler | None = None

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
                enable_brain=self.enable_brain,
            )

            episodic_store = None
            if self.episodic_inject_warnings or self.episodic_auto_record:
                episodic_store = await self._create_episodic_store()

            skill_registry = None
            if self.skill_inject_context or self.skill_expose_tools:
                skill_registry = await self._create_skill_registry()

            conversation_memory = getattr(self, "conversation_memory", None)

            ns = self._create_namespace()

            # Brain/dream-cycle setup is isolated in its own try/except
            # (inside _configure_brain) so a brain failure never wipes out
            # an otherwise-successful episodic/skill/conversation manager.
            brain = None
            org_brain = None
            if self.enable_brain:
                brain, org_brain = await self._configure_brain(ns, episodic_store)

            manager = UnifiedMemoryManager(
                namespace=ns,
                conversation_memory=conversation_memory,
                episodic_store=episodic_store,
                skill_registry=skill_registry,
                config=config,
                brain=brain,
                org_brain=org_brain,
            )
            await manager.configure()
            self._memory_manager = manager

            logger.info(
                "LongTermMemoryMixin configured: episodic=%s, skills=%s, conv=%s, brain=%s",
                episodic_store is not None,
                skill_registry is not None,
                conversation_memory is not None,
                brain is not None,
            )

        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to configure long-term memory: %s", exc)
            self._memory_manager = None

    async def _cleanup_long_term_memory(self) -> None:
        """Stop the dream scheduler (if any) and clean up the memory manager.

        Call this from the agent's ``cleanup()`` method. No-op when
        long-term memory / the brain was never configured. Never raises —
        failures are logged at WARNING.
        """
        if self._dream_scheduler is not None:
            try:
                await self._dream_scheduler.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to stop dream scheduler: %s", exc)
            finally:
                self._dream_scheduler = None

        if self._memory_manager is not None:
            try:
                await self._memory_manager.cleanup()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to clean up long-term memory manager: %s", exc)

    async def _configure_brain(
        self,
        namespace: MemoryNamespace,
        episodic_store: Any,
    ) -> tuple[Any, Any]:
        """Build the brain store(s), dream runner, and start the scheduler.

        Resolves ``brain_storage_dir`` (default ``~/.parrot/brains/<agent_id>``
        — spec §8 open-question decision), constructs a per-agent
        ``BrainStore`` (and an org ``BrainStore`` when
        ``brain_promote_to_org``), builds a ``DreamCycleRunner`` from the
        dream flags, and starts a ``DreamScheduler`` against a
        ``dream_state.json`` sidecar in the same directory.

        Degrades on any failure — including a missing episodic store,
        which the dream cycle cannot consolidate from — returning
        ``(None, None)`` so the agent boots without a brain.

        Args:
            namespace: The agent's memory namespace.
            episodic_store: The configured episodic store, or ``None``.

        Returns:
            ``(brain, org_brain)`` for the ``UnifiedMemoryManager``
            constructor; ``(None, None)`` on failure.
        """
        if episodic_store is None:
            logger.warning(
                "enable_brain=True requires an episodic store; skipping brain setup"
            )
            return None, None

        try:
            from pathlib import Path

            from parrot.memory.dream import (
                BrainStore,
                DreamConfig,
                DreamCycleRunner,
                DreamScheduler,
            )

            agent_id = namespace.agent_id
            org_id = namespace.tenant_id

            storage_dir = (
                Path(self.brain_storage_dir).expanduser()
                if self.brain_storage_dir
                else Path("~/.parrot/brains").expanduser() / agent_id
            )
            storage_dir.mkdir(parents=True, exist_ok=True)

            brain: BrainStore = BrainStore(
                storage_dir,
                wiki_name=f"brain-{agent_id}",
                asserted_by=f"agent:{agent_id}",
            )

            org_brain: BrainStore | None = None
            if self.brain_promote_to_org:
                org_dir = storage_dir.parent / f"org-{org_id}"
                org_dir.mkdir(parents=True, exist_ok=True)
                org_brain = BrainStore(org_dir, wiki_name=f"org-{org_id}")

            dream_config = DreamConfig(
                importance_threshold=self.dream_importance_threshold,
                org_promotion_cycles=self.org_promotion_cycles,
            )

            # Defensive lookup — the mixin is bot-agnostic and must not
            # assume any particular LLM attribute exists on the host class.
            llm_client = getattr(self, "_llm", None)

            runner = DreamCycleRunner(
                episodic_store,
                brain,
                namespace,
                llm_client=llm_client,
                org_brain=org_brain,
                config=dream_config,
            )

            state_path = storage_dir / "dream_state.json"
            scheduler = DreamScheduler(
                runner,
                state_path,
                interval_hours=self.dream_interval_hours,
                config=dream_config,
            )
            await scheduler.start()
            self._dream_scheduler = scheduler

            return brain, org_brain

        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to configure brain/dream cycle: %s", exc)
            self._dream_scheduler = None
            return None, None

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
            from parrot.skills.store import SkillRegistry  # type: ignore[import]

            registry = SkillRegistry()
            return registry

        except (ImportError, ModuleNotFoundError):
            logger.debug("Skill registry module not available — skipping")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not create skill registry: %s", exc)
            return None
