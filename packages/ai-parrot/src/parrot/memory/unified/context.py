"""Context assembler for unified memory — priority-based token budgeting.

Assembles context from multiple memory subsystems (episodic, skills,
conversation) while respecting a configurable token budget.
"""
from __future__ import annotations

import logging

from .models import MemoryConfig, MemoryContext

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
    ) -> MemoryContext:
        """Assemble context respecting token budget.

        Sections are filled in priority order.  Any budget left over from an
        empty (or smaller-than-allocation) section is carried forward and
        added to the remaining sections' budgets proportionally.

        Args:
            episodic_warnings: Past failure lessons from episodic memory.
            relevant_skills: Applicable skills from the skill registry.
            conversation: Recent conversation turns.

        Returns:
            MemoryContext with filled sections and accurate token accounting.
        """
        if not episodic_warnings and not relevant_skills and not conversation:
            logger.debug("ContextAssembler: all inputs empty, returning empty context")
            return MemoryContext(tokens_budget=self.config.max_context_tokens)

        budget = self._max_tokens
        cfg = self.config

        # --- Priority 1: episodic warnings ---
        episodic_budget = int(budget * cfg.episodic_weight)
        filled_episodic, episodic_tokens = self._fill_section(
            episodic_warnings, episodic_budget
        )
        rollover = episodic_budget - episodic_tokens

        # --- Priority 2: relevant skills (gets episodic rollover) ---
        skills_budget = int(budget * cfg.skill_weight) + rollover
        filled_skills, skills_tokens = self._fill_section(
            relevant_skills, skills_budget
        )
        rollover = skills_budget - skills_tokens

        # --- Priority 3: conversation (gets remaining rollover) ---
        conv_budget = budget - episodic_budget - int(budget * cfg.skill_weight) + rollover
        # Simpler: whatever is left from the total after the first two sections
        conv_budget = budget - episodic_tokens - skills_tokens
        filled_conv, conv_tokens = self._fill_conversation(conversation, conv_budget)

        total_tokens = episodic_tokens + skills_tokens + conv_tokens

        logger.debug(
            "ContextAssembler: assembled %d tokens "
            "(episodic=%d, skills=%d, conv=%d, budget=%d)",
            total_tokens,
            episodic_tokens,
            skills_tokens,
            conv_tokens,
            self._max_tokens,
        )

        return MemoryContext(
            episodic_warnings=filled_episodic,
            relevant_skills=filled_skills,
            conversation_summary=filled_conv,
            tokens_used=total_tokens,
            tokens_budget=self.config.max_context_tokens,
        )

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
