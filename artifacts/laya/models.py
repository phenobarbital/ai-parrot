"""Evaluation records for the Laya CPU experiment (spec §2 Data Models). Pydantic only — no ``parrot``."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ERROR_CODES: tuple[str, ...] = (
    "dependency_missing",
    "checkpoint_missing",
    "startup_timeout",
    "inference_timeout",
    "worker_protocol_error",
    "worker_failed",
    "invalid_answer",
    "context_overflow",
    "live_config_missing",
    "provider_error",
    "model_unverified",
    "call_cap_reached",
)
SCENARIOS: tuple[str, ...] = ("injection", "routing", "grounded")
INJECTION_BUCKETS: tuple[str, ...] = (
    "clean",
    "clean_framework",
    "attack_direct",
    "attack_paraphrase",
    "attack_obfuscated",
)
INJECTION_LABELS: tuple[str, ...] = ("injection", "clean")
ROUTE_CHOICES: tuple[str, ...] = ("primary", "cheap", "abstain")
GROUNDED_LABELS: tuple[str, ...] = ("billing", "technical", "sales", "other", "insufficient_evidence")
SCENARIO_LABELS: dict[str, tuple[str, ...]] = {
    "injection": INJECTION_LABELS,
    "routing": ROUTE_CHOICES,
    "grounded": GROUNDED_LABELS,
}
INJECTION_QUESTION_ID = "injection"
ROUTING_QUESTION_ID = "route"
GROUNDED_QUESTION_ID = "category"
Scenario = Literal["injection", "routing", "grounded"]


def _finite(value: float | None, name: str) -> float | None:
    """Return ``value`` if it is None or a finite float; raise ``ValueError`` otherwise."""
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return value


class _Record(BaseModel):
    """Base with forbidden extra fields (spec §2)."""

    model_config = ConfigDict(extra="forbid")


class PredictionRequest(_Record):
    """One worker request: opaque ``state`` text plus a fixed per-scenario question schema."""

    request_id: str = Field(min_length=1)
    state: str
    questions: dict[str, dict[str, Any]] = Field(min_length=1)


class PredictionResult(_Record):
    """One worker response; host fills ``roundtrip_ms`` and worker fills ``inference_ms``."""

    request_id: str = Field(min_length=1)
    status: Literal["ok", "error"]
    answers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    inference_ms: float | None = None
    roundtrip_ms: float | None = None
    error_code: str | None = None
    error_message: str | None = None

    @field_validator("inference_ms", "roundtrip_ms")
    @classmethod
    def _finite_ms(cls, value: float | None, info: Any) -> float | None:
        return _finite(value, info.field_name)

    @model_validator(mode="after")
    def _error_code_consistency(self) -> "PredictionResult":
        """Require a stable error code exactly for error results."""
        if self.status == "error":
            if self.error_code not in ERROR_CODES:
                raise ValueError("error status requires an error_code from ERROR_CODES")
        elif self.error_code is not None:
            raise ValueError("ok status must not include an error_code")
        return self


class EvaluationConfig(_Record):
    """Run configuration (spec §2 table). CLI flags map 1:1 with hyphenated names (TASK-3616)."""

    worker_python: Path
    checkpoint_path: Path
    checkpoint_revision: str = Field(min_length=1)
    scenario: Literal["all", "injection", "routing", "grounded"] = "all"
    live: bool = False
    primary_label: str = "anthropic:opus-5"
    primary_api_model: str | None = None
    cheap_api_model: str | None = None
    max_live_calls: int = Field(default=0, ge=0)
    max_output_tokens: int = Field(default=256, gt=0)
    injection_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    routing_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    startup_timeout_s: float = Field(default=300.0, gt=0)
    prediction_timeout_s: float = Field(default=30.0, gt=0)
    warmup: int = Field(default=3, ge=0)
    repeats: int = Field(default=10, gt=0)
    seed: int = 42
    output_dir: Path
    worker_module: str = "artifacts.laya.worker"
    price_file: Path | None = None

    @field_validator("injection_threshold", "routing_threshold", "startup_timeout_s", "prediction_timeout_s")
    @classmethod
    def _finite_cfg(cls, value: float, info: Any) -> float:
        return _finite(value, info.field_name)  # type: ignore[return-value]


class EvaluationCase(_Record):
    """One labeled English example; ``expected`` must belong to the scenario's label set."""

    id: str = Field(min_length=1)
    scenario: Scenario
    language: Literal["en"]
    split: Literal["calibration", "evaluation"]
    state: str = Field(min_length=1)
    expected: str
    bucket: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_sha256: str | None = None

    @model_validator(mode="after")
    def _label_in_scenario(self) -> "EvaluationCase":
        """Reject labels outside this case's scenario-specific allowlist."""
        if self.expected not in SCENARIO_LABELS[self.scenario]:
            raise ValueError(f"expected label {self.expected!r} is invalid for scenario {self.scenario!r}")
        return self


class RouteDecision(_Record):
    """Allowlisted routing outcome; no model is selected when none was configured."""

    choice: Literal["primary", "cheap", "abstain"]
    selected_model: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str = Field(min_length=1)

    @field_validator("confidence")
    @classmethod
    def _finite_conf(cls, value: float | None) -> float | None:
        return _finite(value, "confidence")


class SampleResult(_Record):
    """One scored observation (one case × one repeat × one arm). Unavailable values stay ``None``."""

    case_id: str
    scenario: Scenario
    repeat: int = Field(ge=0)
    arm: Literal["local", "primary", "routed"] = "local"
    expected: str
    predicted: str | None = None
    status: Literal["ok", "error"]
    error_code: str | None = None
    timings_ms: dict[str, float | None] = Field(default_factory=dict)
    decision: RouteDecision | None = None
    requested_model: str | None = None
    selected_model: str | None = None
    reported_model: str | None = None
    actual_model: str | None = None
    fallback_metadata: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    answer: str | None = None
    quality_pass: bool | None = None

    @field_validator("error_code")
    @classmethod
    def _known_error_code(cls, value: str | None) -> str | None:
        """Reject operational error codes outside the stable allowlist."""
        if value is not None and value not in ERROR_CODES:
            raise ValueError(f"error_code must be one of ERROR_CODES, got {value!r}")
        return value

    @field_validator("timings_ms")
    @classmethod
    def _finite_timings(cls, value: dict[str, float | None]) -> dict[str, float | None]:
        """Reject non-finite timing measurements while preserving unavailable values."""
        for name, timing in value.items():
            _finite(timing, f"timings_ms[{name!r}]")
        return value


class EvaluationReport(_Record):
    """Top-level JSON report (schema_version '1'). ``config`` holds no secrets: keys come from env only."""

    schema_version: Literal["1"] = "1"
    status: Literal["complete", "incomplete", "error"]
    config: EvaluationConfig
    environment: dict[str, Any] = Field(default_factory=dict)
    fixture_sha256: dict[str, str] = Field(default_factory=dict)
    question_schemas: dict[str, dict[str, Any]] = Field(default_factory=dict)
    samples: list[SampleResult] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
