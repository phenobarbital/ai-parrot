"""LLM-wiki ingest target (``/ingest_wiki``) — FEAT-402 triage, admit-only."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from ..models import UploadOutcome, UploadRequest, UploadStatus, UploadTargetKind, WikiTargetConfig
from .base import IngestTarget


class WikiTarget(IngestTarget):
    """Triage with the wiki's charter, ingest only ``admit`` documents."""

    kind = UploadTargetKind.WIKI

    def __init__(self, config: WikiTargetConfig) -> None:
        """Initialize a wiki target and resolve its project paths."""
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.wiki_root = Path(config.wiki_root).expanduser().resolve()
        self.charter_path = (
            Path(config.charter_path).expanduser().resolve()
            if config.charter_path
            else self.wiki_root / ".parrot" / "charter.yaml"
        )
        self._runtime: Any | None = None

    @property
    def lock_key(self) -> Path:
        """Return the resolved wiki root used for job serialization."""
        return self.wiki_root

    @property
    def staging_dir(self) -> Path:
        """Return the upload staging directory excluded from vault scans."""
        return self.wiki_root / ".parrot" / "uploads"

    async def available(self) -> tuple[bool, str]:
        """Return whether the charter and supervised runtime are available."""
        if not self.charter_path.is_file():
            return False, f"no charter at {self.charter_path.name}"
        try:
            self._runtime = await self._build_runtime()
        except Exception as exc:  # noqa: BLE001 - construction failures disable the target
            self.logger.warning("Wiki upload target unavailable: %s", exc, exc_info=True)
            return False, str(exc)
        return True, ""

    async def _build_runtime(self) -> Any:
        """Build and return the supervised wiki ingest runtime."""
        from parrot.knowledge.wiki.charter import load_charter
        from parrot.knowledge.wiki.project import load_effective_config, sqlite_policy_from_config
        from parrot.knowledge.wiki.runtime import build_ingest_runtime, build_novelty_scorer
        from parrot.knowledge.wiki.sources import SourceCollectionManager
        from parrot.knowledge.wiki.store import create_wiki_store

        effective_config = await asyncio.to_thread(load_effective_config, self.wiki_root)
        config = effective_config.config
        if config.backend != "sqlite":
            raise RuntimeError(f"wiki backend {config.backend!r} not supported for uploads")

        storage = config.storage_path(self.wiki_root)
        await asyncio.to_thread(storage.mkdir, parents=True, exist_ok=True)
        store = await asyncio.to_thread(
            create_wiki_store,
            storage,
            wiki_name=config.wiki_name,
            backend=config.backend,
            sqlite_policy=sqlite_policy_from_config(config),
        )
        sources = await asyncio.to_thread(
            SourceCollectionManager,
            storage / "sources",
            db_path=storage / "wiki.db",
            busy_timeout=config.sqlite_busy_timeout,
        )
        charter = await asyncio.to_thread(load_charter, self.charter_path)
        scorer = await build_novelty_scorer(self.wiki_root, config, store)
        return await asyncio.to_thread(
            build_ingest_runtime,
            self.wiki_root,
            config,
            store,
            sources,
            charter,
            self.charter_path,
            lightweight_model=self.config.llm,
            model=self.config.llm,
            novelty_scorer=scorer,
        )

    async def ingest(self, staged_path: Path, request: UploadRequest, job_id: str) -> UploadOutcome:
        """Acquire, triage, admit, ingest, and checkpoint one staged document."""
        from parrot.knowledge.wiki.documents import DocumentRef
        from parrot.knowledge.wiki.store import SQLiteWikiStore

        runtime = self._runtime
        if runtime is None:
            raise RuntimeError("WikiTarget used before available()")

        acquired = await runtime.acquirer.acquire(DocumentRef(uri=str(staged_path), suffix=staged_path.suffix.lower()))
        entry = await runtime.router.triage(staged_path, acquired.text, skip_duplicate_check=request.force)
        detail = {"triage_action": entry.proposed_action}
        if entry.decision_source == "heuristic" and "duplicate" in entry.briefing:
            return UploadOutcome(
                job_id=job_id,
                status=UploadStatus.SKIPPED,
                target=request.target,
                filename=request.filename,
                message="Already present (same content) — use --force",
                detail=detail,
            )
        if entry.proposed_action != "admit":
            return UploadOutcome(
                job_id=job_id,
                status=UploadStatus.REJECTED_BY_TRIAGE,
                target=request.target,
                filename=request.filename,
                message=entry.briefing,
                detail=detail,
            )

        decided = entry.model_copy(update={"decision": "admit", "decision_source": "auto"})
        report = await runtime.orchestrator.ingest(
            str(staged_path),
            runtime.wiki_config,
            triage=decided,
            charter_version=runtime.charter.version,
            acquired=acquired,
        )
        if isinstance(runtime.store, SQLiteWikiStore):
            try:
                await runtime.store.checkpoint()
            except Exception:  # noqa: BLE001 - maintenance must never fail the job
                self.logger.debug("wiki WAL checkpoint failed", exc_info=True)

        if report.status != "ok":
            return UploadOutcome(
                job_id=job_id,
                status=UploadStatus.FAILED,
                target=request.target,
                filename=request.filename,
                message=self._safe_error(report.error),
                detail=detail,
            )
        status = UploadStatus.UPDATED if report.pages_updated > 0 else UploadStatus.ADDED
        return UploadOutcome(
            job_id=job_id,
            status=status,
            target=request.target,
            filename=request.filename,
            message=f"Wiki: {report.pages_created} pages created, {report.pages_updated} updated",
            detail={
                "pages_created": report.pages_created,
                "pages_updated": report.pages_updated,
                "triage_action": entry.proposed_action,
            },
        )

    @staticmethod
    def _safe_error(error: object | None) -> str:
        """Remove absolute filesystem paths from an ingest error message."""
        message = str(error or "Wiki ingest failed")
        return re.sub(r"(?<![\w:])/(?!/)(?:[^/\s:]+/)*[^/\s:]+", "<path>", message)
