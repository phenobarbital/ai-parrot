"""Guardrail telemetry lifecycle event (FEAT-396).

Extends the FEAT-176 ``LifecycleEvent`` taxonomy with a guardrails-scoped
event, following the same additive pattern ``parrot.eval.events`` uses for
the evaluation harness — a new feature-owned event class, not a
modification to ``parrot.core.events.lifecycle`` itself.

Added post-review: the spec's acceptance criterion "Telemetry emits
guardrail name/stage/action/duration/counts... via existing FEAT-176
observers" was previously unmet — `GuardrailPipeline`'s `on_telemetry`
callback (TASK-2025) was never actually supplied by the bot-wiring code
(TASK-2026/2028/2029), so no `GuardrailTelemetryEntry` ever reached a real
observer. `AbstractBot._on_guardrail_telemetry` (see `bots/abstract.py`)
forwards each entry here.
"""
from __future__ import annotations

from dataclasses import dataclass

from parrot.core.events.lifecycle import LifecycleEvent


@dataclass(frozen=True)
class GuardrailActionEvent(LifecycleEvent):
    """Emitted once per guardrail execution within a `GuardrailPipeline.run()`.

    Never carries content — only name/stage/action/duration, per spec §2
    ("Uniform telemetry (name + action + duration + counts, never content)
    via FEAT-176 observers").

    Attributes:
        guardrail_name: The executed guardrail's ``name``.
        stage: The `GuardrailStage` value (``"input"``, ``"tool_output"``,
            ``"output"``, ``"output_stream"``).
        action: The `GuardrailAction` value produced (or the effective
            verdict after error handling, e.g. ``"block"`` for a
            `fail_closed` exception).
        duration_ms: Wall-clock time spent in the guardrail's ``check()``.
        agent_name: Name of the bot that ran the pipeline.
    """

    guardrail_name: str = ""
    stage: str = ""
    action: str = ""
    duration_ms: float = 0.0
    agent_name: str = ""
