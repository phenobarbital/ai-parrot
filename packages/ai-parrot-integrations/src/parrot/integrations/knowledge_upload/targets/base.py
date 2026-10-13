"""Ingest target contract for knowledge uploads."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import UploadOutcome, UploadRequest, UploadTargetKind


class IngestTarget(ABC):
    """A knowledge plane an uploaded document can be ingested into."""

    kind: UploadTargetKind

    @property
    @abstractmethod
    def lock_key(self) -> Path:
        """Resolved root used for the process-wide lock."""

    @property
    @abstractmethod
    def staging_dir(self) -> Path:
        """Directory where the upload is staged for the duration of one ingest."""

    @abstractmethod
    async def available(self) -> tuple[bool, str]:
        """Return whether the target is usable and, if not, why."""

    @abstractmethod
    async def ingest(self, staged_path: Path, request: UploadRequest, job_id: str) -> UploadOutcome:
        """Ingest the staged file and return the user-facing outcome."""
