"""LLM follow-up suggestion provider (FEAT-752) — one lightweight invoke() per answer."""

from __future__ import annotations

import time
from typing import Any, Final, Optional, Sequence

from navconfig.logging import logging

from parrot.models.responses import AIMessage
from parrot.models.suggestions import Suggestion, SuggestionBatch, SuggestionKind, SuggestionSource

from .protocol import SuggestionContext

logger = logging.getLogger(__name__)

SUGGESTION_PROMPT: Final[str] = (
    "You suggest at most {max_items} short follow-up questions a user might ask next, grounded ONLY on the "
    "exchange below.\nRules: each label ≤ 40 characters, each prompt is a complete question the assistant can "
    "answer with the same data\nor context, no duplicates of the original question, no presentation changes (those "
    "are offered separately), no\nactions. Respond with the structured schema only.\n\n"
    "Question: {question}\nAnswer (may be truncated): {answer_text}\n"
)


def _answer_text(response: AIMessage, limit: int) -> str:
    """``response.to_text`` truncated to ``limit`` characters (empty string on failure)."""
    try:
        text = response.to_text or ""
    except Exception:  # noqa: BLE001 — to_text must never break the lane
        text = ""
    return text[:limit]


class LLMSuggestionProvider:
    """lane="llm". Grounded follow-ups via ``bot.get_client()`` → ``invoke(output_type=SuggestionBatch)``."""

    name = "llm"
    lane = "llm"

    def __init__(
        self,
        bot: Any,
        *,
        max_items: int = 4,
        max_tokens: int = 256,
        answer_chars: int = 2000,
        temperature: float = 0.3,
        model: Optional[str] = None,
    ) -> None:
        self.bot = bot
        self.max_items = max_items
        self.max_tokens = max_tokens
        self.answer_chars = answer_chars
        self.temperature = temperature
        self.model = model  # Q2: None keeps AbstractClient._resolve_invoke_model's choice
        self._last_cost: Optional[dict[str, Any]] = None

    @property
    def last_cost(self) -> Optional[dict[str, Any]]:
        """Cost record of the most recent successful call, or None."""
        return self._last_cost

    async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]:
        """Ask the lightweight model for follow-ups; return ``[]`` on any failure (never raises)."""
        self._last_cost = None
        prompt = SUGGESTION_PROMPT.format(
            max_items=self.max_items,
            question=ctx.question,
            answer_text=_answer_text(ctx.response, self.answer_chars),
        )
        started = time.perf_counter()
        try:
            client = self.bot.get_client()
            async with client as entered:
                result = await entered.invoke(
                    prompt,
                    output_type=SuggestionBatch,
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
        except Exception as exc:  # noqa: BLE001 — never fail the answer
            logger.warning("LLM suggestion call failed: %s", exc)
            return []

        try:
            output = result.output
            if not isinstance(output, SuggestionBatch):
                output = SuggestionBatch.model_validate(output)
            chips = [
                Suggestion(
                    label=item.label,
                    prompt=item.prompt,
                    kind=SuggestionKind.FOLLOWUP,
                    source=SuggestionSource.LLM,
                    output_mode=None,
                    action=None,
                )
                for item in output.suggestions[: self.max_items]
            ]
            self._last_cost = {
                "model": result.model,
                "usage": result.usage.model_dump(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        except Exception as exc:  # noqa: BLE001 — a malformed batch must not break the answer
            logger.warning("LLM suggestion output rejected: %s", exc)
            self._last_cost = None
            return []
        return chips
