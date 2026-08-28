"""Meeting registry facade for the Fireflies → Obsidian → Wiki sync (FEAT-472).

Wraps a :class:`~parrot.knowledge.wiki.sources.SourceCollectionManager`
(the wiki's "Raw Sources" persistence layer) with meeting-shaped async
verbs so :class:`~parrot.agents.obsidian.FirefliesObsidianAgent` can dedupe
synced Fireflies transcripts by their immutable transcript id rather than
by note title (spec `sdd/specs/fireflies-meeting-registry.spec.md`).

Identity model:

- ``external_id`` on the manager's ``sources`` row is
  ``f"{EXTERNAL_ID_PREFIX}{fireflies_id}"`` (e.g. ``"fireflies:abc123"``).
- Meeting-specific state (transcript fingerprint, summary fingerprint,
  analysis status/fingerprint, wiki-ingested timestamp, meeting date,
  participants, last error, and a "rejected" flag written by
  :meth:`MeetingRegistry.forget`) lives in the row's ``doc_metadata`` JSON
  column under the ``DOC_METADATA_KEY`` ("fireflies") key, written through
  :meth:`SourceCollectionManager.record_document_metadata` — a
  read-merge-write that never clobbers sibling keys (e.g. the FEAT-451
  ``DocumentMetadata`` the vault ingest writes on the same row).

The manager's public API is synchronous by design (its own module
docstring); every call from this facade is dispatched through
``asyncio.to_thread`` so no manager call ever blocks the event loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from parrot.agents.conf import FIREFLIES_RECHECK_DAYS
from parrot.knowledge.wiki.models import SourceManifestEntry
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.tools.obsidian import ObsidianToolkit

logger = logging.getLogger(__name__)

#: Operating-contract §14.1 preferred external-id format for a Fireflies
#: transcript: ``f"{EXTERNAL_ID_PREFIX}{fireflies_id}"``.
EXTERNAL_ID_PREFIX = "fireflies:"

#: Key under ``SourceManifestEntry.doc_metadata`` where every
#: meeting-specific field this facade tracks lives (spec §2).
DOC_METADATA_KEY = "fireflies"

Classification = Literal["create", "skip", "revise"]
AnalysisStatus = Literal["pending", "done", "failed"]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

_BOM = "\ufeff"
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def normalise_transcript(text: str) -> str:
    """Normalise transcript text so content-only changes drive `fingerprint`.

    Rules (spec §2 New Public Interfaces): strip a leading BOM, normalise
    ``\\r\\n``/``\\r`` line endings to ``\\n``, right-strip every line,
    collapse runs of more than two consecutive blank lines down to two,
    and strip leading/trailing blank lines.

    Args:
        text: Raw transcript text.

    Returns:
        The normalised text, ready for :func:`fingerprint`.
    """
    text = text.removeprefix(_BOM)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def fingerprint(text: str) -> str:
    """SHA-256 hex digest of the normalised transcript text.

    Args:
        text: Raw transcript text (the Fireflies native summary, if any,
            must be fingerprinted separately — never passed here).

    Returns:
        Lowercase hexadecimal SHA-256 digest of
        ``normalise_transcript(text)``.
    """
    return hashlib.sha256(normalise_transcript(text).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Data models (spec §2)
# ---------------------------------------------------------------------------


class MeetingRecord(BaseModel):
    """Meeting-side view of one `sources` row (`doc_metadata['fireflies']` + `external_id`)."""

    fireflies_id: str
    external_id: str
    source_id: str
    note_path: str
    title: str
    meeting_date: str
    participants: list[str] = Field(default_factory=list)
    duration_minutes: float = 0.0
    fingerprint: str | None = None
    summary_fingerprint: str | None = None
    synced_at: str
    analysis_status: AnalysisStatus = "pending"
    analysis_fingerprint: str | None = None
    wiki_ingested_at: str | None = None
    last_error: str | None = None


class Classified(BaseModel):
    """Result of :meth:`MeetingRegistry.classify` for one listing item."""

    action: Classification
    record: MeetingRecord | None = None
    fetched_text: str | None = None
    fingerprint: str | None = None
    summary_fingerprint: str | None = None
    probable_duplicate_of: list[str] = Field(default_factory=list)


class RepairResult(BaseModel):
    """Result of :meth:`MeetingRegistry.repair_path` for one meeting id."""

    fireflies_id: str
    from_path: str | None
    to_path: str | None
    moved: bool


class MergeResult(BaseModel):
    """Result of :meth:`MeetingRegistry.merge_duplicates` for one meeting id."""

    fireflies_id: str
    kept: str
    removed: list[str]


class BackfillReport(BaseModel):
    """Result of :meth:`MeetingRegistry.backfill_from_vault`."""

    seeded: int
    without_analysis: int
    duplicates: list[MergeResult]
    unmerged: list[str]


class MeetingRegistry:
    """Meeting-shaped async facade over :class:`SourceCollectionManager`.

    Attributes:
        registry_dir: Directory whose ``wiki.db``/``sources/`` back this
            registry (shared with the wiki toolkit once it opens the
            same path — spec §2 G5).
        logger: Standard Python logger.

    Degraded mode: if the underlying manager cannot be constructed (or a
    later call raises ``sqlite3.Error``/``OSError``), :attr:`available`
    becomes ``False`` after one WARNING log, and every verb returns a
    neutral value (see each verb's docstring) instead of raising — the
    calling agent is expected to fall back to its own title-based
    dedup logic for that run (spec §2 G10).
    """

    def __init__(
        self,
        registry_dir: Path,
        *,
        manager: SourceCollectionManager | None = None,
    ) -> None:
        """Open (or wrap) the manager backing this registry.

        Args:
            registry_dir: Directory whose ``wiki.db`` (and ``sources/``
                subdirectory) back this registry. Created if needed.
            manager: An already-constructed manager to wrap instead of
                creating a new one (e.g. so the wiki toolkit's own
                manager instance can be shared). When omitted, a
                :class:`SourceCollectionManager` is opened on
                ``registry_dir/"sources"`` with
                ``db_path=registry_dir/"wiki.db"``.
        """
        self.registry_dir: Path = Path(registry_dir)
        self.logger: logging.Logger = logging.getLogger(__name__)
        self._recheck_days: int = FIREFLIES_RECHECK_DAYS
        self._manager: SourceCollectionManager | None = None
        self._available: bool = False

        if manager is not None:
            self._manager = manager
            self._available = True
            return

        try:
            self._manager = SourceCollectionManager(
                self.registry_dir / "sources",
                db_path=self.registry_dir / "wiki.db",
            )
            self._available = True
        except (sqlite3.Error, OSError) as exc:
            self.logger.warning(
                "MeetingRegistry unavailable at %s: %s — falling back to"
                " title-based dedup for this run",
                self.registry_dir,
                exc,
            )
            self._available = False

    @property
    def available(self) -> bool:
        """``True`` when the underlying manager is usable."""
        return self._available

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def lookup(self, fireflies_id: str) -> MeetingRecord | None:
        """Look up a meeting by its Fireflies transcript id.

        Args:
            fireflies_id: The raw Fireflies transcript id (no prefix).

        Returns:
            The :class:`MeetingRecord`, or ``None`` if unknown or the
            registry is unavailable.
        """
        if not self.available:
            return None
        entry = await asyncio.to_thread(self._manager.find_by_external_id, self._external_id(fireflies_id))
        if entry is None:
            return None
        return self._entry_to_record(entry)

    async def classify(
        self,
        item: dict[str, Any],
        *,
        fetch: Callable[[str], Awaitable[str]],
        fetch_summary: Callable[[str], Awaitable[str | None]] | None = None,
        force_refetch: bool = False,
    ) -> Classified:
        """Classify one Fireflies listing item as create/skip/revise.

        See spec §2 "Sync loop" step 2 for the full decision table.

        Args:
            item: One listing dict from
                ``FirefliesObsidianAgent._parse_fireflies_response``
                (keys: ``id``, ``title``, ``date``, ``participants``,
                ``duration``).
            fetch: Awaitable returning the full transcript text for a
                given Fireflies id. Called at most once.
            fetch_summary: Optional awaitable returning the Fireflies
                native summary text (or ``None``) for a given id.
            force_refetch: Bypass the cheap-skip path and always fetch +
                fingerprint when the id is already known.

        Returns:
            A :class:`Classified` result. When the registry is
            unavailable, always ``action="create"`` with nothing fetched
            — the calling agent is expected to use its own fallback
            dedup path instead of calling `classify` in that case.
        """
        fireflies_id = item["id"]
        external_id = self._external_id(fireflies_id)

        if not self.available:
            return Classified(action="create")

        entry = await asyncio.to_thread(self._manager.find_by_external_id, external_id)
        if entry is None:
            fetched_text, fp, summary_fp = await self._fetch_and_fingerprint(fireflies_id, fetch, fetch_summary)
            duplicates = await self._probable_duplicates(fp, external_id)
            return Classified(
                action="create",
                fetched_text=fetched_text,
                fingerprint=fp,
                summary_fingerprint=summary_fp,
                probable_duplicate_of=duplicates,
            )

        record = self._entry_to_record(entry)
        block = (entry.doc_metadata or {}).get(DOC_METADATA_KEY, {})
        if block.get("rejected"):
            return Classified(action="skip", record=record)

        if not force_refetch and self._is_cheap_skip(item, record):
            return Classified(action="skip", record=record)

        fetched_text, fp, summary_fp = await self._fetch_and_fingerprint(fireflies_id, fetch, fetch_summary)
        duplicates = await self._probable_duplicates(fp, external_id)
        if record.fingerprint is not None and record.fingerprint == fp:
            action: Classification = "skip"
        else:
            action = "revise"
        return Classified(
            action=action,
            record=record,
            fetched_text=fetched_text,
            fingerprint=fp,
            summary_fingerprint=summary_fp,
            probable_duplicate_of=duplicates,
        )

    async def pending_analysis(self) -> list[MeetingRecord]:
        """Meetings needing (re-)analysis.

        Returns:
            Records with ``analysis_status != "done"`` OR
            ``analysis_fingerprint != fingerprint``, excluding rejected
            rows. Empty when the registry is unavailable.
        """
        if not self.available:
            return []
        entries = await asyncio.to_thread(self._manager.list_by_external_prefix, EXTERNAL_ID_PREFIX)
        pending: list[MeetingRecord] = []
        for entry in entries:
            block = (entry.doc_metadata or {}).get(DOC_METADATA_KEY, {})
            if block.get("rejected"):
                continue
            record = self._entry_to_record(entry)
            if record.analysis_status != "done" or record.analysis_fingerprint != record.fingerprint:
                pending.append(record)
        return pending

    async def suggest_from_date(self, *, overlap_days: int) -> str | None:
        """Suggest the Fireflies listing `fromDate` from registry history.

        Args:
            overlap_days: Days to subtract from the most recent
                ``synced_at`` in the registry.

        Returns:
            ``max(synced_at).date() - overlap_days`` as an ISO
            ``YYYY-MM-DD`` string, or ``None`` when the registry has no
            rows (or is unavailable) — callers should send no
            ``fromDate`` in that case (today's behaviour).
        """
        if not self.available:
            return None
        entries = await asyncio.to_thread(self._manager.list_by_external_prefix, EXTERNAL_ID_PREFIX)
        synced_ats = [
            block["synced_at"]
            for entry in entries
            if (block := (entry.doc_metadata or {}).get(DOC_METADATA_KEY, {})).get("synced_at")
        ]
        if not synced_ats:
            return None
        latest = max(synced_ats)
        latest_dt = self._parse_iso(latest)
        return (latest_dt.date() - timedelta(days=overlap_days)).isoformat()

    async def unique_slug(self, meetings_folder: str, base_title: str, *, vault_path: Path) -> str:
        """Disambiguate a note title against the registry and the filesystem.

        Args:
            meetings_folder: Vault-relative meetings folder (e.g.
                ``"meetings"``).
            base_title: The candidate note title (no ``.md`` suffix),
                typically ``FirefliesObsidianAgent._make_note_title(...)``.
            vault_path: Absolute path to the vault root.

        Returns:
            ``base_title`` if free, else ``"{base_title}-2"``,
            ``"{base_title}-3"``, ... — the first suffix not present in
            the registry (by URI) nor on disk.
        """
        candidate = base_title
        suffix = 1
        while True:
            candidate_path = (Path(vault_path) / meetings_folder / f"{candidate}.md").resolve()
            on_disk = candidate_path.exists()
            tracked = False
            if self.available:
                tracked_id = await asyncio.to_thread(self._manager.find_by_uri, str(candidate_path))
                tracked = tracked_id is not None
            if not on_disk and not tracked:
                return candidate
            suffix += 1
            candidate = f"{base_title}-{suffix}"

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def record_synced(
        self,
        *,
        fireflies_id: str,
        note_path: Path,
        title: str,
        meeting_date: str,
        participants: list[str],
        duration_minutes: float,
        fingerprint: str,
        summary_fingerprint: str | None,
        reset_analysis: bool,
    ) -> MeetingRecord:
        """Record (or refresh) a meeting's synced state.

        Registers the note file if untracked (or attaches ``external_id``
        to an already-tracked, id-less row), then merges the
        ``doc_metadata["fireflies"]`` block with the new sync state.

        Args:
            fireflies_id: Raw Fireflies transcript id.
            note_path: Path to the note file (must exist).
            title: Meeting title.
            meeting_date: ``YYYY-MM-DD``.
            participants: Participant emails/names.
            duration_minutes: Meeting duration.
            fingerprint: SHA-256 of the normalised transcript.
            summary_fingerprint: SHA-256 of the Fireflies summary, if any.
            reset_analysis: When ``True``, resets
                ``analysis_status="pending"`` and clears
                ``analysis_fingerprint`` (a revise always does this).

        Returns:
            The resulting :class:`MeetingRecord`. When the registry is
            unavailable, a record built from the given arguments is
            returned WITHOUT being persisted (logged once).
        """
        external_id = self._external_id(fireflies_id)
        now = datetime.now(UTC).isoformat()

        if not self.available:
            self.logger.warning(
                "record_synced: registry unavailable, not persisting fireflies_id=%s",
                fireflies_id,
            )
            return MeetingRecord(
                fireflies_id=fireflies_id,
                external_id=external_id,
                source_id="",
                note_path=str(note_path),
                title=title,
                meeting_date=meeting_date,
                participants=participants,
                duration_minutes=duration_minutes,
                fingerprint=fingerprint,
                summary_fingerprint=summary_fingerprint,
                synced_at=now,
            )

        path = Path(note_path)
        existing_id = await asyncio.to_thread(self._manager.find_by_uri, str(path.resolve()))
        if existing_id is None:
            entry = await asyncio.to_thread(self._manager.add_source, path, external_id=external_id)
        else:
            entry = await asyncio.to_thread(self._manager.get_source, existing_id)
            if entry.external_id != external_id:
                entry = await asyncio.to_thread(self._manager.set_external_id, existing_id, external_id)

        patch: dict[str, Any] = {
            "fireflies_id": fireflies_id,
            "title": title,
            "meeting_date": meeting_date,
            "participants": participants,
            "duration_minutes": duration_minutes,
            "fingerprint": fingerprint,
            "summary_fingerprint": summary_fingerprint,
            "synced_at": now,
        }
        if reset_analysis:
            patch["analysis_status"] = "pending"
            patch["analysis_fingerprint"] = None
        updated_entry = await self._merge_doc_metadata(entry, patch)
        return self._entry_to_record(updated_entry)

    async def mark_analyzed(self, fireflies_id: str, fingerprint: str) -> None:
        """Record a successful analysis for a meeting.

        Args:
            fireflies_id: Raw Fireflies transcript id.
            fingerprint: The transcript fingerprint the analysis was
                computed against.
        """
        if not self.available:
            return
        entry = await asyncio.to_thread(self._manager.find_by_external_id, self._external_id(fireflies_id))
        if entry is None:
            self.logger.warning("mark_analyzed: fireflies_id=%s not tracked", fireflies_id)
            return
        await self._merge_doc_metadata(
            entry,
            {"analysis_status": "done", "analysis_fingerprint": fingerprint, "last_error": None},
        )

    async def mark_analysis_failed(self, fireflies_id: str, error: str) -> None:
        """Record a failed analysis attempt for a meeting.

        Args:
            fireflies_id: Raw Fireflies transcript id.
            error: Human-readable error description.
        """
        if not self.available:
            return
        entry = await asyncio.to_thread(self._manager.find_by_external_id, self._external_id(fireflies_id))
        if entry is None:
            self.logger.warning("mark_analysis_failed: fireflies_id=%s not tracked", fireflies_id)
            return
        await self._merge_doc_metadata(entry, {"analysis_status": "failed", "last_error": error})

    async def mark_wiki_ingested(self, *, at: str | None = None) -> int:
        """Stamp `wiki_ingested_at` on every up-to-date, ingested fireflies row.

        Args:
            at: Timestamp to stamp (ISO-8601 UTC). Defaults to now.

        Returns:
            Number of rows stamped. ``0`` when the registry is
            unavailable.
        """
        if not self.available:
            return 0
        timestamp = at or datetime.now(UTC).isoformat()
        entries = await asyncio.to_thread(self._manager.list_by_external_prefix, EXTERNAL_ID_PREFIX)
        stamped = 0
        for entry in entries:
            if not entry.pages_generated:
                continue
            stale = await asyncio.to_thread(self._manager.entry_is_stale, entry)
            if stale:
                continue
            await self._merge_doc_metadata(entry, {"wiki_ingested_at": timestamp})
            stamped += 1
        return stamped

    async def forget(self, fireflies_id: str, *, reject: bool = False) -> bool:
        """Remove (or permanently reject) a tracked meeting.

        Args:
            fireflies_id: Raw Fireflies transcript id.
            reject: When ``True``, the row is kept but flagged
                ``rejected`` in ``doc_metadata["fireflies"]`` so
                :meth:`classify` returns ``"skip"`` for it forever
                (used when the note was deleted by the user but the
                meeting must never be re-created). When ``False``
                (default), the row is removed entirely.

        Returns:
            ``True`` if a tracked row was found and updated/removed;
            ``False`` otherwise (including when the registry is
            unavailable).
        """
        if not self.available:
            return False
        entry = await asyncio.to_thread(self._manager.find_by_external_id, self._external_id(fireflies_id))
        if entry is None:
            return False
        if reject:
            await self._merge_doc_metadata(entry, {"rejected": True})
            return True
        return await asyncio.to_thread(self._manager.remove_source, entry.source_id)

    # ------------------------------------------------------------------
    # Not implemented here — TASK-2555 (backfill, merge, repair)
    # ------------------------------------------------------------------

    async def repair_path(
        self,
        fireflies_id: str,
        *,
        toolkit: ObsidianToolkit,
        meetings_folder: str,
        canonical_title: str,
    ) -> RepairResult:
        """Repair a renamed/moved note's registered path.

        Implemented by TASK-2555 (spec §3 Module 3).
        """
        raise NotImplementedError("repair_path is implemented by TASK-2555")

    async def backfill_from_vault(
        self,
        *,
        toolkit: ObsidianToolkit,
        meetings_folder: str,
        analysis_heading: str,
    ) -> BackfillReport:
        """Seed the registry from existing vault note frontmatter.

        Implemented by TASK-2555 (spec §3 Module 3).
        """
        raise NotImplementedError("backfill_from_vault is implemented by TASK-2555")

    async def merge_duplicates(
        self,
        fireflies_id: str,
        paths: list[str],
        *,
        toolkit: ObsidianToolkit,
        meetings_folder: str,
        analysis_heading: str,
    ) -> MergeResult:
        """Merge duplicate notes registered under one Fireflies id.

        Implemented by TASK-2555 (spec §3 Module 3).
        """
        raise NotImplementedError("merge_duplicates is implemented by TASK-2555")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _external_id(fireflies_id: str) -> str:
        """Build the `external_id` for a raw Fireflies transcript id."""
        return f"{EXTERNAL_ID_PREFIX}{fireflies_id}"

    @staticmethod
    def _entry_to_record(entry: SourceManifestEntry) -> MeetingRecord:
        """Project one `sources` row onto a :class:`MeetingRecord`."""
        block = (entry.doc_metadata or {}).get(DOC_METADATA_KEY, {})
        external_id = entry.external_id or ""
        fireflies_id = block.get("fireflies_id") or external_id.removeprefix(EXTERNAL_ID_PREFIX)
        return MeetingRecord(
            fireflies_id=fireflies_id,
            external_id=external_id,
            source_id=entry.source_id,
            note_path=entry.source_uri,
            title=block.get("title", ""),
            meeting_date=block.get("meeting_date", ""),
            participants=block.get("participants") or [],
            duration_minutes=block.get("duration_minutes", 0.0),
            fingerprint=block.get("fingerprint"),
            summary_fingerprint=block.get("summary_fingerprint"),
            synced_at=block.get("synced_at") or entry.ingested_at,
            analysis_status=block.get("analysis_status", "pending"),
            analysis_fingerprint=block.get("analysis_fingerprint"),
            wiki_ingested_at=block.get("wiki_ingested_at"),
            last_error=block.get("last_error"),
        )

    async def _merge_doc_metadata(self, entry: SourceManifestEntry, patch: dict[str, Any]) -> SourceManifestEntry:
        """Read-merge-write `doc_metadata["fireflies"]`, preserving sibling keys.

        Args:
            entry: The row to update (must already be tracked).
            patch: Fields to set/overwrite within the ``"fireflies"``
                sub-dict; other top-level ``doc_metadata`` keys (e.g.
                FEAT-451's own extracted metadata) are left untouched.

        Returns:
            The refreshed :class:`SourceManifestEntry` after the write.
        """
        doc_metadata = dict(entry.doc_metadata or {})
        block = dict(doc_metadata.get(DOC_METADATA_KEY, {}))
        block.update(patch)
        doc_metadata[DOC_METADATA_KEY] = block
        await asyncio.to_thread(
            self._manager.record_document_metadata,
            entry.source_id,
            doc_metadata=doc_metadata,
            content_type=entry.content_type,
            loader=entry.loader,
        )
        refreshed = await asyncio.to_thread(self._manager.get_source, entry.source_id)
        return refreshed if refreshed is not None else entry

    async def _fetch_and_fingerprint(
        self,
        fireflies_id: str,
        fetch: Callable[[str], Awaitable[str]],
        fetch_summary: Callable[[str], Awaitable[str | None]] | None,
    ) -> tuple[str, str, str | None]:
        """Fetch the transcript (and optional summary) and fingerprint both."""
        text = await fetch(fireflies_id)
        fp = fingerprint(text)
        summary_fp: str | None = None
        if fetch_summary is not None:
            summary_text = await fetch_summary(fireflies_id)
            if summary_text:
                summary_fp = fingerprint(summary_text)
        return text, fp, summary_fp

    async def _probable_duplicates(self, fp: str | None, external_id: str) -> list[str]:
        """Other `external_id`s whose stored fingerprint matches `fp`."""
        if fp is None:
            return []
        entries = await asyncio.to_thread(self._manager.list_by_external_prefix, EXTERNAL_ID_PREFIX)
        matches: list[str] = []
        for other in entries:
            if other.external_id == external_id:
                continue
            block = (other.doc_metadata or {}).get(DOC_METADATA_KEY, {})
            if block.get("fingerprint") == fp:
                matches.append(other.external_id)
        return matches

    def _is_cheap_skip(self, item: dict[str, Any], record: MeetingRecord) -> bool:
        """Whether `item`'s listing metadata is unchanged and `record` is fresh.

        Cheap skip requires the listing to carry ``title``/``date``/
        ``duration`` (spec §7 gotcha: a missing field falls through to a
        real fetch), a non-``None`` stored fingerprint (a backfilled row
        has none — nothing to trust yet, so it must always be fetched
        once), AND the stored ``synced_at`` to be within the recheck
        window.
        """
        if record.fingerprint is None:
            return False
        title = item.get("title")
        date = item.get("date")
        duration = item.get("duration")
        if title is None or date is None or duration is None:
            return False
        date_norm = date.split("T")[0] if isinstance(date, str) else date
        try:
            duration_matches = float(duration) == float(record.duration_minutes)
        except (TypeError, ValueError):
            duration_matches = False
        metadata_unchanged = title == record.title and date_norm == record.meeting_date and duration_matches
        return metadata_unchanged and self._is_within_recheck_window(record.synced_at)

    def _is_within_recheck_window(self, synced_at: str) -> bool:
        """Whether `synced_at` is younger than `self._recheck_days`."""
        try:
            synced_dt = self._parse_iso(synced_at)
        except (ValueError, TypeError):
            return False
        age = datetime.now(UTC) - synced_dt
        return age <= timedelta(days=self._recheck_days)

    @staticmethod
    def _parse_iso(value: str) -> datetime:
        """Parse an ISO-8601 timestamp, defaulting to UTC when tz-naive."""
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
