"""Review semantics, attribution and immutability (FEAT-578 M5, AC11/AC6)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.models import (
    CandidateEdit,
    DecisionError,
    DecisionRecord,
    EvidenceRef,
    GenerationInfo,
    ReviewRequest,
)
from parrot.knowledge.wiki.decisions.review import apply_review, render_export, validate_link_target


@pytest.fixture
def candidate() -> DecisionRecord:
    """An unreviewed inferred candidate with evidence and generation info."""
    return DecisionRecord(
        decision_id="adr:candidate:abc",
        revision=1,
        title="Retry with backoff",
        decision="Retries use exponential backoff.",
        origin="inferred",
        source_status="unknown",
        review_status="unreviewed",
        observations=["The client sleeps 2**n seconds."],
        hypotheses=["Probably to avoid thundering herd on the upstream."],
        evidence=[
            EvidenceRef(
                page_id="file:a.py",
                rel_path="a.py",
                start_line=1,
                end_line=3,
                source_sha1="d",
                excerpt="code",
                kind="code",
            )
        ],
        generation=GenerationInfo(
            model_spec="p:m", scope_id="sym:a.py#f", input_sha1="i", max_input_tokens=12000, max_output_tokens=2000
        ),
    )


def _req(action, **kw) -> ReviewRequest:
    return ReviewRequest(
        decision_id="adr:candidate:abc",
        expected_revision=1,
        action=action,
        actor="human:maintainer",
        reason=kw.pop("reason", "reviewed"),
        **kw,
    )


class TestMaintainerWikiAcceptance:
    def test_acceptance_needs_no_documented_adr(self, candidate):
        """Q3/AC11: acceptance in the wiki, no committed ADR file required."""
        accepted = apply_review(candidate, _req("accept"))
        assert accepted.review_status == "accepted"

    def test_acceptance_preserves_inferred_provenance(self, candidate):
        """AC11: the central invariant of the whole feature."""
        accepted = apply_review(candidate, _req("accept"))
        assert accepted.origin == "inferred"
        assert accepted.source_status == "unknown"

    def test_acceptance_records_the_actor_and_bumps_revision(self, candidate):
        accepted = apply_review(candidate, _req("accept"))
        assert accepted.revision == 2
        assert len(accepted.review_history) == 1
        event = accepted.review_history[0]
        assert event.actor == "human:maintainer" and event.action == "accept"
        assert event.revision == 2 and event.timestamp
        assert event.before_sha1 and event.after_sha1 and event.before_sha1 != event.after_sha1

    def test_stale_revision_is_rejected(self, candidate):
        """AC11: stale revisions are refused, with no automatic retry."""
        with pytest.raises(DecisionError) as exc:
            apply_review(
                candidate,
                ReviewRequest(decision_id="adr:candidate:abc", expected_revision=9, action="accept", actor="a"),
            )
        assert exc.value.code == "ADR_REVISION_CONFLICT"

    def test_observations_and_hypotheses_stay_separate(self, candidate):
        """AC4 survives review."""
        accepted = apply_review(candidate, _req("accept"))
        assert accepted.observations == candidate.observations
        assert accepted.hypotheses == candidate.hypotheses


class TestOtherActions:
    def test_reject_keeps_the_record(self, candidate):
        """spec §2: rejection does not delete."""
        rejected = apply_review(candidate, _req("reject"))
        assert rejected.review_status == "rejected"
        assert rejected.decision == candidate.decision

    def test_revise_resets_review_status(self, candidate):
        edit = CandidateEdit(decision="Retries use jittered exponential backoff.")
        revised = apply_review(candidate, _req("revise", replacement=edit))
        assert revised.decision == "Retries use jittered exponential backoff."
        assert revised.review_status == "unreviewed"

    def test_revise_preserves_evidence_and_generation(self, candidate):
        edit = CandidateEdit(decision="A different decision text.")
        revised = apply_review(candidate, _req("revise", replacement=edit))
        assert revised.evidence == candidate.evidence
        assert revised.generation == candidate.generation

    def test_link_records_an_asserted_association(self, candidate):
        linked = apply_review(candidate, _req("link", documented_decision_id="adr:doc:xyz"))
        assert linked.origin == "inferred"
        new_links = [link for link in linked.links if link.target_id == "adr:doc:xyz"]
        assert len(new_links) == 1
        assert new_links[0].provenance == "asserted"

    def test_link_to_a_missing_or_inferred_target_is_invalid(self, candidate):
        with pytest.raises(DecisionError) as exc:
            validate_link_target(None, "adr:doc:xyz")
        assert exc.value.code == "ADR_INVALID_ARGUMENT"

        inferred_target = candidate.model_copy(update={"decision_id": "adr:candidate:other"})
        with pytest.raises(DecisionError) as exc2:
            validate_link_target(inferred_target, "adr:candidate:other")
        assert exc2.value.code == "ADR_INVALID_ARGUMENT"


class TestImmutabilityAndHistory:
    @pytest.mark.parametrize("action", ["accept", "reject"])
    def test_immutable_fields_never_change(self, candidate, action):
        result = apply_review(candidate, _req(action))
        for field in ("decision_id", "origin", "source_status", "evidence", "generation"):
            assert getattr(result, field) == getattr(candidate, field)

    def test_history_is_append_only(self, candidate):
        """AC6: a later review can never erase an earlier one."""
        first = apply_review(candidate, _req("accept"))
        second = apply_review(
            first,
            ReviewRequest(
                decision_id="adr:candidate:abc",
                expected_revision=2,
                action="reject",
                actor="human:other",
                reason="changed my mind",
            ),
        )
        assert [e.action for e in second.review_history] == ["accept", "reject"]
        assert second.review_history[0] == first.review_history[0]

    def test_input_record_is_not_mutated(self, candidate):
        """A caller must be able to retry from the record it read."""
        apply_review(candidate, _req("accept"))
        assert candidate.revision == 1 and candidate.review_history == []

    def test_candidate_edit_cannot_reach_immutable_fields(self):
        """spec §2: CandidateEdit has exactly six fields."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CandidateEdit(origin="documented")


class TestExport:
    def test_export_keeps_the_inferred_label(self, candidate):
        """An exported candidate is still unmistakably a candidate (AC9)."""
        rendered = render_export(candidate)
        assert "INFERRED" in rendered
        assert "Observations" in rendered
        assert "Hypotheses" in rendered
