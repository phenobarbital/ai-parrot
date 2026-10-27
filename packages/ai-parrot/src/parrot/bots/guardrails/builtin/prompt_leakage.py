"""PromptLeakageGuardrail — system-prompt extraction attempts (INPUT) and disclosures (OUTPUT). FEAT-761.

OUTPUT detection is deterministic: canary -> word-shingle overlap ->
rapidfuzz segment alignment, against the turn's rendered system prompt in
``ctx.extras["system_prompt"]``. Streaming turns are checked on the final
message only (v1): chunks already sent cannot be retracted — reports carry
``stream_checked: "final_only"``.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from parrot.security.prompt_injection import SecurityEventLogger, ThreatLevel

from ..base import Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage
from .prompt_injection import PromptInjectionGuardrail

logger = logging.getLogger(__name__)

REDACTION_MARKER = "[redacted: system-prompt disclosure]"
_WORD = re.compile(r"\w+")
_WS = re.compile(r"\s+")


class LeakagePolicy(BaseModel):
    """Policy for :class:`PromptLeakageGuardrail` (registry dict config keys)."""

    ngram_size: int = Field(default=8, ge=3)
    min_prompt_shingles: int = Field(default=12, ge=1)
    shingle_hit_threshold: float = Field(default=0.12, gt=0.0, le=1.0)
    fuzzy_threshold: int = Field(default=85, ge=50, le=100)
    canary: str | None = None
    block_on_threat: bool = False
    strict_mode: bool = True


_EXTRACTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # English
        r"\brepeat\s+(all\s+)?(of\s+)?(the\s+)?(text|instructions|everything|words)\s+(above|before)",
        r"\b(print|show|reveal|output|display|dump|leak)\s+(me\s+)?(your|the)\s+(full\s+|entire\s+|exact\s+)?"
        r"(system\s+)?(prompt|instructions)(\s+verbatim)?",
        r"\bwhat\s+(were|are)\s+your\s+(initial|original|system|hidden|secret)\s+(instructions|prompt)",
        r"\bignore\s+.{0,40}\band\s+(print|show|reveal|output)\s+.{0,20}(prompt|instructions)",
        r"\b(copy|paste|quote)\s+(your|the)\s+(system\s+)?(prompt|instructions)",
        r"\bwhat\s+is\s+(written\s+)?(in\s+)?your\s+system\s+(prompt|message)",
        r"\btell\s+me\s+your\s+(system\s+)?(prompt|instructions)",
        r"\b(everything|text)\s+(above|before)\s+this\s+(line|message)\s+verbatim",
        # Spanish
        r"\brepite\s+(todo|tus\s+instrucciones|el\s+texto)\s+(anterior|de\s+arriba)",
        r"\b(mu[eé]stra|revela|imprime|ens[eé][nñ]a|dime)(me)?\s+(tu|el|las|tus)\s+"
        r"(prompt|mensaje|instrucciones)\s*(de\s+sistema|inicial(es)?|del\s+sistema|originales)?",
        r"\bcu[aá]les\s+son\s+tus\s+instrucciones\s+(iniciales|originales|de\s+sistema|del\s+sistema)",
        r"\bcu[aá]l\s+es\s+tu\s+(prompt|mensaje)\s+(de\s+sistema|del\s+sistema|inicial)",
        r"\b(copia|pega)\s+(tu|el)\s+(prompt|mensaje\s+de\s+sistema)",
        r"\bignora\s+.{0,40}\by\s+(muestra|revela|imprime)\s+.{0,20}(prompt|instrucciones)",
    )
)


@dataclass
class _LeakMatch:
    """Content-free result of the leak matcher."""

    canary_hit: bool = False
    shingle_hit_ratio: float = 0.0
    matched_segments: int = 0
    spans: list[tuple[int, int]] = field(default_factory=list)  # char spans in the ORIGINAL response

    @property
    def leaked(self) -> bool:
        """Whether any detection fired."""
        return self.canary_hit or bool(self.spans)


def _normalize(text: str) -> str:
    return _WS.sub(" ", text.lower()).strip()


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _detect_leak(prompt: str, response: str, policy: LeakagePolicy) -> _LeakMatch:
    """Pure deterministic matcher (algorithm in TASK-4836 Context, steps 1-4).

    Args:
        prompt: The rendered system prompt.
        response: The model response.
        policy: Thresholds.

    Returns:
        A content-free :class:`_LeakMatch`.
    """
    match = _LeakMatch()
    # 1. canary
    if policy.canary and _normalize(policy.canary) and _normalize(policy.canary) in _normalize(response):
        match.canary_hit = True

    # 2. tokens with offsets
    n = policy.ngram_size
    p_tokens = [m.group().lower() for m in _WORD.finditer(prompt)]
    r_matches = list(_WORD.finditer(response))
    r_tokens = [m.group().lower() for m in r_matches]

    # 3. shingles
    p_shingles = {tuple(p_tokens[i : i + n]) for i in range(len(p_tokens) - n + 1)}
    if len(p_shingles) < policy.min_prompt_shingles:
        return match
    spans: list[tuple[int, int]] = []
    hits: set[tuple[str, ...]] = set()
    for i in range(len(r_tokens) - n + 1):
        sh = tuple(r_tokens[i : i + n])
        if sh in p_shingles:
            hits.add(sh)
            spans.append((r_matches[i].start(), r_matches[i + n - 1].end()))
    match.shingle_hit_ratio = len(hits) / len(p_shingles)
    shingle_leak = match.shingle_hit_ratio >= policy.shingle_hit_threshold
    if shingle_leak:
        match.spans.extend(spans)

    # 4. fuzzy segments (lazy import)
    from rapidfuzz import fuzz

    seg_len = 3 * n
    r_lower = response.lower()
    for i in range(0, len(p_tokens), seg_len):
        segment = p_tokens[i : i + seg_len]
        if len(segment) < n:
            continue
        aln = fuzz.partial_ratio_alignment(" ".join(segment), r_lower, score_cutoff=policy.fuzzy_threshold)
        if aln is not None and aln.score >= policy.fuzzy_threshold:
            match.matched_segments += 1
            match.spans.append((aln.dest_start, aln.dest_end))

    match.spans = _merge(match.spans)
    return match


def _redact(response: str, spans: list[tuple[int, int]]) -> str:
    """Replace merged spans right-to-left with REDACTION_MARKER."""
    out = response
    for start, end in sorted(_merge(spans), reverse=True):
        out = out[:start] + REDACTION_MARKER + out[end:]
    return out


class PromptLeakageGuardrail(Guardrail):
    """System-prompt extraction (INPUT) and disclosure (OUTPUT) guardrail."""

    name = "prompt_leakage"
    stages: ClassVar[set] = {GuardrailStage.INPUT, GuardrailStage.OUTPUT}
    priority = {GuardrailStage.INPUT: 12, GuardrailStage.OUTPUT: 220}
    requires_system_prompt: ClassVar[bool] = True

    def __init__(self, **policy: Any) -> None:
        """Accept :class:`LeakagePolicy` fields as kwargs (registry dict config); unknown keys ignored."""
        known = {k: v for k, v in policy.items() if k in LeakagePolicy.model_fields}
        self.policy = LeakagePolicy(**known)
        self.on_error = "fail_closed" if self.policy.block_on_threat else "fail_open"
        self.logger = logging.getLogger(__name__)
        self._security_logger = SecurityEventLogger(logger=self.logger)

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        """Dispatch to INPUT heuristics or OUTPUT matcher; never puts text in reports/logs."""
        if ctx.extras.get("trusted_source", False) or not self.policy.strict_mode or not content:
            return GuardrailResult(action=GuardrailAction.PASS)
        if ctx.stage == GuardrailStage.INPUT:
            return await self._check_input(content, ctx)
        if ctx.stage == GuardrailStage.OUTPUT:
            return await self._check_output(content, ctx)
        return GuardrailResult(action=GuardrailAction.PASS)

    async def _check_input(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        if not any(p.search(content) for p in _EXTRACTION_PATTERNS):
            return GuardrailResult(action=GuardrailAction.PASS)
        threats = [
            {
                "type": "prompt_leakage",
                "level": ThreatLevel.HIGH,
                "pattern": "extraction-heuristic",
                "description": "System prompt extraction attempt",
            }
        ]
        await self._security_logger.log_security_category_event(
            category="prompt_leakage",
            severity=ThreatLevel.HIGH,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            chatbot_id=ctx.extras.get("chatbot_id"),
            counts={"extraction_attempts": 1},
        )
        report = {"severity": ThreatLevel.HIGH.value, "extraction_attempt": True}
        if self.policy.block_on_threat:
            return GuardrailResult(action=GuardrailAction.BLOCK, reason="prompt_extraction_attempt", report=report)
        return GuardrailResult(
            action=GuardrailAction.TRANSFORM,
            content=PromptInjectionGuardrail._wrap_flagged_input(content, threats),
            report=report,
        )

    async def _check_output(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        prompt = ctx.extras.get("system_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return GuardrailResult(action=GuardrailAction.PASS)
        # CPU-bound (shingles + fuzzy alignment): keep it off the event loop.
        match = await asyncio.to_thread(_detect_leak, prompt, content, self.policy)
        if not match.leaked:
            return GuardrailResult(action=GuardrailAction.PASS)
        severity = ThreatLevel.CRITICAL if match.canary_hit else ThreatLevel.HIGH
        await self._security_logger.log_security_category_event(
            category="prompt_leakage",
            severity=severity,
            score=match.shingle_hit_ratio,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            chatbot_id=ctx.extras.get("chatbot_id"),
            counts={
                "matched_segments": match.matched_segments,
                "redacted_spans": len(match.spans),
                "canary_hit": int(match.canary_hit),
            },
        )
        report = {
            "severity": severity.value,
            "shingle_hit_ratio": round(match.shingle_hit_ratio, 4),
            "matched_segments": match.matched_segments,
            "canary_hit": match.canary_hit,
            "redacted_spans": len(match.spans),
            "stream_checked": "final_only" if ctx.method == "ask_stream" else "full",
        }
        if self.policy.block_on_threat:
            return GuardrailResult(action=GuardrailAction.BLOCK, reason="prompt_leakage_detected", report=report)
        # A canary hit means the response carries the canary token itself; span redaction never
        # covers it, so the whole response is replaced rather than delivered with the canary intact.
        redacted = REDACTION_MARKER if (match.canary_hit or not match.spans) else _redact(content, match.spans)
        return GuardrailResult(action=GuardrailAction.TRANSFORM, content=redacted, report=report)
