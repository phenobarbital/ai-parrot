"""Strict discriminated contracts for bounded independent inspections (FEAT-584).

Every request kind is validated *before* any I/O runs: a duplicate id, a
malformed range, an abbreviated commit id or an out-of-shape cursor is
rejected by Pydantic at admission time, never discovered mid-batch.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = (
    "InspectionModel",
    "ReadRequest",
    "InfoRequest",
    "SearchRequest",
    "FilesRequest",
    "GitStatusRequest",
    "GitDiffNamesRequest",
    "InspectionRequest",
    "InspectionBatchArgs",
    "InspectionItem",
    "InspectionBatch",
)

#: Opaque cursor shape emitted by the runner: "<index>:<offset>".
_CURSOR_CHARS = frozenset("0123456789:")


def _is_full_sha(value: str) -> bool:
    """True when ``value`` is a lowercase 40-hex Git commit id.

    Args:
        value: The candidate string.

    Returns:
        True when ``value`` looks like a full, immutable commit id.
    """
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value)


def _check_cursor(value: str | None) -> str | None:
    """Reject a continuation cursor that is not the runner's opaque shape.

    Args:
        value: The caller-supplied cursor, or None.

    Returns:
        The cursor, unchanged.

    Raises:
        ValueError: The cursor is empty, oversized or contains unexpected
            characters.
    """
    if value is None:
        return value
    if not value or len(value) > 64 or not all(char in _CURSOR_CHARS for char in value):
        raise ValueError(f"{value!r} is not a valid continuation cursor")
    return value


class InspectionModel(BaseModel):
    """Reject undeclared arguments before effects."""

    model_config = ConfigDict(extra="forbid")


class ReadRequest(InspectionModel):
    """Read a bounded revision-checked line range."""

    id: str = Field(min_length=1)
    kind: Literal["read"]
    path: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    expected_sha256: str | None = None

    @model_validator(mode="after")
    def _check_range_and_revision(self) -> "ReadRequest":
        """Require both range ends together, a non-inverted range, a real digest."""
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("start_line and end_line must be supplied together")
        if self.start_line is not None and self.end_line is not None and self.start_line > self.end_line:
            raise ValueError("start_line must be <= end_line")
        if self.expected_sha256 is not None:
            digest = self.expected_sha256
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("expected_sha256 must be a lowercase 64-hex sha256 digest")
        return self


class InfoRequest(InspectionModel):
    """Inspect metadata without returning unbounded source."""

    id: str = Field(min_length=1)
    kind: Literal["info"]
    path: str


class SearchRequest(InspectionModel):
    """Search literal text in confined paths."""

    id: str = Field(min_length=1)
    kind: Literal["search"]
    paths: list[str] = Field(min_length=1, max_length=8)
    text: str = Field(min_length=1, max_length=1024)
    max_matches: int = Field(default=20, ge=1, le=100)
    continuation: str | None = None

    @model_validator(mode="after")
    def _check_continuation(self) -> "SearchRequest":
        """Reject a cursor that is not this runner's opaque shape."""
        _check_cursor(self.continuation)
        return self


class FilesRequest(InspectionModel):
    """List bounded repository-relative paths under validated roots."""

    id: str = Field(min_length=1)
    kind: Literal["files"]
    paths: list[str] = Field(default_factory=lambda: ["."], min_length=1, max_length=8)
    continuation: str | None = None

    @model_validator(mode="after")
    def _check_continuation(self) -> "FilesRequest":
        """Reject a cursor that is not this runner's opaque shape."""
        _check_cursor(self.continuation)
        return self


class GitStatusRequest(InspectionModel):
    """Read status without index refresh or writes."""

    id: str = Field(min_length=1)
    kind: Literal["git_status"]


class GitDiffNamesRequest(InspectionModel):
    """Compare immutable full Git commit ids."""

    id: str = Field(min_length=1)
    kind: Literal["git_diff_names"]
    base_sha: str
    head_sha: str

    @model_validator(mode="after")
    def _check_full_shas(self) -> "GitDiffNamesRequest":
        """Reject anything but a full 40-hex commit id on either side."""
        for name, value in (("base_sha", self.base_sha), ("head_sha", self.head_sha)):
            if not _is_full_sha(value):
                raise ValueError(f"{name} must be a full 40-hex commit id, not {value!r}")
        return self


InspectionRequest = Annotated[
    ReadRequest | InfoRequest | SearchRequest | FilesRequest | GitStatusRequest | GitDiffNamesRequest,
    Field(discriminator="kind"),
]


class InspectionBatchArgs(InspectionModel):
    """Bound batch cardinality, admission and response size."""

    requests: list[InspectionRequest] = Field(min_length=1, max_length=8)
    concurrency: int = Field(default=4, ge=1, le=4)
    max_output_bytes: int = Field(default=24576, ge=4096, le=24576)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "InspectionBatchArgs":
        """Reject a batch that reuses one item id across requests."""
        seen: set[str] = set()
        for request in self.requests:
            if request.id in seen:
                raise ValueError(f"duplicate request id: {request.id!r}")
            seen.add(request.id)
        return self


class InspectionItem(InspectionModel):
    """One stable item result even when peers fail."""

    id: str
    kind: str
    status: Literal["ok", "error", "cancelled"]
    data: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = None
    elapsed_ms: int = Field(ge=0)
    truncated: bool = False
    continuation: str | None = None


class InspectionBatch(InspectionModel):
    """Ordered response with snapshot consistency and measured byte cost."""

    schema_version: Literal[1] = 1
    items: list[InspectionItem]
    partial: bool
    consistent: bool
    head_before: str | None
    head_after: str | None
    elapsed_ms: int = Field(ge=0)
    sum_item_ms: int = Field(ge=0)
    returned_bytes: int = Field(ge=0)
