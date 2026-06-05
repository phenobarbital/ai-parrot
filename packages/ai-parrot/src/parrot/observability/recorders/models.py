"""UsageRecord — the normalized, PII-free record shared by all usage recorders.

A single ``UsageRecord`` is built per successful LLM call by
``UsageRecordingSubscriber`` from an ``AfterClientCallEvent`` plus an optional
``CostCalculator`` result, then fanned out to every configured
``AbstractLogger`` backend.

Privacy: this record carries NO prompt/completion content and NO
``user_id``/``session_id`` — only provider/model identifiers, token counts,
cost, timing, and a correlation ``trace_id``. This preserves the observability
PII contract (see ``observability/README.md``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, computed_field


class UsageRecord(BaseModel):
    """Normalized usage/token/cost record for one LLM API call.

    Attributes:
        provider: ``gen_ai.system`` value (e.g. ``"openai"``, ``"anthropic"``,
            ``"gemini"``) resolved via ``resolve_gen_ai_system``.
        client_name: Raw client identifier as emitted by the client (kept for
            traceability alongside the resolved ``provider``).
        model: Model identifier.
        input_tokens: Prompt/input token count (0 when unknown).
        output_tokens: Completion/output token count (0 when unknown).
        cost_usd: Estimated USD cost for this call, or ``None`` when pricing is
            unavailable for the ``(provider, model)`` pair.
        cumulative_cost_usd: Process-cumulative estimated USD cost across all
            calls observed so far (set by the subscriber), or ``None`` when cost
            tracking is disabled.
        duration_ms: Wall-clock duration of the call in milliseconds.
        finish_reason: Provider stop reason (e.g. ``"stop"``), or ``None``.
        trace_id: Correlation trace id (no content), or ``None``.
        service_name: Configured ``service.name``.
        timestamp: UTC timestamp at record construction.
    """

    provider: str
    client_name: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Optional[float] = None
    cumulative_cost_usd: Optional[float] = None
    duration_ms: float = 0.0
    finish_reason: Optional[str] = None
    trace_id: Optional[str] = None
    service_name: str = "ai-parrot"
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> int:
        """Sum of input and output tokens."""
        return self.input_tokens + self.output_tokens
