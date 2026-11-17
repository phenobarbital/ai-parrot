"""Context assembler for unified memory — priority-based token budgeting.

Assembles context from multiple memory subsystems (episodic, skills,
conversation) while respecting a configurable token budget.
"""

from __future__ import annotations

import hashlib
import logging

from parrot.memory.agent_memory.models import MemoryRequestScope

from .models import MemoryCandidate, MemoryConfig, MemoryContext
from parrot.memory.dynamics.models import MemoryRef

logger = logging.getLogger(__name__)

_HEADROOM = 0.9  # keep 10% buffer below max_tokens


class ContextAssembler:
    """Assembles context from multiple sources within a token budget.

    Priority order (highest first):
    1. Episodic failure warnings — critical for avoiding past mistakes
    2. Relevant skills — applicable knowledge
    3. Conversation history — recent turns (truncated from oldest)

    Each section gets a weight-based allocation from the total budget.
    Unused budget from empty sections rolls forward to the next priority.

    Args:
        config: Optional MemoryConfig; defaults to MemoryConfig() if omitted.

    Example:
        assembler = ContextAssembler(MemoryConfig(max_context_tokens=2000))
        ctx = assembler.assemble(
            episodic_warnings="Don't call X without auth",
            relevant_skills="Use get_schema tool",
            conversation="User: hello\\nAssistant: hi",
        )
        print(ctx.tokens_used)
    """

    def __init__(self, config: MemoryConfig | None = None) -> None:
        self.config = config or MemoryConfig()
        self._max_tokens = int(self.config.max_context_tokens * _HEADROOM)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assemble(
        self,
        episodic_warnings: str = "",
        relevant_skills: str = "",
        conversation: str = "",
        semantic_knowledge: str = "",
    ) -> MemoryContext:
        """Assemble context respecting token budget.

        Sections are filled in priority order.  Any budget left over from an
        empty (or smaller-than-allocation) section is carried forward and
        added to the remaining sections' budgets proportionally.

        Args:
            episodic_warnings: Past failure lessons from episodic memory.
            relevant_skills: Applicable skills from the skill registry.
            conversation: Recent conversation turns.
            semantic_knowledge: Distilled long-term knowledge from the
                agent's brain wiki (FEAT-390); budgeted at
                ``config.brain_weight``. Empty by default, so 3-argument
                call sites behave exactly as before.

        Returns:
            MemoryContext with filled sections and accurate token accounting.
        """
        if not episodic_warnings and not relevant_skills and not conversation and not semantic_knowledge:
            logger.debug("ContextAssembler: all inputs empty, returning empty context")
            return MemoryContext(tokens_budget=self.config.max_context_tokens)

        budget = self._max_tokens
        cfg = self.config

        # --- Priority 1: episodic warnings ---
        episodic_budget = int(budget * cfg.episodic_weight)
        filled_episodic, episodic_tokens = self._fill_section(episodic_warnings, episodic_budget)
        rollover = episodic_budget - episodic_tokens

        # --- Priority 2: relevant skills (gets episodic rollover) ---
        skills_budget = int(budget * cfg.skill_weight) + rollover
        filled_skills, skills_tokens = self._fill_section(relevant_skills, skills_budget)
        rollover = skills_budget - skills_tokens

        # --- Priority 3: brain knowledge (gets skills rollover) ---
        brain_budget = int(budget * cfg.brain_weight) + rollover
        filled_brain, brain_tokens = self._fill_section(semantic_knowledge, brain_budget)

        # --- Priority 4: conversation (gets whatever's left) ---
        conv_budget = budget - episodic_tokens - skills_tokens - brain_tokens
        filled_conv, conv_tokens = self._fill_conversation(conversation, conv_budget)

        total_tokens = episodic_tokens + skills_tokens + brain_tokens + conv_tokens

        logger.debug(
            "ContextAssembler: assembled %d tokens " "(episodic=%d, skills=%d, brain=%d, conv=%d, budget=%d)",
            total_tokens,
            episodic_tokens,
            skills_tokens,
            brain_tokens,
            conv_tokens,
            self._max_tokens,
        )

        return MemoryContext(
            episodic_warnings=filled_episodic,
            relevant_skills=filled_skills,
            conversation_summary=filled_conv,
            semantic_knowledge=filled_brain,
            tokens_used=total_tokens,
            tokens_budget=self.config.max_context_tokens,
        )

    def assemble_candidates(
        self,
        candidates: list[MemoryCandidate],
        *,
        scope: MemoryRequestScope,
    ) -> MemoryContext:
        """Pack complete scoped candidate blocks into one bounded context.

        Candidate scope is checked before any budget or ordering decision.  A
        candidate is either included in full or omitted; references are added
        only after its complete text has been accepted into the packed
        section.  The digest covers the final formatted context that callers
        deliver to the model.

        Args:
            candidates: Retrieved, typed supplementary memory candidates.
            scope: Trusted runtime scope that candidates must match exactly.

        Returns:
            A ``MemoryContext`` containing only complete, in-scope blocks.
        """
        section_candidates: dict[str, list[MemoryCandidate]] = {
            "episodic": [],
            "skills": [],
            "brain": [],
            "user_knowledge": [],
        }
        section_for_type = {
            "episodic": "episodic",
            "skill": "skills",
            "brain": "brain",
            "user": "user_knowledge",
        }
        user_sources = {"user", "user_memory", "user_knowledge"}

        for candidate in candidates:
            if candidate.scope != scope or not candidate.text:
                continue
            section = (
                "user_knowledge" if candidate.source in user_sources else section_for_type[candidate.candidate_type]
            )
            if section == "user_knowledge" and scope.user_id is None:
                continue
            if section not in self.config.normalized_section_weights:
                continue
            section_candidates[section].append(candidate)

        for section, items in section_candidates.items():
            items.sort(
                key=lambda candidate: (
                    -(
                        candidate.relevance
                        if section == "user_knowledge" or candidate.ranking_score is None
                        else candidate.ranking_score
                    ),
                    candidate.memory_id,
                    candidate.content_version,
                    candidate.source,
                )
            )

        weights = self.config.normalized_section_weights
        budget = self._max_tokens
        rollover = 0
        packed_sections: dict[str, str] = {}
        accepted_candidates: dict[str, list[MemoryCandidate]] = {
            "episodic": [],
            "skills": [],
            "brain": [],
            "user_knowledge": [],
        }
        tokens_used = 0

        def pack_section(section: str, section_budget: int) -> int:
            """Pack complete candidates into one section budget."""
            if section_budget <= 0:
                packed_sections[section] = ""
                return 0

            section_text = ""
            for candidate in section_candidates[section]:
                proposed = candidate.text if not section_text else f"{section_text}\n{candidate.text}"
                if self._estimate_tokens(proposed) > section_budget:
                    continue
                section_text = proposed
                accepted_candidates[section].append(candidate)
            packed_sections[section] = section_text
            return self._estimate_tokens(section_text)

        def pack_episodic(section_budget: int) -> int:
            """Pack warning and recall lanes into one shared episodic budget."""
            if section_budget <= 0:
                packed_sections["episodic_warnings"] = ""
                packed_sections["episodic_recall"] = ""
                return 0

            warning_candidates = [
                candidate for candidate in section_candidates["episodic"] if candidate.lane == "warning"
            ]
            recall_candidates = [
                candidate for candidate in section_candidates["episodic"] if candidate.lane == "recall"
            ]
            ordered_candidates = warning_candidates + recall_candidates
            warning_text = ""
            recall_text = ""

            for candidate in ordered_candidates:
                lane_text = warning_text if candidate.lane == "warning" else recall_text
                proposed_lane = candidate.text if not lane_text else f"{lane_text}\n{candidate.text}"
                proposed_warning = proposed_lane if candidate.lane == "warning" else warning_text
                proposed_recall = proposed_lane if candidate.lane == "recall" else recall_text
                combined = "\n".join(text for text in (proposed_warning, proposed_recall) if text)
                if self._estimate_tokens(combined) > section_budget:
                    continue
                if candidate.lane == "warning":
                    warning_text = proposed_lane
                else:
                    recall_text = proposed_lane
                accepted_candidates["episodic"].append(candidate)

            packed_sections["episodic_warnings"] = warning_text
            packed_sections["episodic_recall"] = recall_text
            return self._estimate_tokens("\n".join(text for text in (warning_text, recall_text) if text))

        def pack_with_budget(section: str, section_budget: int) -> int:
            """Pack a section, using the shared episodic lane budget when needed."""
            if section == "episodic":
                return pack_episodic(section_budget)
            return pack_section(section, section_budget)

        if self.config.user_priority == "high" and "user_knowledge" in weights:
            user_cap = self.config.user_context_tokens
            if user_cap is None:
                user_cap = int(budget * weights["user_knowledge"])
            user_budget = min(user_cap, budget)
            user_tokens = pack_with_budget("user_knowledge", user_budget)
            tokens_used += user_tokens

        sections = (
            ("episodic", "skills", "brain")
            if self.config.user_priority == "high"
            else (
                "episodic",
                "skills",
                "brain",
                "user_knowledge",
            )
        )
        for section in sections:
            if section not in weights:
                continue
            section_budget = int(budget * weights[section]) + rollover
            section_budget = min(section_budget, budget - tokens_used)
            if section == "user_knowledge" and self.config.user_context_tokens is not None:
                section_budget = min(section_budget, self.config.user_context_tokens)
            section_tokens = pack_with_budget(section, section_budget)
            tokens_used += section_tokens
            rollover = section_budget - section_tokens

        ordered_sections = ("episodic", "skills", "brain", "user_knowledge")
        delivered_refs = [
            self._candidate_ref(candidate) for section in ordered_sections for candidate in accepted_candidates[section]
        ]
        memory_refs: list[MemoryRef] = [
            candidate.memory_ref
            for section in ordered_sections
            for candidate in accepted_candidates[section]
            if candidate.memory_ref is not None
        ]

        context = MemoryContext(
            episodic_warnings=packed_sections.get("episodic_warnings", ""),
            episodic_recall=packed_sections.get("episodic_recall", ""),
            relevant_skills=packed_sections.get("skills", ""),
            semantic_knowledge=packed_sections.get("brain", ""),
            user_knowledge=packed_sections.get("user_knowledge", ""),
            tokens_used=tokens_used,
            tokens_budget=self.config.max_context_tokens,
            delivered_refs=tuple(delivered_refs),
            memory_refs=tuple(memory_refs),
        )
        packed_text = context.to_prompt_string()
        if not packed_text:
            return context
        return context.model_copy(update={"packed_digest": hashlib.sha256(packed_text.encode("utf-8")).hexdigest()})

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Approximate token count using chars / 4 heuristic.

        Args:
            text: Input string to estimate.

        Returns:
            Estimated token count (integer).
        """
        return len(text) // 4

    @staticmethod
    def _candidate_ref(candidate: MemoryCandidate) -> str:
        """Return a stable source, identity and version reference."""
        return f"{candidate.source}:{candidate.memory_id}:{candidate.content_version}"

    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """Truncate *text* so it fits within *max_tokens*.

        Truncation happens from the end (tail dropped) and a trailing
        ellipsis is appended to signal that content was removed.

        Args:
            text: The text to truncate.
            max_tokens: Maximum allowed tokens.

        Returns:
            Possibly-truncated string.
        """
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3] + "..."

    def _fill_section(self, text: str, budget: int) -> tuple[str, int]:
        """Fill a single section within *budget* tokens.

        Args:
            text: Raw section text (may be empty).
            budget: Maximum tokens this section may use.

        Returns:
            Tuple of (filled_text, tokens_used).
        """
        if not text or budget <= 0:
            return "", 0
        truncated = self._truncate_to_tokens(text, budget)
        return truncated, self._estimate_tokens(truncated)

    def _fill_conversation(self, text: str, budget: int) -> tuple[str, int]:
        """Fill conversation section, dropping *oldest* turns first.

        Conversation is split by newlines.  When the full text exceeds
        budget, lines are dropped from the top (oldest) until it fits.

        Args:
            text: Full conversation history as newline-separated turns.
            budget: Maximum tokens this section may use.

        Returns:
            Tuple of (filled_text, tokens_used).
        """
        if not text or budget <= 0:
            return "", 0

        if self._estimate_tokens(text) <= budget:
            return text, self._estimate_tokens(text)

        # Drop oldest lines until within budget
        lines = text.split("\n")
        while lines and self._estimate_tokens("\n".join(lines)) > budget:
            lines.pop(0)

        result = "\n".join(lines)
        return result, self._estimate_tokens(result)
