"""Unit tests for `parrot.flows.thales.models` (FEAT-425 TASK-2226)."""

import pytest
from pydantic import ValidationError

from parrot.flows.thales.models import (
    Bibliography,
    Finding,
    ResearchAngle,
    ResearchDeck,
    SlideSpec,
    SourceClaim,
    ThalesConfig,
    ThalesResult,
)
from parrot.flows.thales.models.result import ArtifactRef


class TestThalesConfig:
    def test_num_decks_floor(self):
        with pytest.raises(ValidationError):
            ThalesConfig(thesis="t", num_decks=9)

    def test_num_decks_default(self):
        assert ThalesConfig(thesis="t").num_decks == 10

    def test_num_decks_no_cap(self):
        assert ThalesConfig(thesis="t", num_decks=500).num_decks == 500

    def test_default_sources(self):
        cfg = ThalesConfig(thesis="t")
        assert cfg.sources == ["web", "deep_research", "arxiv"]

    def test_max_paragraphs_default(self):
        assert ThalesConfig(thesis="t").max_paragraphs_per_finding == 6


class TestSourceClaim:
    def test_verification_labels(self):
        for label in ("groundedness", "provider_grounding", "unverified"):
            assert SourceClaim(
                url="https://x",
                accessed_date="2026-08-17",
                source_tool="web_search",
                verification=label,
            )

    def test_verification_rejects_unknown_label(self):
        with pytest.raises(ValidationError):
            SourceClaim(
                url="https://x",
                accessed_date="2026-08-17",
                source_tool="web_search",
                verification="vibes",
            )

    def test_published_date_optional(self):
        claim = SourceClaim(
            url="https://x",
            accessed_date="2026-08-17",
            source_tool="web_search",
            verification="unverified",
        )
        assert claim.published_date is None


class TestRoundTrip:
    def test_deck_roundtrip(self):
        deck = ResearchDeck(
            angle=ResearchAngle(angle_id="a1", title="t", question="q", rationale="r"),
            findings=[],
            tools_used=["web_search"],
        )
        assert ResearchDeck.model_validate_json(deck.model_dump_json()) == deck

    def test_slide_spec_roundtrip(self):
        spec = SlideSpec(
            deck_ref="a1",
            layout="default",
            headline="Headline",
            bullets=["one", "two"],
        )
        assert SlideSpec.model_validate_json(spec.model_dump_json()) == spec

    def test_thales_result_roundtrip(self):
        result = ThalesResult(
            thesis="t",
            decks=[],
            slides=[],
            bibliography=Bibliography(),
            executive_summary="summary",
            final_document=ArtifactRef(kind="final_html"),
        )
        assert ThalesResult.model_validate_json(result.model_dump_json()) == result

    def test_finding_requires_claims_list(self):
        finding = Finding(text="text", claims=[])
        assert finding.numeric_series is None
        assert Finding.model_validate_json(finding.model_dump_json()) == finding
