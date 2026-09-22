# TASK-3605: Laya evaluation Pydantic models, label sets and error codes

**Feature**: FEAT-589 — Evaluate Laya for typed classification and agent model routing
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §2 "Data Models" and the schema half of §3 **Module 1**. Every other task
imports these records: the worker protocol (`PredictionRequest`/`PredictionResult`), the
routing adapter (`RouteDecision`), the scenario runners (`EvaluationCase`, `SampleResult`) and
the CLI (`EvaluationConfig`, `EvaluationReport`). The spec fixes the field lists; this task
turns them into Pydantic v2 models with `extra="forbid"` and finite-number validation, and
declares the fixed label sets and the twelve stable error codes as module constants so no
later task re-types a string.

Everything under `artifacts/` is git-ignored (`.gitignore:279`); the files this task creates
must be force-added individually (`git add -f <file>`), never the directory.

This task also creates the test directory `packages/ai-parrot/tests/unit/laya_eval/` (no
`__init__.py`, distinctive `test_laya_*.py` basenames) and its `conftest.py`, which puts the
repository root on `sys.path` so `import artifacts.laya...` works regardless of rootdir.

---

## Scope

- Create `artifacts/laya/__init__.py` (docstring only).
- Create `artifacts/laya/models.py` with: `ERROR_CODES`, `SCENARIOS`, `INJECTION_BUCKETS`,
  `ROUTE_CHOICES`, `GROUNDED_LABELS`, `INJECTION_LABELS`, `SCENARIO_LABELS`, the question-id
  constants, and the seven models `EvaluationConfig`, `EvaluationCase`, `PredictionRequest`,
  `PredictionResult`, `RouteDecision`, `SampleResult`, `EvaluationReport`.
- Create `packages/ai-parrot/tests/unit/laya_eval/conftest.py` (sys.path shim).
- Write `packages/ai-parrot/tests/unit/laya_eval/test_laya_models.py`.

**NOT in scope**: `load_cases` / `validate_answers` (TASK-3606); fixture files (TASK-3607);
any code that imports `parrot.*` — `models.py` depends on Pydantic only, because the isolated
worker environment may import it later.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/__init__.py` | CREATE | Package marker + docstring |
| `artifacts/laya/models.py` | CREATE | Constants + seven Pydantic v2 models |
| `packages/ai-parrot/tests/unit/laya_eval/conftest.py` | CREATE | Repo-root `sys.path` shim for `artifacts.*` imports |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_models.py` | CREATE | Model construction/validation tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `1a7ccd5a1` on 2026-09-21.

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator  # pydantic 2.12.5 (venv; packages/ai-parrot/pyproject.toml:54)
```

### Existing Signatures to Use
```python
# None — this module is new and depends on the standard library + Pydantic only.
# Repository facts the tests rely on:
#   pytest.ini (repo root)                       -> asyncio_mode = auto, rootdir = repo root
#   packages/ai-parrot/pyproject.toml:1008-1016  -> markers: real_llm, network, live, integration, e2e
#   packages/ai-parrot/tests/unit/               -> has conftest.py, NO __init__.py (module basenames must be unique)
#   .gitignore:279                               -> `artifacts/` is ignored: `git add -f` each new file
```

### Does NOT Exist
- ~~`artifacts/laya/`~~ — the directory does not exist yet; nothing under it may be assumed.
- ~~`parrot.evaluation`, `parrot.laya`~~ — no evaluation module exists in the core package.
- ~~a `language` column in the injection benchmark~~ — `EvaluationCase.language` is authored per fixture, never inferred.
- ~~`from parrot.models import ...` inside `models.py`~~ — forbidden here: the worker environment has no `parrot`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/laya/__init__.py", "action": "CREATE"},
    {"path": "artifacts/laya/models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/laya_eval/conftest.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_models.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `model_config = ConfigDict(extra="forbid")` on every model (spec §2 "forbidden extra fields").
- Every float field is validated finite (`math.isfinite`) — NaN/Inf must fail validation, not be
  stored (spec §2 "finite numbers").
- Nullable fields default to `None`, never to `0`/`""` (spec §2 `SampleResult` row).
- No `parrot` import. No `print`. Standard `logging` only if needed (not expected here).
- `ERROR_CODES` is the single source of truth for `error_code` values; `PredictionResult` and
  `SampleResult` validate membership.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` — house style for
  Pydantic v2 record models with validators (read for style only; do not import).

---

## Implementation Blueprint

### Steps (in order)
1. Write `artifacts/laya/__init__.py` and the `conftest.py` shim — *why*: tests cannot import
   `artifacts.laya` until the repo root is on `sys.path`.
2. Write the constants block, then the models in dependency order (`RouteDecision` before
   `SampleResult`, `EvaluationConfig` before `EvaluationReport`) — *why*: forward references are
   avoidable and the executor never has to guess a name.
3. Write the tests, run them, then `git add -f` the four files — *why*: `artifacts/` is ignored.

### `artifacts/laya/__init__.py` (CREATE)
```python
"""FEAT-589 — standalone CPU evaluation of Laya typed decisions (spec: sdd/specs/laya-adoption.spec.md).

Host-side modules depend on Pydantic and (where stated) on ``parrot``; ``worker.py`` is the only
module that runs inside the isolated Laya environment and imports nothing from this package.
"""
```

### `packages/ai-parrot/tests/unit/laya_eval/conftest.py` (CREATE)
```python
"""Make the repository-root ``artifacts`` namespace importable for the Laya evaluation tests."""
from __future__ import annotations

import sys
from pathlib import Path

# conftest.py -> laya_eval -> unit -> tests -> ai-parrot -> packages -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
```
**Why this shape**: the root `conftest.py` normally puts the repo root on `sys.path`, but
`packages/ai-parrot/tests/unit/` has no `__init__.py`, so rootdir detection varies by invocation.
The shim makes `from artifacts.laya.models import ...` deterministic.

### `artifacts/laya/models.py` (CREATE — constants + request/response models)
```python
"""Evaluation records for the Laya CPU experiment (spec §2 Data Models). Pydantic only — no ``parrot``."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ERROR_CODES: tuple[str, ...] = (
    "dependency_missing", "checkpoint_missing", "startup_timeout", "inference_timeout",
    "worker_protocol_error", "worker_failed", "invalid_answer", "context_overflow",
    "live_config_missing", "provider_error", "model_unverified", "call_cap_reached",
)
SCENARIOS: tuple[str, ...] = ("injection", "routing", "grounded")
INJECTION_BUCKETS: tuple[str, ...] = ("clean", "clean_framework", "attack_direct", "attack_paraphrase", "attack_obfuscated")
INJECTION_LABELS: tuple[str, ...] = ("injection", "clean")
ROUTE_CHOICES: tuple[str, ...] = ("primary", "cheap", "abstain")
GROUNDED_LABELS: tuple[str, ...] = ("billing", "technical", "sales", "other", "insufficient_evidence")
SCENARIO_LABELS: dict[str, tuple[str, ...]] = {"injection": INJECTION_LABELS, "routing": ROUTE_CHOICES, "grounded": GROUNDED_LABELS}
INJECTION_QUESTION_ID = "injection"   # noul question; positive outcome == injection
ROUTING_QUESTION_ID = "route"         # choice question over ROUTE_CHOICES
GROUNDED_QUESTION_ID = "category"     # choice question over GROUNDED_LABELS
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
    """One worker response; ``roundtrip_ms`` is filled by the host, ``inference_ms`` by the worker."""

    request_id: str = Field(min_length=1)
    status: Literal["ok", "error"]
    answers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    inference_ms: float | None = None
    roundtrip_ms: float | None = None
    error_code: str | None = None
    error_message: str | None = None

    @field_validator("inference_ms", "roundtrip_ms")
    @classmethod
    def _finite_ms(cls, v: float | None, info: Any) -> float | None:
        return _finite(v, info.field_name)

    @model_validator(mode="after")
    def _error_code_consistency(self) -> "PredictionResult":
        # FILL IN: status=="error" requires error_code in ERROR_CODES; status=="ok" requires error_code is None — bounded by spec §2 "stable error codes"
        return self
```
**Why this shape**: the wire records are the contract between host and isolated worker; both
sides validate them, so they carry no `parrot` types. `questions` is opaque `dict[str, dict]`
by spec; the per-scenario schemas are built in TASK-3614 and validated in TASK-3606.

### `artifacts/laya/models.py` (CREATE — continued: config, case, decision, sample, report)
```python
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
    worker_module: str = "artifacts.laya.worker"   # test seam: mocked e2e substitutes a fake protocol worker
    price_file: Path | None = None                 # optional explicit per-model prices (spec §4)

    @field_validator("injection_threshold", "routing_threshold", "startup_timeout_s", "prediction_timeout_s")
    @classmethod
    def _finite_cfg(cls, v: float, info: Any) -> float:
        return _finite(v, info.field_name)  # type: ignore[return-value]


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
        # FILL IN: raise ValueError unless self.expected in SCENARIO_LABELS[self.scenario] — bounded by spec §2 "expected label belongs to scenario's declared set"
        return self


class RouteDecision(_Record):
    """Allowlisted routing outcome; ``selected_model`` is None whenever no model was configured."""

    choice: Literal["primary", "cheap", "abstain"]
    selected_model: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str = Field(min_length=1)

    @field_validator("confidence")
    @classmethod
    def _finite_conf(cls, v: float | None) -> float | None:
        return _finite(v, "confidence")


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
    # FILL IN: validators — error_code in ERROR_CODES when not None; every timings_ms value finite — bounded by spec §2


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
```
**Why this shape**: field names and defaults are the spec §2 table verbatim, plus three
deliberate additions that must be kept: `worker_module` (mocked end-to-end seam, TASK-3617),
`price_file` (spec §4 cost estimates) and `SampleResult.arm` (spec §2 paired primary/routed
calls need an arm discriminator). `Path` fields are not resolved or checked for existence here —
that is CLI-time work (TASK-3616).

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_models.py` (CREATE)
```python
"""FEAT-589 M1 — record models: forbidden extras, finite numbers, label membership, error codes."""
from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from artifacts.laya.models import (
    ERROR_CODES, GROUNDED_LABELS, ROUTE_CHOICES, EvaluationCase, EvaluationConfig,
    PredictionResult, RouteDecision, SampleResult,
)


def _config(**overrides) -> EvaluationConfig:
    base = dict(worker_python=Path("/usr/bin/python3"), checkpoint_path=Path("/tmp/ckpt"),
                checkpoint_revision="abc123", output_dir=Path("/tmp/out"))
    base.update(overrides)
    return EvaluationConfig(**base)


def test_error_codes_are_the_twelve_spec_codes():
    assert len(ERROR_CODES) == 12 and len(set(ERROR_CODES)) == 12
    assert "context_overflow" in ERROR_CODES and "call_cap_reached" in ERROR_CODES


def test_config_defaults_and_ranges():
    cfg = _config()
    assert cfg.primary_label == "anthropic:opus-5" and cfg.injection_threshold == 0.5 and cfg.routing_threshold == 0.8
    with pytest.raises(ValidationError):
        _config(injection_threshold=1.5)
    with pytest.raises(ValidationError):
        _config(repeats=0)
    with pytest.raises(ValidationError):
        _config(unknown_field=1)


def test_case_label_must_belong_to_scenario():
    kwargs = dict(id="c1", scenario="routing", language="en", split="evaluation", state="hi", bucket="simple", source="authored")
    assert EvaluationCase(expected=ROUTE_CHOICES[0], **kwargs).expected == "primary"
    with pytest.raises(ValidationError):
        EvaluationCase(expected=GROUNDED_LABELS[0], **kwargs)
    with pytest.raises(ValidationError):
        EvaluationCase(expected="primary", **{**kwargs, "language": "es"})


def test_finite_numbers_are_enforced():
    with pytest.raises(ValidationError):
        RouteDecision(choice="primary", confidence=math.nan, reason="x")
    with pytest.raises(ValidationError):
        PredictionResult(request_id="r", status="ok", inference_ms=math.inf)


def test_prediction_result_error_code_consistency():
    # FILL IN: status="error" without error_code fails; status="ok" with error_code fails; unknown code fails — bounded by spec §2 stable error codes
    raise NotImplementedError


def test_sample_result_nullable_fields_default_none():
    s = SampleResult(case_id="c", scenario="injection", repeat=0, expected="clean", status="ok")
    assert s.predicted is None and s.actual_model is None and s.usage is None and s.quality_pass is None
```
**Why**: spec §4 "Fixture validation" and "Answer validation" rows start here (schema-level);
TASK-3606 adds the function-level cases.

### FILL IN checklist
- [ ] `models.py::PredictionResult._error_code_consistency` — status/error_code coupling; spec §2
- [ ] `models.py::EvaluationCase._label_in_scenario` — membership in `SCENARIO_LABELS`; spec §2
- [ ] `models.py::SampleResult` validators — error_code membership, finite timings; spec §2
- [ ] `test_laya_models.py::test_prediction_result_error_code_consistency` — three failing shapes

---

## Acceptance Criteria

- [ ] AC-1 — All seven models reject unknown fields and non-finite floats.
- [ ] AC-2 — `EvaluationCase` rejects a label outside its scenario's set and any `language != "en"`.
- [ ] AC-3 — `ERROR_CODES` contains exactly the twelve spec §2 codes.
- [ ] AC-4 — `models.py` imports nothing from `parrot`.
- [ ] `ruff check artifacts/laya/models.py` clean (pass the file explicitly — `ruff.toml:94` excludes the `artifacts` directory from discovery).

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_models.py -q`

---

## Test Specification

See the CREATE block above; it is the scaffold. Add one test that `EvaluationReport` round-trips
through `model_dump_json()` / `model_validate_json()` with an empty sample list.

---

## Agent Instructions

1. Read spec §2 "Data Models" and §7 "`artifacts/` is ignored".
2. Implement from the Blueprint; complete every `FILL IN`.
3. Run the Validation Command; `ruff check` and `black --check -l 120` on the new files.
4. `git add -f` each of the four files (never `git add artifacts/`), commit, move this file to
   `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note


- Task: TASK-3605
- Feature: laya-adoption
- Implementation SHA: aa8ff03daf18d4efb8ef2bd98049116a6ab5ca62
- Closed at (UTC): 2026-09-22T11:37:47+00:00
- Fix commits: aa8ff03daf18d4efb8ef2bd98049116a6ab5ca62

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| merge_validation | completed (exit_code=0, 7 passed) |
| orchestrator_fix | force-added 2 gitignored files (artifacts/laya/__init__.py, models.py) the coder created on disk but never staged past .gitignore |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 193.474s · Tokens: n/a |
