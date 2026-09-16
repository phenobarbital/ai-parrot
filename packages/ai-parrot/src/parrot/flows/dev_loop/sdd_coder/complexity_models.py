"""Pydantic complexity models for deterministic SDD task routing (spec §2-§4).

No logic, no I/O. All structured values use Pydantic models, extra fields forbidden.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MetricEvidence(BaseModel):
    """Evidence snapshot for one metric family.

    Attributes:
        state: Measurement outcome - ok (valid measurement), unknown (tool failed
            or result unavailable), not_applicable (metric does not apply to this task).
        value: The measured integer value, or None if state is not 'ok'.
        reason: Human-readable explanation of the state, including tool name/version
            for unknown, or the rationale for not_applicable.
        source: Origin of the measurement (e.g., 'ruff', 'wikitoolkit', 'task_parser').
    """

    model_config = ConfigDict(extra="forbid")

    state: Literal["ok", "unknown", "not_applicable"]
    value: Optional[int] = None
    reason: str
    source: str

    @model_validator(mode="after")
    def _value_requires_ok(self) -> "MetricEvidence":
        """Enforce per-state value semantics (spec §2).

        `ok` requires a measured value. `not_applicable` is never a
        measurement and must carry no value. `unknown` may optionally
        carry an observed lower bound (e.g. a partial count before a
        tool timed out); an absent value is equally valid for `unknown`.
        """
        if self.state == "ok" and self.value is None:
            raise ValueError("state 'ok' requires a value")
        if self.state == "not_applicable" and self.value is not None:
            raise ValueError(f"state {self.state!r} requires value to be None")
        return self


class ComplexityTarget(BaseModel):
    """One file target from the task's Files to Create / Modify table.

    Attributes:
        path: Repo-relative path to the target file.
        action: The declared action - CREATE or MODIFY.
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    action: Literal["CREATE", "MODIFY"]


class ComplexityContract(BaseModel):
    """Machine-readable contract declaring task targets and existing symbols.

    Attributes:
        schema_version: Must be 1 for this specification.
        targets: Tuple of ComplexityTarget entries from the task.
        contract_symbols: Tuple of symbol IDs (e.g., 'sym:path#SymbolName') that
            the task's Codebase Contract verified. None indicates legacy missing
            coverage; empty tuple is an explicit declaration of zero symbols.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    targets: Tuple[ComplexityTarget, ...]
    contract_symbols: Optional[Tuple[str, ...]] = None


class StrongModelIdentity(BaseModel):
    """A canonical model candidate and its backend mapping.

    Attributes:
        canonical_model: The policy-level identifier (e.g., 'gpt-5.6-terra', 'sonnet-5').
        backend: The backend name that provides this model (e.g., 'codex', 'claude', 'native').
        model: The exact deployed model identifier as reported by the provider.
    """

    model_config = ConfigDict(extra="forbid")

    canonical_model: str
    backend: str
    model: str


class ComplexityPolicy(BaseModel):
    """Versioned policy governing complexity classification and routing.

    Attributes:
        version: Policy version string (e.g., 'v1').
        strong_models: Tuple of allowed model identities for complex/unknown tasks.
        bands: Mapping from metric name to (min_points, max_points) tuples for scoring.
            Each band contributes at most 2 points.
        hard_limits: Mapping from metric name to threshold that triggers complex
            classification directly, regardless of total_points (spec §2's three named
            hard triggers only: cyclomatic_max, blast_symbols, downstream_tasks).
        two_point_thresholds: Mapping from EVERY metric name to the value at/above which
            it scores 2 points (spec's "inclusive bands" second boundary, all six
            metrics: 11/21, 10/30, 4/8, 2/3, 5/8, 2/5). Distinct from hard_limits: scoring
            2 points on weighted_files/modules/acceptance_criteria contributes to
            total_points but never auto-triggers complex by itself, unlike the three
            hard_limits metrics.
        score_threshold: Total points at or above which a task is classified complex.
        timeout_seconds: Maximum seconds to wait for any measurement tool.
        max_output_bytes: Maximum bytes to capture from measurement tool output.
        max_concurrency: Maximum parallel measurement operations.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = "v1"
    strong_models: Tuple[StrongModelIdentity, ...] = ()
    bands: Dict[str, Tuple[int, int]] = Field(
        default_factory=lambda: {
            "cyclomatic_max": (0, 10),
            "blast_symbols": (0, 9),
            "weighted_files": (0, 3),
            "modules": (0, 1),
            "acceptance_criteria": (0, 4),
            "downstream_tasks": (0, 1),
        }
    )
    hard_limits: Dict[str, int] = Field(
        default_factory=lambda: {
            "cyclomatic_max": 21,
            "blast_symbols": 30,
            "downstream_tasks": 5,
        }
    )
    two_point_thresholds: Dict[str, int] = Field(
        default_factory=lambda: {
            "cyclomatic_max": 21,
            "blast_symbols": 30,
            "weighted_files": 8,
            "modules": 3,
            "acceptance_criteria": 8,
            "downstream_tasks": 5,
        }
    )
    score_threshold: int = 5
    timeout_seconds: int = 30
    max_output_bytes: int = 8388608
    max_concurrency: int = 4

    @model_validator(mode="after")
    def _validate_bands(self) -> "ComplexityPolicy":
        """Reject negative or non-ascending band bounds."""
        for key, (low, high) in self.bands.items():
            if low < 0 or high < 0:
                raise ValueError(f"band {key!r} has negative bound: ({low}, {high})")
            if low > high:
                raise ValueError(f"band {key!r} is non-ascending: ({low}, {high})")
        return self

    @model_validator(mode="after")
    def _validate_hard_limits(self) -> "ComplexityPolicy":
        """Reject non-positive hard limits or unknown metric keys."""
        known_metrics = set(self.bands.keys())
        for key, value in self.hard_limits.items():
            if key not in known_metrics:
                raise ValueError(f"hard_limit references unknown metric {key!r}")
            if value <= 0:
                raise ValueError(f"hard_limit {key!r} must be positive, got {value}")
        return self

    @model_validator(mode="after")
    def _validate_two_point_thresholds(self) -> "ComplexityPolicy":
        """Reject unknown metric keys or a threshold not strictly above its band's max
        (the 2-points tier must start after the 0-points band ends)."""
        for key, value in self.two_point_thresholds.items():
            if key not in self.bands:
                raise ValueError(f"two_point_thresholds references unknown metric {key!r}")
            if value <= 0:
                raise ValueError(f"two_point_thresholds {key!r} must be positive, got {value}")
            band_max = self.bands[key][1]
            if value <= band_max:
                raise ValueError(f"two_point_thresholds {key!r} ({value}) must exceed its band max ({band_max})")
        return self

    @model_validator(mode="after")
    def _validate_strong_models(self) -> "ComplexityPolicy":
        """Reject duplicate or ambiguous backend+model mappings."""
        seen: Dict[Tuple[str, str], str] = {}  # (backend, model) -> canonical_model
        for sm in self.strong_models:
            key = (sm.backend, sm.model)
            if key in seen:
                raise ValueError(
                    f"ambiguous model mapping: ({sm.backend!r}, {sm.model!r}) "
                    f"maps to both {seen[key]!r} and {sm.canonical_model!r}"
                )
            seen[key] = sm.canonical_model
        return self


class ComplexityEvidence(BaseModel):
    """Complete evidence snapshot for one task's complexity assessment.

    Attributes:
        task_id: The task identifier (e.g., 'TASK-3286').
        contract: The ComplexityContract parsed from the task.
        metrics: Dictionary of metric name to MetricEvidence.
        head_sha: Git HEAD SHA at time of collection.
        task_sha256: SHA-256 of the task file content.
        index_sha256: SHA-256 of the per-spec index file.
        policy_sha256: SHA-256 of the ComplexityPolicy used.
        target_hashes: Mapping from target path to content hash, or None for CREATE.
        wiki_evidence_hashes: Mapping from symbol root to wiki query result hash.
        collector_versions: Mapping from collector name to version string.
        details: Additional diagnostic information including direct dependents,
            CREATE/MODIFY counts, impacted files, per-function values and raw results.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    contract: ComplexityContract
    metrics: Dict[str, MetricEvidence]
    head_sha: str
    task_sha256: str
    index_sha256: str
    policy_sha256: str
    target_hashes: Dict[str, Optional[str]]
    wiki_evidence_hashes: Dict[str, str]
    collector_versions: Dict[str, str]
    details: Dict[str, Any]

    @model_validator(mode="after")
    def _validate_create_hashes(self) -> "ComplexityEvidence":
        """Ensure CREATE targets have explicit None, not missing entries."""
        for target in self.contract.targets:
            if target.action == "CREATE":
                if target.path not in self.target_hashes:
                    raise ValueError(f"CREATE target {target.path!r} missing from target_hashes")
        return self


class ComplexityAssessment(BaseModel):
    """Immutable complexity classification result for one task.

    Attributes:
        schema_version: Must be 1 for this specification.
        policy_version: The ComplexityPolicy version used.
        task_id: The task identifier.
        classification: One of 'standard', 'complex', or 'unknown'.
        total_points: Sum of component points per policy bands.
        component_points: Per-metric point contribution.
        reason_codes: Tuple of reason codes explaining the classification.
        evidence: The ComplexityEvidence this assessment is based on (owned/copied).
        assessment_id: SHA-256 of canonical JSON representation.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    policy_version: str
    task_id: str
    classification: Literal["standard", "complex", "unknown"]
    total_points: int
    component_points: Dict[str, int]
    reason_codes: Tuple[str, ...]
    evidence: ComplexityEvidence
    assessment_id: str

    @model_validator(mode="after")
    def _freeze_evidence(self) -> "ComplexityAssessment":
        """Ensure evidence is owned/copied so caller mutations cannot change assessment."""
        # Create a deep copy by re-serializing and parsing

        evidence_json = self.evidence.model_dump_json()
        self.evidence = ComplexityEvidence.model_validate_json(evidence_json)
        return self


COMPLEXITY_ERROR_CODES: frozenset[str] = frozenset(
    {
        "complexity_contract_invalid",
        "complexity_plan_stale",
        "complex_model_unavailable",
        "complexity_audit_failed",
    }
)
"""The four complexity-specific error codes (spec §2). Mirrored into
`sdd_coder.models.ERROR_CODES` (the closed set for `CoderError.code`); kept
local here, rather than imported back from `models.py`, because `models.py`
imports from this module and a reverse import would create a cycle.
"""


class ComplexityBlock(BaseModel):
    """A routing block preventing task dispatch.

    Attributes:
        task_id: The task identifier.
        assessment_id: The ComplexityAssessment ID if available, else None.
        code: One of the complexity error codes.
        message: Human-readable explanation.
        details: Additional diagnostic information.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    assessment_id: Optional[str] = None
    code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_code(self) -> "ComplexityBlock":
        """Reject any code outside the closed complexity error-code set."""
        if self.code not in COMPLEXITY_ERROR_CODES:
            raise ValueError(f"unknown error code: {self.code!r}")
        return self
