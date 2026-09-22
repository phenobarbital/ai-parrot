"""Evaluation records for the Laya CPU experiment (spec §2 Data Models). Pydantic only — no ``parrot``."""

from __future__ import annotations

import hashlib
import json
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


_SUM_TOLERANCE = 0.001


def manifest_sha256(path: Path) -> str:
    """Return the hex SHA-256 of the file's exact bytes (spec §4 corpus hash)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(path: Path, scenario: str) -> list[EvaluationCase]:
    """Validate JSONL cases; reject duplicate IDs, unknown labels and split overlap.

    Args:
        path: JSONL file, one case object per non-empty line, in the order to evaluate.
        scenario: One of ``SCENARIOS``; every case must declare this scenario.

    Returns:
        Cases in file order.

    Raises:
        ValueError: On a malformed line, a wrong ``scenario``, a duplicate ``id`` or a case
            text that appears in both the ``calibration`` and ``evaluation`` splits.
    """
    if scenario not in SCENARIO_LABELS:
        raise ValueError(f"unknown scenario {scenario!r}")
    cases: list[EvaluationCase] = []
    seen_ids: set[str] = set()
    by_split: dict[str, set[str]] = {"calibration": set(), "evaluation": set()}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            case = EvaluationCase(**payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid JSONL case at line {lineno}: {exc}") from exc
        if case.scenario != scenario:
            raise ValueError(f"case at line {lineno} has scenario {case.scenario!r}, expected {scenario!r}")
        if case.id in seen_ids:
            raise ValueError(f"duplicate case id {case.id!r} at line {lineno}")
        seen_ids.add(case.id)
        by_split[case.split].add(case.state)
        cases.append(case)
    overlap = by_split["calibration"] & by_split["evaluation"]
    if overlap:
        raise ValueError(f"{len(overlap)} state(s) present in both calibration and evaluation splits")
    return cases


def _invalid(result: PredictionResult, message: str) -> PredictionResult:
    """Return an ``invalid_answer`` error copy of ``result`` (never raise for worker output)."""
    return result.model_copy(
        update={"status": "error", "answers": {}, "error_code": "invalid_answer", "error_message": message}
    )


def _valid_probability(value: Any) -> bool:
    """Return whether ``value`` is a finite numeric probability in the unit interval."""
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0.0 <= value <= 1.0
    )


def validate_answers(request: PredictionRequest, result: PredictionResult) -> PredictionResult:
    """Validate required question IDs, answer types, choice membership and finite probabilities.

    Returns ``result`` unchanged when it is already an error or fully valid; otherwise an
    ``invalid_answer`` error result carrying the first defect found.
    """
    if result.status == "error":
        return result
    if result.request_id != request.request_id:
        return _invalid(result, f"request_id mismatch: {result.request_id!r} != {request.request_id!r}")
    for qid, question in request.questions.items():
        answer = result.answers.get(qid)
        if answer is None:
            return _invalid(result, f"missing answer for question {qid!r}")
        question_type = question.get("type")
        if answer.get("type") != question_type:
            return _invalid(result, f"wrong answer type for question {qid!r}")
        if question_type == "noul":
            if not _valid_probability(answer.get("noul")) or not _valid_probability(answer.get("confidence")):
                return _invalid(result, f"invalid noul probability for question {qid!r}")
        elif question_type == "choice":
            options = question.get("options")
            probabilities = answer.get("probabilities")
            if not isinstance(options, list) or not all(isinstance(option, str) for option in options):
                return _invalid(result, f"invalid choice options for question {qid!r}")
            if answer.get("choice") not in options or not isinstance(probabilities, dict):
                return _invalid(result, f"invalid choice answer for question {qid!r}")
            if set(probabilities) != set(options):
                return _invalid(result, f"choice probabilities do not cover options for question {qid!r}")
            if not all(_valid_probability(value) for value in probabilities.values()):
                return _invalid(result, f"invalid choice probability for question {qid!r}")
            if abs(sum(probabilities.values()) - 1.0) > _SUM_TOLERANCE:
                return _invalid(result, f"choice probabilities do not sum to one for question {qid!r}")
            if not _valid_probability(answer.get("confidence")):
                return _invalid(result, f"invalid choice confidence for question {qid!r}")
        else:
            return _invalid(result, f"unknown question type for question {qid!r}")
    extra = set(result.answers) - set(request.questions)
    if extra:
        return _invalid(result, f"unexpected answers: {sorted(extra)}")
    return result
