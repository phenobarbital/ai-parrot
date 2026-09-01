"""Unit tests for §10 frontmatter schemas + §34 validation (FEAT-481,
spec Module 5 / TASK-2661).
"""
from __future__ import annotations

import pytest
from parrot.flows.wiki_ingest.models import (
    ActionItem,
    Classification,
    ContradictionFrontmatter,
    EntityFrontmatter,
    MeetingExtraction,
    MeetingSourceFrontmatter,
)
from parrot.flows.wiki_ingest.validation import ValidationContext, validate
from pydantic import ValidationError

_BASE_KWARGS = {
    "id": "source:fireflies:abc123",
    "title": "Weekly Sync",
    "source_id": "fireflies:abc123",
    "meeting_date": "2026-08-31",
    "processed_at": "2026-08-31T12:00:00+00:00",
    "processing_mode": "summary-only",
    "classification_confidence": "high",
    "raw_summary": "Raw/Processed/acme/proj/2026/08/fireflies-abc123/summary.md",
    "raw_transcript": "Raw/Processed/acme/proj/2026/08/fireflies-abc123/transcript.md",
    "summary_sha256": "a" * 64,
    "transcript_sha256": "b" * 64,
    "primary_project": "[[Projects/Acme/Acme]]",
    "projects": ["[[Projects/Acme/Acme]]"],
    "created": "2026-08-31T12:00:00+00:00",
    "updated": "2026-08-31T12:00:00+00:00",
}


def test_meeting_source_frontmatter_valid() -> None:
    """A well-formed frontmatter block validates cleanly."""
    fm = MeetingSourceFrontmatter(**_BASE_KWARGS)
    assert fm.primary_project in fm.projects


def test_primary_project_invariant() -> None:
    """D2 — primary_project not in projects fails validation."""
    kwargs = dict(_BASE_KWARGS, projects=["[[Projects/Other/Other]]"])
    with pytest.raises(ValidationError, match="D2"):
        MeetingSourceFrontmatter(**kwargs)


def test_raw_provenance_plain_paths() -> None:
    """D1 — a [[wikilink]] in raw_transcript/raw_summary fails."""
    kwargs = dict(_BASE_KWARGS, raw_transcript="[[Raw/Processed/x/transcript]]")
    with pytest.raises(ValidationError, match="D1"):
        MeetingSourceFrontmatter(**kwargs)


def test_source_id_must_be_fireflies_prefixed() -> None:
    """D4 — source_id must be 'fireflies:<id>'."""
    kwargs = dict(_BASE_KWARGS, source_id="abc123")
    with pytest.raises(ValidationError, match="D4"):
        MeetingSourceFrontmatter(**kwargs)


def test_entity_id_prefix_matches_type() -> None:
    """Entity id prefix must match its type."""
    with pytest.raises(ValidationError):
        EntityFrontmatter(
            id="company:acme",
            type="person",
            title="Acme Corp",
            created="2026-08-31T12:00:00+00:00",
            updated="2026-08-31T12:00:00+00:00",
        )


def test_classification_and_extraction_models() -> None:
    """Classification/MeetingExtraction construct with defaults."""
    classification = Classification(confidence="medium")
    assert classification.additional_projects == []
    extraction = MeetingExtraction(action_items=[ActionItem(action="Follow up")])
    assert extraction.action_items[0].owner == "Unknown"


def test_validate_passes_on_empty_context() -> None:
    """An empty ValidationContext (nothing to check) passes cleanly."""
    result = validate(ValidationContext())
    assert result.passed
    assert result.failures == []


def test_validate_flags_dangling_wikilink_and_fabrication() -> None:
    """validate() flags a dangling wikilink (§8.1) and a fabricated
    value substituted for an insufficient-evidence field (rule #12)."""
    ctx = ValidationContext(
        new_wikilinks=["Wiki/Entities/People/Ghost Person"],
        existing_or_queued_pages=[],
        insufficient_evidence_fields={"meeting owner": "Definitely Bob"},
    )
    result = validate(ctx)
    assert not result.passed
    assert any("dangling wikilink" in f for f in result.failures)
    assert any("rule #12" in f for f in result.failures)


def test_validate_allows_placeholder_for_insufficient_evidence() -> None:
    """A properly-rendered placeholder (rule #12) does not fail validation."""
    ctx = ValidationContext(insufficient_evidence_fields={"meeting owner": "Unknown"})
    result = validate(ctx)
    assert result.passed


def test_validate_flags_raw_immutability_violation() -> None:
    """§34 source integrity: pre/post-move hash mismatch fails."""
    ctx = ValidationContext(
        pre_move_hashes={"Raw/Processed/x/transcript.md": "hash-a"},
        post_move_hashes={"Raw/Processed/x/transcript.md": "hash-b"},
    )
    result = validate(ctx)
    assert not result.passed
    assert any("hash mismatch" in f for f in result.failures)


def test_validate_flags_private_access() -> None:
    """§34 operational integrity: Private/ accessed fails (§2 rule 1)."""
    result = validate(ValidationContext(private_accessed=True))
    assert not result.passed
    assert any("Private/" in f for f in result.failures)


def test_validate_flags_unsafe_filename() -> None:
    """§8.2 — a filename with unsafe punctuation fails."""
    result = validate(ValidationContext(written_filenames=["2026-08-31 - Q3: Review.md"]))
    assert not result.passed
    assert any("unsafe" in f for f in result.failures)


def test_contradiction_frontmatter_requires_severity() -> None:
    """§10.5 — severity is a required enum field."""
    with pytest.raises(ValidationError):
        ContradictionFrontmatter(
            id="contradiction:foo",
            title="Foo",
            created="2026-08-31T12:00:00+00:00",
            updated="2026-08-31T12:00:00+00:00",
        )
