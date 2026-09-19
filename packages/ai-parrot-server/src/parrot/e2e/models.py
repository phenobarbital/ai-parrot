"""Strict persisted schemas for the deterministic E2E gate (FEAT-581, M2).

Every model below is a normative field contract translated from spec §2
"Data Models" (``sdd/specs/agentic-e2e-testing.spec.md``). All persisted
models use Pydantic v2 with ``extra="forbid"``, ``schema_version=1``, UTC
timestamps and finite/positive numeric constraints. IDs are validated as
nonempty safe slugs; pytest node IDs are validated to reject wildcard or
bare-directory selection (spec §2 "A node ID belongs to one scenario only;
parameterized nodes must be enumerated, not selected by wildcard or
directory.").

This module is intentionally dependency-light: only Pydantic and the
standard library. No target/provider imports, no filesystem or network
side effects — path *existence* and manifest hashing belong to
``parrot.e2e.plan`` / ``parrot.e2e.evidence`` (out of this task's scope).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

__all__ = [
    "E2EPlan",
    "TargetConfig",
    "ScenarioSpec",
    "LiveBudget",
    "ProcessIdentity",
    "RunState",
    "SourceIdentity",
    "ScenarioResult",
    "E2EVerdict",
    "VerificationResult",
]

# A nonempty "safe slug": starts with an alphanumeric, then alphanumerics,
# dash, underscore or dot. Used for feature/run/owner/target/scenario IDs.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# Pytest node IDs must select one concrete test (``path::name``), never a
# bare directory/module (which would collect everything in it) nor a glob.
_WILDCARD_CHARS = ("*", "?", "[", "]")

_PolicyLiteral = Literal["required", "optional", "none"]
_TargetKindLiteral = Literal["mcp-toolkit", "mcp-stdio", "mcp-agent", "botmanager", "ui", "browser"]
_ProfileLiteral = Literal["minimal", "full"]
_TierLiteral = Literal["deterministic", "live", "exploratory"]
_RunStatusLiteral = Literal["starting", "ready", "stopping", "stopped", "failed"]
_OutcomeLiteral = Literal["passed", "failed", "skipped", "xfailed", "xpassed", "blocked", "missing"]
_VerdictStatusLiteral = Literal["PASS", "FAIL", "BLOCKED"]
_VerificationStatusLiteral = Literal["PASS", "FAIL", "BLOCKED", "MISSING"]


def _validate_safe_id(value: str, *, field_name: str) -> str:
    """Validate a nonempty safe slug used as a stable identifier.

    Args:
        value: The candidate identifier.
        field_name: Name used in the raised error message.

    Returns:
        The validated identifier, unchanged.

    Raises:
        ValueError: If the identifier is empty or contains unsafe characters.
    """
    if not value or not _SAFE_ID_RE.match(value):
        raise ValueError(f"{field_name} must be a nonempty safe slug (matched {_SAFE_ID_RE.pattern!r}): {value!r}")
    return value


def _validate_node_id(value: str) -> str:
    """Validate one pytest node ID (spec §2: enumerated, never wildcard/directory).

    Args:
        value: The candidate pytest node ID (e.g. ``tests/e2e/test_x.py::test_y``).

    Returns:
        The validated node ID, unchanged.

    Raises:
        ValueError: If empty, contains a wildcard character, or does not
            select a concrete test (missing the ``::`` node separator).
    """
    if not value:
        raise ValueError("node_id must be nonempty")
    if any(ch in value for ch in _WILDCARD_CHARS):
        raise ValueError(f"node_id must not contain wildcard characters: {value!r}")
    if value.endswith("/") or "::" not in value:
        raise ValueError(f"node_id must select one concrete test via '::', not a directory/module: {value!r}")
    return value


def _ensure_utc(value: datetime) -> datetime:
    """Ensure a datetime is timezone-aware and expressed in UTC.

    Args:
        value: The candidate timestamp.

    Returns:
        The same instant, guaranteed to carry ``timezone.utc``.

    Raises:
        ValueError: If ``value`` is naive (no tzinfo).
    """
    if value.tzinfo is None:
        raise ValueError(f"timestamp must be timezone-aware UTC, got naive datetime: {value!r}")
    return value.astimezone(timezone.utc)


class _E2EBaseModel(BaseModel):
    """Shared strict configuration for every persisted E2E model."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class LiveBudget(_E2EBaseModel):
    """Aggregate cap on one run's optional live provider usage (spec §2 "Live Provider Budget").

    Attributes:
        model: Google model ID the budget is enforced against.
        max_calls: Maximum generation attempts across initial/continuation/repair/retry sends.
        max_output_tokens: Output token ceiling; growth on ``MAX_TOKENS`` is clamped to this value.
        max_request_bytes: Serialized request byte ceiling (history + system + tools + prompt).
        timeout_s: Maximum wall-clock seconds for the whole live session.
    """

    model: str = "google:gemini-2.5-flash-lite"
    max_calls: int = Field(default=4, gt=0)
    max_output_tokens: int = Field(default=512, gt=0)
    max_request_bytes: int = Field(default=16384, gt=0)
    timeout_s: float = Field(default=60, gt=0)

    @field_validator("model")
    @classmethod
    def _model_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model must be a nonempty model identifier")
        return value


class TargetConfig(_E2EBaseModel):
    """One supervised target's launch/readiness configuration (spec §2).

    Attributes:
        kind: Target adapter selector.
        profile: ``minimal`` (default) or ``full`` launch profile.
        startup_timeout_s: Seconds allowed for the target to become ready.
        shutdown_timeout_s: Seconds allowed for graceful shutdown before SIGKILL.
        options: Adapter-specific options; allowed keys are validated by the
            target adapter before spawn (out of scope for this schema).
    """

    kind: _TargetKindLiteral
    profile: _ProfileLiteral = "minimal"
    startup_timeout_s: float = Field(default=60, gt=0)
    shutdown_timeout_s: float = Field(default=10, gt=0)
    options: dict[str, JsonValue] = Field(default_factory=dict)


class ScenarioSpec(_E2EBaseModel):
    """One declared E2E scenario: a tier, its targets and its coverage (spec §2).

    Attributes:
        id: Stable scenario ID, unique within a plan.
        tier: ``deterministic``, ``live`` or ``exploratory``.
        target_ids: Target keys (from :class:`E2EPlan.targets`) this scenario uses.
        required: Whether the scenario must execute successfully for the gate.
        node_ids: Enumerated pytest node IDs. Nonempty for codified tiers
            (``deterministic``/``live``); must be empty for ``exploratory``.
        timeout_s: Seconds allowed for this scenario's execution.
        prerequisites: Other scenario IDs that must pass before this one runs.
        assertions: Human-readable assertion descriptions recorded as intent.
    """

    id: str
    tier: _TierLiteral
    target_ids: list[str] = Field(default_factory=list)
    required: bool = False
    node_ids: list[str] = Field(default_factory=list)
    timeout_s: float = Field(default=60, gt=0)
    prerequisites: list[str] = Field(default_factory=list)
    assertions: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _validate_safe_id(value, field_name="ScenarioSpec.id")

    @field_validator("target_ids")
    @classmethod
    def _validate_target_ids(cls, value: list[str]) -> list[str]:
        return [_validate_safe_id(v, field_name="ScenarioSpec.target_ids") for v in value]

    @field_validator("prerequisites")
    @classmethod
    def _validate_prerequisites(cls, value: list[str]) -> list[str]:
        return [_validate_safe_id(v, field_name="ScenarioSpec.prerequisites") for v in value]

    @field_validator("node_ids")
    @classmethod
    def _validate_node_ids(cls, value: list[str]) -> list[str]:
        validated = [_validate_node_id(v) for v in value]
        if len(set(validated)) != len(validated):
            raise ValueError(f"node_ids must be unique within a scenario: {value!r}")
        return validated

    @model_validator(mode="after")
    def _check_tier_coverage(self) -> "ScenarioSpec":
        """Reject required exploration and require codified node IDs (spec §2)."""
        if self.tier == "exploratory":
            if self.required:
                raise ValueError(f"exploratory scenario {self.id!r} cannot be required")
            if self.node_ids:
                raise ValueError(f"exploratory scenario {self.id!r} must declare no node_ids")
        else:
            if not self.node_ids:
                raise ValueError(f"codified scenario {self.id!r} (tier={self.tier!r}) requires explicit node_ids")
        if self.id in self.prerequisites:
            raise ValueError(f"scenario {self.id!r} cannot list itself as a prerequisite")
        return self


class E2EPlan(_E2EBaseModel):
    """The complete, validated selection and budget for one E2E run (spec §2).

    Attributes:
        schema_version: Always ``1`` for this schema generation.
        feature_id: Owning feature's stable ID (e.g. ``FEAT-581``).
        spec_path: Repository-relative path to the authoritative feature spec.
        policy: ``required``, ``optional`` or ``none``. Required demands at
            least one required, codified (non-exploratory) scenario.
        targets: Named target configurations, keyed by target ID.
        scenarios: Declared scenarios; scenario IDs and node IDs are unique.
        budget: Live-provider usage cap applied to any ``live`` scenario.
        run_timeout_s: Overall run deadline in seconds (1..3600).
    """

    schema_version: Literal[1] = 1
    feature_id: str
    spec_path: str
    policy: _PolicyLiteral
    targets: dict[str, TargetConfig] = Field(default_factory=dict)
    scenarios: list[ScenarioSpec] = Field(default_factory=list)
    budget: LiveBudget = Field(default_factory=LiveBudget)
    run_timeout_s: int = Field(default=600, ge=1, le=3600)

    @field_validator("feature_id")
    @classmethod
    def _validate_feature_id(cls, value: str) -> str:
        return _validate_safe_id(value, field_name="E2EPlan.feature_id")

    @field_validator("spec_path")
    @classmethod
    def _validate_spec_path(cls, value: str) -> str:
        if not value:
            raise ValueError("spec_path must be nonempty")
        if value.startswith("/") or ".." in value.replace("\\", "/").split("/"):
            raise ValueError(f"spec_path must be a safe worktree-relative path (no absolute/traversal): {value!r}")
        return value

    @field_validator("targets")
    @classmethod
    def _validate_target_keys(cls, value: dict[str, TargetConfig]) -> dict[str, TargetConfig]:
        for key in value:
            _validate_safe_id(key, field_name="E2EPlan.targets key")
        return value

    @model_validator(mode="after")
    def _check_plan_consistency(self) -> "E2EPlan":
        """Validate unique scenario/node ownership and required codified coverage."""
        scenario_ids = [scenario.id for scenario in self.scenarios]
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError(f"scenario IDs must be unique within a plan: {scenario_ids!r}")

        all_node_ids: list[str] = []
        for scenario in self.scenarios:
            all_node_ids.extend(scenario.node_ids)
            for target_id in scenario.target_ids:
                if target_id not in self.targets:
                    raise ValueError(
                        f"scenario {scenario.id!r} references undeclared target_id {target_id!r}"
                    )
            for prerequisite in scenario.prerequisites:
                if prerequisite not in scenario_ids:
                    raise ValueError(
                        f"scenario {scenario.id!r} references undeclared prerequisite {prerequisite!r}"
                    )
        if len(set(all_node_ids)) != len(all_node_ids):
            raise ValueError(f"node IDs must belong to exactly one scenario across the plan: {all_node_ids!r}")

        if self.policy == "required":
            has_required_codified = any(
                scenario.required and scenario.tier != "exploratory" and scenario.node_ids
                for scenario in self.scenarios
            )
            if not has_required_codified:
                raise ValueError("policy 'required' demands at least one required codified scenario")
        return self


class ProcessIdentity(_E2EBaseModel):
    """A verifiable OS process identity used to gate signaling (spec §2).

    Never sufficient to signal on ``pid`` alone: ``pgid``, ``create_time`` and
    ``boot_id`` must all match before any SIGTERM/SIGKILL is sent, guarding
    against PID reuse across reboots or foreign processes.

    Attributes:
        pid: OS process ID.
        pgid: OS process group ID.
        create_time: Process creation timestamp as reported by the OS (UTC).
        boot_id: Host boot identifier, to detect a reboot invalidating ``pid``.
        owned: Whether this process was spawned (and may be signaled) by the
            supervisor, as opposed to an adopted/foreign endpoint.
    """

    pid: int = Field(gt=0)
    pgid: int = Field(gt=0)
    create_time: datetime
    boot_id: str
    owned: bool

    @field_validator("create_time")
    @classmethod
    def _validate_create_time(cls, value: datetime) -> datetime:
        return _ensure_utc(value)

    @field_validator("boot_id")
    @classmethod
    def _validate_boot_id(cls, value: str) -> str:
        if not value:
            raise ValueError("boot_id must be nonempty")
        return value


class RunState(_E2EBaseModel):
    """Persisted, worktree-local state for one supervised run (spec §2).

    Attributes:
        schema_version: Always ``1`` for this schema generation.
        feature_id: Owning feature's stable ID.
        run_id: Stable ID for this run.
        worktree: Canonical (absolute, resolved) path of the owning worktree.
        owner_id: Identity of the runner/session that owns this run.
        controller_identity: Identity of the foreground controller process.
        supervisor_identity: Identity of the supervisor process.
        process_identity: Identity of the supervised target process.
        target_id: Target key (from :class:`E2EPlan.targets`) this state describes.
        status: Current lifecycle status.
        endpoint: Reachable target endpoint (e.g. ``http://127.0.0.1:PORT``), or
            ``None`` before readiness / for non-networked targets.
        control_socket: Path to the private Unix control socket mediating
            supervisor request/response exchange.
        started_at: UTC timestamp the run was started.
        deadline: UTC timestamp after which the watchdog forces teardown.
        log_path: Path to this run's log file.
        shutdown_forced: Whether teardown required SIGKILL after SIGTERM.
        cleanup_complete: Whether cleanup was verified complete.
    """

    schema_version: Literal[1] = 1
    feature_id: str
    run_id: str
    worktree: str
    owner_id: str
    controller_identity: ProcessIdentity
    supervisor_identity: ProcessIdentity
    process_identity: ProcessIdentity
    target_id: str
    status: _RunStatusLiteral
    endpoint: Optional[str] = None
    control_socket: str
    started_at: datetime
    deadline: datetime
    log_path: str
    shutdown_forced: bool = False
    cleanup_complete: bool = False

    @field_validator("feature_id")
    @classmethod
    def _validate_feature_id(cls, value: str) -> str:
        return _validate_safe_id(value, field_name="RunState.feature_id")

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str) -> str:
        return _validate_safe_id(value, field_name="RunState.run_id")

    @field_validator("owner_id")
    @classmethod
    def _validate_owner_id(cls, value: str) -> str:
        return _validate_safe_id(value, field_name="RunState.owner_id")

    @field_validator("target_id")
    @classmethod
    def _validate_target_id(cls, value: str) -> str:
        return _validate_safe_id(value, field_name="RunState.target_id")

    @field_validator("worktree")
    @classmethod
    def _validate_worktree(cls, value: str) -> str:
        if not value.startswith("/") or ".." in value.split("/"):
            raise ValueError(f"worktree must be a canonical absolute path (no traversal): {value!r}")
        return value

    @field_validator("started_at", "deadline")
    @classmethod
    def _validate_timestamps(cls, value: datetime) -> datetime:
        return _ensure_utc(value)

    @model_validator(mode="after")
    def _check_deadline_after_start(self) -> "RunState":
        if self.deadline < self.started_at:
            raise ValueError("deadline must not precede started_at")
        return self


class SourceIdentity(_E2EBaseModel):
    """A verifiable snapshot of the exact source/config a run was validated against (spec §2).

    Attributes:
        commit: Git commit SHA the working tree was based on.
        manifest_sha256: Hash of the canonical sorted tracked+nonignored-untracked
            file manifest (paths, modes and content hashes; never source contents).
        spec_sha256: Hash of the authoritative feature spec content.
        plan_sha256: Hash of the frozen :class:`E2EPlan` content.
        environment_sha256: Hash of the nonsecret environment fingerprint
            (interpreter, installed versions, lockfile, model, opt-ins).
        worktree: Canonical (absolute, resolved) path the manifest was captured from.
    """

    commit: str
    manifest_sha256: str
    spec_sha256: str
    plan_sha256: str
    environment_sha256: str
    worktree: str

    @field_validator("commit")
    @classmethod
    def _validate_commit(cls, value: str) -> str:
        if not re.match(r"^[0-9a-f]{7,40}$", value):
            raise ValueError(f"commit must be a hex git SHA: {value!r}")
        return value

    @field_validator("manifest_sha256", "spec_sha256", "plan_sha256", "environment_sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if not re.match(r"^[0-9a-f]{64}$", value):
            raise ValueError(f"expected a lowercase hex sha256 digest: {value!r}")
        return value

    @field_validator("worktree")
    @classmethod
    def _validate_worktree(cls, value: str) -> str:
        if not value.startswith("/") or ".." in value.split("/"):
            raise ValueError(f"worktree must be a canonical absolute path (no traversal): {value!r}")
        return value


class ScenarioResult(_E2EBaseModel):
    """Machine evidence for one executed scenario/node (spec §2).

    Attributes:
        scenario_id: The :class:`ScenarioSpec.id` this result belongs to.
        node_id: The specific pytest node ID this result reports on.
        outcome: Final outcome; ``passed``/``failed``/``skipped``/``xfailed``/
            ``xpassed``/``blocked``/``missing``. Only ``passed`` counts toward
            satisfied required coverage.
        reason_code: Machine-readable reason for a non-passed outcome, if any.
        setup_outcome: Pytest ``setup`` phase outcome, if collected.
        call_outcome: Pytest ``call`` phase outcome, if collected.
        teardown_outcome: Pytest ``teardown`` phase outcome, if collected.
        exit_code: Pytest process exit code for the run that produced this result.
        duration_s: Wall-clock seconds the node took to execute.
        target_run_ids: :class:`RunState.run_id` values this node depended on.
        artifact_paths: Relative paths of artifacts (logs, JUnit XML, screenshots)
            captured for this result; hashed centrally in :class:`E2EVerdict.artifact_hashes`.
    """

    scenario_id: str
    node_id: str
    outcome: _OutcomeLiteral
    reason_code: Optional[str] = None
    setup_outcome: Optional[str] = None
    call_outcome: Optional[str] = None
    teardown_outcome: Optional[str] = None
    exit_code: Optional[int] = None
    duration_s: float = Field(ge=0)
    target_run_ids: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)

    @field_validator("scenario_id")
    @classmethod
    def _validate_scenario_id(cls, value: str) -> str:
        return _validate_safe_id(value, field_name="ScenarioResult.scenario_id")

    @field_validator("node_id")
    @classmethod
    def _validate_node_id_field(cls, value: str) -> str:
        return _validate_node_id(value)


class E2EVerdict(_E2EBaseModel):
    """The runner-computed, atomically-persisted final evidence for one run (spec §2).

    Attributes:
        schema_version: Always ``1`` for this schema generation.
        feature_id: Owning feature's stable ID.
        run_id: Stable ID for this run.
        policy: The :class:`E2EPlan.policy` this run was evaluated against.
        source_identity_before: Source identity captured before execution.
        source_identity_after: Source identity captured after execution.
        selected_node_ids: Node IDs the plan selected for this run.
        collected_node_ids: Node IDs pytest actually collected.
        results: Per-scenario/node machine evidence.
        counts: Outcome name to count mapping (e.g. ``{"passed": 3}``).
        argv: Exact CLI argv used to invoke the run.
        exit_code: Overall process exit code (spec §2 exit mapping).
        cleanup_results: Target run ID to "cleanup verified complete" mapping.
        artifact_hashes: Relative artifact path to SHA-256 hex digest mapping.
        status: ``PASS``, ``FAIL`` or ``BLOCKED``.
        gate_satisfied: Whether required coverage was fully satisfied.
        started_at: UTC timestamp execution began.
        completed_at: UTC timestamp execution (including cleanup) completed.
    """

    schema_version: Literal[1] = 1
    feature_id: str
    run_id: str
    policy: _PolicyLiteral
    source_identity_before: SourceIdentity
    source_identity_after: SourceIdentity
    selected_node_ids: list[str] = Field(default_factory=list)
    collected_node_ids: list[str] = Field(default_factory=list)
    results: list[ScenarioResult] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    argv: list[str] = Field(default_factory=list)
    exit_code: int
    cleanup_results: dict[str, bool] = Field(default_factory=dict)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    status: _VerdictStatusLiteral
    gate_satisfied: bool
    started_at: datetime
    completed_at: datetime

    @field_validator("feature_id")
    @classmethod
    def _validate_feature_id(cls, value: str) -> str:
        return _validate_safe_id(value, field_name="E2EVerdict.feature_id")

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str) -> str:
        return _validate_safe_id(value, field_name="E2EVerdict.run_id")

    @field_validator("started_at", "completed_at")
    @classmethod
    def _validate_timestamps(cls, value: datetime) -> datetime:
        return _ensure_utc(value)

    @field_validator("artifact_hashes")
    @classmethod
    def _validate_artifact_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        for digest in value.values():
            if not re.match(r"^[0-9a-f]{64}$", digest):
                raise ValueError(f"expected a lowercase hex sha256 digest: {digest!r}")
        return value

    @model_validator(mode="after")
    def _check_completed_after_started(self) -> "E2EVerdict":
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        return self


class VerificationResult(_E2EBaseModel):
    """The read-only outcome of validating a run's evidence without executing tests (spec §2).

    ``MISSING`` is synthesized by verification itself (e.g. no evidence file
    found, or policy ``none``'s explicit exemption) — never fabricated as a
    successful run.

    Attributes:
        status: ``PASS``, ``FAIL``, ``BLOCKED`` or ``MISSING``.
        gate_satisfied: Whether required coverage was fully satisfied.
        reason_codes: Machine-readable reason codes explaining ``status``.
    """

    status: _VerificationStatusLiteral
    gate_satisfied: bool
    reason_codes: list[str] = Field(default_factory=list)
