"""JailbreakGuardrail — INPUT detection of boundary-bypass attempts (FEAT-761).

Engine resolution follows ``PARROT_JAILBREAK_ONNX_DIR`` -> cached Hugging Face
snapshot -> a local heuristic floor. Construction never downloads a model; hosts
may call :func:`warmup_jailbreak_model` during startup.
"""

import logging
import re
from typing import Any, ClassVar

from parrot.security.prompt_injection import (
    PromptInjectionDetector,
    SecurityEventLogger,
    ThreatLevel,
    max_threat_level,
)

from ..base import Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage
from ._engine_chassis import EngineSpec, resolve_engine, score_async, warmup_model
from .prompt_injection import PromptInjectionGuardrail

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_ID: str = "madhurjindal/Jailbreak-Detector-Large"
_DEFAULT_GRAPH_PATH: str = "onnx/model.onnx"
_DEFAULT_POSITIVE_LABELS: tuple[str, ...] = ("jailbreak", "malicious")
_DEFAULT_THRESHOLD: float = 0.044844940304756165

_JAILBREAK_SPEC = EngineSpec(
    category="jailbreak",
    env_prefix="PARROT_JAILBREAK",
    default_model_id=_DEFAULT_MODEL_ID,
    known_graph_paths={_DEFAULT_MODEL_ID: _DEFAULT_GRAPH_PATH} if _DEFAULT_MODEL_ID else {},
    kind="classifier",
    positive_label_match=_DEFAULT_POSITIVE_LABELS,
)

#: Heuristic floor (no model resolved). Data, not logic — ES/EN, compiled once.
_HEURISTIC_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bDAN\b",
        r"\bdeveloper\s+mode\b",
        r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?",
        r"disregard\s+(?:all\s+)?(?:previous|prior|above|your)\s+instructions?",
        r"you\s+are\s+no\s+longer\s+(?:an\s+AI|bound)",
        r"pretend\s+(?:that\s+)?you\s+have\s+no\s+(?:rules|restrictions)",
        r"(?:bypass|override)\s+(?:your\s+)?(?:rules|restrictions|safety)",
        r"jailbreak\s+(?:mode|the\s+system)",
        r"ignora\s+(?:todas\s+)?las\s+instrucciones\s+(?:anteriores|previas)",
        r"modo\s+desarrollador",
        r"ya\s+no\s+tienes\s+(?:reglas|restricciones)",
        r"act[úu]a\s+como\s+si\s+no\s+tuvieras\s+(?:l[íi]mites|filtros)",
        r"(?:elude|anula)\s+(?:las\s+)?(?:reglas|restricciones|seguridad)",
        r"rompe\s+(?:tus\s+)?(?:reglas|restricciones)",
    )
)


class JailbreakGuardrail(Guardrail):
    """INPUT guardrail for jailbreak attempts; policy parity with prompt injection."""

    name = "jailbreak"
    stages: ClassVar[set] = {GuardrailStage.INPUT}
    priority = 11

    def __init__(
        self,
        strict_mode: bool = True,
        block_on_threat: bool = False,
        jailbreak_probability_threshold: float = _DEFAULT_THRESHOLD,
        **kwargs: Any,
    ) -> None:
        """Resolve the engine offline; use the heuristic floor when none is available."""
        self.strict_mode = strict_mode
        self.block_on_threat = block_on_threat
        self.jailbreak_probability_threshold = jailbreak_probability_threshold
        self.on_error = "fail_closed" if block_on_threat else "fail_open"
        self.logger = logging.getLogger(__name__)
        self._framework_sanitizer = PromptInjectionDetector(logger=self.logger)
        self._engine = resolve_engine(_JAILBREAK_SPEC)
        self._security_logger = SecurityEventLogger(logger=self.logger)

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        """Return PASS, TRANSFORM, or BLOCK without placing content in telemetry."""
        if ctx.extras.get("trusted_source", False):
            return GuardrailResult(action=GuardrailAction.PASS)
        if not self.strict_mode:
            return GuardrailResult(action=GuardrailAction.PASS)
        if not content or not content.strip():
            return GuardrailResult(action=GuardrailAction.PASS)

        scan_text = self._framework_sanitizer.strip_framework_patterns(content)
        threats: list[dict[str, Any]] = []
        score: float | None = None
        engine_name = "heuristic"

        if self._engine is not None:
            score = await score_async(self._engine, scan_text)
            if score > self.jailbreak_probability_threshold:
                threats.append(
                    {
                        "type": "jailbreak",
                        "level": ThreatLevel.CRITICAL,
                        "probability": score,
                        "pattern": "onnx-model",
                        "description": "High probability jailbreak attempt",
                    }
                )
            engine_name = "onnx"
        elif any(pattern.search(scan_text) for pattern in _HEURISTIC_PATTERNS):
            threats.append(
                {
                    "type": "jailbreak",
                    "level": ThreatLevel.HIGH,
                    "pattern": "heuristic",
                    "description": "Jailbreak instruction override attempt",
                }
            )

        if not threats:
            return GuardrailResult(action=GuardrailAction.PASS)

        max_severity = max_threat_level(threats)
        await self._security_logger.log_security_category_event(
            category="jailbreak",
            severity=max_severity,
            score=score,
            user_id=ctx.user_id or "anonymous",
            session_id=ctx.session_id or "unknown",
            chatbot_id=str(ctx.extras.get("chatbot_id", "")),
            counts={"threats_detected": len(threats)},
        )

        if self.block_on_threat and max_severity in (ThreatLevel.CRITICAL, ThreatLevel.HIGH):
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason="jailbreak_detected",
                report={"threats_detected": len(threats)},
            )

        return GuardrailResult(
            action=GuardrailAction.TRANSFORM,
            content=PromptInjectionGuardrail._wrap_flagged_input(content, threats),
            report={
                "threats_detected": len(threats),
                "max_severity": max_severity.value,
                "engine": engine_name,
            },
        )


async def warmup_jailbreak_model(force_download: bool = False) -> str:
    """Warm the configured model, returning ``"onnx"`` or ``"none"`` without raising."""
    return await warmup_model(_JAILBREAK_SPEC, force_download=force_download)
