"""Reflection engine for episodic memory.

LLM-powered reflection with heuristic fallback. Analyzes agent interactions
and extracts actionable lessons to store alongside episodes.
"""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from .models import EpisodeOutcome, ReflectionResult

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient

logger = logging.getLogger(__name__)

REFLECTION_PROMPT = """Analyze this agent interaction episode and extract a concise lesson.

## Episode
- **Situation**: {situation}
- **Action taken**: {action_taken}
- **Outcome**: {outcome}
{error_section}

## Instructions
Respond with a JSON object containing exactly these three fields:
- "reflection": A brief analysis of what happened (1-2 sentences).
- "lesson_learned": A concise actionable lesson (max 100 characters).
- "suggested_action": What to do differently next time (1 sentence).

Respond ONLY with the JSON object, no markdown or extra text."""

# Heuristic patterns: (compiled regex, lesson_learned, suggested_action)
_HEURISTIC_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"not found|does not exist|no such|missing", re.IGNORECASE),
        "Verify resource exists before accessing",
        "Check existence or list available resources first.",
    ),
    (
        re.compile(r"timeout|timed out|deadline exceeded", re.IGNORECASE),
        "Consider reducing scope or adding timeout",
        "Use shorter timeouts and break large operations into chunks.",
    ),
    (
        re.compile(r"rate.?limit|429|too many requests|throttl", re.IGNORECASE),
        "Add delay between API calls",
        "Implement backoff or reduce request frequency.",
    ),
    (
        re.compile(r"permission|403|unauthorized|forbidden|access denied", re.IGNORECASE),
        "Check permissions before action",
        "Verify credentials and permissions before attempting the operation.",
    ),
    (
        re.compile(r"connection|refused|unreachable|network|ECONNREFUSED", re.IGNORECASE),
        "Verify service availability before calling",
        "Check service health or connectivity before making requests.",
    ),
    (
        re.compile(r"invalid|malformed|bad request|400|validation", re.IGNORECASE),
        "Validate input format before sending",
        "Check input against expected schema before the API call.",
    ),
    (
        re.compile(r"out of memory|OOM|memory", re.IGNORECASE),
        "Reduce data size or batch processing",
        "Process data in smaller batches to avoid memory issues.",
    ),
]


class ReflectionEngine:
    """LLM-powered reflection engine with heuristic fallback.

    When an LLM client is available, uses structured prompting to generate
    reflections. Falls back to pattern-matching heuristics when the LLM
    is unavailable or fails.

    Args:
        llm_client: Optional AbstractClient instance for LLM-powered reflection.
        llm_provider: Provider name (used for selecting model).
        model: Model identifier for reflection calls.
        fallback_to_heuristic: If True, use heuristic when LLM is unavailable or fails.
    """

    def __init__(
        self,
        llm_client: AbstractClient | None = None,
        llm_provider: str = "google",
        model: str = "gemini-2.5-flash",
        fallback_to_heuristic: bool = True,
    ) -> None:
        self._llm_client = llm_client
        self._llm_provider = llm_provider
        self._model = model
        self._fallback_to_heuristic = fallback_to_heuristic

    async def reflect(
        self,
        situation: str,
        action_taken: str,
        outcome: EpisodeOutcome | str,
        error_message: str | None = None,
    ) -> ReflectionResult:
        """Generate a reflection for an episode.

        Tries LLM first (if client available), then falls back to heuristics.

        Args:
            situation: What the agent was trying to do.
            action_taken: What action was executed.
            outcome: The outcome of the action.
            error_message: Error message if the outcome was a failure.

        Returns:
            ReflectionResult with reflection, lesson_learned, and suggested_action.
        """
        outcome_str = outcome.value if isinstance(outcome, EpisodeOutcome) else outcome

        # Try LLM reflection first
        if self._llm_client is not None:
            try:
                return await self._llm_reflect(
                    situation, action_taken, outcome_str, error_message
                )
            except Exception as e:
                logger.warning(
                    "LLM reflection failed: %s. %s",
                    e,
                    "Falling back to heuristic." if self._fallback_to_heuristic else "No fallback.",
                )
                if not self._fallback_to_heuristic:
                    raise

        # Heuristic fallback
        if self._fallback_to_heuristic:
            return self._heuristic_reflect(
                situation, action_taken, outcome_str, error_message
            )

        raise RuntimeError(
            "No LLM client configured and heuristic fallback is disabled."
        )

    async def _llm_reflect(
        self,
        situation: str,
        action_taken: str,
        outcome: str,
        error_message: str | None,
    ) -> ReflectionResult:
        """Generate reflection via LLM call."""
        error_section = ""
        if error_message:
            error_section = f"- **Error**: {error_message}"

        prompt = REFLECTION_PROMPT.format(
            situation=situation,
            action_taken=action_taken,
            outcome=outcome,
            error_section=error_section,
        )

        response = await self._llm_client.ask(
            prompt=prompt,
            model=self._model,
            max_tokens=512,
            temperature=0.3,
            structured_output=ReflectionResult,
        )

        # Extract content from MessageResponse
        content = response.get("content", [])
        if not content:
            raise ValueError("Empty LLM response for reflection")

        text = ""
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                break
            elif isinstance(block, str):
                text = block
                break

        # If structured_output returned a parsed object directly
        if isinstance(content, ReflectionResult):
            return content

        # Parse the JSON response
        try:
            data = json.loads(text)
            return ReflectionResult(**data)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            raise ValueError(f"Failed to parse LLM reflection response: {e}") from e

    @staticmethod
    def _heuristic_reflect(
        situation: str,
        action_taken: str,
        outcome: str,
        error_message: str | None,
    ) -> ReflectionResult:
        """Generate reflection using pattern-matching heuristics.

        Matches error messages against known patterns to produce
        actionable lessons without requiring an LLM call.
        """
        is_failure = outcome in (
            EpisodeOutcome.FAILURE.value,
            EpisodeOutcome.TIMEOUT.value,
        )

        if is_failure and error_message:
            # Match against known error patterns
            for pattern, lesson, suggestion in _HEURISTIC_PATTERNS:
                if pattern.search(error_message):
                    return ReflectionResult(
                        reflection=f"Action failed with error: {error_message[:200]}",
                        lesson_learned=lesson,
                        suggested_action=suggestion,
                    )

            # Default failure reflection
            return ReflectionResult(
                reflection=f"Action '{action_taken[:100]}' failed: {error_message[:200]}",
                lesson_learned="Review approach and consider alternatives",
                suggested_action="Analyze the error and try a different strategy.",
            )

        if is_failure:
            return ReflectionResult(
                reflection=f"Action '{action_taken[:100]}' did not succeed.",
                lesson_learned="Review approach and consider alternatives",
                suggested_action="Investigate why the action failed and try a different approach.",
            )

        if outcome == EpisodeOutcome.PARTIAL.value:
            return ReflectionResult(
                reflection=f"Action '{action_taken[:100]}' partially succeeded.",
                lesson_learned="Partial success; refine approach",
                suggested_action="Identify what worked and what didn't to improve the approach.",
            )

        # Success
        return ReflectionResult(
            reflection=f"Action '{action_taken[:100]}' succeeded for: {situation[:100]}",
            lesson_learned="Approach worked; remember this pattern",
            suggested_action="Reuse this approach for similar situations.",
        )
