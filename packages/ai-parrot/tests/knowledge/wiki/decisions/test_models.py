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

    def test_effective_prefixes_includes_local(self) -> None:
        """The local prefix joins the immutable allowlist without changing fields."""
        config = DecisionConfig(local_prefix="fs", known_prefixes=["parrot", "FS"])
        assert config.local_prefix == "FS"
        assert config.known_prefixes == ["PARROT", "FS"]
        assert config.effective_prefixes() == frozenset({"FS", "PARROT"})
        assert DecisionConfig().effective_prefixes() == frozenset()
        assert DecisionConfig.model_validate(config.model_dump()) == config

    @pytest.mark.parametrize("bad", ["1FS", "F S", "", "ADR1", "adr00001", "RFC2119"])
    def test_reserved_and_invalid_prefixes(self, bad: str) -> None:
        """Both prefix fields reject invalid and compact-citation names."""
        with pytest.raises(ValidationError):
            DecisionConfig(local_prefix=bad)
        with pytest.raises(ValidationError):
            DecisionConfig(known_prefixes=[bad])
        accepted = DecisionConfig(local_prefix="adr123456", known_prefixes=["fs"])
        assert accepted.local_prefix == "ADR123456"
        assert accepted.known_prefixes == ["FS"]


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


# --- FEAT-784 schema 2 -------------------------------------------------------
from parrot.knowledge.wiki.decisions.models import DecisionRef, DecisionTarget  # noqa: E402


def _v2(**overrides) -> DecisionRecord:
    """Build a minimal schema-2 decision record."""
    base = dict(
        schema_version=2,
        decision_id="adr:spec:doc#rule",
        decision="x",
        origin="documented",
        source_status="accepted",
    )
    return DecisionRecord(**{**base, **overrides})


def test_schema1_record_parses_unchanged():
    """AC2: a schema-1 payload validates with every schema-2 field at its default."""
    record = DecisionRecord(decision_id="adr:spec:doc#rule", decision="x", origin="documented")
    assert record.schema_version == 1
    assert record.lifecycle == "active"
    assert record.about == []
    assert record.targets == []
    assert record.contradicts == []
    assert record.supersedes_refs == []
    assert record.normative is None
    assert record.document_id is None
    assert record.entry_id is None
    assert record.batch_id is None
    assert record.rationale == ""
    assert record.rejected_alternatives == []


def test_schema1_with_schema2_fields_rejected():
    """Schema-1 records reject any non-default schema-2 field."""
    with pytest.raises(ValidationError):
        DecisionRecord(
            decision_id="adr:spec:doc#rule",
            decision="x",
            origin="documented",
            schema_version=1,
            about=["memory"],
        )


def test_schema2_round_trips_through_model_dump():
    """Schema-2 records preserve typed references through JSON-compatible dumps."""
    record = _v2(
        about=["memory"],
        targets=[DecisionTarget(target_id="sym:a.py#f", kind="symbol")],
        contradicts=[DecisionRef(decision_id="adr:spec:other", revision=2)],
    )
    assert DecisionRecord.model_validate(record.model_dump(mode="json")) == record


@pytest.mark.parametrize(
    "target_id,kind,ok",
    [
        ("sym:a.py#f", "symbol", True),
        ("file:a.py", "file", True),
        ("dir:pkg", "dir", True),
        ("file:a.py", "dir", False),
        ("pkg/a.py", "file", False),
    ],
)
def test_decision_target_prefix(target_id, kind, ok):
    """Target prefixes determine their allowed structural kind."""
    if ok:
        assert DecisionTarget(target_id=target_id, kind=kind).kind == kind
    else:
        with pytest.raises(ValidationError):
            DecisionTarget(target_id=target_id, kind=kind)


def test_decision_ref_revision_ge_1():
    """Decision references use positive revisions only."""
    with pytest.raises(ValidationError):
        DecisionRef(decision_id="x", revision=0)
