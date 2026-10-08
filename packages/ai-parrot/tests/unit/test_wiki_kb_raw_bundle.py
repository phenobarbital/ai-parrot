"""Unit tests for the raw bundle layer (FEAT-481, spec Module 3 /
TASK-2664): pairing, hashing, immutable moves, duplicate routing.
"""

from __future__ import annotations

from pathlib import Path

from parrot.flows.wiki_ingest.nodes import raw_bundle
from parrot.flows.wiki_ingest.nodes.fetch_gate import GatedMeeting


def _fetched_meeting(fireflies_id: str = "id-1") -> GatedMeeting:
    return GatedMeeting(
        fireflies_id=fireflies_id,
        source_id=f"fireflies:{fireflies_id}",
        title="Weekly Sync",
        meeting_date="2026-08-20",
        meeting_date_iso="2026-08-20T10:00:00-05:00",
        participants=["a@x.com"],
        duration_minutes=30.0,
        outcome="fetch",
        transcript_text="This is the transcript.",
        summary_text="This is the summary.",
    )


def test_write_bundle_to_incoming(tmp_path: Path) -> None:
    meeting = _fetched_meeting()
    written = raw_bundle.write_bundle_to_incoming(tmp_path, meeting)

    assert "Raw/Incoming/id-1.transcript.md" in written
    assert "Raw/Incoming/id-1.summary.md" in written
    assert "Raw/Incoming/id-1.metadata.json" in written
    assert (tmp_path / "Raw/Incoming/id-1.transcript.md").read_text() == "This is the transcript."


def test_pair_incoming_bundles_complete(tmp_path: Path) -> None:
    meeting = _fetched_meeting()
    raw_bundle.write_bundle_to_incoming(tmp_path, meeting)
    incoming_dir = tmp_path / "Raw" / "Incoming"

    paired, unpaired = raw_bundle.pair_incoming_bundles(incoming_dir)

    assert unpaired == []
    assert len(paired) == 1
    assert paired[0].source_id == "id-1"
    assert paired[0].summary_path == "id-1.summary.md"
    assert paired[0].metadata_path == "id-1.metadata.json"


def test_incomplete_bundle_review_item(tmp_path: Path) -> None:
    """A missing transcript is reported as an unpaired review item;
    other complete bundles still process."""
    incoming_dir = tmp_path / "Raw" / "Incoming"
    incoming_dir.mkdir(parents=True)
    (incoming_dir / "orphan.summary.md").write_text("summary only", encoding="utf-8")

    raw_bundle.write_bundle_to_incoming(tmp_path, _fetched_meeting("id-2"))

    paired, unpaired = raw_bundle.pair_incoming_bundles(incoming_dir)

    assert len(paired) == 1
    assert paired[0].source_id == "id-2"
    assert len(unpaired) == 1
    assert unpaired[0].source_id == "orphan"
    assert unpaired[0].reason == "missing transcript"


def test_pair_unmatched_filename_is_reported(tmp_path: Path) -> None:
    incoming_dir = tmp_path / "Raw" / "Incoming"
    incoming_dir.mkdir(parents=True)
    (incoming_dir / "random-file.txt").write_text("nope", encoding="utf-8")

    paired, unpaired = raw_bundle.pair_incoming_bundles(incoming_dir)

    assert paired == []
    assert len(unpaired) == 1
    assert "does not match" in unpaired[0].reason


def test_immutable_move_hash_verify(tmp_path: Path) -> None:
    """Pre/post-move hashes match; raw bytes are unchanged after the move."""
    meeting = _fetched_meeting()
    raw_bundle.write_bundle_to_incoming(tmp_path, meeting)
    incoming_dir = tmp_path / "Raw" / "Incoming"
    paired, _ = raw_bundle.pair_incoming_bundles(incoming_dir)
    bundle = paired[0]

    original_transcript_bytes = (incoming_dir / bundle.transcript_path).read_bytes()
    hashes = raw_bundle.hash_bundle(incoming_dir, bundle)

    result = raw_bundle.move_to_processed(tmp_path, incoming_dir, bundle, hashes, meeting_date=meeting.meeting_date)

    assert result.outcome == "processed"
    assert result.transcript_path == "Raw/Processed/Uncategorized/id-1/transcript.md"
    assert (tmp_path / result.transcript_path).read_bytes() == original_transcript_bytes
    # Incoming copy is gone (moved, not copied).
    assert not (incoming_dir / bundle.transcript_path).exists()


def test_move_to_processed_classified_destination(tmp_path: Path) -> None:
    meeting = _fetched_meeting()
    raw_bundle.write_bundle_to_incoming(tmp_path, meeting)
    incoming_dir = tmp_path / "Raw" / "Incoming"
    paired, _ = raw_bundle.pair_incoming_bundles(incoming_dir)
    bundle = paired[0]
    hashes = raw_bundle.hash_bundle(incoming_dir, bundle)

    result = raw_bundle.move_to_processed(
        tmp_path,
        incoming_dir,
        bundle,
        hashes,
        meeting_date="2026-08-20",
        client="Acme",
        project="Roadmap",
    )

    assert result.transcript_path == "Raw/Processed/Acme/Roadmap/2026/08/id-1/transcript.md"


def test_known_id_duplicate_skip(tmp_path: Path) -> None:
    """A source id already under Raw/Processed/ routes to Duplicates/ as
    a permanent duplicate-skip — never a Revisions/ entry."""
    # Pre-seed Raw/Processed/ as if id-1 was already processed.
    existing = tmp_path / "Raw" / "Processed" / "Uncategorized" / "id-1"
    existing.mkdir(parents=True)
    (existing / "transcript.md").write_text("already processed", encoding="utf-8")

    meeting = _fetched_meeting("id-1")
    raw_bundle.write_bundle_to_incoming(tmp_path, meeting)
    incoming_dir = tmp_path / "Raw" / "Incoming"
    paired, _ = raw_bundle.pair_incoming_bundles(incoming_dir)
    bundle = paired[0]
    hashes = raw_bundle.hash_bundle(incoming_dir, bundle)

    result = raw_bundle.move_to_processed(tmp_path, incoming_dir, bundle, hashes, meeting_date=meeting.meeting_date)

    assert result.outcome == "duplicate-skip"
    assert result.transcript_path == "Raw/Processed/Duplicates/id-1/transcript.md"
    assert not (tmp_path / "Raw" / "Processed" / "Revisions").exists()
    # The original, already-processed bundle is untouched.
    assert (existing / "transcript.md").read_text() == "already processed"


def test_reclassify_move_relocates_processed_bundle(tmp_path: Path) -> None:
    meeting = _fetched_meeting()
    raw_bundle.write_bundle_to_incoming(tmp_path, meeting)
    incoming_dir = tmp_path / "Raw" / "Incoming"
    paired, _ = raw_bundle.pair_incoming_bundles(incoming_dir)
    bundle = paired[0]
    hashes = raw_bundle.hash_bundle(incoming_dir, bundle)
    processed = raw_bundle.move_to_processed(tmp_path, incoming_dir, bundle, hashes, meeting_date=meeting.meeting_date)

    relocated = raw_bundle.reclassify_move(
        tmp_path, processed, meeting_date="2026-08-20", client="Acme", project="Roadmap"
    )

    assert relocated.transcript_path == "Raw/Processed/Acme/Roadmap/2026/08/id-1/transcript.md"
    assert (tmp_path / relocated.transcript_path).exists()
    assert not (tmp_path / processed.transcript_path).exists()
