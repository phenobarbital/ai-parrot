"""EpisodicMemoryMixin for AbstractBot integration.

Provides automatic episodic memory recording and context injection
as an opt-in mixin for bot classes. Hooks into the ask() flow to:
1. Inject episodic context (warnings, preferences) pre-LLM.
2. Record tool executions as episodes post-tool.
3. Record significant conversations post-ask.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .models import (
    EpisodeCategory,
    EpisodeOutcome,
    MemoryNamespace,
)
from .store import EpisodicMemoryStore

logger = logging.getLogger(__name__)

# Minimum query length to consider recording
_MIN_QUERY_LENGTH = 10

# Trivial greetings that don't warrant recording
_TRIVIAL_PATTERNS = frozenset({
    "hello", "hi", "hey", "thanks", "thank you", "bye", "goodbye",
    "ok", "okay", "yes", "no", "sure", "help",
})


class EpisodicMemoryMixin:
    """Mixin that adds automatic episodic memory to bots.

    Provides hooks that bot implementations call at appropriate points
    in their ask() flow. The mixin is opt-in — bots that don't inherit
    it are completely unaffected.

    Configuration attributes (override in subclass or set via kwargs):
        enable_episodic_memory: Master toggle for the mixin.
        episodic_backend: Backend type ("pgvector" or "faiss").
        episodic_dsn: PostgreSQL DSN for PgVector backend.
        episodic_faiss_path: Persistence path for FAISS backend.
        episodic_schema: PostgreSQL schema name.
        episodic_reflection_enabled: Whether to generate reflections.
        episodic_inject_warnings: Whether to inject failure warnings pre-LLM.
        episodic_max_warnings: Maximum warnings to inject.
        episodic_trivial_tools: Tools to skip when recording.
    """

    enable_episodic_memory: bool = False
    episodic_backend: str = "faiss"
    episodic_dsn: str | None = None
    episodic_faiss_path: str | None = None
    episodic_schema: str = "parrot_memory"
    episodic_reflection_enabled: bool = True
    episodic_inject_warnings: bool = True
    episodic_max_warnings: int = 3
    episodic_trivial_tools: set[str] = frozenset({
        "get_time", "get_date", "get_current_time",
    })

    _episodic_store: EpisodicMemoryStore | None = None

    async def _configure_episodic_memory(self) -> None:
        """Initialize the episodic memory store.

        Call this from the bot's configure() method. Creates the store
        with the appropriate backend, embedding provider, and reflection
        engine based on configuration attributes.
        """
        if not self.enable_episodic_memory:
            return

        try:
            from .embedding import EpisodeEmbeddingProvider
            from .reflection import ReflectionEngine

            embedding = EpisodeEmbeddingProvider()

            reflection = None
            if self.episodic_reflection_enabled:
                # Use the bot's LLM client if available
                llm_client = getattr(self, "_llm", None)
                reflection = ReflectionEngine(
                    llm_client=llm_client,
                    fallback_to_heuristic=True,
                )

            # Create cache if Redis is available
            cache = None
            redis_client = getattr(self, "redis", None)
            if redis_client is not None:
                from .cache import EpisodeRedisCache
                cache = EpisodeRedisCache(redis_client=redis_client)

            # Create store with appropriate backend
            if self.episodic_backend == "pgvector" and self.episodic_dsn:
                self._episodic_store = await EpisodicMemoryStore.create_pgvector(
                    dsn=self.episodic_dsn,
                    schema=self.episodic_schema,
                    embedding_provider=embedding,
                    reflection_engine=reflection,
                    redis_cache=cache,
                )
            else:
                self._episodic_store = await EpisodicMemoryStore.create_faiss(
                    persistence_path=self.episodic_faiss_path,
                    embedding_provider=embedding,
                    reflection_engine=reflection,
                    redis_cache=cache,
                )

            # Register toolkit with tool manager if available
            tool_manager = getattr(self, "tool_manager", None)
            if tool_manager is not None:
                from .tools import EpisodicMemoryToolkit

                agent_id = self._get_agent_id()
                ns = MemoryNamespace(tenant_id="default", agent_id=agent_id)
                toolkit = EpisodicMemoryToolkit(
                    store=self._episodic_store,
                    namespace=ns,
                )
                for tool in toolkit.get_tools():
                    tool_manager.register_tool(tool)

            logger.info(
                "Episodic memory configured: backend=%s",
                self.episodic_backend,
            )

        except Exception as e:
            logger.warning("Failed to configure episodic memory: %s", e)
            self._episodic_store = None

    def _get_agent_id(self) -> str:
        """Get the agent identifier from the bot."""
        return getattr(self, "name", "unknown_agent")

    async def _build_episodic_context(
        self,
        query: str,
        user_id: str | None = None,
        room_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """Build episodic context for system prompt injection.

        Assembles warnings, user preferences, and room context into
        a formatted string suitable for appending to the system prompt.

        Args:
            query: The current user query.
            user_id: Optional user identifier.
            room_id: Optional room identifier.
            session_id: Optional session identifier.

        Returns:
            Formatted episodic context string, or empty string if none.
        """
        if not self._episodic_store or not self.enable_episodic_memory:
            return ""

        agent_id = self._get_agent_id()
        ns = MemoryNamespace(
            tenant_id="default",
            agent_id=agent_id,
            user_id=user_id,
            room_id=room_id,
            session_id=session_id,
        )

        parts: list[str] = []

        # Failure warnings
        if self.episodic_inject_warnings:
            try:
                warnings = await self._episodic_store.get_failure_warnings(
                    namespace=ns,
                    current_query=query,
                    max_warnings=self.episodic_max_warnings,
                )
                if warnings:
                    parts.append(warnings)
            except Exception as e:
                logger.debug("Episodic warnings retrieval failed: %s", e)

        # User preferences
        if user_id:
            try:
                prefs = await self._episodic_store.get_user_preferences(ns, limit=5)
                if prefs:
                    pref_lines = ["USER PREFERENCES:"]
                    for p in prefs:
                        if p.lesson_learned:
                            pref_lines.append(f"- {p.lesson_learned}")
                        else:
                            pref_lines.append(f"- {p.situation[:100]}")
                    parts.append("\n".join(pref_lines))
            except Exception as e:
                logger.debug("Episodic preferences retrieval failed: %s", e)

        # Room context
        if room_id:
            try:
                room_eps = await self._episodic_store.get_room_context(
                    ns, limit=5
                )
                if room_eps:
                    room_lines = ["ROOM CONTEXT (recent activity):"]
                    for ep in room_eps[:5]:
                        status = "OK" if not ep.is_failure else "FAIL"
                        room_lines.append(
                            f"- [{status}] {ep.situation[:80]}"
                        )
                    parts.append("\n".join(room_lines))
            except Exception as e:
                logger.debug("Episodic room context retrieval failed: %s", e)

        return "\n\n".join(parts)

    async def _record_post_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: Any,
        user_query: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        room_id: str | None = None,
    ) -> None:
        """Record a tool execution as an episode (fire-and-forget).

        Skips trivial tools. Uses asyncio.create_task to avoid blocking.

        Args:
            tool_name: Name of the tool that was called.
            tool_args: Arguments passed to the tool.
            tool_result: The result from tool execution.
            user_query: The user query that triggered the tool.
            user_id: Optional user identifier.
            session_id: Optional session identifier.
            room_id: Optional room identifier.
        """
        if not self._episodic_store or not self.enable_episodic_memory:
            return

        if tool_name in self.episodic_trivial_tools:
            return

        agent_id = self._get_agent_id()
        ns = MemoryNamespace(
            tenant_id="default",
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            room_id=room_id,
        )

        asyncio.create_task(
            self._safe_record_tool(ns, tool_name, tool_args, tool_result, user_query)
        )

    async def _safe_record_tool(
        self,
        namespace: MemoryNamespace,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: Any,
        user_query: str | None,
    ) -> None:
        """Safe wrapper for recording tool episodes (catches all exceptions)."""
        try:
            await self._episodic_store.record_tool_episode(
                namespace=namespace,
                tool_name=tool_name,
                tool_args=tool_args,
                tool_result=tool_result,
                user_query=user_query,
            )
        except Exception as e:
            logger.debug("Failed to record tool episode: %s", e)

    async def _record_post_ask(
        self,
        query: str,
        response: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        room_id: str | None = None,
    ) -> None:
        """Record a conversation as an episode (fire-and-forget).

        Skips trivial queries (greetings, very short messages).

        Args:
            query: The user's query.
            response: The bot's response (truncated for storage).
            user_id: Optional user identifier.
            session_id: Optional session identifier.
            room_id: Optional room identifier.
        """
        if not self._episodic_store or not self.enable_episodic_memory:
            return

        # Skip trivial queries
        if len(query.strip()) < _MIN_QUERY_LENGTH:
            return
        if query.strip().lower() in _TRIVIAL_PATTERNS:
            return

        agent_id = self._get_agent_id()
        ns = MemoryNamespace(
            tenant_id="default",
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            room_id=room_id,
        )

        asyncio.create_task(
            self._safe_record_ask(ns, query, response)
        )

    async def _safe_record_ask(
        self,
        namespace: MemoryNamespace,
        query: str,
        response: str | None,
    ) -> None:
        """Safe wrapper for recording conversation episodes."""
        try:
            await self._episodic_store.record_episode(
                namespace=namespace,
                situation=query[:500],
                action_taken=f"Responded: {(response or '')[:200]}",
                outcome=EpisodeOutcome.SUCCESS,
                category=EpisodeCategory.QUERY_RESOLUTION,
                importance=3,
            )
        except Exception as e:
            logger.debug("Failed to record ask episode: %s", e)
