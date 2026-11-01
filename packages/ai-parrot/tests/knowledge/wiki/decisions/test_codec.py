"""Codec round-trip, labels, and envelope rejection (FEAT-578 Module 1)."""

from __future__ import annotations

import hashlib
import json

import pytest

from parrot.knowledge.wiki.decisions.codec import (
    ENVELOPE_MARKER,
    ENVELOPE_MARKER_V2,
    candidate_decision_id,
    content_fingerprint,
    decision_from_page,
    decision_to_page,
    documented_decision_id,
    spec_decision_id,
)
from parrot.knowledge.wiki.decisions.models import (
    ADR_CATEGORY,
    ADR_INVALID_ID,
    MAX_RECORD_BYTES,
    DecisionError,
    DecisionLink,
    DecisionRecord,
    DecisionTarget,
    EvidenceRef,
    ReviewEvent,
)


@pytest.fixture
def documented() -> DecisionRecord:
    """A fully populated documented record — every field must survive."""
    evidence = [
        EvidenceRef(
            page_id="sym:src/a.py#f",
            rel_path="src/a.py",
            start_line=10,
            end_line=20,
            source_sha1="abc123",
            excerpt="def f(): ...",
            kind="code",
        ),
        EvidenceRef(
            page_id="docs/adr/0001-pgvector.md",
            rel_path="docs/adr/0001-pgvector.md",
            start_line=1,
            end_line=5,
            source_sha1="def456",
            excerpt="# ADR-1",
            kind="adr",
        ),
    ]
    links = [
        DecisionLink(
            target_id="sym:src/a.py#f",
            relation="explains",
            provenance="extracted",
            evidence_indexes=[0],
        )
    ]
    review_history = [
        ReviewEvent(
            revision=1,
            action="accept",
            actor="human:jlara",
            timestamp="2026-09-19T00:00:00Z",
            reason="looks correct",
            before_sha1="beforehash",
            after_sha1="afterhash",
        )
    ]
    return DecisionRecord(
        decision_id="adr:doc:testid",
        revision=1,
        title="Use pgvector for the primary store",
        context="We need a vector store for embeddings.",
        decision="Use pgvector.",
        consequences="Operational simplicity; ties us to Postgres.",
        source_status="accepted",
        source_status_raw="Accepted",
        origin="documented",
        review_status="unreviewed",
        source_path="docs/adr/0001-pgvector.md",
        external_id="ADR-1",
        evidence=evidence,
        links=links,
        observations=["pgvector supports HNSW indexes."],
        hypotheses=["Might need sharding later."],
        review_history=review_history,
        generation=None,
        content_fingerprint="",
    )


class TestRoundTrip:
    def test_codec_roundtrip_and_labels(self, documented):
        """All fields survive encode/decode; labels are visible in the stub."""
        page = decision_to_page(documented)
        assert page.category == "adr"
        assert page.source_id is None  # survives source-slice deletion
        assert page.title.startswith("[DOCUMENTED /")
        assert page.summary.startswith("[DOCUMENTED /")
        decoded = decision_from_page(page.model_dump())
        assert decoded == documented

    def test_inferred_labels_are_unmistakable(self):
        """A candidate can never render as an unlabeled decision (AC3/AC9)."""
        record = DecisionRecord(
            decision_id="adr:candidate:testid",
            title="Adopt a caching layer",
            decision="Add a read-through cache.",
            origin="inferred",
            review_status="unreviewed",
        )
        page = decision_to_page(record)
        assert page.title.startswith("[INFERRED / UNREVIEWED]")
        assert page.summary.startswith("[INFERRED / UNREVIEWED]")

    def test_envelope_is_one_canonical_line(self, documented):
        """Line 1 is the marker, line 2 is sorted compact JSON."""
        lines = decision_to_page(documented).body.split("\n")
        assert lines[0] == ENVELOPE_MARKER
        assert json.loads(lines[1])["schema_version"] == 1
        assert ", " not in lines[1] and '": ' not in lines[1]


class TestInvalidEnvelope:
    @pytest.mark.parametrize(
        "mutate,reason",
        [
            (lambda p: p.update(body="not an adr"), "missing marker"),
            (lambda p: p.update(body="<!-- parrot-adr:v2 -->\n{}"), "unsupported version"),
            (lambda p: p.update(category="concept"), "wrong category"),
            (lambda p: p.update(body=f"{ENVELOPE_MARKER}\n{{nope"), "corrupt json"),
        ],
    )
    def test_invalid_envelope_and_version(self, documented, mutate, reason):
        """Corrupt/unsupported/wrong-category pages fail with a stable code."""
        page = decision_to_page(documented).model_dump()
        mutate(page)
        with pytest.raises(DecisionError) as exc:
            decision_from_page(page)
        assert exc.value.code == "ADR_SCHEMA_UNSUPPORTED", reason

    def test_oversized_record_is_refused_not_truncated(self):
        """History and evidence are never dropped to fit (spec §2)."""
        record = DecisionRecord(
            decision_id="adr:doc:huge",
            decision="Use pgvector.",
            origin="documented",
            source_status="accepted",
            context="x" * (MAX_RECORD_BYTES + 1000),
        )
        with pytest.raises(DecisionError) as exc:
            decision_to_page(record)
        assert exc.value.code == "ADR_RECORD_TOO_LARGE"


class TestIdentity:
    @pytest.mark.parametrize("a,b", [("docs/adr/1.md", "./docs/adr/1.md"), ("docs/adr/1.md", "docs/adr/1.md")])
    def test_documented_id_is_path_normalized(self, a, b):
        """Equivalent spellings of one path yield one id."""
        assert documented_decision_id(a) == documented_decision_id(b)

    def test_distinct_paths_never_merge(self):
        """Path identity deliberately does not merge duplicate ADR numbers."""
        assert documented_decision_id("docs/adr/0042-a.md") != documented_decision_id("docs/adrs/0042-a.md")

    def test_candidate_id_is_stable_for_same_evidence(self):
        """AC6: same scope + evidence + decision text reuses the same id."""
        args = ("sym:a.py#f", "fp-1", 1, "  Use  pgvector ")
        assert candidate_decision_id(*args) == candidate_decision_id("sym:a.py#f", "fp-1", 1, "Use pgvector")

    def test_fingerprint_ignores_revision_and_history(self, documented):
        """A pure review action must not change the content fingerprint."""
        original_fingerprint = content_fingerprint(documented)
        revised = documented.model_copy(deep=True)
        revised.revision += 1
        revised.review_history.append(
            ReviewEvent(
                revision=2,
                action="accept",
                actor="human:jlara",
                timestamp="2026-09-19T01:00:00Z",
                reason="second look",
                before_sha1="beforehash2",
                after_sha1="afterhash2",
            )
        )
        assert content_fingerprint(revised) == original_fingerprint


# --- FEAT-784 ------------------------------------------------------------------
def test_v1_record_keeps_v1_marker_and_hash(documented):
    """Schema-1 pages retain the established marker and JSON-only hash."""
    page = decision_to_page(documented)
    envelope = page.body.split("\n", 2)[1]
    assert page.body.startswith(f"{ENVELOPE_MARKER}\n")
    assert page.content_hash == hashlib.sha1(envelope.encode("utf-8")).hexdigest()  # noqa: S324


def test_v2_record_round_trips():
    """Schema-2 records use the v2 marker and preserve typed targets."""
    record = DecisionRecord(
        schema_version=2,
        decision_id="adr:spec:feat-784#codec-v2",
        decision="Write schema-2 records behind the v2 envelope.",
        origin="documented",
        source_status="accepted",
        normative="requires",
        about=["knowledge"],
        targets=[
            DecisionTarget(
                target_id="file:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py",
                kind="file",
            )
        ],
        document_id="feat-784",
        entry_id="codec-v2",
    )
    page = decision_to_page(record)
    assert page.body.startswith(f"{ENVELOPE_MARKER_V2}\n")
    assert decision_from_page(page.model_dump()) == record


@pytest.mark.parametrize("marker,schema", [("<!-- parrot-adr:v3 -->", 3), (None, 3), (None, 2)])
def test_unsupported_schema_fails_explicitly(documented, marker, schema):
    """Unknown markers and marker/payload disagreement fail before model validation."""
    payload = documented.model_dump(mode="json")
    payload["schema_version"] = schema
    page = {
        "concept_id": documented.decision_id,
        "category": ADR_CATEGORY,
        "body": f"{marker or ENVELOPE_MARKER}\n{json.dumps(payload)}",
    }
    with pytest.raises(DecisionError) as exc:
        decision_from_page(page)
    assert exc.value.code == "ADR_SCHEMA_UNSUPPORTED"


@pytest.mark.parametrize(
    "doc,entry,ok",
    [
        ("feat-784", "rule_1", True),
        ("Feat", "x", False),
        ("a b", "x", False),
        ("doc", "", False),
        ("doc", "a#b", False),
    ],
)
def test_spec_decision_id_charset(doc, entry, ok):
    """Spec decision ids accept only the frozen document and entry charset."""
    if ok:
        assert spec_decision_id(doc, entry) == f"adr:spec:{doc}#{entry}"
        return
    with pytest.raises(DecisionError) as exc:
        spec_decision_id(doc, entry)
    assert exc.value.code == ADR_INVALID_ID


def test_lazy_exports():
    """Schema-2 reference models remain available via lazy package exports."""
    import parrot.knowledge.wiki.decisions as pkg

    assert pkg.DecisionRef.__name__ == "DecisionRef"
    assert "DecisionTarget" in pkg.__all__
