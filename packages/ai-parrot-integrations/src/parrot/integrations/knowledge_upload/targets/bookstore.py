"""Bookstore ingest target (``/ingest_book``)."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from ..models import BookstoreTargetConfig, UploadOutcome, UploadRequest, UploadStatus, UploadTargetKind
from .base import IngestTarget


class BookstoreTarget(IngestTarget):
    """Ingest uploads with ``Bookstore.add_book`` (same as ``bookstore add``)."""

    kind = UploadTargetKind.BOOKSTORE

    def __init__(self, config: BookstoreTargetConfig) -> None:
        """Initialize a target rooted at the configured Bookstore library."""
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.library_dir = Path(os.path.expandvars(config.library_dir)).expanduser().resolve()
        self._bookstore: Any | None = None

    @property
    def lock_key(self) -> Path:
        """Return the resolved library directory used for target locking."""
        return self.library_dir

    @property
    def staging_dir(self) -> Path:
        """Return the stable private directory used to stage uploads."""
        return self.library_dir / ".uploads"

    async def available(self) -> tuple[bool, str]:
        """Initialize the Bookstore if a configured LLM adapter is available."""
        from parrot.knowledge.bookstore._llm import resolve_adapter
        from parrot.knowledge.bookstore.config import LibraryLocation
        from parrot.knowledge.bookstore.library import Bookstore

        try:
            adapter, lightweight_model, _client = await asyncio.to_thread(resolve_adapter, self.config.llm)
            if adapter is None:
                return False, f"no LLM for {self.config.llm}"
            self.library_dir.mkdir(parents=True, exist_ok=True)
            self._bookstore = Bookstore(
                [LibraryLocation(scope="project", root=self.library_dir)],
                adapter=adapter,
                lightweight_model=lightweight_model,
            )
        except Exception as exc:  # noqa: BLE001 - target availability must not break startup
            return False, f"Bookstore unavailable: {exc}"
        return True, ""

    async def ingest(self, staged_path: Path, request: UploadRequest, job_id: str) -> UploadOutcome:
        """Ingest a staged document and return its user-facing Bookstore outcome."""
        from parrot.knowledge.bookstore.library import BookstoreError

        if self._bookstore is None:
            raise RuntimeError("BookstoreTarget used before available()")
        try:
            card, status = await self._bookstore.add_book(
                staged_path,
                scope="project",
                title=request.title or None,
                authors=request.authors or None,
                topics=request.topics or None,
                force=request.force,
            )
        except BookstoreError as exc:
            message = str(exc).replace(str(staged_path.resolve()), staged_path.name)
            message = message.replace(str(self.library_dir), "")
            return UploadOutcome(
                job_id=job_id,
                status=UploadStatus.FAILED,
                target=self.kind,
                filename=request.filename,
                message=message,
            )

        detail = {"book_id": card.book_id, "title": card.title}
        if status == "added":
            outcome_status = UploadStatus.ADDED
            message = f"Added *{card.title}* to the Bookstore"
        elif status == "updated":
            outcome_status = UploadStatus.UPDATED
            message = f"Updated *{card.title}* in the Bookstore"
        else:
            outcome_status = UploadStatus.SKIPPED
            message = "Already present (same content) — use --force"
        return UploadOutcome(
            job_id=job_id,
            status=outcome_status,
            target=self.kind,
            filename=request.filename,
            message=message,
            detail=detail,
        )
