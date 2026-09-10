"""Pydantic contracts for the tool-optimizations toolkits (FEAT-543).

This module holds every typed contract shared by :class:`LocalGitToolkit`,
:class:`BoundedSourceToolkit` and :class:`TargetedWriterToolkit`:

* Operation results (:class:`StepResult`, :class:`OperationError`,
  :class:`OperationResult`).
* Bounded-reader results (:class:`SourceInfo`, :class:`SourceResult`).
* Delegation contracts (:class:`ReferenceSlice`, :class:`TargetFile`,
  :class:`DelegationPacket`, :class:`WriterLimits`, :class:`PatchManifest`).
* Per-tool argument models, used both as ``@tool_schema`` schemas and as the
  raw-argument validation seam in
  :meth:`~parrot_tools.tool_optimizations.base.OptimizationToolkitBase._pre_execute`.

Every model sets ``extra="forbid"``: the argument models see *raw* MCP input
(``MCPToolAdapter.execute`` calls ``tool._execute(**arguments)`` directly), so
unknown keys must be rejected rather than silently dropped.

Note:
    ``from __future__ import annotations`` is deliberately **not** used here.
    ``ToolkitTool`` reads ``func._args_schema`` and calls ``model_json_schema()``
    on these classes; keeping annotations eager avoids any string-annotation
    resolution surprises at schema-generation time.
"""

import re
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

__all__ = (
    "OperationError",
    "StepResult",
    "OperationResult",
    "SourceInfo",
    "SourceResult",
    "WriterLimits",
    "ReferenceSlice",
    "TargetFile",
    "DelegationPacket",
    "PatchManifest",
    "GitRecentArgs",
    "GitFetchArgs",
    "GitPreflightArgs",
    "GitPrepareFilesArgs",
    "GitPullArgs",
    "GitPushArgs",
    "SourceInfoArgs",
    "SourceReadArgs",
    "WriterGenerateArgs",
    "WriterApplyArgs",
)

#: Bounded string used by every caller-supplied string argument.
ShortStr = Annotated[str, StringConstraints(min_length=1, max_length=4096)]

#: A lowercase hex SHA-256 digest.
Sha256Str = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

#: An opaque artifact identifier (32 lowercase hex characters).
ArtifactIdStr = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class _StrictModel(BaseModel):
    """Base class applying ``extra='forbid'`` to every contract."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Operation results
# --------------------------------------------------------------------------- #
class OperationError(_StrictModel):
    """A structured, machine-readable operation failure.

    Attributes:
        code: A snake_case error code (e.g. ``range_required``,
            ``path_outside_root``, ``secret_file``, ``unrelated_staged``).
        message: A short human-readable explanation.
        details: Optional structured context for the caller.
    """

    code: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., max_length=4096)
    details: Dict[str, Any] = Field(default_factory=dict)


class StepResult(_StrictModel):
    """The outcome of one independent step inside a composite operation.

    Success is never inferred from the last command alone: every step records
    its own exit code, timeout flag and whether it changed state.

    Attributes:
        name: The step identifier (e.g. ``git_status``).
        exit_code: The process exit code, or ``None`` when it never ran or
            timed out.
        timed_out: True when the step exceeded its timeout.
        state_changed: True when the step mutated repository or index state.
        stdout: Bounded standard output.
        stderr: Bounded standard error.
        truncated: True when ``stdout``/``stderr`` were clipped to fit a budget.
    """

    name: str = Field(..., min_length=1, max_length=128)
    exit_code: Optional[int] = None
    timed_out: bool = False
    state_changed: bool = False
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False


class OperationResult(_StrictModel):
    """The bounded domain result returned by every optimization tool.

    ``status`` is the *domain* outcome; the MCP ``isError`` flag is reserved
    for argument rejection and crashes.

    Attributes:
        status: ``ok``, ``error`` or ``uncertain`` (e.g. a push that timed out
            after transmission, whose remote effect is unknown).
        operation: The tool/method name that produced this result.
        data: The bounded operation payload.
        error: Structured failure details when ``status`` is not ``ok``.
        steps: Per-step outcomes, in execution order.
        truncated: True when content was reduced to fit the byte budget.
        diagnostic_path: Optional repo-relative path to a retained diagnostic.
        elapsed_ms: Wall-clock duration of the operation, in milliseconds.
    """

    status: Literal["ok", "error", "uncertain"]
    operation: str = Field(..., min_length=1, max_length=128)
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[OperationError] = None
    steps: List[StepResult] = Field(default_factory=list)
    truncated: bool = False
    diagnostic_path: Optional[str] = None
    elapsed_ms: int = Field(..., ge=0)


# --------------------------------------------------------------------------- #
# Bounded reader results
# --------------------------------------------------------------------------- #
class SourceInfo(_StrictModel):
    """Bounded metadata about a source file, with no file content.

    Attributes:
        path: Repo-relative POSIX path.
        sha256: SHA-256 of the on-disk bytes.
        size_bytes: On-disk size in bytes.
        line_count: Exact logical line count, or ``None`` when only threshold
            detection ran (large files short-circuit exact counting).
        is_large: True when either configured threshold is exceeded.
        max_lines: The configured line threshold in effect.
        large_file_bytes: The configured byte threshold in effect.
        range_required: True when a read must supply both range ends.
    """

    path: str = Field(..., min_length=1)
    sha256: Sha256Str
    size_bytes: int = Field(..., ge=0)
    line_count: Optional[int] = Field(default=None, ge=0)
    is_large: bool
    max_lines: int = Field(..., ge=1)
    large_file_bytes: int = Field(..., ge=1)
    range_required: bool


class SourceResult(_StrictModel):
    """A bounded slice of a source file with an explicit continuation cursor.

    Attributes:
        path: Repo-relative POSIX path.
        sha256: SHA-256 of the whole file's on-disk bytes (the revision).
        size_bytes: On-disk size in bytes.
        start_line: First returned line, 1-based inclusive.
        end_line: Last returned line, 1-based inclusive. ``0`` with an empty
            ``content`` denotes an empty file.
        content: The returned complete lines.
        truncated: True when fewer lines were returned than requested because
            of the serialized byte budget.
        next_line: The line to request next, or ``None`` at EOF.
        eof: True when the returned range reaches the end of the file.
    """

    path: str = Field(..., min_length=1)
    sha256: Sha256Str
    size_bytes: int = Field(..., ge=0)
    start_line: int = Field(..., ge=0)
    end_line: int = Field(..., ge=0)
    content: str = ""
    truncated: bool = False
    next_line: Optional[int] = Field(default=None, ge=1)
    eof: bool = False


# --------------------------------------------------------------------------- #
# Delegation contracts
# --------------------------------------------------------------------------- #
class WriterLimits(_StrictModel):
    """Hard budgets applied to one delegated generation operation.

    Attributes:
        max_packet_bytes: Maximum serialized delegation-packet size.
        max_context_bytes: Maximum size of the locally built prompt context.
        max_patch_bytes: Maximum size of the generated unified patch.
        max_output_tokens: Maximum model output tokens.
        generation_deadline_seconds: Overall deadline for the operation,
            covering transport retries and the optional repair call.
        max_repairs: At most one repair attempt for a valid packet.
    """

    max_packet_bytes: int = Field(default=128_000, gt=0)
    max_context_bytes: int = Field(default=128_000, gt=0)
    max_patch_bytes: int = Field(default=128_000, gt=0)
    max_output_tokens: int = Field(default=8_192, gt=0)
    generation_deadline_seconds: int = Field(default=180, gt=0)
    max_repairs: Literal[0, 1] = 1


class ReferenceSlice(_StrictModel):
    """A hashed, bounded excerpt of an existing file included as context.

    Attributes:
        path: Repo-relative POSIX path of the referenced file.
        sha256: SHA-256 of the referenced file's bytes, checked for freshness.
        start_line: First referenced line, 1-based inclusive.
        end_line: Last referenced line, 1-based inclusive.
        purpose: Why the delegate needs this excerpt.
    """

    path: ShortStr
    sha256: Sha256Str
    start_line: int = Field(..., ge=1)
    end_line: int = Field(..., ge=1)
    purpose: str = Field(..., min_length=1, max_length=4096)

    @model_validator(mode="after")
    def _check_range(self) -> "ReferenceSlice":
        """Reject an inverted line range."""
        if self.start_line > self.end_line:
            raise ValueError("start_line must be <= end_line")
        return self


class TargetFile(_StrictModel):
    """One file the delegate is allowed to create or modify.

    Attributes:
        path: Repo-relative POSIX path.
        action: ``create`` (the file must be absent) or ``modify``.
        expected_sha256: Required for ``modify`` (the baseline revision);
            must be ``None`` for ``create``, whose precondition is absence.
        planned_changes: The already-decided change description.
        blocks: Identifiers of the labelled TASK code blocks that specify
            this file's implementation. At least one is required.
    """

    path: ShortStr
    action: Literal["create", "modify"]
    expected_sha256: Optional[Sha256Str] = None
    planned_changes: str = Field(..., min_length=1, max_length=65_536)
    blocks: List[ShortStr] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _check_action_hash(self) -> "TargetFile":
        """Bind the expected hash to the declared action."""
        if self.action == "modify" and self.expected_sha256 is None:
            raise ValueError("action 'modify' requires expected_sha256")
        if self.action == "create" and self.expected_sha256 is not None:
            raise ValueError("action 'create' must not set expected_sha256 (its precondition is absence)")
        return self


class DelegationPacket(_StrictModel):
    """The complete, already-decided implementation contract for one TASK.

    ``design_complete`` is an eligibility *declaration*, not proof of
    correctness: this model checks structural completeness, while the
    thinking model verifies semantics.

    Attributes:
        schema_version: Always ``1`` in v1.
        task_id: The owning task identifier (``TASK-<NNN>``).
        spec_path: Repo-relative path of the governing spec.
        design_complete: Must be ``True``; a packet is otherwise ineligible.
        targets: The approved file scope (at least one, unique paths).
        references: Hashed bounded excerpts supplied as read-only context.
        implementation_blocks: Labels of the decided code blocks in the TASK.
        acceptance_criteria: The criteria the change must satisfy.
        validation_commands: argv lists owned by the SDD workflow. No command
            from a model response is ever executed.
        limits: The budgets for this delegation.
    """

    schema_version: Literal[1]
    task_id: str = Field(..., pattern=r"^TASK-\d{3,}$")
    spec_path: ShortStr
    design_complete: Literal[True]
    targets: List[TargetFile] = Field(..., min_length=1)
    references: List[ReferenceSlice] = Field(default_factory=list)
    implementation_blocks: List[ShortStr] = Field(..., min_length=1)
    acceptance_criteria: List[ShortStr] = Field(..., min_length=1)
    validation_commands: List[List[ShortStr]] = Field(default_factory=list)
    limits: WriterLimits = Field(default_factory=WriterLimits)

    @field_validator("targets")
    @classmethod
    def _unique_targets(cls, value: List[TargetFile]) -> List[TargetFile]:
        """Reject duplicate target paths."""
        paths = [target.path for target in value]
        if len(set(paths)) != len(paths):
            raise ValueError("target paths must be unique")
        return value

    @field_validator("implementation_blocks")
    @classmethod
    def _unique_blocks(cls, value: List[str]) -> List[str]:
        """Reject duplicate implementation-block labels."""
        if len(set(value)) != len(value):
            raise ValueError("implementation_blocks must be unique")
        return value

    @field_validator("validation_commands")
    @classmethod
    def _non_empty_argv(cls, value: List[List[str]]) -> List[List[str]]:
        """Reject an empty argv list."""
        for argv in value:
            if not argv:
                raise ValueError("each validation command must be a non-empty argv list")
        return value


class PatchManifest(_StrictModel):
    """Provenance and validation state for one generated patch artifact.

    Attributes:
        artifact_id: Opaque identifier of the stored artifact directory.
        task_id: The originating task identifier.
        packet_sha256: Hash of the canonical delegation packet.
        patch_sha256: Hash of the normalized unified patch.
        before_hashes: Per-target baseline hash; ``None`` means "must be absent".
        after_hashes: Per-target hash after staged application.
        allowed_paths: The approved target scope.
        configured_model: The model identity requested by configuration.
        actual_model: The model identity reported by the provider, if known.
        used_fallback: True when the provider reported a model substitution.
        usage: Token usage; ``None`` values mean the provider reported nothing
            (unknown is never recorded as zero).
        repairs: Number of repair calls consumed (0 or 1).
        elapsed_ms: Wall-clock duration of generation.
        validation_state: ``validated`` or ``rejected``.
        created_at: ISO-8601 UTC creation timestamp.
    """

    artifact_id: ArtifactIdStr
    task_id: str = Field(..., pattern=r"^TASK-\d{3,}$")
    packet_sha256: Sha256Str
    patch_sha256: Sha256Str
    before_hashes: Dict[str, Optional[str]] = Field(default_factory=dict)
    after_hashes: Dict[str, str] = Field(default_factory=dict)
    allowed_paths: List[str] = Field(default_factory=list)
    configured_model: str = Field(..., min_length=1, max_length=512)
    actual_model: Optional[str] = Field(default=None, max_length=512)
    used_fallback: bool = False
    usage: Dict[str, Optional[int]] = Field(default_factory=dict)
    repairs: int = Field(default=0, ge=0, le=1)
    elapsed_ms: int = Field(..., ge=0)
    validation_state: Literal["validated", "rejected"]
    created_at: str = Field(..., min_length=1, max_length=64)

    @field_validator("before_hashes")
    @classmethod
    def _check_before(cls, value: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
        """Allow only a SHA-256 digest or an explicit ``None`` (absence)."""
        for path, digest in value.items():
            if digest is not None and not _SHA256_RE.match(digest):
                raise ValueError(f"before_hashes[{path!r}] must be a sha256 digest or null")
        return value

    @field_validator("after_hashes")
    @classmethod
    def _check_after(cls, value: Dict[str, str]) -> Dict[str, str]:
        """Require a SHA-256 digest for every written target."""
        for path, digest in value.items():
            if not _SHA256_RE.match(digest):
                raise ValueError(f"after_hashes[{path!r}] must be a sha256 digest")
        return value


# --------------------------------------------------------------------------- #
# Per-tool argument models
#
# These are both the ``@tool_schema`` schemas AND the raw-argument validation
# seam used by ``OptimizationToolkitBase._pre_execute``. They must therefore
# reject unknown keys and out-of-range values on their own.
# --------------------------------------------------------------------------- #
class GitRecentArgs(_StrictModel):
    """Arguments for ``git_recent``."""

    ref: ShortStr = "HEAD"
    limit: int = Field(default=3, ge=1, le=50)


class GitFetchArgs(_StrictModel):
    """Arguments for ``git_fetch``."""

    remote: ShortStr = "origin"
    branch: ShortStr = "dev"
    recent: int = Field(default=3, ge=1, le=50)


class GitPreflightArgs(_StrictModel):
    """Arguments for ``git_preflight`` (none)."""


class GitPrepareFilesArgs(_StrictModel):
    """Arguments for ``git_prepare_files``."""

    paths: List[ShortStr] = Field(..., min_length=1)


class GitPullArgs(_StrictModel):
    """Arguments for ``git_pull``."""

    remote: ShortStr = "origin"
    branch: Optional[ShortStr] = None


class GitPushArgs(_StrictModel):
    """Arguments for ``git_push``."""

    remote: ShortStr = "origin"
    branch: Optional[ShortStr] = None


class SourceInfoArgs(_StrictModel):
    """Arguments for ``source_info``."""

    path: ShortStr


class SourceReadArgs(_StrictModel):
    """Arguments for ``source_read``.

    Both range ends are required together: one coordinate system (1-based
    inclusive lines) and no offset/limit aliases.
    """

    path: ShortStr
    start_line: Optional[int] = Field(default=None, ge=1)
    end_line: Optional[int] = Field(default=None, ge=1)
    expected_sha256: Optional[Sha256Str] = None

    @model_validator(mode="after")
    def _check_range(self) -> "SourceReadArgs":
        """Require both range ends or neither, and a non-inverted range."""
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("start_line and end_line must be supplied together")
        if self.start_line is not None and self.end_line is not None and self.start_line > self.end_line:
            raise ValueError("start_line must be <= end_line")
        return self


class WriterGenerateArgs(_StrictModel):
    """Arguments for ``writer_generate``."""

    task_path: ShortStr


class WriterApplyArgs(_StrictModel):
    """Arguments for ``writer_apply``."""

    artifact_id: ArtifactIdStr
    reviewed_sha256: Sha256Str
