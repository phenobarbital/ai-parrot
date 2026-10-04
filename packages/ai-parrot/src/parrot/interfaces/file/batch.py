"""Batch result models shared by Graph managers and FileManagerToolkit (FEAT-603).

This module deliberately has no Microsoft Graph dependency so generic file-manager
batch operations can use it with every supported storage backend.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from navigator.utils.file import FileMetadata
from pydantic import BaseModel, ConfigDict, Field

BatchState = Literal["succeeded", "failed", "skipped"]
# "permission_denied" was intentionally removed (FEAT-603 review): AC8 is explicit that a
# 401 *or* 403 both classify as "auth" (GraphDriveFileManager._classify never distinguishes
# them), so a separate "permission_denied" code was dead and unreachable.
BatchErrorCode = Literal["not_found", "throttled", "timeout", "auth", "conflict", "invalid_path", "io", "unknown"]


class BatchItemResult(BaseModel):
    """Outcome of one item inside ``upload_files`` or ``download_files``.

    A batch never raises for one item: failures are represented by this model.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    index: int
    source: str
    destination: str
    state: BatchState
    ok: bool
    metadata: Optional[FileMetadata] = None
    error: Optional[str] = None
    error_code: Optional[BatchErrorCode] = None
    status_code: Optional[int] = None
    attempts: int = Field(default=1, ge=0)


class BatchSummary(BaseModel):
    """Aggregate returned by the toolkit's batch tools."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    total: int
    succeeded: int
    failed: int
    skipped: int
    aborted: bool = False
    items: List[BatchItemResult]

    @classmethod
    def from_items(cls, items: List[BatchItemResult], *, aborted: bool = False) -> "BatchSummary":
        """Build aggregate counters from batch item results.

        Args:
            items: Ordered item results from one batch operation.
            aborted: Whether the caller stopped scheduling work early.

        Returns:
            A summary whose counters match the item states.
        """
        return cls(
            total=len(items),
            succeeded=sum(item.state == "succeeded" for item in items),
            failed=sum(item.state == "failed" for item in items),
            skipped=sum(item.state == "skipped" for item in items),
            aborted=aborted or any(item.state == "skipped" for item in items),
            items=items,
        )
