"""Unified guardrails infrastructure for AI-Parrot bots (FEAT-396).

Provides one pluggable ``Guardrail`` abstraction with four stages
(INPUT, TOOL_OUTPUT, OUTPUT, OUTPUT_STREAM) and four verdicts
(PASS, TRANSFORM, FLAG, BLOCK) that PII, prompt-injection, secrets,
moderation, and future controls plug into.

This module currently exposes the core data models, enums, the
``Guardrail`` ABC, the ``StreamingGuardrail`` adapter contract (TASK-2024),
the ``GuardrailPipeline`` execution engine (TASK-2025), and the named
registry + config coercion used to build a bot's per-stage pipelines
(TASK-2026). Built-in plugins are added by later tasks in this feature.
"""
from .base import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
    GuardrailStage,
)
from .config import build_pipelines_from_config
from .events import GuardrailActionEvent
from .pipeline import GuardrailPipeline, GuardrailTelemetryEntry, PipelineOutcome
from .registry import build_guardrails, register_guardrail
from .streaming import StreamingGuardrail

__all__ = [
    "Guardrail",
    "GuardrailAction",
    "GuardrailActionEvent",
    "GuardrailContext",
    "GuardrailPipeline",
    "GuardrailResult",
    "GuardrailStage",
    "GuardrailTelemetryEntry",
    "PipelineOutcome",
    "StreamingGuardrail",
    "build_guardrails",
    "build_pipelines_from_config",
    "register_guardrail",
]
