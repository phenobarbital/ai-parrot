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
from typing import Literal, Optional

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
        run_id: FEAT-479 — the dev-loop / dev-flow run identifier, from the
            ``current_run_id`` ContextVar, or ``None`` when unattributed.
        seat: FEAT-479 — the accounting seat, e.g. ``"development"`` or a
            pool-worker seat ``"development.w1"``, from the ``current_seat``
            ContextVar, or ``None`` when unattributed.
        node_id: FEAT-479 — the roll-up owner node id (``"development.w1"``
            rolls up to ``"development"``), or ``None``.
        cycle: FEAT-479 — 1-based attempt index within ``(run_id, seat)``,
            assigned by the ledger sink at record time; ``None`` here (the
            subscriber never assigns it).
        usage_reported: FEAT-479 — ``False`` when the provider reported
            neither token count (the ``0``-coercion on ``input_tokens``/
            ``output_tokens`` still applies for Prometheus/OpenLit; this flag
            preserves the distinction so the report renders ``—`` instead of
            a fabricated ``0``).
        status: FEAT-479 — ``"completed"`` or ``"failed"``.
        error_type: FEAT-479 — the exception CLASS NAME only (never the
            message — see the module's privacy contract), or ``None``.
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

    # ── FEAT-479: flow attribution. All optional/defaulted. ──
    run_id: Optional[str] = None
    seat: Optional[str] = None
    node_id: Optional[str] = None
    cycle: Optional[int] = None

    # ── FEAT-479: honesty + failure. ──
    usage_reported: bool = True
    status: Literal["completed", "failed"] = "completed"
    error_type: Optional[str] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> int:
        """Sum of input and output tokens."""
        return self.input_tokens + self.output_tokens
