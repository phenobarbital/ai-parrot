"""Versioned evidence, checkpoint, compaction and background contracts.

Spec `sdd/specs/sdd-execution-optimization.spec.md` (FEAT-584), modules M2
(evidence/events, R3), M4 (finalization/checkpoint, R4/R5), M5 (compaction
receipt, R6) and M8 (background registry/status, R8). No logic, no I/O: these
are pure Pydantic v2 data contracts (`extra="forbid"`) consumed by later
tasks' modules (`evidence.py`, `checkpoint.py`, `phase_boundary.py`,
`background.py`). Identity fields are never inferred from free text -- they
are validated against the same canonical shapes used elsewhere in
`sdd_coder` (UUID `execution_id`, `TASK-<digits>` task ids, full git SHAs,
sha256 hex digests, UTC timestamps).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Reusable identity/state validators (shared shapes, not new business logic).
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"
_TASK_ID_PATTERN = r"^TASK-\d{1,5}$"

# Keys that must never appear (at any nesting depth) inside a persisted event
# payload or completion-fact bag: spec R3 "sin texto de prompts ni
# credenciales". Numeric telemetry (e.g. a `tokens` count) is not a secret
# and is intentionally not matched here.
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "prompt",
        "prompts",
        "secret",
        "secrets",
        "credential",
        "credentials",
        "password",
        "passwords",
        "api_key",
        "apikey",
        "access_token",
        "auth_token",
        "authorization",
    }
)

# Byte budgets. `payload`/`brief`/`log_tail`/`envelope` values come straight
# from spec R3/R5/R8; the event payload budget has no single number in the
# spec text (only "bound payload") so a conservative value is chosen here,
# well below the smallest neighbouring budget (the 8 KiB checkpoint brief).
_MAX_EVENT_PAYLOAD_BYTES = 4096
_MAX_CHECKPOINT_BRIEF_BYTES = 8192
_MAX_LOG_TAIL_BYTES = 4096
_MAX_STATUS_ENVELOPE_BYTES = 8192


def _check_uuid(value: str) -> str:
    """Reject a string that is not a canonical (lowercase, hyphenated) UUID.

    Applied to the same `execution_id` identity convention already used by
    `sdd_coder.models` (`ExecutionSnapshot`, `ExecutionPoolView`): a
    caller-generated UUID, never inferred from free text.
    """
    if not _UUID_RE.match(value):
        raise ValueError(f"expected a canonical UUID string, got {value!r}")
    return value


def _check_full_sha(value: str) -> str:
    """Reject an abbreviated or malformed git SHA (spec R1: 'base_sha completo')."""
    if not _FULL_SHA_RE.match(value):
        raise ValueError(f"expected a full 40-hex-char git SHA, got {value!r}")
    return value


def _check_optional_task_id(value: str | None) -> str | None:
    """Apply the closed `TASK-<1-5 digits>` shape only when a task_id is present."""
    if value is None:
        return value
    if not re.match(_TASK_ID_PATTERN, value):
        raise ValueError(f"invalid task id {value!r}; expected TASK-<1-5 digits>")
    return value


def _require_utc(value: datetime | None) -> datetime | None:
    """Reject a naive or non-UTC timestamp (spec R3: 'timestamps UTC para correlación')."""
    if value is None:
        return value
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"timestamp must be timezone-aware UTC, got {value!r}")
    return value


def _scan_forbidden_keys(node: object, *, path: str = "payload") -> None:
    """Recursively reject forbidden keys (prompts/secrets/credentials) in a payload."""
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in _FORBIDDEN_PAYLOAD_KEYS:
                raise ValueError(f"{path}.{key} is a forbidden key: prompts/credentials are never persisted")
            _scan_forbidden_keys(value, path=f"{path}.{key}")
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            _scan_forbidden_keys(item, path=f"{path}[{index}]")


class OptimizationModel(BaseModel):
    """Reject extra keys; never manufacture unknown measurements."""

    model_config = ConfigDict(extra="forbid")


class EvidenceRef(OptimizationModel):
    """Resolve content-addressed references only under durable storage."""

    artifact_id: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256_HEX_PATTERN)
    relative_path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1)


# Minimal event kinds from spec R3, mapped to the identity fields each one
# must carry when present. A kind outside this table is a producer-defined
# extension: R3 lists these ten as the *minimum* set, not a closed one, so
# unknown kinds are accepted without an extra identity requirement.
_EVENT_KIND_REQUIRED_IDENTITY: dict[str, tuple[str, ...]] = {
    "attempt.dispatched": ("task_id", "attempt_uid"),
    "attempt.finished": ("task_id", "attempt_uid"),
    "delivery.observed": ("task_id", "attempt_uid"),
    "merge.finished": ("task_id",),
    "validation.finished": ("job_id",),
    "task.accepted": ("task_id",),
    "review.checkpoint": (),
    "compaction.requested": (),
    "compaction.finished": (),
    "review.started": (),
    "review.finished": (),
}


class WorkflowEvent(OptimizationModel):
    """One bounded event with explicit source and clock provenance."""

    schema_version: Literal[1] = 1
    event_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    execution_id: str
    task_id: str | None = None
    attempt_uid: str | None = None
    job_id: str | None = None
    timestamp: datetime
    source: Literal["engine", "worker_observation", "transcript_import"]
    payload: dict[str, object] = Field(default_factory=dict)

    _exec_uuid = field_validator("execution_id")(_check_uuid)
    _task_id_shape = field_validator("task_id")(_check_optional_task_id)
    _ts_utc = field_validator("timestamp")(_require_utc)

    @model_validator(mode="after")
    def _validate_identity_and_payload(self) -> "WorkflowEvent":
        """Enforce per-kind required identity and a bounded, secret-free payload."""
        required = _EVENT_KIND_REQUIRED_IDENTITY.get(self.kind, ())
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(f"event kind {self.kind!r} requires {missing} to be set")

        _scan_forbidden_keys(self.payload)

        encoded = json.dumps(self.payload, sort_keys=True, default=str).encode("utf-8")
        if len(encoded) > _MAX_EVENT_PAYLOAD_BYTES:
            raise ValueError(f"payload exceeds {_MAX_EVENT_PAYLOAD_BYTES} bytes ({len(encoded)} bytes)")

        self._reject_reversed_window()
        return self

    def _reject_reversed_window(self) -> None:
        """Reject a reversed `started_at`/`ended_at` window carried in the payload.

        Only `*.finished`/`*.observed` kinds are expected to carry a settled
        span (spec R3); other kinds are not constrained by this check.
        """
        if not (self.kind.endswith(".finished") or self.kind.endswith(".observed")):
            return
        started_raw = self.payload.get("started_at")
        ended_raw = self.payload.get("ended_at")
        if started_raw is None or ended_raw is None:
            return
        try:
            started = datetime.fromisoformat(str(started_raw))
            ended = datetime.fromisoformat(str(ended_raw))
        except ValueError as exc:
            raise ValueError(f"payload started_at/ended_at must be ISO-8601 timestamps: {exc}") from exc
        if ended < started:
            raise ValueError(f"payload has a reversed window: ended_at {ended} < started_at {started}")


class TaskCompletionEvidence(OptimizationModel):
    """Green checks and semantic review tied to one implementation revision."""

    feature_slug: str = Field(min_length=1)
    task_id: str = Field(pattern=_TASK_ID_PATTERN)
    implementation_sha: str
    validation_refs: list[EvidenceRef]
    review_evidence: EvidenceRef
    fix_commits: list[str] = Field(default_factory=list)
    completion_facts: dict[str, object]

    _impl_sha = field_validator("implementation_sha")(_check_full_sha)

    @field_validator("fix_commits")
    @classmethod
    def _check_fix_commits(cls, value: list[str]) -> list[str]:
        """Every fix commit must be a full SHA (spec R4 identity, no abbreviations)."""
        return [_check_full_sha(item) for item in value]


class ReviewCheckpoint(OptimizationModel):
    """Neutral continuation identity, criteria, constraints and evidence."""

    schema_version: Literal[1] = 1
    checkpoint_id: str = Field(pattern=_SHA256_HEX_PATTERN)
    feature: str = Field(min_length=1)
    execution_id: str
    worktree: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    base_sha: str
    implementation_head: str
    spec_hash: str = Field(pattern=_SHA256_HEX_PATTERN)
    index_hash: str = Field(pattern=_SHA256_HEX_PATTERN)
    convention_hashes: dict[str, str]
    task_refs: list[EvidenceRef]
    criteria_refs: list[EvidenceRef]
    commits: list[str]
    validation_refs: list[EvidenceRef]
    evidence_refs: list[EvidenceRef]
    user_constraints: list[str]
    user_constraint_refs: list[EvidenceRef] = Field(default_factory=list)
    pending_actions: list[str]
    settlement_ref: EvidenceRef
    neutral_brief: str
    context_id: str | None = None

    _exec_uuid = field_validator("execution_id")(_check_uuid)
    _base_sha = field_validator("base_sha")(_check_full_sha)
    _head_sha = field_validator("implementation_head")(_check_full_sha)

    @field_validator("commits")
    @classmethod
    def _check_commits(cls, value: list[str]) -> list[str]:
        """Every recorded commit must be a full SHA (spec R5 `commits`)."""
        return [_check_full_sha(item) for item in value]

    @field_validator("convention_hashes")
    @classmethod
    def _check_convention_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        """Every convention-file hash must be a 64-hex-char sha256 digest."""
        for file_path, digest in value.items():
            if not re.match(_SHA256_HEX_PATTERN, digest):
                raise ValueError(f"convention_hashes[{file_path!r}] is not a sha256 hex digest: {digest!r}")
        return value

    @field_validator("neutral_brief")
    @classmethod
    def _check_brief_size(cls, value: str) -> str:
        """Reject a brief exceeding the 8 KiB budget (spec R5)."""
        size = len(value.encode("utf-8"))
        if size > _MAX_CHECKPOINT_BRIEF_BYTES:
            raise ValueError(f"neutral_brief exceeds {_MAX_CHECKPOINT_BRIEF_BYTES} bytes ({size} bytes)")
        return value

    @model_validator(mode="after")
    def _validate_checkpoint_id(self) -> "ReviewCheckpoint":
        """Reject a `checkpoint_id` that does not match its own canonical content hash.

        Spec R5/AC: the hash excludes `checkpoint_id` itself, so a caller
        cannot forge or silently mutate a checkpoint without recomputing it.
        """
        expected = self._canonical_hash()
        if self.checkpoint_id != expected:
            raise ValueError(
                f"checkpoint_id {self.checkpoint_id!r} does not match its canonical content hash {expected!r}"
            )
        return self

    def _canonical_hash(self) -> str:
        """Sha256 hex digest of every field except `checkpoint_id`, canonical JSON."""
        canonical_fields = self.model_dump(mode="json", exclude={"checkpoint_id"})
        canonical = json.dumps(canonical_fields, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def compute_checkpoint_id(cls, **fields: object) -> str:
        """Compute the deterministic `checkpoint_id` for a field set excluding it.

        Producers (spec M4 `prepare_review_checkpoint`) call this with every
        other field -- as raw values, `EvidenceRef` instances or their
        `model_dump()` form, either works -- to obtain the value to pass as
        `checkpoint_id` before constructing the model. Fields left out because
        they only carry their declared default (e.g. an empty
        `user_constraint_refs`) are filled in the same way the model itself
        would fill them, via an unvalidated `model_construct`, so the digest
        matches exactly what the model recomputes for itself on construction.
        The canonical JSON uses sorted keys and no insignificant whitespace so
        the digest is stable across processes and independent of
        field-construction order.
        """
        fields.pop("checkpoint_id", None)
        placeholder = cls.model_construct(checkpoint_id="0" * 64, **fields)
        return placeholder._canonical_hash()


class CompactionReceipt(OptimizationModel):
    """Actual outcome, including unsupported or still-unsettled requests."""

    checkpoint_id: str = Field(pattern=_SHA256_HEX_PATTERN)
    context_id: str = Field(min_length=1)
    status: Literal["completed", "skipped", "unsupported", "failed", "in_progress"]
    reason: str = Field(min_length=1, max_length=2048)
    backend: Literal["jev", "builtin", "unknown"]
    before_bytes: int | None = Field(default=None, ge=0)
    after_bytes: int | None = Field(default=None, ge=0)
    before_tokens: int | None = Field(default=None, ge=0)
    after_tokens: int | None = Field(default=None, ge=0)
    elapsed_ms: int = Field(ge=0)


class BackgroundRegistration(OptimizationModel):
    """Opaque launch identity bound to its true owner and worktree."""

    handle: str = Field(min_length=1)
    execution_id: str
    task_id: str | None = None
    attempt_uid: str | None = None
    launch_id: str = Field(min_length=1)
    owner_instance_id: str = Field(min_length=1)
    kind: Literal["mcp_job", "validation", "native_agent", "host_bridge"]
    authority: Literal["supervisor", "engine", "host_observation"]
    worktree: str = Field(min_length=1)
    backend: str = Field(min_length=1)
    started_at: datetime | None = None
    registered_log_ref: EvidenceRef | None = None

    _exec_uuid = field_validator("execution_id")(_check_uuid)
    _task_id_shape = field_validator("task_id")(_check_optional_task_id)
    _started_utc = field_validator("started_at")(_require_utc)

    @field_validator("worktree")
    @classmethod
    def _check_worktree_absolute(cls, value: str) -> str:
        """Reject a non-absolute worktree path (spec R8: 'worktree canónico')."""
        if not value.startswith("/"):
            raise ValueError(f"worktree must be an absolute path, got {value!r}")
        return value


class BackgroundStatus(OptimizationModel):
    """Known status is distinct from successful validation or task acceptance."""

    state: Literal["pending", "running", "finished", "unknown"]
    outcome: Literal["completed", "failed", "timed_out", "cancelled"] | None = None
    exit_code: int | None = None
    source: str = Field(min_length=1)
    authority: Literal["supervisor", "engine", "host_observation"]
    verified_at: datetime | None
    stale: bool
    revision: int = Field(ge=0)
    changed: bool
    log_tail: str | None = None
    log_ref: EvidenceRef | None = None
    log_truncated: bool = False
    elapsed_ms: int = Field(ge=0)
    next_poll_after_ms: int = Field(ge=0)

    _verified_utc = field_validator("verified_at")(_require_utc)

    @field_validator("log_tail")
    @classmethod
    def _check_log_tail_bounded(cls, value: str | None) -> str | None:
        """Reject a tail exceeding the 4 KiB budget (spec R8 `tail_bytes` 0-4096)."""
        if value is None:
            return value
        size = len(value.encode("utf-8"))
        if size > _MAX_LOG_TAIL_BYTES:
            raise ValueError(f"log_tail exceeds {_MAX_LOG_TAIL_BYTES} bytes ({size} bytes)")
        return value

    @model_validator(mode="after")
    def _validate_state_semantics(self) -> "BackgroundStatus":
        """Enforce the R8 state machine.

        Unresolved states (`pending`/`running`) carry no outcome/exit_code
        yet; `finished` always carries a known outcome (never implies
        acceptance); `unknown` (authority lost, e.g. after a restart) never
        carries a stale exit_code; `host_observation` authority (native
        agent handback) never fabricates a POSIX exit code. A `124` exit
        code alone is never converted into `outcome='timed_out'` by this
        model -- that requires a deadline event the caller must supply.
        """
        if self.state in ("pending", "running") and (self.outcome is not None or self.exit_code is not None):
            raise ValueError(f"state {self.state!r} must not carry an outcome or exit_code yet")
        if self.state == "finished" and self.outcome is None:
            raise ValueError("state 'finished' requires a known outcome")
        if self.state == "unknown" and self.exit_code is not None:
            raise ValueError("state 'unknown' must not carry an exit_code (spec R8: exit_code=null)")
        if self.authority == "host_observation" and self.exit_code is not None:
            raise ValueError("host_observation authority never yields a POSIX exit_code")
        return self

    @model_validator(mode="after")
    def _validate_envelope_size(self) -> "BackgroundStatus":
        """Reject a serialized envelope over the 8 KiB response budget (spec R8)."""
        size = len(self.model_dump_json().encode("utf-8"))
        if size > _MAX_STATUS_ENVELOPE_BYTES:
            raise ValueError(f"status envelope exceeds {_MAX_STATUS_ENVELOPE_BYTES} bytes ({size} bytes)")
        return self
