"""Schema of the planogram live E2E harness (FEAT-612, spec Module 14)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CASE_TYPES: dict[str, str] = {
    "shelves": "product_on_shelves",
    "ink-wall": "ink_wall",
    "backlit-endcap": "endcap_backlit_multitier",
}


class GroundTruth(BaseModel):
    """Human-labelled expectations and tolerances; no generated baseline is accepted as truth."""

    model_config = ConfigDict(extra="forbid")

    expected_positions: dict[str, str]
    expected_occupancy: dict[str, Literal["occupied", "empty", "unknown"]]
    expected_rules: dict[str, bool]
    overall_score: float
    score_tolerance: float
    min_coverage: float
    max_identity_errors: int
    max_occupancy_errors: int

    @model_validator(mode="after")
    def _check_labels_and_bounds(self) -> "GroundTruth":
        """Reject empty labels, nonfinite values, out-of-range scores and negative budgets."""
        if not (self.expected_positions or self.expected_occupancy or self.expected_rules):
            raise ValueError("ground truth must contain at least one assertion")
        for name in ("overall_score", "score_tolerance", "min_coverage"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and within [0, 1]")
        if self.max_identity_errors < 0 or self.max_occupancy_errors < 0:
            raise ValueError("error budgets must be non-negative")
        return self


class LiveCase(BaseModel):
    """Local paths and bounded execution, never committed retailer data."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    planogram_type: Literal["product_on_shelves", "ink_wall", "endcap_backlit_multitier"]
    photos: list[Path]
    config_path: Path
    ground_truth_path: Path
    backend: str
    cache_dir: Path
    output_dir: Path
    max_provider_requests: int = 64
    timeout_seconds: float = 600.0

    @model_validator(mode="after")
    def _check_case(self) -> "LiveCase":
        """Validate case/type pairing, explicit backend and positive finite limits."""
        if self.case_id not in CASE_TYPES or CASE_TYPES[self.case_id] != self.planogram_type:
            raise ValueError(f"case_id {self.case_id!r} does not match planogram_type {self.planogram_type!r}")
        if not self.photos:
            raise ValueError("photos must not be empty")
        parts = self.backend.split(":", 1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            raise ValueError("backend must be an explicit provider:model")
        if self.max_provider_requests <= 0:
            raise ValueError("max_provider_requests must be positive")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        return self


class LiveManifest(BaseModel):
    """The local manifest: cases plus credential environment variables per provider."""

    model_config = ConfigDict(extra="forbid")

    cases: list[LiveCase]
    required_env: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_namespaces(self) -> "LiveManifest":
        """Ensure case ids and writable cache/output namespaces are unique."""
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case_id values must be unique")
        cache_dirs = [case.cache_dir.resolve() for case in self.cases]
        output_dirs = [case.output_dir.resolve() for case in self.cases]
        if len(cache_dirs) != len(set(cache_dirs)):
            raise ValueError("cache_dir values must be unique")
        if len(output_dirs) != len(set(output_dirs)):
            raise ValueError("output_dir values must be unique")
        return self
