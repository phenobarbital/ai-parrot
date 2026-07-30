"""DreamCycleRunner — episodic -> wiki brain distillation pipeline (FEAT-390).

Implements the per-cycle pipeline described in
``sdd/specs/dream-cycle-brain-consolidation.spec.md`` §2 Overview:
collect -> cluster -> distill -> archive -> mark -> promote.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from ..episodic.models import EpisodicMemory, MemoryNamespace
from ..episodic.store import EpisodicMemoryStore
from .brain import BrainStore
from .models import DistilledKnowledge, DreamConfig, DreamCycleReport, DreamState

logger = logging.getLogger(__name__)

# Distill prompt: JSON-only contract, mirroring reflection.py's REFLECTION_PROMPT.
DISTILL_PROMPT = """Analyze these related agent episodes and distill ONE piece of durable knowledge.

## Episodes
{episodes_block}

## Instructions
Respond with a JSON object with exactly these fields:
- "title": short title (max 80 chars)
- "body": the distilled knowledge in markdown (what to remember and why)
- "category": one of "lesson", "decision", "concept", "note"
- "confidence": 0.0-1.0 — how well-supported this knowledge is by the episodes

Respond ONLY with the JSON object, no markdown or extra text."""

# Hard cap on distilled body length (spec §7 risk: distill hallucination).
_MAX_BODY_CHARS = 4000

# confidence below this threshold never masquerades as a learned rule.
_LOW_CONFIDENCE_THRESHOLD = 0.3


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Plain-Python cosine similarity between two equal-length vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine similarity in [-1, 1], or 0.0 when either vector has zero norm.
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


class DreamCycleRunner:
    """Runs one dream-cycle: collect, cluster, distill, archive, mark, promote.

    Attributes:
        logger: Standard module logger.

    Args:
        episodic_store: Source of episodes to consolidate.
        brain: Agent's per-agent brain wiki (``BrainStore``).
        namespace: Scoping dimensions for episode collection.
        llm_client: Optional ``AbstractClient`` for the distill LLM call;
            when ``None``, distillation falls back to a deterministic
            heuristic (concatenated lessons).
        org_brain: Optional org-level brain wiki for page promotion.
        config: Tunables; defaults to ``DreamConfig()``.
    """

    def __init__(
        self,
        episodic_store: EpisodicMemoryStore,
        brain: BrainStore,
        namespace: MemoryNamespace,
        llm_client: Any = None,
        org_brain: BrainStore | None = None,
        config: DreamConfig | None = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self._episodic_store = episodic_store
        self._brain = brain
        self._namespace = namespace
        self._llm_client = llm_client
        self._org_brain = org_brain
        self._config = config or DreamConfig()

    async def run_cycle(self, state: DreamState) -> DreamCycleReport:
        """Run one dream cycle, mutating ``state`` in place.

        Never raises: any unexpected failure results in an aborted report
        (``aborted=True``) with the watermark left unchanged.

        Args:
            state: Persisted scheduler/runner state (mutated in place).

        Returns:
            A structured report of what happened this cycle.
        """
        report = DreamCycleReport(started_at=datetime.now(UTC))
        try:
            episodes = await self._collect(state)
            report.episodes_collected = len(episodes)

            groups = await self._cluster(episodes)
            report.groups_formed = len(groups)
            groups_to_process = groups[: self._config.max_groups_per_cycle]

            newest_consolidated: datetime | None = None
            reinforced_this_cycle: set[str] = set()

            for group in groups_to_process:
                try:
                    distilled = await self._distill(group)
                except Exception as e:  # noqa: BLE001 - memory must never raise
                    report.groups_skipped += 1
                    self.logger.warning(
                        "Distill failed for a group of %d episode(s): %s",
                        len(group),
                        e,
                    )
                    continue

                category = distilled.category
                if distilled.confidence < _LOW_CONFIDENCE_THRESHOLD:
                    category = "note"
                body = distilled.body[:_MAX_BODY_CHARS]

                try:
                    result = await self._brain.remember(
                        body, title=distilled.title, category=category
                    )
                except Exception as e:  # noqa: BLE001 - abort clean, don't raise
                    report.aborted = True
                    report.abort_reason = f"archive failed: {e}"
                    report.finished_at = datetime.now(UTC)
                    self.logger.warning(
                        "Dream cycle aborted (archive failed): %s", e
                    )
                    return report

                page_id = result["page_id"]
                report.groups_distilled += 1
                report.pages_written.append(page_id)

                if page_id not in reinforced_this_cycle:
                    state.reinforcement_counts[page_id] = (
                        state.reinforcement_counts.get(page_id, 0) + 1
                    )
                    reinforced_this_cycle.add(page_id)

                episode_ids = [ep.episode_id for ep in group]
                await self._episodic_store.mark_consolidated(episode_ids, page_id)
                state.episodes_consolidated += len(episode_ids)

                group_newest = max(ep.created_at for ep in group)
                if newest_consolidated is None or group_newest > newest_consolidated:
                    newest_consolidated = group_newest

                if (
                    self._org_brain is not None
                    and state.reinforcement_counts.get(page_id, 0)
                    >= self._config.org_promotion_cycles
                    and page_id not in state.promoted_pages
                ):
                    try:
                        await self._brain.copy_page_to(page_id, self._org_brain)
                        state.promoted_pages.append(page_id)
                        report.pages_promoted.append(page_id)
                    except Exception as e:  # noqa: BLE001 - degrade, don't raise
                        self.logger.warning(
                            "Promotion of page %s failed: %s", page_id, e
                        )

            if newest_consolidated is not None:
                state.last_run = newest_consolidated
            state.cycles_completed += 1
            report.finished_at = datetime.now(UTC)
            return report

        except Exception as e:  # noqa: BLE001 - memory must never raise
            report.aborted = True
            report.abort_reason = str(e)
            report.finished_at = datetime.now(UTC)
            self.logger.warning("Dream cycle aborted: %s", e)
            return report

    async def _collect(self, state: DreamState) -> list[EpisodicMemory]:
        """Collect eligible, not-yet-consolidated episodes since the watermark.

        Sorted ascending by ``created_at`` so that group-cap deferral and
        the watermark-advance rule interact correctly: episodes deferred
        past the cap are always newer than the advanced watermark, so
        they are picked up again next cycle.

        Args:
            state: Current dream state (``last_run`` is the watermark).

        Returns:
            Eligible episodes, oldest first.
        """
        namespace_filter = self._namespace.build_filter()
        # Reach through EpisodicMemoryStore to its backend — the store has
        # no public get_recent() passthrough (per the Codebase Contract).
        backend = self._episodic_store._backend
        episodes = await backend.get_recent(
            namespace_filter=namespace_filter,
            limit=1000,
            since=state.last_run,
        )
        eligible = [
            ep
            for ep in episodes
            if (
                ep.importance >= self._config.importance_threshold
                or bool(ep.lesson_learned)
            )
            and "consolidated_into" not in ep.metadata
        ]
        eligible.sort(key=lambda ep: ep.created_at)
        return eligible

    async def _cluster(
        self, episodes: list[EpisodicMemory]
    ) -> list[list[EpisodicMemory]]:
        """Group episodes by embedding similarity, or by category+tools.

        Args:
            episodes: Eligible episodes (oldest first).

        Returns:
            List of episode groups, in the same relative order as input.
        """
        if not episodes:
            return []

        embedding_provider = getattr(self._episodic_store, "_embedding", None)
        if embedding_provider is not None:
            texts = [
                f"{ep.situation} {ep.lesson_learned or ''}".strip()
                for ep in episodes
            ]
            try:
                vectors = await embedding_provider.embed_batch(texts)
            except Exception as e:  # noqa: BLE001 - degrade to fallback grouping
                self.logger.warning(
                    "Embedding failed; falling back to category grouping: %s", e
                )
                return self._cluster_by_category(episodes)
            return self._cluster_by_embedding(episodes, vectors)

        return self._cluster_by_category(episodes)

    def _cluster_by_embedding(
        self,
        episodes: list[EpisodicMemory],
        vectors: list[list[float]],
    ) -> list[list[EpisodicMemory]]:
        """Greedy single-pass clustering by cosine similarity.

        The first episode of a cluster is its centroid — no re-centering.

        Args:
            episodes: Episodes to cluster.
            vectors: Embedding vectors, aligned by index with ``episodes``.

        Returns:
            List of episode groups.
        """
        groups: list[list[EpisodicMemory]] = []
        centroids: list[list[float]] = []
        for episode, vector in zip(episodes, vectors):
            placed = False
            for i, centroid in enumerate(centroids):
                if (
                    _cosine_similarity(vector, centroid)
                    >= self._config.similarity_threshold
                ):
                    groups[i].append(episode)
                    placed = True
                    break
            if not placed:
                groups.append([episode])
                centroids.append(vector)
        return groups

    def _cluster_by_category(
        self, episodes: list[EpisodicMemory]
    ) -> list[list[EpisodicMemory]]:
        """Fallback grouping by ``(category, sorted related_tools)``.

        Args:
            episodes: Episodes to cluster.

        Returns:
            List of episode groups, in first-seen order.
        """
        buckets: dict[tuple[str, tuple[str, ...]], list[EpisodicMemory]] = {}
        order: list[tuple[str, tuple[str, ...]]] = []
        for episode in episodes:
            category = (
                episode.category.value
                if hasattr(episode.category, "value")
                else str(episode.category)
            )
            key = (category, tuple(sorted(episode.related_tools)))
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(episode)
        return [buckets[key] for key in order]

    async def _distill(
        self, group: list[EpisodicMemory]
    ) -> DistilledKnowledge:
        """Distill one group of episodes into a single piece of knowledge.

        Uses the configured LLM client when available (one call per
        group); falls back to a deterministic heuristic when no client
        is configured. LLM errors/malformed JSON propagate to the caller,
        which counts the group as skipped and retries it next cycle.

        Args:
            group: Episodes belonging to the same cluster.

        Returns:
            The distilled knowledge for this group.
        """
        if self._llm_client is None:
            return self._heuristic_distill(group)
        return await self._llm_distill(group)

    async def _llm_distill(
        self, group: list[EpisodicMemory]
    ) -> DistilledKnowledge:
        """One LLM call per group, following reflection.py's JSON-contract style.

        Args:
            group: Episodes belonging to the same cluster.

        Returns:
            The parsed ``DistilledKnowledge``.

        Raises:
            ValueError: If the response cannot be parsed into
                ``DistilledKnowledge``.
        """
        prompt = DISTILL_PROMPT.format(episodes_block=self._format_episodes(group))

        response = await self._llm_client.ask(
            prompt=prompt,
            model=self._config.distill_model,
            max_tokens=512,
            temperature=0.3,
            structured_output=DistilledKnowledge,
        )

        if isinstance(response, DistilledKnowledge):
            return response

        for attr in ("structured_output", "output", "data"):
            candidate = getattr(response, attr, None)
            if isinstance(candidate, DistilledKnowledge):
                return candidate
            if isinstance(candidate, dict):
                try:
                    return DistilledKnowledge(**candidate)
                except (TypeError, ValueError):
                    pass

        text = self._extract_text(response)
        if not text:
            raise ValueError("Empty LLM response for distill")

        try:
            data = json.loads(text)
            return DistilledKnowledge(**data)
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
            raise ValueError(f"Failed to parse LLM distill response: {e}") from e

    @staticmethod
    def _format_episodes(group: list[EpisodicMemory]) -> str:
        """Render a group of episodes as a block for the distill prompt."""
        lines = []
        for ep in group:
            lines.append(
                f"- Situation: {ep.situation}\n"
                f"  Action: {ep.action_taken}\n"
                f"  Lesson: {ep.lesson_learned or 'N/A'}"
            )
        return "\n".join(lines)

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Best-effort extraction of textual content from an LLM response.

        Same extraction idiom as ``ReflectionEngine._extract_text``.
        """
        if response is None:
            return ""
        if isinstance(response, str):
            return response

        to_text = getattr(response, "to_text", None)
        if isinstance(to_text, str) and to_text:
            return to_text
        resp_text = getattr(response, "response", None)
        if isinstance(resp_text, str) and resp_text:
            return resp_text

        if isinstance(response, dict):
            content = response.get("content", [])
            if isinstance(content, str):
                return content
            for block in content or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")
                if isinstance(block, str):
                    return block

        output = getattr(response, "output", None)
        if isinstance(output, str):
            return output
        return ""

    @staticmethod
    def _heuristic_distill(group: list[EpisodicMemory]) -> DistilledKnowledge:
        """Deterministic distillation without an LLM: concatenate lessons.

        Title is derived from the dominant category among the group.

        Args:
            group: Episodes belonging to the same cluster.

        Returns:
            A ``DistilledKnowledge`` built heuristically.
        """
        lessons = [ep.lesson_learned for ep in group if ep.lesson_learned]
        if lessons:
            body = "\n".join(f"- {lesson}" for lesson in lessons)
            category = "lesson"
        else:
            body = "\n".join(
                f"- {ep.situation}: {ep.action_taken}" for ep in group
            )
            category = "note"

        counts: dict[str, int] = {}
        for ep in group:
            cat = (
                ep.category.value
                if hasattr(ep.category, "value")
                else str(ep.category)
            )
            counts[cat] = counts.get(cat, 0) + 1
        dominant = max(counts, key=counts.get) if counts else "note"
        title = f"{dominant.replace('_', ' ').title()} pattern"[:80]

        return DistilledKnowledge(
            title=title,
            body=body[:_MAX_BODY_CHARS],
            category=category,
            confidence=0.5,
        )
