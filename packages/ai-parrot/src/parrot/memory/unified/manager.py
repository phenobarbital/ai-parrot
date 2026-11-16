"""Unified Memory Manager — coordinates all long-term memory subsystems.

Orchestrates parallel retrieval from episodic memory, skill registry, and
conversation memory, then passes results through ContextAssembler for
token-budgeted context assembly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from typing import Any, Optional, Protocol, runtime_checkable

from parrot.memory.abstract import ConversationMemory
from parrot.memory.agent_memory.attribution import ToolAttempt, build_tool_signal, validate_citation
from parrot.memory.agent_memory.models import MemoryEvent, MemoryRequestScope, MemoryWriteReceipt
from parrot.memory.dynamics.models import MemoryExposure, MemoryRef
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.unified.models import MemoryCandidate
from parrot.memory.user.extraction import extract_user_knowledge
from parrot.memory.user.models import UserKnowledge, UserKnowledgeCommand, UserMemoryReceipt
from parrot.memory.user.store import UserMemoryStore

from .context import ContextAssembler
from .models import MemoryConfig, MemoryContext
from .routing import CrossDomainRouter

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

    When ``cross_domain_router`` is provided, ``get_context_for_query`` also
    queries episodic memories from relevant agent namespaces identified by the
    router. Cross-domain results are labeled and appended to the episodic
    warnings text. Cross-domain failures never break the main retrieval flow.

    Args:
        namespace: Scoping dimensions for episodic memory queries.
        conversation_memory: Optional conversation history store.
        episodic_store: Optional episodic memory store.
        skill_registry: Optional skill registry (duck-typed via SkillRegistry
            protocol).
        config: Optional memory configuration; defaults to ``MemoryConfig()``.
        cross_domain_router: Optional router for multi-agent memory sharing.
        user_memory_store: Optional independently-owned user knowledge store.
        extraction_client: Optional client used for bounded user-knowledge extraction.
        brain_service: Optional injected tenant-bound brain service.

    Example:
        manager = UnifiedMemoryManager(
            namespace=MemoryNamespace(agent_id="my-agent"),
            episodic_store=store,
            cross_domain_router=router,
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
        cross_domain_router: Optional[CrossDomainRouter] = None,
        user_memory_store: UserMemoryStore | None = None,
        extraction_client: Any | None = None,
        brain_service: Any | None = None,
    ) -> None:
        self.namespace = namespace
        self.conversation = conversation_memory
        self.episodic = episodic_store
        self.skills = skill_registry
        self.config = config or MemoryConfig()
        self._assembler = ContextAssembler(self.config)
        self._cross_domain_router = cross_domain_router
        self.user_memory_store = user_memory_store
        self.extraction_client = extraction_client
        self.brain_service = brain_service
        self._memory_exposures: dict[str, MemoryExposure] = {}
        self._active_memory_exposures: set[str] = set()
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
        first_error: Exception | None = None
        for name, subsystem in self._subsystems():
            method = getattr(subsystem, "cleanup", None) or getattr(subsystem, "close", None)
            if callable(method):
                self.logger.debug("Cleaning up subsystem: %s", name)
                try:
                    await method()
                except Exception as exc:  # noqa: BLE001 - a failing subsystem must not leak the others
                    self.logger.warning("Cleanup of subsystem %s failed: %s", name, type(exc).__name__)
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error

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
        brain_task = self._get_brain_knowledge(query)

        episodic_text, skills_text, conv_text, brain_text = await asyncio.gather(
            episodic_task,
            skills_task,
            conversation_task,
            brain_task,
        )

        return self._assembler.assemble(
            episodic_warnings=episodic_text,
            relevant_skills=skills_text,
            conversation=conv_text,
            semantic_knowledge=brain_text,
        )

    async def prepare_context(self, query: str, *, scope: MemoryRequestScope) -> MemoryContext:
        """Retrieve enabled supplementary capabilities under an immutable request scope.

        Unlike :meth:`get_context_for_query`, this agent-owned path never retrieves
        conversation history.  The host already owns hydrated history and adding it
        here would create a second, unguarded history source.

        Args:
            query: Current user query used for scoped retrieval.
            scope: Server-resolved immutable request identity.

        Returns:
            One bounded supplementary context assembled from complete candidates.
        """
        episodic_task = self._get_episodic_candidates(query, scope)
        skills_task = self._get_skill_candidates(query, scope)
        user_task = self._get_user_candidates(query, scope)
        brain_task = self._get_brain_candidates(query, scope)
        candidate_groups = await asyncio.gather(episodic_task, skills_task, user_task, brain_task)
        candidates = [candidate for group in candidate_groups for candidate in group]
        context = self._assembler.assemble_candidates(candidates, scope=scope)

        # BrainService phase one returns plain text.  It is useful contextual data,
        # but it does not identify a versioned brain page and therefore cannot be
        # exposed as reviewable evidence.
        brain_prefix = "brain_text:"
        return context.model_copy(
            update={"delivered_refs": tuple(ref for ref in context.delivered_refs if not ref.startswith(brain_prefix))}
        )

    def commit_memory_exposure(self, context: MemoryContext, *, scope: MemoryRequestScope) -> MemoryContext:
        """Mint and retain the complete final-delivery manifest for review admission.

        Only versioned episodic references can be reviewed by this feature. User facts,
        skills, and the phase-one text-only brain service remain contextual data without
        dynamics attribution.
        """
        if self.episodic is None or context.packed_digest is None:
            return context
        refs = tuple(
            memory_ref
            for delivered_ref in context.delivered_refs
            if (memory_ref := self._delivered_memory_ref(delivered_ref, scope)) is not None
        )
        if not refs:
            return context

        exposure_id = f"exposure-{uuid.uuid4().hex}"
        exposure = MemoryExposure(
            exposure_id=exposure_id,
            scope=scope,
            attempt_id=scope.turn_id,
            refs=refs,
            packed_digest=context.packed_digest,
        )
        self._memory_exposures[exposure_id] = exposure
        return context.model_copy(
            update={
                "exposure_id": exposure_id,
                "exposure_metadata": {
                    "attempt_id": scope.turn_id,
                    "packed_digest": context.packed_digest,
                },
            }
        )

    def activate_memory_exposure(self, exposure_id: str, scope: MemoryRequestScope) -> bool:
        """Make a manifest reviewable only after its provider response completed."""
        exposure = self._memory_exposures.get(exposure_id)
        if exposure is None or exposure.scope != scope:
            return False
        self._active_memory_exposures.add(exposure_id)
        return True

    def deactivate_memory_exposure(self, exposure_id: str) -> None:
        """Reject later events for a manifest after its invocation has been admitted.

        The manifest is released, not retained: an unknown ID is rejected by ``activate_memory_exposure`` and by tool
        events, so the registry does not grow with every invocation.
        """
        self._active_memory_exposures.discard(exposure_id)
        self._memory_exposures.pop(exposure_id, None)
        if self.episodic is not None:
            self.episodic._citations.pop(exposure_id, None)

    def discard_memory_exposure(self, exposure_id: str) -> None:
        """Invalidate a provider-failed or cancelled manifest without revealing its refs."""
        self._active_memory_exposures.discard(exposure_id)
        self._memory_exposures.pop(exposure_id, None)
        if self.episodic is not None:
            self.episodic._citations.pop(exposure_id, None)

    async def record_event(self, event: MemoryEvent) -> MemoryWriteReceipt:
        """Route an observed event to its owning stores without replaying tool attempts.

        A response without verified outcome evidence becomes one PARTIAL episodic
        record.  Tool observations remain owned by their execution hook, so they are
        never replayed as either tool or response episodes here.  User extraction is
        independent of episodic recording and preserves any durable write failures in
        the returned receipt.

        Args:
            event: Validated, scoped observation from one request lifecycle.

        Returns:
            A receipt describing only durable effects and recorded failures.
        """
        if event.kind == "tool":
            return await self._record_tool_event(event)

        episode_ids: list[str] = []
        knowledge_ids: list[str] = []
        statuses: list[str] = []
        failures: list[str] = []

        if event.kind == "response" and self.config.enable_episodic and self.episodic is not None:
            try:
                episode = await self._record_response_event(event)
                episode_ids.append(episode.episode_id)
                statuses.append("applied")
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("response episode recording failed: %s", type(exc).__name__)
                statuses.append("storage_unavailable")
                failures.append(f"episodic:{type(exc).__name__}")

        if event.kind in {"response", "user_knowledge"}:
            user_statuses, user_ids, user_failures = await self._record_user_knowledge(event)
            statuses.extend(user_statuses)
            knowledge_ids.extend(user_ids)
            failures.extend(user_failures)

        return MemoryWriteReceipt(
            event_id=event.event_id,
            scope=event.scope,
            status=self._receipt_status(statuses),
            episode_ids=tuple(episode_ids),
            knowledge_ids=tuple(knowledge_ids),
            failures=tuple(failures),
        )

    async def _record_tool_event(self, event: MemoryEvent) -> MemoryWriteReceipt:
        """Apply only cited runtime failures against the active delivered manifest."""
        ignored = MemoryWriteReceipt(event_id=event.event_id, scope=event.scope, status="ignored")
        if self.episodic is None or not event.evidence_refs:
            return ignored
        exposure_id = event.payload.get("exposure_id")
        attempt = event.payload.get("attempt")
        if not isinstance(exposure_id, str) or not isinstance(attempt, ToolAttempt):
            return ignored
        if exposure_id not in self._active_memory_exposures:
            return ignored
        exposure = self._memory_exposures.get(exposure_id)
        citation = self.episodic._citations.get(exposure_id)
        if exposure is None or citation is None:
            return ignored
        try:
            validate_citation(citation, exposure, scope=event.scope)
            signal = build_tool_signal(attempt, scope=event.scope, evidence_ref=event.evidence_refs[0])
        except ValueError:
            return ignored
        if signal is None or signal.outcome != "failure":
            return ignored

        try:
            receipts = await self.episodic.review(
                [ref.memory_id for ref in citation.refs],
                signal,
                namespace=citation.refs[0].namespace,
                exposure_id=exposure_id,
            )
        except ValueError:
            return ignored
        statuses = {receipt.status for receipt in receipts}
        if "applied" in statuses:
            status = "applied"
        elif statuses == {"duplicate"}:
            status = "duplicate"
        elif "storage_unavailable" in statuses:
            status = "storage_unavailable"
        elif statuses & {"conflict", "stale_revision"}:
            status = "conflict"
        else:
            status = "ignored"
        return MemoryWriteReceipt(
            event_id=event.event_id,
            scope=event.scope,
            status=status,
            review_ids=tuple(receipt.dedupe_key for receipt in receipts if receipt.status in {"applied", "duplicate"}),
            failures=tuple(
                receipt.reason or "review storage is unavailable"
                for receipt in receipts
                if receipt.status == "storage_unavailable"
            ),
        )

    @staticmethod
    def _delivered_memory_ref(delivered_ref: str, scope: MemoryRequestScope) -> MemoryRef | None:
        """Parse one assembler reference into a scoped episodic version."""
        try:
            source, identity_and_version = delivered_ref.split(":", 1)
            memory_id, content_version = identity_and_version.rsplit(":", 1)
        except ValueError:
            return None
        if source != "episodic" or not memory_id or not content_version:
            return None
        namespace = MemoryNamespace(
            tenant_id=scope.tenant_id,
            agent_id=scope.agent_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
            room_id=scope.room_id,
            crew_id=scope.crew_id,
            model_id=scope.model_id,
        )
        return MemoryRef(
            namespace=namespace,
            kind="episode",
            memory_id=memory_id,
            content_version=content_version,
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
                await self._record_episodic(query, response, tool_calls, user_id, session_id)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("record_interaction: episodic recording failed — %s", exc)

    # ------------------------------------------------------------------
    # Private retrieval helpers
    # ------------------------------------------------------------------

    async def _get_episodic_warnings(self, query: str) -> str:
        """Retrieve failure warnings from episodic store.

        When a ``cross_domain_router`` is configured, also retrieves warnings
        from relevant agent namespaces and appends them with a
        ``[cross-domain: <agent_id>]`` label.

        Cross-domain retrieval failures are caught and logged at WARNING level
        without breaking the main retrieval path.

        Returns empty string when episodic store is ``None`` or on error.
        """
        if self.episodic is None:
            return ""

        # Primary episodic warnings for current namespace
        try:
            local_warnings = await self.episodic.get_failure_warnings(
                namespace=self.namespace,
                current_query=query,
                max_warnings=self.config.episodic_max_warnings,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Episodic retrieval failed: %s", exc)
            return ""

        # Cross-domain routing (optional, never blocks main flow)
        if self._cross_domain_router is None:
            return local_warnings

        cross_domain_parts: list[str] = []
        try:
            embedding_provider = getattr(self.episodic, "_embedding", None)
            if embedding_provider is None:
                return local_warnings

            query_embedding = await embedding_provider.embed(query)
            relevant_agents = await self._cross_domain_router.find_relevant_agents(
                query_embedding=query_embedding,
                current_agent_id=self.namespace.agent_id,
                embedding_provider=embedding_provider,
                tenant_id=self.namespace.tenant_id,
            )

            if relevant_agents:
                cross_ns_tasks = [
                    self.episodic.get_failure_warnings(
                        namespace=MemoryNamespace(
                            tenant_id=self.namespace.tenant_id,
                            agent_id=agent_id,
                        ),
                        current_query=query,
                        max_warnings=2,  # Limit cross-domain results
                    )
                    for agent_id in relevant_agents
                ]

                cross_results = await asyncio.gather(*cross_ns_tasks, return_exceptions=True)

                for agent_id, result in zip(relevant_agents, cross_results, strict=True):
                    if isinstance(result, Exception):
                        self.logger.warning(
                            "Cross-domain retrieval from %s failed: %s",
                            agent_id,
                            result,
                        )
                        continue
                    if result and isinstance(result, str):
                        cross_domain_parts.append(f"[cross-domain: {agent_id}]\n{result}")

        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Cross-domain routing failed: %s", exc)

        if cross_domain_parts:
            parts = [p for p in [local_warnings] + cross_domain_parts if p]
            return "\n\n".join(parts)

        return local_warnings

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

    async def _get_brain_knowledge(self, query: str) -> str:
        """Retrieve plain-text brain knowledge for the legacy text API.

        Args:
            query: Current user query.

        Returns:
            Packed brain-knowledge text, or ``""`` when unavailable.
        """
        if self.brain_service is None:
            return ""
        try:
            result = await self.brain_service.search(
                query,
                self.namespace.tenant_id,
                self.config.max_context_tokens,
            )
            return result if isinstance(result, str) else ""
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Brain retrieval failed: %s", exc)
            return ""

    async def _get_episodic_candidates(
        self,
        query: str,
        scope: MemoryRequestScope,
    ) -> list[MemoryCandidate]:
        """Retrieve scoped experiential candidates without mutating manager state."""
        if not self.config.enable_episodic or self.episodic is None:
            return []
        try:
            episodes = await self.episodic.recall_similar(
                query=query,
                namespace=self._namespace_for_scope(scope),
                top_k=self.config.episodic_max_warnings,
                include_failures_only=True,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Episodic candidate retrieval failed: %s", type(exc).__name__)
            return []

        candidates: list[MemoryCandidate] = []
        for episode in episodes:
            text = episode.searchable_text()
            if not text:
                continue
            score = episode.ranking_score if episode.ranking_score is not None else episode.score
            candidates.append(
                MemoryCandidate(
                    scope=scope,
                    memory_id=episode.episode_id,
                    content_version="v1",
                    source="episodic",
                    text=text,
                    relevance=min(max(score, 0.0), 1.0),
                    similarity=min(max(episode.score, 0.0), 1.0),
                    ranking_score=score,
                    candidate_type="episodic",
                    importance=episode.importance,
                )
            )
        return candidates

    async def _get_skill_candidates(self, query: str, scope: MemoryRequestScope) -> list[MemoryCandidate]:
        """Return the formatted skill result as one non-experiential candidate."""
        if not self.config.enable_skills:
            return []
        text = await self._get_relevant_skills(query)
        if not text:
            return []
        return [
            MemoryCandidate(
                scope=scope,
                memory_id=self._text_id("skill", query),
                content_version="text-v1",
                source="skill",
                text=text,
                relevance=1.0,
                candidate_type="skill",
            )
        ]

    async def _get_user_candidates(self, query: str, scope: MemoryRequestScope) -> list[MemoryCandidate]:
        """Retrieve active user knowledge independently of episodic capability."""
        if not self.config.enable_user_memory or self.user_memory_store is None or scope.user_id is None:
            return []
        try:
            knowledge = await self.user_memory_store.recall(query, scope=scope)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("User knowledge retrieval failed: %s", type(exc).__name__)
            return []
        return [self._user_candidate(item, scope) for item in knowledge]

    async def _get_brain_candidates(self, query: str, scope: MemoryRequestScope) -> list[MemoryCandidate]:
        """Retrieve tenant-bound plain-text brain context without a page reference."""
        if not self.config.enable_brain or self.brain_service is None:
            return []
        try:
            text = await self.brain_service.search(query, scope.tenant_id, self.config.max_context_tokens)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Brain candidate retrieval failed: %s", type(exc).__name__)
            return []
        if not isinstance(text, str) or not text:
            return []
        return [
            MemoryCandidate(
                scope=scope,
                memory_id=self._text_id("brain", query),
                content_version="text-only",
                source="brain_text",
                text=text,
                relevance=1.0,
                candidate_type="brain",
            )
        ]

    async def _record_response_event(self, event: MemoryEvent) -> Any:
        """Persist one unverified response as a PARTIAL query-resolution episode."""
        query = self._event_text(event.payload, "query", "user_message", "prompt")
        response = self._event_text(event.payload, "response", "response_text", "assistant_message")
        return await self.episodic.record_episode(  # type: ignore[union-attr]
            episode_id=self._response_episode_id(event.event_id),
            namespace=self._namespace_for_scope(event.scope),
            situation=query[:500],
            action_taken=f"Responded: {response}",
            outcome=EpisodeOutcome.PARTIAL,
            category=EpisodeCategory.QUERY_RESOLUTION,
        )

    async def _record_user_knowledge(self, event: MemoryEvent) -> tuple[list[str], list[str], list[str]]:
        """Extract and persist scoped user knowledge, retaining each durable result."""
        if not self.config.enable_user_memory or self.user_memory_store is None or self.extraction_client is None:
            return [], [], []
        try:
            client = self.extraction_client
            if hasattr(client, "__aenter__"):
                # Bots enter their client before every call (it initializes the provider session).
                async with client as entered:
                    candidates = await extract_user_knowledge(event, client=entered)
            else:
                candidates = await extract_user_knowledge(event, client=client)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("User knowledge extraction failed: %s", type(exc).__name__)
            return ["storage_unavailable"], [], [f"user_extraction:{type(exc).__name__}"]

        statuses: list[str] = []
        knowledge_ids: list[str] = []
        failures: list[str] = []
        for index, candidate in enumerate(candidates):
            command = UserKnowledgeCommand(
                event_id=self._candidate_event_id(event.event_id, index),
                candidate=candidate,
                evidence_refs=event.evidence_refs,
            )
            try:
                receipt: UserMemoryReceipt = await self.user_memory_store.upsert(command, scope=event.scope)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("User knowledge persistence failed: %s", type(exc).__name__)
                statuses.append("storage_unavailable")
                failures.append(f"user_memory:{type(exc).__name__}")
                continue
            statuses.append(receipt.status)
            if receipt.knowledge_id is not None:
                knowledge_ids.append(receipt.knowledge_id)
        return statuses, knowledge_ids, failures

    @staticmethod
    def _namespace_for_scope(scope: MemoryRequestScope) -> MemoryNamespace:
        """Build a per-request episodic namespace without changing ``self.namespace``."""
        return MemoryNamespace(
            tenant_id=scope.tenant_id,
            agent_id=scope.agent_id,
            model_id=scope.model_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
            room_id=scope.room_id,
            crew_id=scope.crew_id,
        )

    @staticmethod
    def _response_episode_id(event_id: str) -> str:
        """Derive a stable episode ID from the response event so a retried turn is written once (spec F3)."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"parrot:agent-memory:response-episode:{event_id}"))

    @staticmethod
    def _event_text(payload: dict[str, Any], *keys: str) -> str:
        """Return the first textual payload value from trusted event data."""
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str):
                return value
        return ""

    @staticmethod
    def _candidate_event_id(event_id: str, index: int) -> str:
        """Derive a bounded, deterministic store event identity per extracted claim."""
        material = f"{event_id}\x00{index}".encode("utf-8")
        return f"knowledge-{hashlib.sha256(material).hexdigest()}"

    @staticmethod
    def _text_id(kind: str, text: str) -> str:
        """Return a stable identifier for non-versioned contextual text."""
        return f"{kind}-{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _receipt_status(statuses: list[str]) -> str:
        """Summarize component receipts without claiming success after a failed write."""
        if "applied" in statuses:
            return "applied"
        if "duplicate" in statuses:
            return "duplicate"
        if "conflict" in statuses:
            return "conflict"
        if "storage_unavailable" in statuses:
            return "storage_unavailable"
        return "ignored"

    @staticmethod
    def _user_candidate(knowledge: UserKnowledge, scope: MemoryRequestScope) -> MemoryCandidate:
        """Translate a durable user fact into a contextual candidate."""
        value = json.dumps(knowledge.value, ensure_ascii=False, sort_keys=True)
        return MemoryCandidate(
            scope=scope,
            memory_id=knowledge.knowledge_id,
            content_version=str(knowledge.revision),
            source="user_memory",
            text=f"{knowledge.kind}: {value}",
            relevance=1.0,
            candidate_type="user",
        )

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
            room_id=self.namespace.room_id,
            crew_id=self.namespace.crew_id,
        )
        response_text = response if isinstance(response, str) else getattr(response, "content", str(response))
        if not isinstance(response_text, str):
            response_text = str(response_text)
        # ``tool_calls`` is accepted for signature compatibility only: tool calls
        # are not proof of success and their own hooks record tool episodes
        # (FEAT-571 M0). A conversation turn has no verified outcome here, so it
        # is recorded as PARTIAL and no memory review is emitted.
        self.logger.debug(
            "_record_episodic: recording query episode for %s/%s (tool_calls=%d ignored)",
            user_id,
            session_id,
            len(tool_calls or []),
        )
        await self.episodic.record_episode(  # type: ignore[union-attr]
            namespace=ns,
            situation=query[:500],
            action_taken=f"Responded: {response_text}",
            outcome=EpisodeOutcome.PARTIAL,
            category=EpisodeCategory.QUERY_RESOLUTION,
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
                ("user_memory", self.user_memory_store),
            ]
            if obj is not None
        ]
