"""Agent-usable tools for episodic memory.

Exposes episodic memory operations as agent-callable tools via AbstractToolkit.
LLM agents can search past experiences, record lessons, and retrieve warnings
during their reasoning loop.
"""
from __future__ import annotations

import logging

from parrot.memory.agent_memory.runtime import current_memory_exposure, current_memory_scope
from parrot.tools.toolkit import AbstractToolkit

from .models import EpisodeCategory, EpisodeOutcome, MemoryNamespace
from .store import EpisodicMemoryStore, _EXPLICIT_LESSON_KEY, _EXPLICIT_REFLECTION_KEY

logger = logging.getLogger(__name__)


class EpisodicMemoryToolkit(AbstractToolkit):
    """Toolkit exposing episodic memory as agent-callable tools.

    Provides four tools for LLM agents:
    - search_episodic_memory: Semantic search over past experiences.
    - record_lesson: Explicitly record a lesson for future reference.
    - get_warnings: Retrieve relevant past failure warnings.
    - cite_memory: Attribute delivered memories without reinforcing them.

    Args:
        store: The EpisodicMemoryStore instance.
        namespace: The namespace scope for all operations.
    """

    tool_prefix: str = "ep"

    def __init__(
        self,
        store: EpisodicMemoryStore,
        namespace: MemoryNamespace,
        **kwargs,
    ) -> None:
        self._store = store
        self._namespace = namespace
        super().__init__(**kwargs)

    async def search_episodic_memory(
        self,
        query: str,
        top_k: int = 5,
        failures_only: bool = False,
    ) -> str:
        """Search past agent experiences by semantic similarity.

        Use this tool to recall what happened in similar past situations,
        including lessons learned and outcomes.

        Args:
            query: What to search for in past experiences.
            top_k: Maximum number of results to return.
            failures_only: If True, only return past failures and mistakes.

        Returns:
            Formatted list of relevant past experiences with lessons learned.
        """
        try:
            results = await self._store.recall_similar(
                query=query,
                namespace=self._namespace,
                top_k=top_k,
                include_failures_only=failures_only,
            )

            if not results:
                return "No relevant past experiences found."

            lines = []
            for i, ep in enumerate(results, 1):
                outcome_icon = (
                    "FAIL" if ep.is_failure else "OK"
                )
                line = f"{i}. [{outcome_icon}] {ep.situation[:120]}"
                line += f"\n   Action: {ep.action_taken[:120]}"
                if ep.lesson_learned:
                    line += f"\n   Lesson: {ep.lesson_learned}"
                if ep.suggested_action:
                    line += f"\n   Suggestion: {ep.suggested_action}"
                line += f"\n   (score: {ep.score:.2f}, importance: {ep.importance})"
                lines.append(line)

            return f"Found {len(results)} relevant experiences:\n\n" + "\n\n".join(lines)

        except Exception as e:
            logger.warning("search_episodic_memory failed: %s", e)
            return f"Error searching episodic memory: {e}"

    async def record_lesson(
        self,
        situation: str,
        lesson: str,
        category: str = "decision",
        importance: int = 5,
    ) -> str:
        """Explicitly record a lesson learned for future reference.

        Use this when you discover something important that should be
        remembered for similar future situations.

        Args:
            situation: What was happening when the lesson was learned.
            lesson: The concise lesson or insight to remember.
            category: Type of lesson (decision, user_preference, workflow_pattern).
            importance: How important this lesson is (1-10, default 5).

        Returns:
            Confirmation that the lesson was recorded.
        """
        try:
            # Map category string to enum
            category_map = {
                "decision": EpisodeCategory.DECISION,
                "user_preference": EpisodeCategory.USER_PREFERENCE,
                "workflow_pattern": EpisodeCategory.WORKFLOW_PATTERN,
                "tool_execution": EpisodeCategory.TOOL_EXECUTION,
                "error_recovery": EpisodeCategory.ERROR_RECOVERY,
                "query_resolution": EpisodeCategory.QUERY_RESOLUTION,
                "handoff": EpisodeCategory.HANDOFF,
            }
            cat = category_map.get(category.lower(), EpisodeCategory.DECISION)

            episode = await self._store.record_episode(
                namespace=self._namespace,
                situation=situation,
                action_taken=f"Recorded lesson: {lesson[:200]}",
                outcome=EpisodeOutcome.SUCCESS,
                category=cat,
                importance=max(1, min(10, importance)),
                generate_reflection=False,
                metadata={
                    _EXPLICIT_LESSON_KEY: lesson,
                    _EXPLICIT_REFLECTION_KEY: f"Agent explicitly recorded: {lesson}",
                },
            )

            return (
                f"Lesson recorded (id: {episode.episode_id[:8]}). "
                f"Category: {cat.value}, importance: {importance}."
            )

        except Exception as e:
            logger.warning("record_lesson failed: %s", e)
            return f"Error recording lesson: {e}"

    async def cite_memory(self, episode_ids: list[str]) -> str:
        """Cite delivered episode versions without selecting a review grade.

        Args:
            episode_ids: Episode identifiers present in the runtime-delivered memory exposure.

        Returns:
            A bounded acknowledgement, or a non-leaking rejection message.
        """
        scope = current_memory_scope()
        exposure_id = current_memory_exposure()
        if scope is None or exposure_id is None:
            return "Error citing episodic memory: no runtime memory exposure is bound."

        try:
            namespace = MemoryNamespace(
                tenant_id=scope.tenant_id,
                agent_id=scope.agent_id,
                user_id=scope.user_id,
                session_id=scope.session_id,
                room_id=scope.room_id,
                crew_id=scope.crew_id,
                model_id=scope.model_id,
            )
            if not self._namespace_allows(namespace):
                raise ValueError("runtime memory scope does not match the toolkit namespace")
            citation = await self._store.cite(episode_ids, namespace=namespace, exposure_id=exposure_id)
            return f"Cited {len(citation.refs)} delivered episodic memories."
        except Exception as exc:
            logger.warning("cite_memory rejected runtime references: %s", exc)
            return "Error citing episodic memory: one or more references are unavailable."

    def _namespace_allows(self, runtime_namespace: MemoryNamespace) -> bool:
        """Require configured scope dimensions to agree with the runtime-derived scope."""
        if (
            self._namespace.tenant_id != runtime_namespace.tenant_id
            or self._namespace.agent_id != runtime_namespace.agent_id
        ):
            return False
        for field in ("user_id", "session_id", "room_id", "crew_id", "model_id"):
            configured = getattr(self._namespace, field)
            if configured is not None and configured != getattr(runtime_namespace, field):
                return False
        return True

    async def get_warnings(
        self,
        context: str = "",
    ) -> str:
        """Get warnings about past mistakes relevant to the current task.

        Use this before attempting actions that might fail, to check
        if similar attempts have failed before.

        Args:
            context: Description of what you're about to do (for relevance matching).

        Returns:
            Formatted warnings about past failures and successful approaches,
            or a message if no relevant warnings exist.
        """
        try:
            warnings = await self._store.get_failure_warnings(
                namespace=self._namespace,
                current_query=context if context else None,
            )

            if not warnings:
                return "No relevant warnings from past experiences."

            return warnings

        except Exception as e:
            logger.warning("get_warnings failed: %s", e)
            return f"Error retrieving warnings: {e}"
