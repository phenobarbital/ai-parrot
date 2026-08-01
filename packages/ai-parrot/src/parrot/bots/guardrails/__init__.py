"""Unified guardrails infrastructure for AI-Parrot bots (FEAT-396).

Provides one pluggable ``Guardrail`` abstraction with four stages
(INPUT, TOOL_OUTPUT, OUTPUT, OUTPUT_STREAM) and four verdicts
(PASS, TRANSFORM, FLAG, BLOCK) that PII, prompt-injection, secrets,
moderation, and future controls plug into.

This module currently exposes the core data models, enums, the
``Guardrail`` ABC, and the ``StreamingGuardrail`` adapter contract
(TASK-2024). Pipeline execution, registry/config coercion, and built-in
plugins are added by later tasks in this feature.
"""
from .base import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
    GuardrailStage,
)
from .streaming import StreamingGuardrail

__all__ = [
    "Guardrail",
    "GuardrailAction",
    "GuardrailContext",
    "GuardrailResult",
    "GuardrailStage",
    "StreamingGuardrail",
]
