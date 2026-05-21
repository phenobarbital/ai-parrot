"""Escalation intent detector for HITL multi-tier escalation.

Detects when a user's free-text response is a request to be escalated
to a human operator (e.g. "I need a human", "pasame con un humano").

Strategy (§3 C5 of the FEAT-194 spec):
1. Regex match against a seed phrase list.
2. Optional LLM confirmation via Groq Haiku when regex is ambiguous and
   ``llm_client`` is provided (inline await, ``llm_timeout_seconds``
   default = 1.5 s; any failure → return False).

Pure helper module — no side effects, no global state.

FEAT-194 — TASK-1278
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Any, List, Optional


class RejectIntentDetector:
    """Detects escalation intent from free-text user responses.

    Usage::

        detector = RejectIntentDetector()
        if await detector.is_escalation_intent("I need a human"):
            ...

    Args:
        regex_phrases: Override the default phrase list (list of regex strings).
            When provided, REPLACES (not extends) the defaults.
        llm_client: Optional async callable used as LLM fallback.  It is
            invoked as ``await llm_client(text) -> bool`` for short texts
            (< 80 chars) that do not match regex.  When ``None`` (default),
            the LLM fallback is disabled.
        llm_timeout_seconds: Maximum wait for the LLM response before
            returning ``False`` (default 1.5 s).
    """

    # ------------------------------------------------------------------
    # Default phrase banks (regex, IGNORECASE applied at compile time)
    # ------------------------------------------------------------------

    _DEFAULT_REGEX_PHRASES_ES: List[str] = [
        r"\bpasame con (un )?humano\b",
        r"\bnecesito (un )?humano\b",
        r"\bquiero hablar con (un )?humano\b",
        r"\bescalar\b",
        r"\batencion humana\b",
        r"\bayuda humana\b",
        r"\bhablar con soporte\b",
        r"\besto no me (sirve|ayuda)\b",
        r"\bno entiendo[,.]? pasame\b",
    ]

    _DEFAULT_REGEX_PHRASES_EN: List[str] = [
        r"\b(i )?need (a )?human\b",
        r"\btalk to (a )?human\b",
        r"\bspeak (with|to) (an? )?(human|agent)\b",
        r"\b(please )?escalate( this)?\b",
        r"\blet me talk to support\b",
        r"\bhuman help\b",
        r"\blive agent( please)?\b",
        r"\bthis isn'?t helping\b",
    ]

    def __init__(
        self,
        *,
        regex_phrases: Optional[List[str]] = None,
        llm_client: Optional[Any] = None,
        llm_timeout_seconds: float = 1.5,
    ) -> None:
        phrases = regex_phrases or (
            self._DEFAULT_REGEX_PHRASES_ES + self._DEFAULT_REGEX_PHRASES_EN
        )
        self._pattern: re.Pattern = re.compile(
            "|".join(phrases), re.IGNORECASE
        )
        self._llm: Optional[Any] = llm_client
        self._llm_timeout: float = llm_timeout_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def is_escalation_intent(self, text: Any) -> bool:
        """Return True if *text* expresses a desire to escalate to a human.

        Algorithm:
        1. Normalise and lowercase.
        2. Regex match → return True on hit.
        3. If LLM client configured and text < 80 chars → LLM fallback
           with timeout.
        4. Return False on no match or timeout/error.

        Args:
            text: The user's response string (non-strings → False).

        Returns:
            True when escalation intent is detected, False otherwise.
        """
        if not isinstance(text, str) or not text.strip():
            return False

        # NFKD decomposes accented chars; strip combining marks to get ASCII-friendly base
        norm = "".join(
            c for c in unicodedata.normalize("NFKD", text)
            if unicodedata.category(c) != "Mn"
        ).lower()

        # Step 1: regex
        if self._pattern.search(norm):
            return True

        # Step 2: LLM fallback for short ambiguous inputs
        if self._llm is None or len(norm) > 80:
            return False

        try:
            return await asyncio.wait_for(
                self._llm_classify(norm), timeout=self._llm_timeout
            )
        except (asyncio.TimeoutError, Exception):
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _llm_classify(self, text: str) -> bool:
        """Ask the LLM whether *text* expresses escalation intent.

        The ``llm_client`` is expected to be an async callable that accepts
        the normalised text and returns a bool.  Callers are responsible for
        wiring a concrete implementation (e.g. a closure over a Groq client).

        Args:
            text: Normalised, lowercased user input (< 80 chars).

        Returns:
            True if the LLM classifies the text as an escalation request.
        """
        return bool(await self._llm(text))
