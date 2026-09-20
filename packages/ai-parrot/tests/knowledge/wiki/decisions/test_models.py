"""Model invariants for the ADR decision plane (FEAT-578 Module 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.knowledge.wiki.decisions.models import (
    DecisionConfig,
    DecisionError,
    DecisionLink,
    DecisionRecord,
    EvidenceRef,
    ReviewRequest,
)
from parrot.knowledge.wiki.project import WikiProjectConfig


def _evidence(**overrides) -> EvidenceRef:
    """Build a valid EvidenceRef, overriding single fields per test."""
    base = dict(
        page_id="file:a.py",
        rel_path="a.py",
        start_line=1,
        end_line=3,
        source_sha1="d0",
        excerpt="x",
        kind="code",
    )
    return EvidenceRef(**{**base, **overrides})


class TestDecisionConfig:
    def test_defaults_disable_generation(self):
        """Generation is opt-in — a bare config never enables a model call (AC5)."""
        config = DecisionConfig()
        assert config.generation_enabled is False
        assert config.adr_globs == [
            "docs/adr/**/*.md",
            "docs/adrs/**/*.md",
            "docs/decisions/**/*.md",
        ]

    def test_project_config_carries_decisions(self):
        """WikiProjectConfig gains the field without breaking existing configs."""
        assert WikiProjectConfig().decisions == DecisionConfig()
        # A config dict without a "decisions" key must still validate.
        loaded = WikiProjectConfig.model_validate({"wiki_name": "codebase"})
        assert loaded.decisions == DecisionConfig()

    @pytest.mark.parametrize("field,value", [("max_records", 0), ("max_files", 0), ("timeout_seconds", 0)])
    def test_rejects_non_positive_limits(self, field, value):
        """Every numeric limit is positive (spec §2 Data Models)."""
        with pytest.raises(ValidationError):
            DecisionConfig(**{field: value})


class TestEvidenceRef:
    def test_rejects_inverted_range(self):
        """end_line < start_line is not a span."""
        with pytest.raises(ValidationError):
            _evidence(start_line=9, end_line=2)

    @pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.py"])
    def test_rejects_unconfined_path(self, bad):
        """Paths stay repository-relative (ADR_PATH_OUTSIDE_ROOT rationale)."""
        with pytest.raises(ValidationError):
            _evidence(rel_path=bad)


class TestDecisionRecord:
    def test_inferred_record_cannot_claim_a_source_status(self):
        """AC11: inferred provenance pins source_status to 'unknown'."""
        with pytest.raises(ValidationError):
            DecisionRecord(
                decision_id="adr:inferred:x",
                decision="d",
                origin="inferred",
                source_status="accepted",
            )
        # origin='inferred' + source_status='unknown' (the default) succeeds.
        record = DecisionRecord(decision_id="adr:inferred:x", decision="d", origin="inferred")
        assert record.origin == "inferred"
        assert record.source_status == "unknown"

    def test_link_evidence_indexes_must_address_own_evidence(self):
        """A link may only cite evidence this record actually carries (AC4)."""
        with pytest.raises(ValidationError):
            DecisionRecord(
                decision_id="adr:doc:x",
                decision="d",
                origin="documented",
                evidence=[_evidence()],
                links=[
                    DecisionLink(
                        target_id="adr:doc:y", relation="explains", provenance="extracted", evidence_indexes=[5]
                    )
                ],
            )

    def test_extra_fields_are_forbidden(self):
        """A forged field never survives into a stored record."""
        with pytest.raises(ValidationError):
            DecisionRecord(decision_id="adr:doc:x", decision="d", origin="documented", forged=True)


class TestReviewRequest:
    def test_revise_requires_replacement(self):
        """A 'revise' with no CandidateEdit is an invalid argument."""
        with pytest.raises(ValidationError):
            ReviewRequest(decision_id="adr:doc:x", expected_revision=1, action="revise", actor="human:jlara")

    def test_link_requires_documented_id(self):
        """A 'link' with no documented_decision_id is an invalid argument."""
        with pytest.raises(ValidationError):
            ReviewRequest(decision_id="adr:doc:x", expected_revision=1, action="link", actor="human:jlara")


def test_decision_error_carries_code_and_id():
    """DecisionError exposes code/message/decision_id for CLI + MCP rendering."""
    err = DecisionError("ADR_REVISION_CONFLICT", "stale", decision_id="adr:doc:a")
    assert (err.code, err.decision_id) == ("ADR_REVISION_CONFLICT", "adr:doc:a")
    assert isinstance(err, ValueError)
