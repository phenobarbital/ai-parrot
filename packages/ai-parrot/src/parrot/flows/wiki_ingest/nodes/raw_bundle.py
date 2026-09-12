"""Raw bundle layer — pairing, hashing, immutable moves (FEAT-481,
spec Module 3, contract §13/§14/§27).

Deterministic, no LLM calls. Operates on plain filesystem paths under
``Raw/`` via ``pathlib``/``shutil`` — raw files are outside Obsidian's
page model (§7 "Safe Tool Use"), so this module does not go through
:class:`~parrot.tools.obsidian.ObsidianToolkit`.

**Sequencing note.** The pipeline places this module BEFORE classification
(spec Component Diagram: ``[RawBundle] ... move→Raw/Processed`` precedes
``[Classify+Confidence]``) — so the initial move always routes to
``Raw/Processed/Uncategorized/<source-id>/`` (this task's own
Implementation Notes: "Destination client/project come from TASK-2665's
classification; default Uncategorized/"). :func:`reclassify_move` is the
follow-up move the classify node (Module 7) calls once the primary
client/project are known — every move (initial or reclassify) verifies
pre/post hashes, so raw bytes are never edited regardless of how many
times a bundle is relocated.

**No revisions (R3).** ``Raw/Processed/Revisions/`` does not exist and is
never created — a source id already present under ``Raw/Processed/``
(scanned the same way the fetch-gate does) routes any further occurrence
to ``Raw/Processed/Duplicates/<source-id>/`` as a permanent
``duplicate-skip``, never a revision.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from parrot.agents.meeting_registry import fingerprint

from .. import conf
from .fetch_gate import GatedMeeting, _scan_raw_processed_ids

logger = logging.getLogger(__name__)

#: Matches this subsystem's own Raw/Incoming/ filename convention:
#: "<source-id>.<kind>.<ext>" — kind is transcript/summary/metadata.
_INCOMING_NAME_RE = re.compile(r"^(?P<source_id>.+)\.(?P<kind>transcript|summary|metadata)\.[^.]+$")


class PairedBundle(BaseModel):
    """One paired Raw/Incoming/ bundle (§13).

    Attributes:
        source_id: The raw Fireflies id (no ``"fireflies:"`` prefix) used
            as the pairing key.
        transcript_path: Vault-relative path of the transcript file.
        summary_path: Vault-relative path of the summary file, if paired.
        metadata_path: Vault-relative path of the metadata file, if paired.
    """

    source_id: str
    transcript_path: str
    summary_path: str | None = None
    metadata_path: str | None = None


class UnpairedGroup(BaseModel):
    """An incomplete/ambiguous Raw/Incoming/ group (§13 — review item).

    Attributes:
        source_id: The inferred pairing key.
        paths: The vault-relative paths found for this key.
        reason: Why pairing failed (e.g. "missing transcript").
    """

    source_id: str
    paths: list[str]
    reason: str


class BundleHashes(BaseModel):
    """SHA-256 hashes for one paired bundle (§14.2)."""

    transcript_sha256: str
    summary_sha256: str | None = None


class ProcessedBundle(BaseModel):
    """Result of moving one paired bundle into ``Raw/Processed/`` (§14).

    Attributes:
        source_id: The raw Fireflies id.
        outcome: ``"processed"`` (moved to its classified/uncategorized
            destination) or ``"duplicate-skip"`` (a bundle for this id
            already exists under ``Raw/Processed/`` — routed to
            ``Duplicates/`` instead, R3).
        transcript_path: Final vault-relative transcript path.
        summary_path: Final vault-relative summary path, if any.
        metadata_path: Final vault-relative metadata path, if any.
        hashes: The verified :class:`BundleHashes`.
    """

    source_id: str
    outcome: Literal["processed", "duplicate-skip"]
    transcript_path: str
    summary_path: str | None = None
    metadata_path: str | None = None
    hashes: BundleHashes


def write_bundle_to_incoming(vault_path: str | Path, meeting: GatedMeeting) -> list[str]:
    """§13 — write a fetched meeting's transcript/summary/metadata into
    ``Raw/Incoming/`` unchanged (no normalization, no editing).

    Args:
        vault_path: The Obsidian vault root.
        meeting: A :class:`~.fetch_gate.GatedMeeting` with
            ``outcome == "fetch"`` (has ``transcript_text``).

    Returns:
        The vault-relative paths written.

    Raises:
        ValueError: If ``meeting.transcript_text`` is missing.
    """
    if meeting.transcript_text is None:
        raise ValueError(f"write_bundle_to_incoming: {meeting.fireflies_id} has no transcript_text to write")

    incoming = Path(vault_path) / conf.WIKI_KB_RAW_ROOT / "Incoming"
    incoming.mkdir(parents=True, exist_ok=True)

    written: list[str] = []

    transcript_file = incoming / f"{meeting.fireflies_id}.transcript.md"
    transcript_file.write_text(meeting.transcript_text, encoding="utf-8")
    written.append(_rel(vault_path, transcript_file))

    if meeting.summary_text is not None:
        summary_file = incoming / f"{meeting.fireflies_id}.summary.md"
        summary_file.write_text(meeting.summary_text, encoding="utf-8")
        written.append(_rel(vault_path, summary_file))

    metadata = {
        "fireflies_id": meeting.fireflies_id,
        "source_id": meeting.source_id,
        "title": meeting.title,
        "meeting_date": meeting.meeting_date,
        "meeting_date_iso": meeting.meeting_date_iso,
        "participants": meeting.participants,
        "duration_minutes": meeting.duration_minutes,
    }
    metadata_file = incoming / f"{meeting.fireflies_id}.metadata.json"
    metadata_file.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    written.append(_rel(vault_path, metadata_file))

    return written


def pair_incoming_bundles(incoming_dir: Path) -> tuple[list[PairedBundle], list[UnpairedGroup]]:
    """§13 — pair files under ``Raw/Incoming/`` by the strongest available key.

    This subsystem's own writer (:func:`write_bundle_to_incoming`) embeds
    the source id directly in the filename (the strongest key, §13 rule
    1), so pairing here is a straightforward group-by; the ladder's
    weaker keys (shared id in filenames / explicit refs / normalized
    stem+date+title) are not needed for bundles this subsystem wrote
    itself, but any other file dropped into ``Incoming/`` groups the same
    way — anything that does not match the ``<id>.<kind>.<ext>``
    convention at all is reported as its own unpaired, single-file group.

    Args:
        incoming_dir: The ``Raw/Incoming/`` directory (created if it does
            not yet exist).

    Returns:
        ``(paired, unpaired)`` — complete bundles (has a transcript file)
        and incomplete/ambiguous groups (§13 — a review item; do not
        guess, leave raw untouched, continue with the rest).
    """
    if not incoming_dir.is_dir():
        return [], []

    groups: dict[str, dict[str, Path]] = {}
    unmatched: list[UnpairedGroup] = []

    for path in sorted(incoming_dir.iterdir()):
        if not path.is_file():
            continue
        match = _INCOMING_NAME_RE.match(path.name)
        if not match:
            unmatched.append(
                UnpairedGroup(source_id=path.stem, paths=[path.name], reason="does not match <id>.<kind>.<ext>")
            )
            continue
        source_id = match.group("source_id")
        kind = match.group("kind")
        groups.setdefault(source_id, {})[kind] = path

    paired: list[PairedBundle] = []
    unpaired: list[UnpairedGroup] = list(unmatched)
    for source_id, kinds in groups.items():
        transcript = kinds.get("transcript")
        if transcript is None:
            unpaired.append(
                UnpairedGroup(
                    source_id=source_id,
                    paths=[p.name for p in kinds.values()],
                    reason="missing transcript",
                )
            )
            continue
        paired.append(
            PairedBundle(
                source_id=source_id,
                transcript_path=transcript.name,
                summary_path=kinds["summary"].name if "summary" in kinds else None,
                metadata_path=kinds["metadata"].name if "metadata" in kinds else None,
            )
        )
    return paired, unpaired


def hash_bundle(incoming_dir: Path, bundle: PairedBundle) -> BundleHashes:
    """§14.2 — SHA-256 the paired bundle's files.

    The transcript is hashed via FEAT-472's :func:`fingerprint`
    (``sha256(normalise_transcript(text))``), aligning with the
    ``MeetingRegistry``'s own fingerprint so the two never disagree on
    "did the content change". The summary is hashed separately, on its
    raw bytes (no normalization — normalization is transcript-specific).

    Args:
        incoming_dir: The ``Raw/Incoming/`` directory containing the
            bundle's files.
        bundle: The :class:`PairedBundle` to hash.

    Returns:
        The computed :class:`BundleHashes`.
    """
    transcript_text = (incoming_dir / bundle.transcript_path).read_text(encoding="utf-8")
    summary_sha256 = None
    if bundle.summary_path is not None:
        summary_bytes = (incoming_dir / bundle.summary_path).read_bytes()
        summary_sha256 = hashlib.sha256(summary_bytes).hexdigest()
    return BundleHashes(transcript_sha256=fingerprint(transcript_text), summary_sha256=summary_sha256)


def _hash_file(path: Path) -> str:
    """Plain SHA-256 of a file's raw bytes (post-move verification)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(vault_path: str | Path, path: Path) -> str:
    """Vault-relative POSIX path string for ``path``."""
    return path.relative_to(Path(vault_path)).as_posix()


def _move_verified(src: Path, dst: Path) -> None:
    """Move one raw file, verifying the pre/post-move hash matches.

    Args:
        src: Source path (must exist).
        dst: Destination path (parent directories created as needed).

    Raises:
        RuntimeError: If the post-move hash does not match the pre-move
            hash — the caller must treat the whole bundle as failed and
            not proceed (raw immutability, §2 rule 2).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    pre_hash = _hash_file(src)
    shutil.move(str(src), str(dst))
    post_hash = _hash_file(dst)
    if post_hash != pre_hash:
        raise RuntimeError(f"raw immutable move hash mismatch: {src} -> {dst} (pre={pre_hash} post={post_hash})")


def move_to_processed(
    vault_path: str | Path,
    incoming_dir: Path,
    bundle: PairedBundle,
    hashes: BundleHashes,
    *,
    meeting_date: str,
    client: str = "Uncategorized",
    project: str | None = None,
) -> ProcessedBundle:
    """§14 — immutably move a paired bundle from ``Raw/Incoming/`` into
    ``Raw/Processed/``.

    A source id already present under ``Raw/Processed/`` (scanned via
    :func:`~.fetch_gate._scan_raw_processed_ids`) routes this occurrence
    to ``Raw/Processed/Duplicates/<source-id>/`` instead — a permanent
    ``duplicate-skip`` (R3), never a revision. Every file move verifies
    its pre/post hash; a mismatch aborts the whole bundle (nothing is
    left half-moved into the destination).

    Args:
        vault_path: The Obsidian vault root.
        incoming_dir: The ``Raw/Incoming/`` directory holding the bundle.
        bundle: The :class:`PairedBundle` to move.
        hashes: The bundle's :class:`BundleHashes` (from :func:`hash_bundle`).
        meeting_date: ``YYYY-MM-DD`` — used for the ``YYYY/MM`` routing
            tier when ``client`` is not ``"Uncategorized"``.
        client: Primary client folder name (default ``"Uncategorized"`` —
            spec Module 3: destination client/project are unknown before
            classification runs).
        project: Primary project folder name (required unless ``client``
            is ``"Uncategorized"``).

    Returns:
        The :class:`ProcessedBundle` result.

    Raises:
        RuntimeError: On a post-move hash mismatch (see :func:`_move_verified`).
    """
    vault_path = Path(vault_path)
    processed_root = vault_path / conf.WIKI_KB_RAW_ROOT / "Processed"
    known_ids = _scan_raw_processed_ids(processed_root)

    if bundle.source_id in known_ids:
        destination = processed_root / "Duplicates" / bundle.source_id
        outcome: Literal["processed", "duplicate-skip"] = "duplicate-skip"
    elif client == "Uncategorized":
        destination = processed_root / "Uncategorized" / bundle.source_id
        outcome = "processed"
    else:
        if not project:
            raise ValueError("move_to_processed: 'project' is required when client != 'Uncategorized'")
        year, month = meeting_date[:4], meeting_date[5:7]
        destination = processed_root / client / project / year / month / bundle.source_id
        outcome = "processed"

    transcript_dst = destination / "transcript.md"
    _move_verified(incoming_dir / bundle.transcript_path, transcript_dst)

    summary_dst_rel = None
    if bundle.summary_path is not None:
        summary_dst = destination / "summary.md"
        _move_verified(incoming_dir / bundle.summary_path, summary_dst)
        summary_dst_rel = _rel(vault_path, summary_dst)

    metadata_dst_rel = None
    if bundle.metadata_path is not None:
        metadata_dst = destination / "metadata.json"
        _move_verified(incoming_dir / bundle.metadata_path, metadata_dst)
        metadata_dst_rel = _rel(vault_path, metadata_dst)

    return ProcessedBundle(
        source_id=bundle.source_id,
        outcome=outcome,
        transcript_path=_rel(vault_path, transcript_dst),
        summary_path=summary_dst_rel,
        metadata_path=metadata_dst_rel,
        hashes=hashes,
    )


def reclassify_move(
    vault_path: str | Path,
    processed: ProcessedBundle,
    *,
    meeting_date: str,
    client: str,
    project: str,
) -> ProcessedBundle:
    """Relocate an already-``Uncategorized/``-routed bundle once
    classification (spec Module 7) has determined its primary
    client/project.

    Every file move re-verifies its hash — raw bytes are never edited by
    a reclassification, only relocated.

    Args:
        vault_path: The Obsidian vault root.
        processed: The bundle's current :class:`ProcessedBundle` (from
            :func:`move_to_processed`, ``outcome == "processed"``).
        meeting_date: ``YYYY-MM-DD``.
        client: The classified primary client folder name.
        project: The classified primary project folder name.

    Returns:
        The updated :class:`ProcessedBundle` at its new location.

    Raises:
        ValueError: If ``processed.outcome != "processed"`` (a
            duplicate-skip bundle in ``Duplicates/`` is never relocated).
    """
    if processed.outcome != "processed":
        raise ValueError("reclassify_move: only a 'processed' bundle can be relocated")

    vault_path = Path(vault_path)
    year, month = meeting_date[:4], meeting_date[5:7]
    destination = (
        vault_path / conf.WIKI_KB_RAW_ROOT / "Processed" / client / project / year / month / processed.source_id
    )

    transcript_dst = destination / "transcript.md"
    _move_verified(vault_path / processed.transcript_path, transcript_dst)

    summary_dst_rel = None
    if processed.summary_path is not None:
        summary_dst = destination / "summary.md"
        _move_verified(vault_path / processed.summary_path, summary_dst)
        summary_dst_rel = _rel(vault_path, summary_dst)

    metadata_dst_rel = None
    if processed.metadata_path is not None:
        metadata_dst = destination / "metadata.json"
        _move_verified(vault_path / processed.metadata_path, metadata_dst)
        metadata_dst_rel = _rel(vault_path, metadata_dst)

    return ProcessedBundle(
        source_id=processed.source_id,
        outcome="processed",
        transcript_path=_rel(vault_path, transcript_dst),
        summary_path=summary_dst_rel,
        metadata_path=metadata_dst_rel,
        hashes=processed.hashes,
    )
