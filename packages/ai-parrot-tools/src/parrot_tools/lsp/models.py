"""Data models for the LSP research pilot (FEAT-580, M1).

Defines the wire-safe evidence/configuration contracts consumed by the
public toolkit (``LSPToolkit``, added by a later task) and the private
snapshot/session records consumed by ``snapshot.py``/``session.py``
(also added by later tasks). Every model below performs pure, in-memory
validation only: constructing any model here never opens a file, starts a
process, or probes an executable.

Two diagnostic representations exist on purpose:

- :class:`LSPDiagnostic` is the JSON-safe, public shape returned in
  :class:`LSPResult` — its ``message`` is bounded to keep tool output
  small.
- :class:`RawDiagnostic` is the private, uncropped shape used internally
  by :class:`DiagnosticBatch` / :class:`DiagnosticSnapshot` so that
  freshness comparisons never operate on truncated text.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Sentinel ``environment_id`` meaning "no operator-provisioned dependency
#: environment yet". The toolkit must return ``status="unavailable"``,
#: ``code="invalid_request"`` before any process starts when it sees this
#: value; the model layer only guarantees the value round-trips as a plain
#: string.
OPERATOR_UNCONFIGURED_ENVIRONMENT_ID = "operator-unconfigured"

#: Fixed operational error-code vocabulary (spec §2). ``LSPResult.code``
#: and ``LSPFailure.code`` may only take one of these values (or ``None``
#: for ``LSPResult.code``).
LSP_ERROR_CODES: frozenset[str] = frozenset(
    {
        "invalid_request",
        "path_outside_root",
        "unsupported_language",
        "file_missing",
        "invalid_encoding",
        "file_too_large",
        "position_out_of_range",
        "source_changed",
        "workspace_changed",
        "workspace_limit",
        "server_missing",
        "server_version_mismatch",
        "startup_timeout",
        "request_timeout",
        "diagnostics_timeout",
        "diagnostics_unversioned",
        "unsupported_capability",
        "server_crashed",
        "protocol_error",
        "resource_limit",
        "baseline_missing",
        "baseline_scope_mismatch",
        "baseline_incompatible",
        "result_limit",
    }
)

#: Maximum length of an ``LSPFailure`` bounded detail string.
_MAX_FAILURE_DETAIL_LENGTH = 1000

#: Maximum length of a public ``LSPDiagnostic.message``.
_MAX_DIAGNOSTIC_MESSAGE_LENGTH = 1000

#: Configurable limit defaults/maxima (spec §2 "Bounds").
STARTUP_TIMEOUT_DEFAULT_S = 20.0
STARTUP_TIMEOUT_MAX_S = 60.0
REQUEST_TIMEOUT_DEFAULT_S = 10.0
REQUEST_TIMEOUT_MAX_S = 30.0
DIAGNOSTICS_TIMEOUT_DEFAULT_S = 20.0
DIAGNOSTICS_TIMEOUT_MAX_S = 60.0
IDLE_TIMEOUT_DEFAULT_S = 120.0
IDLE_TIMEOUT_MIN_S = 30.0
IDLE_TIMEOUT_MAX_S = 600.0
NODE_HEAP_DEFAULT_MB = 1024
NODE_HEAP_MAX_MB = 2048

#: Diagnostic-baseline cache bounds (spec §2 ``DiagnosticSnapshot``).
MAX_DIAGNOSTIC_SNAPSHOTS = 8
DIAGNOSTIC_SNAPSHOT_TTL_SECONDS = 1800

#: Exactly 64 lowercase hex characters — a sha256 hex digest.
SHA256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _validate_repo_relative_posix_path(value: str) -> str:
    """Validate a repository-relative POSIX path shape (no filesystem I/O).

    Args:
        value: Candidate path string.

    Returns:
        The unchanged value, once validated.

    Raises:
        ValueError: If the value is empty, uses backslashes, is absolute,
            contains a NUL byte, or contains a ``..`` traversal segment.
    """
    if not value:
        raise ValueError("path must be a non-empty string")
    if "\x00" in value:
        raise ValueError("path must not contain NUL bytes")
    if "\\" in value:
        raise ValueError("path must use POSIX '/' separators, not backslashes")
    if value.startswith("/"):
        raise ValueError("path must be repository-relative, not absolute")
    posix = PurePosixPath(value)
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError("path must be a repository-relative path with no '..' segments")
    return value


class _LSPModel(BaseModel):
    """Shared base: forbid unknown fields on every LSP wire/private model."""

    model_config = ConfigDict(extra="forbid")


class LSPConfig(_LSPModel):
    """Trusted, operator-controlled configuration for one toolkit instance.

    Validating an :class:`LSPConfig` never spawns a process, opens a file,
    or probes an executable — it only checks shapes and bounds.
    """

    repo_root: Path
    server_command: list[str] = Field(default_factory=lambda: ["pyright-langserver", "--stdio"])
    version_command: list[str] = Field(default_factory=lambda: ["pyright", "--version"])
    expected_server_version: str = "1.1.414"
    python_path: Path = Field(default_factory=lambda: Path(sys.executable))
    source_roots: list[Path] = Field(default_factory=list)
    environment_id: str = Field(min_length=1)

    startup_timeout_s: float = Field(default=STARTUP_TIMEOUT_DEFAULT_S, ge=1.0, le=STARTUP_TIMEOUT_MAX_S)
    request_timeout_s: float = Field(default=REQUEST_TIMEOUT_DEFAULT_S, ge=1.0, le=REQUEST_TIMEOUT_MAX_S)
    diagnostics_timeout_s: float = Field(default=DIAGNOSTICS_TIMEOUT_DEFAULT_S, ge=1.0, le=DIAGNOSTICS_TIMEOUT_MAX_S)
    idle_timeout_s: float = Field(default=IDLE_TIMEOUT_DEFAULT_S, ge=IDLE_TIMEOUT_MIN_S, le=IDLE_TIMEOUT_MAX_S)
    node_heap_mb: int = Field(default=NODE_HEAP_DEFAULT_MB, ge=1, le=NODE_HEAP_MAX_MB)

    @field_validator("repo_root")
    @classmethod
    def _validate_repo_root_absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("repo_root must be an absolute path")
        return value

    @field_validator("server_command", "version_command")
    @classmethod
    def _validate_argv(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("argv list must not be empty")
        if any(not isinstance(item, str) or not item for item in value):
            raise ValueError("argv entries must be non-empty strings")
        return value

    @model_validator(mode="after")
    def _validate_source_roots_in_root(self) -> "LSPConfig":
        for root in self.source_roots:
            if not root.is_absolute():
                raise ValueError(f"source_roots entries must be absolute paths: {root}")
            if not root.is_relative_to(self.repo_root):
                raise ValueError(f"source_roots entries must be within repo_root: {root}")
        return self


class SourcePosition(_LSPModel):
    """A verified, one-based Unicode position inside a repository file."""

    path: str
    line: int = Field(ge=1)
    column: int = Field(ge=1)
    expected_sha256: SHA256Hex

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _validate_repo_relative_posix_path(value)


class SourceRange(_LSPModel):
    """A one-based, end-exclusive Unicode coordinate range in a file."""

    path: str
    start_line: int = Field(ge=1)
    start_column: int = Field(ge=1)
    end_line: int = Field(ge=1)
    end_column: int = Field(ge=1)

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _validate_repo_relative_posix_path(value)

    @model_validator(mode="after")
    def _validate_end_not_before_start(self) -> "SourceRange":
        start = (self.start_line, self.start_column)
        end = (self.end_line, self.end_column)
        if end < start:
            raise ValueError("range end must not precede range start")
        return self


class SourceState(_LSPModel):
    """The exact hashed content identity of one on-disk file."""

    path: str
    sha256: SHA256Hex
    document_version: int = Field(ge=1)

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _validate_repo_relative_posix_path(value)


class LSPLocation(_LSPModel):
    """One readable, confined Python source/stub location; no source body."""

    range: SourceRange
    sha256: SHA256Hex


class LSPDiagnostic(_LSPModel):
    """Public, JSON-safe diagnostic evidence with a bounded message."""

    range: SourceRange
    severity: int = Field(default=3, ge=1, le=4)
    severity_defaulted: bool = False
    code: str | None = None
    source: str | None = None
    message: str = Field(max_length=_MAX_DIAGNOSTIC_MESSAGE_LENGTH)

    @model_validator(mode="before")
    @classmethod
    def _default_missing_severity(cls, data: Any) -> Any:
        if isinstance(data, dict) and "severity" not in data:
            data = dict(data)
            data["severity"] = 3
            data.setdefault("severity_defaulted", True)
        return data


class RawDiagnostic(_LSPModel):
    """Private, uncropped diagnostic record used for freshness comparisons.

    Mirrors :class:`LSPDiagnostic` except ``full_message`` is never
    truncated, so ``DiagnosticBatch``/``DiagnosticSnapshot`` can preserve
    complete evidence internally while the public ``LSPDiagnostic`` stays
    bounded.
    """

    range: SourceRange
    severity: int = Field(default=3, ge=1, le=4)
    severity_defaulted: bool = False
    code: str | None = None
    source: str | None = None
    full_message: str

    @model_validator(mode="before")
    @classmethod
    def _default_missing_severity(cls, data: Any) -> Any:
        if isinstance(data, dict) and "severity" not in data:
            data = dict(data)
            data["severity"] = 3
            data.setdefault("severity_defaulted", True)
        return data


class EvidenceMeta(_LSPModel):
    """Provenance/freshness metadata attached to every non-trivial result."""

    repo_root: Path
    workspace_id: str = Field(min_length=1)
    generation: int = Field(ge=0)
    workspace_digest: str = Field(min_length=1)
    environment_id: str = Field(min_length=1)
    server_version: str = Field(min_length=1)
    config_digest: str = Field(min_length=1)
    observed_at: datetime
    source_states: list[SourceState] = Field(default_factory=list)
    elapsed_ms: int = Field(ge=0)
    cold_start: bool
    coverage: Literal["selected_files", "static_references"]

    @field_validator("repo_root")
    @classmethod
    def _validate_repo_root_absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("repo_root must be an absolute path")
        return value

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError("observed_at must be a UTC-aware datetime")
        return value


class LSPResult(_LSPModel):
    """The typed envelope returned by every public toolkit method."""

    status: Literal["ok", "partial", "unavailable", "error"]
    operation: str = Field(min_length=1)
    code: str | None = None
    message: str = ""
    evidence: EvidenceMeta | None = None
    locations: list[LSPLocation] = Field(default_factory=list)
    diagnostics: list[LSPDiagnostic] = Field(default_factory=list)
    added: list[LSPDiagnostic] = Field(default_factory=list)
    removed: list[LSPDiagnostic] = Field(default_factory=list)
    snapshot_id: str | None = None
    checked_paths: list[str] = Field(default_factory=list)
    missing_paths: list[str] = Field(default_factory=list)
    truncated: bool = False
    omitted_count: int = Field(default=0, ge=0)
    fallback: str | None = None

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str | None) -> str | None:
        if value is not None and value not in LSP_ERROR_CODES:
            raise ValueError(f"code must be one of the fixed operational codes, got {value!r}")
        return value

    @field_validator("checked_paths", "missing_paths")
    @classmethod
    def _validate_path_list(cls, value: list[str]) -> list[str]:
        return [_validate_repo_relative_posix_path(item) for item in value]


class WorkspaceSnapshot(_LSPModel):
    """Private bounded snapshot of the exact files a call depends on.

    Produced by ``snapshot.py``'s ``capture_workspace`` (a later task);
    never opens or hashes anything itself.
    """

    digest: str = Field(min_length=1)
    file_hashes: dict[str, SHA256Hex] = Field(default_factory=dict)
    requested_text: dict[str, str] = Field(default_factory=dict)
    config_digest: str = Field(min_length=1)
    missing_paths: list[str] = Field(default_factory=list)

    @field_validator("file_hashes", "requested_text")
    @classmethod
    def _validate_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in value:
            _validate_repo_relative_posix_path(key)
        return value

    @field_validator("missing_paths")
    @classmethod
    def _validate_missing_paths(cls, value: list[str]) -> list[str]:
        return [_validate_repo_relative_posix_path(item) for item in value]


class DiagnosticBatch(_LSPModel):
    """Private, complete-or-explicitly-incomplete diagnostic publication set.

    Never represents unknown coverage as an empty complete list: if
    ``missing_paths`` or ``unversioned_paths`` is non-empty, ``complete``
    must be ``False``.
    """

    diagnostics: dict[str, list[RawDiagnostic]] = Field(default_factory=dict)
    matched_versions: dict[str, int] = Field(default_factory=dict)
    missing_paths: list[str] = Field(default_factory=list)
    unversioned_paths: list[str] = Field(default_factory=list)
    complete: bool

    @field_validator("diagnostics")
    @classmethod
    def _validate_diagnostics_keys(cls, value: dict[str, list[RawDiagnostic]]) -> dict[str, list[RawDiagnostic]]:
        for key in value:
            _validate_repo_relative_posix_path(key)
        return value

    @field_validator("matched_versions")
    @classmethod
    def _validate_matched_versions(cls, value: dict[str, int]) -> dict[str, int]:
        for key, version in value.items():
            _validate_repo_relative_posix_path(key)
            if version < 1:
                raise ValueError("matched document versions must be >= 1")
        return value

    @field_validator("missing_paths", "unversioned_paths")
    @classmethod
    def _validate_path_lists(cls, value: list[str]) -> list[str]:
        return [_validate_repo_relative_posix_path(item) for item in value]

    @model_validator(mode="after")
    def _validate_completeness(self) -> "DiagnosticBatch":
        if (self.missing_paths or self.unversioned_paths) and self.complete:
            raise ValueError("a batch with missing/unversioned paths cannot be complete")
        return self


class DiagnosticSnapshot(_LSPModel):
    """Private in-memory diagnostic baseline record.

    At most :data:`MAX_DIAGNOSTIC_SNAPSHOTS` snapshots are retained per
    toolkit instance (LRU eviction), each expiring after
    :data:`DIAGNOSTIC_SNAPSHOT_TTL_SECONDS` seconds. Both bounds are
    enforced by the toolkit (a later task), not by this model.
    """

    snapshot_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    paths: tuple[str, ...]
    environment_id: str = Field(min_length=1)
    config_digest: str = Field(min_length=1)
    server_version: str = Field(min_length=1)
    generation: int = Field(ge=0)
    source_states: list[SourceState] = Field(default_factory=list)
    diagnostics: dict[str, list[RawDiagnostic]] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("paths")
    @classmethod
    def _validate_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            _validate_repo_relative_posix_path(item)
        if len(set(value)) != len(value):
            raise ValueError("paths must not contain duplicates")
        if tuple(sorted(value)) != tuple(value):
            raise ValueError("paths must be exactly sorted")
        return value

    @field_validator("created_at")
    @classmethod
    def _validate_created_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError("created_at must be a UTC-aware datetime")
        return value


class LSPFailure(Exception):
    """Internal failure signal carrying one fixed operational code.

    Raised by ``snapshot.py``/``session.py`` (later tasks); the toolkit
    converts it into an :class:`LSPResult` rather than letting it escape.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in LSP_ERROR_CODES:
            raise ValueError(f"Unknown LSP operational code: {code!r}")
        if len(detail) > _MAX_FAILURE_DETAIL_LENGTH:
            detail = detail[:_MAX_FAILURE_DETAIL_LENGTH]
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)
