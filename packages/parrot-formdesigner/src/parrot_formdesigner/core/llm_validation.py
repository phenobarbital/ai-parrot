"""LLM-assisted answer plausibility configuration and report models (FEAT-649).

Declares the typed ``FormSchema.llm_validation`` block, the per-answer verdict
and the report returned by ``AnswerPlausibilityChecker`` (services/plausibility.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator

from .types import FieldType

if TYPE_CHECKING:
    from .schema import FormField, FormSchema

_DEFAULT_EXCLUDED: tuple[FieldType, ...] = (
    FieldType.PASSWORD,
    FieldType.HIDDEN,
    FieldType.FILE,
    FieldType.IMAGE_DROPZONE,
    FieldType.CREDIT_CARD,
    FieldType.SIGNATURE,
)


class LLMValidationConfig(BaseModel):
    """Per-form LLM plausibility settings (``FormSchema.llm_validation``)."""

    enabled: bool = False
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    on_error: Literal["skip", "block"] = "skip"
    on_implausible: Literal["annotate", "review", "reject"] = "annotate"
    """What to do with an answer the model judged implausible.

    ``annotate`` (default) stores it with the verdict attached — FEAT-649
    behaviour, unchanged; ``review`` refuses the submission until the client
    reconfirms; ``reject`` always refuses. Distinct from ``on_error``, which
    governs LLM *unavailability* only.
    """
    model: str | None = None
    timeout_s: float = Field(default=8.0, gt=0.0)
    max_fields: int = Field(default=50, ge=1)
    exclude_field_types: list[FieldType] = Field(default_factory=lambda: list(_DEFAULT_EXCLUDED))


class PlausibilityVerdict(BaseModel):
    """LLM judgement for one (question, answer) pair."""

    plausible: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, value: object) -> float:
        """Clamp out-of-range confidences into [0, 1] instead of rejecting them."""
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("confidence must be a number")
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError("confidence must be a number") from exc
        if number != number:  # NaN
            raise ValueError("confidence must be a number")
        return max(0.0, min(1.0, number))


class PlausibilityReport(BaseModel):
    """Outcome of one plausibility batch."""

    status: Literal["ok", "skipped", "blocked"]
    reason: str | None = None
    model: str | None = None
    threshold: float
    latency_ms: int | None = None
    items: dict[str, PlausibilityVerdict] = Field(default_factory=dict)


def llm_validation_enabled(form: FormSchema, field: FormField) -> bool:
    """Return whether ``field`` takes part in plausibility checking.

    ``field.llm_validation`` wins when not ``None``; otherwise inherit
    ``form.llm_validation.enabled`` (``False`` when the block is absent).
    """
    if field.llm_validation is not None:
        return field.llm_validation
    return bool(form.llm_validation and form.llm_validation.enabled)


def implausible_fields(report: PlausibilityReport) -> list[str]:
    """Return sorted field ids whose verdict trips the enforcement gate.

    Args:
        report: One plausibility batch outcome.

    Returns:
        Sorted field ids for implausible verdicts. Reports whose status is not
        ``"ok"`` remain on the LLM-unavailability path and return no ids.
    """
    if report.status != "ok":
        return []
    return sorted(
        field_id
        for field_id, verdict in report.items.items()
        if not verdict.plausible or verdict.confidence < report.threshold
    )
