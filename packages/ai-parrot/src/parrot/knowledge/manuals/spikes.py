"""Spike harness for FEAT-601's validation gate (M0 / AC1).

Measures figure pairing, video alignment, tip survival and media delivery
over an owner-supplied corpus and writes one JSON report per run.

Running these spikes against the real owner-supplied corpus (and signing off
AC1 on the resulting numbers) is a human-in-the-loop step — this module only
builds the repeatable, testable measurement harness (spec §3 Module 0).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Literal, Sequence

from pydantic import BaseModel, Field

from .catalog import (
    AnswerRecord,
    CatalogConflictError,
    ManualCatalogStore,
    PublicationRecord,
    UpsertResult,
    queue_entries_for,
)
from .graph_loader import ManualGraphLoader
from .library import ManualLibrary
from .models import ManualCard, ManualVersion, ProcedureAnswer, Step, manual_snapshot_payload
from .tips import add_tip
from .video import JudgementLog, align_video

logger = logging.getLogger(__name__)

SPIKE_CORPUS_ENV = "MANUALS_SPIKE_CORPUS"
REPORT_ROOT = Path("artifacts/logs/FEAT-601")
REQUIRED_MEDIA_CHANNELS: tuple[str, ...] = ("msteams", "whatsapp", "telegram")
THRESHOLDS: dict[str, dict[str, float]] = {
    "figures": {"steps_in_order_ratio": 0.90, "missing_required": 0.0, "primary_figure_accuracy": 0.80},
    "video": {"coverage": 0.70},
    "tips": {"expected_outcomes_matched": 3.0},
    "media": {"channels_delivered": float(len(REQUIRED_MEDIA_CHANNELS))},
}
ChannelSender = Callable[[str, Any], Awaitable[None]]
CHANNEL_SENDERS: dict[str, ChannelSender] = {}


class SpikeReport(BaseModel):
    """One spike's measured numbers, thresholds and pass/fail; serialised under artifacts/logs/."""

    name: Literal["figures", "media", "video", "tips"]
    measurements: dict[str, float]
    thresholds: dict[str, float]
    passed: bool
    notes: list[str] = Field(default_factory=list)


def _evaluate(name: str, measurements: dict[str, float], notes: list[str]) -> SpikeReport:
    """Apply THRESHOLDS[name]: ratios/counts use >=, 'missing_required' must be 0."""
    thresholds = THRESHOLDS[name]
    passed = True
    report_notes = list(notes)
    for key, threshold in thresholds.items():
        if key not in measurements:
            passed = False
            report_notes.append(f"missing measurement {key!r} required by the {name!r} threshold")
            continue
        value = measurements[key]
        ok = value == 0.0 if key == "missing_required" else value >= threshold
        if not ok:
            passed = False
    return SpikeReport(name=name, measurements=measurements, thresholds=thresholds, passed=passed, notes=report_notes)


def register_channel_sender(channel: str, sender: ChannelSender) -> None:
    """Register the live or fake sender used by spike_media for ``channel``."""
    CHANNEL_SENDERS[channel] = sender


def corpus_dir_from_env() -> Path:
    """Resolve MANUALS_SPIKE_CORPUS; missing/nonexistent ⇒ FileNotFoundError with a clear hint."""
    raw = os.environ.get(SPIKE_CORPUS_ENV)
    if not raw:
        raise FileNotFoundError(
            f"{SPIKE_CORPUS_ENV} is not set; point it at the owner-supplied spike corpus directory "
            "(a folder with the manual sources and an expected.json of hand counts)"
        )
    path = Path(raw)
    if not path.is_dir():
        raise FileNotFoundError(f"{SPIKE_CORPUS_ENV}={raw!r} does not exist or is not a directory")
    return path


def write_report(report: SpikeReport, *, root: Path = REPORT_ROOT) -> Path:
    """Write spike-<name>-<UTC ts>.json (sorted keys) under ``root``; return the path."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = root / f"spike-{report.name}-{timestamp}.json"
    payload = report.model_dump(mode="json")
    path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# A dependency-free ManualLibrary for the default (``library=None``) path.
#
# Real corpus runs still need a working structured-output adapter (handed in
# by the caller) to draft procedures from arbitrary manual text, but they
# should not require a live database or object store just to run a spike.
# This in-process catalog and local file manager exist only for that
# throwaway, single-process default; nothing here is durable across runs.
# --------------------------------------------------------------------------


class _EphemeralCatalog(ManualCatalogStore):
    """Minimal, in-memory ManualCatalogStore backing a spike's default library."""

    def __init__(self, *, tenant_id: str = "manuals-spike") -> None:
        """Initialize empty in-memory state."""
        super().__init__(tenant_id=tenant_id)
        self._cards: dict[str, ManualCard] = {}
        self._revisions: dict[str, int] = {}
        self._history: dict[str, list[ManualVersion]] = {}
        self._answers: dict[str, AnswerRecord] = {}
        self._outbox: dict[tuple, PublicationRecord] = {}

    async def upsert(
        self, card: ManualCard, *, expected_revision: int | None = None, version: ManualVersion | None = None
    ) -> UpsertResult:
        """Write a card and its history row without durability or concurrency guarantees."""
        stored = self._cards.get(card.manual_id)
        actual = self._revisions.get(card.manual_id)
        if expected_revision is not None and expected_revision != actual:
            raise CatalogConflictError(card.manual_id, expected_revision, actual)
        created = stored is None
        revision = 1 if created else actual + 1  # type: ignore[operator]
        history = self._history.setdefault(card.manual_id, [])
        version_n = version.n if version is not None else len(history) + 1
        written = card.model_copy(update={"versions": []})
        recorded = version or ManualVersion(
            n=version_n, revision=card.revision, source_sha256=card.source_sha256,
            card_snapshot=manual_snapshot_payload(written),
        )
        history.append(recorded)
        written = written.model_copy(update={"versions": list(history)})
        self._cards[card.manual_id] = written
        self._revisions[card.manual_id] = revision
        return UpsertResult(manual_id=card.manual_id, revision=revision, created=created, version_n=recorded.n)

    async def get(self, manual_id: str) -> ManualCard | None:
        """Return a stored manual card."""
        return self._cards.get(manual_id)

    async def find_by_sha(self, sha256: str) -> ManualCard | None:
        """Return a card by its source hash."""
        return next((card for card in self._cards.values() if card.source_sha256 == sha256), None)

    async def find_by_source_uri(self, uri: str) -> ManualCard | None:
        """Return a card by canonical source URI."""
        return next((card for card in self._cards.values() if card.source_uri == uri), None)

    async def list_cards(self, *, verification: Any = None, active_only: bool = True) -> list[ManualCard]:
        """List cards ordered by manual id; all cards are active in this ephemeral catalog."""
        del active_only
        return sorted(
            (card for card in self._cards.values() if verification is None or card.verification == verification),
            key=lambda card: card.manual_id,
        )

    async def versions(self, manual_id: str) -> list[ManualVersion]:
        """Return one manual's version history."""
        return list(self._history.get(manual_id, []))

    async def search(self, query: str, top_k: int = 8) -> list[Any]:
        """Search is not exercised by the spikes; return no hits."""
        del query, top_k
        return []

    async def verification_queue(self, *, limit: int = 50) -> list[Any]:
        """Return derived verification-queue entries."""
        entries = [entry for card in self._cards.values() for entry in queue_entries_for(card)]
        entries.sort(key=lambda entry: (entry.priority, entry.card.manual_id))
        return entries[:limit]

    async def record_answer(self, record: AnswerRecord) -> None:
        """Persist an audit record."""
        self._answers[record.answer_id] = record

    async def get_answer(self, answer_id: str) -> AnswerRecord | None:
        """Return one audited answer."""
        return self._answers.get(answer_id)

    async def enqueue_publication(self, record: PublicationRecord) -> PublicationRecord:
        """Idempotently store one publication row."""
        existing = self._outbox.get(record.key)
        if existing is not None:
            return existing
        self._outbox[record.key] = record
        return record

    async def pending_publications(self, *, limit: int = 50) -> list[PublicationRecord]:
        """Return pending and failed rows."""
        rows = [record for record in self._outbox.values() if record.state in ("pending", "failed")]
        return sorted(rows, key=lambda record: record.key)[:limit]

    async def claim_publication(self, *, limit: int = 1) -> list[PublicationRecord]:
        """Mark pending rows in flight."""
        claimed: list[PublicationRecord] = []
        for record in await self.pending_publications(limit=limit):
            updated = record.model_copy(update={"state": "in_flight", "attempts": record.attempts + 1})
            self._outbox[record.key] = updated
            claimed.append(updated)
        return claimed

    async def complete_publication(self, record: PublicationRecord, *, receipt: str) -> PublicationRecord:
        """Mark a publication record as published."""
        updated = record.model_copy(update={"state": "published", "receipt": receipt, "last_error": None})
        self._outbox[record.key] = updated
        return updated

    async def fail_publication(self, record: PublicationRecord, *, error: str) -> PublicationRecord:
        """Mark a publication record retryably failed."""
        updated = record.model_copy(update={"state": "failed", "last_error": error})
        self._outbox[record.key] = updated
        return updated

    async def setup(self) -> None:
        """No-op lifecycle hook."""

    async def close(self) -> None:
        """No-op lifecycle hook."""


class _LocalFileManager:
    """Writes figure bytes to local disk and returns ``file://`` URLs (no cloud dependency)."""

    def __init__(self, root: Path) -> None:
        """Initialize the manager rooted at ``root``."""
        self._root = Path(root)

    async def upload_file(self, source: Any, destination: str) -> Any:
        """Store ``source`` bytes at ``destination`` under the local root."""
        data = await asyncio.to_thread(source.read_bytes) if isinstance(source, Path) else source.read()
        path = self._root / destination
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return SimpleNamespace(path=destination, size=len(data))

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Return a local ``file://`` URL for ``path``."""
        return f"file://{self._root / path}?expiry={expiry}"

    async def download_file(self, source: str, destination: Any) -> Path:
        """Copy a stored object to ``destination``."""
        data = await asyncio.to_thread((self._root / source).read_bytes)
        if isinstance(destination, Path):
            destination.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(destination.write_bytes, data)
            return destination
        destination.write(data)
        return Path(getattr(destination, "name", source))


def _build_default_library(root: Path, *, adapter: Any) -> ManualLibrary:
    """Build a throwaway ManualLibrary (ephemeral catalog, local file store) for one spike run."""
    return ManualLibrary(
        catalog=_EphemeralCatalog(),
        storage_root=root / "storage",
        evidence_root=root / "evidence",
        adapter=adapter,
        file_manager=_LocalFileManager(root / "figures"),
        vision_client=None,
    )


def _matches_step(token: str, step: Step) -> bool:
    """Return whether an expected step token (a step_id or a text excerpt) identifies ``step``."""
    normalized = (token or "").strip()
    if not normalized:
        return False
    if normalized == step.identity.step_id:
        return True
    text = (step.text.value or "").casefold()
    return normalized.casefold() in text


def _lcs_ratio(expected: Sequence[str], steps: Sequence[Step]) -> float:
    """Return the longest-common-subsequence length between ``expected`` and ``steps``, over ``len(expected)``."""
    if not expected:
        return 1.0
    if not steps:
        return 0.0
    rows, cols = len(expected), len(steps)
    table = [[0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            if _matches_step(expected[i - 1], steps[j - 1]):
                table[i][j] = table[i - 1][j - 1] + 1
            else:
                table[i][j] = max(table[i - 1][j], table[i][j - 1])
    return table[rows][cols] / len(expected)


async def spike_figures(
    corpus_dir: Path, *, adapter: Any, expected: dict[str, Any], library: Any | None = None
) -> SpikeReport:
    """Run M6 extraction + M5 pass 2 over each manual; compare against expected.json hand counts."""
    owns_library = library is None
    tmp_dir = tempfile.TemporaryDirectory(prefix="manuals-spike-figures-") if owns_library else None
    if owns_library:
        library = _build_default_library(Path(tmp_dir.name), adapter=adapter)  # type: ignore[union-attr]
    notes: list[str] = []
    order_ratios: list[float] = []
    missing_required_total = 0
    primary_correct = 0
    primary_total = 0
    try:
        for filename, spec in expected.items():
            path = Path(corpus_dir) / filename
            if not path.is_file():
                notes.append(f"{filename}: not found under corpus_dir")
                continue
            result = await library.add_manual(
                path, equipment=[Path(filename).stem], revision="spike", force=True
            )
            if result.card is None:
                notes.append(f"{filename}: ingest refused ({'; '.join(result.warnings)})")
                continue
            steps = sorted(
                (step for procedure in result.card.procedures for step in procedure.steps),
                key=lambda step: step.order,
            )
            expected_steps = list(spec.get("steps", []))
            order_ratios.append(_lcs_ratio(expected_steps, steps))

            required = list(spec.get("required", []))
            missing_required_total += sum(
                1 for token in required if not any(_matches_step(token, step) for step in steps)
            )

            figures_by_id = {figure.media_id: figure for figure in result.card.figures}
            for order_key, expected_label in (spec.get("primary_figures") or {}).items():
                step = next((candidate for candidate in steps if str(candidate.order) == str(order_key)), None)
                if step is None:
                    continue
                primary_link = next((link for link in step.media if link.role == "primary"), None)
                if primary_link is None:
                    continue
                figure = figures_by_id.get(primary_link.media_id)
                if figure is None or not figure.label:
                    continue
                primary_total += 1
                if figure.label.strip().casefold() == str(expected_label).strip().casefold():
                    primary_correct += 1
    finally:
        if tmp_dir is not None:
            tmp_dir.cleanup()

    measurements = {
        "steps_in_order_ratio": (sum(order_ratios) / len(order_ratios)) if order_ratios else 0.0,
        "missing_required": float(missing_required_total),
        "primary_figure_accuracy": (primary_correct / primary_total) if primary_total else 1.0,
    }
    return _evaluate("figures", measurements, notes)


async def spike_video(corpus_dir: Path, *, adapter: Any, expected: dict[str, Any]) -> SpikeReport:
    """Run M7 alignment; score t_start/t_end precision and coverage per step (deterministic pass reported separately)."""
    tmp_dir = tempfile.TemporaryDirectory(prefix="manuals-spike-video-")
    notes: list[str] = []
    covered = precise_total = det_covered = det_total = expected_total = 0
    try:
        library = _build_default_library(Path(tmp_dir.name), adapter=adapter)
        video_expected: dict[str, Any] = expected.get("video", expected)
        for filename, spec in video_expected.items():
            manual_path = Path(corpus_dir) / filename
            transcript_path = Path(corpus_dir) / spec["transcript"]
            if not manual_path.is_file() or not transcript_path.is_file():
                notes.append(f"{filename}: manual or transcript not found under corpus_dir")
                continue
            result = await library.add_manual(
                manual_path, equipment=[Path(filename).stem], revision="spike", force=True
            )
            if result.card is None:
                notes.append(f"{filename}: ingest refused ({'; '.join(result.warnings)})")
                continue
            transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
            judgement_log = JudgementLog(Path(tmp_dir.name) / "_judgements" / f"{result.card.manual_id}.json")
            refs, links, _report = await align_video(
                result.card,
                uri=f"spike://{filename}",
                transcript=transcript,
                adapter=adapter,
                judgement_log=judgement_log,
                force=True,
            )
            order_by_step_id = {
                step.identity.step_id: step.order for procedure in result.card.procedures for step in procedure.steps
            }
            segments = spec.get("segments", {})
            expected_total += len(segments)
            for ref, link in zip(refs, links, strict=True):
                order = order_by_step_id.get(ref.label)
                window = segments.get(str(order)) if order is not None else None
                if window is None:
                    continue
                is_deterministic = link.origin == "manual"
                if is_deterministic:
                    det_total += 1
                precise_total += 1
                overlaps = (
                    ref.t_start is not None and ref.t_end is not None and ref.t_start < window[1] and window[0] < ref.t_end
                )
                if overlaps:
                    covered += 1
                    if is_deterministic:
                        det_covered += 1
    finally:
        tmp_dir.cleanup()

    measurements = {
        "coverage": (covered / expected_total) if expected_total else 0.0,
        "precision": (covered / precise_total) if precise_total else 0.0,
        "deterministic_coverage": (det_covered / expected_total) if expected_total else 0.0,
        "deterministic_precision": (det_covered / det_total) if det_total else 0.0,
    }
    return _evaluate("video", measurements, notes)


async def spike_tips(graph_store: Any, catalog: ManualCatalogStore, *, revisions: tuple[Path, Path]) -> SpikeReport:
    """Add three tips, publish rev B (one renumbered, one reworded, one removed); assert relink outcomes.

    ``revisions`` are only used to locate the already-ingested manual (by the sha256 of
    ``revisions[1]``'s bytes): ingesting rev A, **publishing it once** (so the graph records
    rev A as the manual's last-seen revision — :meth:`ManualGraphLoader.publish_all`'s relink
    step only fires when the graph's own memory of the revision differs from the catalog's
    current one), and then refreshing to rev B is the caller's job (e.g. via
    :class:`~.library.ManualLibrary`, exactly as :func:`spike_figures` already does for the
    same corpus). This spike only needs the resulting ``catalog`` to hold both revisions, then
    adds the three tips (attached to rev A's steps) and performs the publish that triggers
    relinking against rev B.
    """
    _rev_a_path, rev_b_path = revisions
    notes: list[str] = []
    payload = await asyncio.to_thread(Path(rev_b_path).read_bytes)
    sha_b = hashlib.sha256(payload).hexdigest()
    card = await catalog.find_by_sha(sha_b)
    if card is None or len(card.versions) < 2:
        notes.append(
            "revisions[1] was not found in the catalog with >= 2 versions; ingest rev A then refresh "
            "to rev B (e.g. via ManualLibrary.add_manual then .refresh) before calling spike_tips"
        )
        return _evaluate("tips", {"expected_outcomes_matched": 0.0}, notes)

    previous = ManualCard.model_validate(card.versions[-2].card_snapshot)
    previous_steps = sorted(
        (step for procedure in previous.procedures for step in procedure.steps), key=lambda step: step.order
    )
    if len(previous_steps) < 3:
        notes.append("revisions[0]'s manual has fewer than 3 steps; cannot exercise the three-tip matrix")
        return _evaluate("tips", {"expected_outcomes_matched": 0.0}, notes)

    # Positional picks matching the brainstorm's fixed matrix: the first step is the one most
    # likely to survive untouched (renumbered or unchanged), a middle step is the one most
    # likely reworded, and the last is the one most likely dropped in the next revision.
    picks: dict[str, tuple[Step, frozenset[str]]] = {
        "renumbered_or_unchanged": (previous_steps[0], frozenset({"source_identity", "unchanged"})),
        "reworded": (previous_steps[len(previous_steps) // 2], frozenset({"content_hash", "candidate"})),
        "removed": (previous_steps[-1], frozenset({"orphaned"})),
    }

    graph_loader = ManualGraphLoader(catalog=catalog, graph_store=graph_store)
    ctx = graph_loader.context()
    tip_ids: dict[str, str] = {}
    for label, (step, _accepted) in picks.items():
        tip = await add_tip(
            graph_store,
            ctx,
            step_id=step.identity.step_id,
            text=f"spike tip ({label})",
            author_employee_id="manuals-spike",
            source_revision=previous.revision,
        )
        tip_ids[label] = tip.tip_id

    publication = await graph_loader.publish(card)
    notes.extend(publication.errors)
    relink = publication.tip_relink
    if relink is None:
        notes.append("no tips were relinked by the publish; the previous revision's steps may be unreachable")
        return _evaluate("tips", {"expected_outcomes_matched": 0.0}, notes)

    outcomes_by_tip_id = {outcome.tip_id: outcome for outcome in (relink.relinked + relink.orphaned + relink.candidates)}
    matched = 0
    for label, (_step, accepted) in picks.items():
        tip_id = tip_ids[label]
        outcome = outcomes_by_tip_id.get(tip_id)
        if outcome is not None and outcome.method in accepted:
            matched += 1
        else:
            got = outcome.method if outcome is not None else "missing"
            notes.append(f"{label}: expected one of {sorted(accepted)}, got {got!r}")

    return _evaluate("tips", {"expected_outcomes_matched": float(matched)}, notes)


async def spike_media(answer: ProcedureAnswer, *, channels: Sequence[str]) -> SpikeReport:
    """Deliver one presigned figure through the named channel wrappers; record render/send outcome per channel."""
    from parrot.integrations.parser import ParsedResponse  # noqa: PLC0415 - optional satellite, lazy on purpose

    notes: list[str] = []
    url = answer.media[0].media_id if answer.media else None
    if url is None:
        notes.append("answer.media is empty; nothing to deliver")

    delivered = 0
    for channel in channels:
        sender = CHANNEL_SENDERS.get(channel)
        if sender is None:
            notes.append(f"{channel}: no sender registered")
            continue
        parsed = ParsedResponse(image_urls=[url] if url else [])
        try:
            await sender(channel, parsed)
        except Exception as exc:  # noqa: BLE001 - per-channel delivery failure is recorded, not fatal
            notes.append(f"{channel}: {exc}")
            continue
        delivered += 1

    return _evaluate("media", {"channels_delivered": float(delivered)}, notes)
