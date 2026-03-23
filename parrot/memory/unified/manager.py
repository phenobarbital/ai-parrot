"""Unified Memory Manager — coordinates all long-term memory subsystems.

Orchestrates parallel retrieval from episodic memory, skill registry, and
conversation memory, then passes results through ContextAssembler for
token-budgeted context assembly.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Protocol, runtime_checkable

from parrot.memory.abstract import ConversationMemory
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore

from .context import ContextAssembler
from .models import MemoryConfig, MemoryContext

logger = logging.getLogger(__name__)


@runtime_checkable
class SkillRegistry(Protocol):
    """Structural protocol for skill registries.

    Any object that implements ``get_relevant_skills`` satisfies this
    protocol without explicit inheritance.
    """

    async def get_relevant_skills(
        self,
        query: str,
        max_skills: int = 3,
    ) -> str:
        """Return relevant skill descriptions for *query* as formatted text."""
        ...

    async def configure(self, **kwargs: Any) -> None:
        """Optional lifecycle hook — initialise the registry."""
        ...

    async def cleanup(self) -> None:
        """Optional lifecycle hook — release resources."""
        ...


class UnifiedMemoryManager:
    """Coordinates episodic memory, skill registry, and conversation memory.

    All retrieval in ``get_context_for_query`` runs concurrently via
    ``asyncio.gather``.  Subsystems that are ``None`` are silently skipped.

    Args:
        namespace: Scoping dimensions for episodic memory queries.
        conversation_memory: Optional conversation history store.
        episodic_store: Optional episodic memory store.
        skill_registry: Optional skill registry (duck-typed via SkillRegistry
            protocol).
        config: Optional memory configuration; defaults to ``MemoryConfig()``.

    Example:
        manager = UnifiedMemoryManager(
            namespace=MemoryNamespace(agent_id="my-agent"),
            episodic_store=store,
        )
        ctx = await manager.get_context_for_query("user query", "u1", "s1")
        prompt += ctx.to_prompt_string()
    """

    def __init__(
        self,
        namespace: MemoryNamespace,
        conversation_memory: Optional[ConversationMemory] = None,
        episodic_store: Optional[EpisodicMemoryStore] = None,
        skill_registry: Optional[Any] = None,
        config: Optional[MemoryConfig] = None,
    ) -> None:
        self.namespace = namespace
        self.conversation = conversation_memory
        self.episodic = episodic_store
        self.skills = skill_registry
        self.config = config or MemoryConfig()
        self._assembler = ContextAssembler(self.config)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def configure(self, **kwargs: Any) -> None:
        """Initialise all non-None subsystems.

        Calls ``configure(**kwargs)`` on each subsystem that exposes it.
        Subsystems that lack a ``configure`` method are silently skipped.

        Args:
            **kwargs: Forwarded verbatim to each subsystem's ``configure``.
        """
        for name, subsystem in self._subsystems():
            method = getattr(subsystem, "configure", None)
            if callable(method):
                self.logger.debug("Configuring subsystem: %s", name)
                await method(**kwargs)

    async def cleanup(self) -> None:
        """Release resources held by all non-None subsystems.

        Calls ``cleanup()`` on each subsystem that exposes it.
        """
        for name, subsystem in self._subsystems():
            method = getattr(subsystem, "cleanup", None)
            if callable(method):
                self.logger.debug("Cleaning up subsystem: %s", name)
                await method()

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    async def get_context_for_query(
        self,
        query: str,
        user_id: str,
        session_id: str,
    ) -> MemoryContext:
        """Retrieve and assemble context from all memory subsystems.

        All three retrieval calls run concurrently via ``asyncio.gather``.
        If a subsystem is ``None`` or raises an exception its section is
        returned as an empty string.

        Args:
            query: Current user query — used for semantic similarity search.
            user_id: User identifier for conversation history lookup.
            session_id: Session identifier for conversation history lookup.

        Returns:
            ``MemoryContext`` assembled within the configured token budget.
        """
        episodic_task = self._get_episodic_warnings(query)
        skills_task = self._get_relevant_skills(query)
        conversation_task = self._get_conversation(user_id, session_id)

        episodic_text, skills_text, conv_text = await asyncio.gather(
            episodic_task,
            skills_task,
            conversation_task,
        )

        return self._assembler.assemble(
            episodic_warnings=episodic_text,
            relevant_skills=skills_text,
            conversation=conv_text,
        )

    async def record_interaction(
        self,
        query: str,
        response: Any,
        tool_calls: list[Any],
        user_id: str,
        session_id: str,
    ) -> None:
        """Record a completed interaction to episodic and conversation memory.

        This method is exception-safe: any error is logged at WARNING level
        and execution continues.  It is designed to be called fire-and-forget
        after returning a response to the user.

        Args:
            query: The user's original query.
            response: The agent's response object (content extracted as str).
            tool_calls: List of tool call objects from the interaction.
            user_id: User identifier.
            session_id: Session identifier.
        """
        try:
            if self.episodic is not None:
                await self._record_episodic(
                    query, response, tool_calls, user_id, session_id
                )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "record_interaction: episodic recording failed — %s", exc
            )

    # ------------------------------------------------------------------
    # Private retrieval helpers
    # ------------------------------------------------------------------

    async def _get_episodic_warnings(self, query: str) -> str:
        """Retrieve failure warnings from episodic store.

        Returns empty string when episodic store is ``None`` or on error.
        """
        if self.episodic is None:
            return ""
        try:
            return await self.episodic.get_failure_warnings(
                namespace=self.namespace,
                current_query=query,
                max_warnings=self.config.episodic_max_warnings,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Episodic retrieval failed: %s", exc)
            return ""

    async def _get_relevant_skills(self, query: str) -> str:
        """Retrieve relevant skills from the skill registry.

        Returns empty string when skill registry is ``None`` or on error.
        """
        if self.skills is None:
            return ""
        try:
            return await self.skills.get_relevant_skills(
                query=query,
                max_skills=self.config.skill_max_context,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Skill retrieval failed: %s", exc)
            return ""

    async def _get_conversation(self, user_id: str, session_id: str) -> str:
        """Retrieve and format recent conversation history.

        Returns empty string when conversation memory is ``None`` or on error.
        """
        if self.conversation is None:
            return ""
        try:
            history = await self.conversation.get_history(
                user_id=user_id,
                session_id=session_id,
            )
            if history is None or not history.turns:
                return ""
            lines: list[str] = []
            for turn in history.turns:
                lines.append(f"User: {turn.user_message}")
                lines.append(f"Assistant: {turn.assistant_response}")
            return "\n".join(lines)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Conversation retrieval failed: %s", exc)
            return ""

    async def _record_episodic(
        self,
        query: str,
        response: Any,
        tool_calls: list[Any],
        user_id: str,
        session_id: str,
    ) -> None:
        """Record the interaction to episodic memory.

        Args:
            query: User's original query.
            response: Agent response (str or object with .content attribute).
            tool_calls: Tool calls made during the interaction.
            user_id: User identifier.
            session_id: Session identifier.
        """
        ns = MemoryNamespace(
            tenant_id=self.namespace.tenant_id,
            agent_id=self.namespace.agent_id,
            user_id=user_id,
            session_id=session_id,
        )
        response_text = (
            response if isinstance(response, str)
            else getattr(response, "content", str(response))
        )
        await self.episodic.record_tool_episode(  # type: ignore[union-attr]
            namespace=ns,
            query=query,
            response=response_text,
            tool_calls=tool_calls,
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _subsystems(self) -> list[tuple[str, Any]]:
        """Return (name, instance) pairs for all non-None subsystems."""
        return [
            (name, obj)
            for name, obj in [
                ("episodic", self.episodic),
                ("skills", self.skills),
                ("conversation", self.conversation),
            ]
            if obj is not None
        ]
