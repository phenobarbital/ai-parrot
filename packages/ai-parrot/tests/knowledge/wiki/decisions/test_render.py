"""Dossier budget packing invariants (FEAT-578 Module 4, AC3/AC9)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.models import DecisionHit, EvidenceRef
from parrot.knowledge.wiki.decisions.render import (
    clamp_budget,
    clamp_limit,
    labels_of,
    pack_dossier,
    render_dossier_text,
)


def _hit(decision_id: str, origin: str = "documented", excerpt: str = "short", **kw) -> DecisionHit:
    return DecisionHit(
        decision_id=decision_id,
        revision=1,
        title=kw.pop("title", "t"),
        origin=origin,
        source_status=kw.pop("source_status", "accepted" if origin == "documented" else "unknown"),
        review_status=kw.pop("review_status", "unreviewed"),
        freshness=kw.pop("freshness", "current"),
        decision=kw.pop("decision", "use the thing"),
        citations=[EvidenceRef(page_id="file:a.py", rel_path="a.py", start_line=1, end_line=2,
                               source_sha1="d", excerpt=excerpt, kind="code")],
        **kw,
    )


class TestBounds:
    @pytest.mark.parametrize("given,expected", [(0, 1), (10, 10), (999, 50)])
    def test_limit_is_clamped(self, given, expected):
        assert clamp_limit(given) == expected

    @pytest.mark.parametrize("given,expected", [(0, 256), (3000, 3000)])
    def test_budget_has_a_floor(self, given, expected):
        assert clamp_budget(given) == expected


class TestPacking:
    def test_groups_stay_separate(self):
        """AC3: a candidate is never merged into the documented group."""
        d = pack_dossier([_hit("adr:doc:a")], [_hit("adr:candidate:b", origin="inferred")])
        assert [h.decision_id for h in d.documented] == ["adr:doc:a"]
        assert [h.decision_id for h in d.candidates] == ["adr:candidate:b"]

    def test_limit_counts_across_both_groups(self):
        """3 documented + 3 candidates with limit=4 yields 4 hits total,
        documented filled first."""
        documented = [_hit(f"adr:doc:{i}") for i in range(3)]
        candidates = [_hit(f"adr:candidate:{i}", origin="inferred") for i in range(3)]
        d = pack_dossier(documented, candidates, limit=4)
        assert len(d.documented) == 3
        assert len(d.candidates) == 1
        assert [h.decision_id for h in d.documented] == ["adr:doc:0", "adr:doc:1", "adr:doc:2"]
        assert [h.decision_id for h in d.candidates] == ["adr:candidate:0"]
        assert d.truncated is True

    def test_tight_budget_drops_candidates_before_documented(self):
        """A budget that fits only one hit keeps the documented one and
        sets truncated."""
        # Sized so the documented hit alone consumes ~244 of the 256-token
        # floor, leaving less than the candidate's labels+citation floor
        # (~22 tokens) — the candidate is dropped entirely, not shortened.
        wide_excerpt = "lorem ipsum dolor sit amet consectetur adipiscing elit sed do " * 22
        documented = [_hit("adr:doc:a", excerpt=wide_excerpt)]
        candidates = [_hit("adr:candidate:b", origin="inferred")]
        d = pack_dossier(documented, candidates, budget_tokens=256)
        assert [h.decision_id for h in d.documented] == ["adr:doc:a"]
        assert d.candidates == []
        assert d.truncated is True

    def test_long_excerpt_is_shortened_not_dropped(self):
        """spec §2: shorten the excerpt, retain the citation."""
        hit = _hit("adr:doc:a", excerpt="x " * 5000)
        d = pack_dossier([hit], [], budget_tokens=256)
        assert d.documented, "the hit must survive with a shortened excerpt"
        kept = d.documented[0]
        assert kept.citations and kept.citations[0].rel_path == "a.py"
        assert kept.citations[0].start_line == 1 and kept.citations[0].end_line == 2
        assert d.truncated is True

    def test_labels_never_stripped_to_fit(self):
        """AC9: a hit is omitted rather than emitted unlabeled."""
        # decision_id itself is part of the mandatory floor and is never
        # trimmed, so an enormous id pushes even the minimum legal
        # rendering above the 256-token budget floor.
        unfitting_id = "adr:doc:" + ("x" * 2000)
        unfitting = _hit(unfitting_id)
        tiny = _hit("adr:doc:tiny")
        d = pack_dossier([unfitting, tiny], [], budget_tokens=256)
        kept_ids = {h.decision_id for h in d.documented}
        assert unfitting_id not in kept_ids, "a hit that cannot fit its labels+citation floor must be omitted"
        assert "adr:doc:tiny" in kept_ids
        for hit in d.documented:
            assert hit.origin in ("documented", "inferred")
            assert hit.source_status
            assert hit.review_status
            assert hit.freshness
            assert hit.citations
        assert d.truncated is True

    def test_dropping_hits_downgrades_status_to_partial(self):
        """assert status == "partial" when a hit was omitted from an
        otherwise 'ok' result."""
        documented = [_hit(f"adr:doc:{i}") for i in range(5)]
        d = pack_dossier(documented, [], limit=1, status="ok")
        assert len(d.documented) == 1
        assert d.truncated is True
        assert d.status == "partial"

    def test_nothing_dropped_leaves_truncated_false(self):
        d = pack_dossier([_hit("adr:doc:a")], [])
        assert d.truncated is False and d.status == "ok"


class TestRendering:
    def test_labels_show_origin_status_and_freshness(self):
        assert labels_of(_hit("adr:doc:a")) == "[DOCUMENTED / ACCEPTED / current]"
        assert labels_of(_hit("adr:candidate:b", origin="inferred")) == "[INFERRED / UNREVIEWED / current]"

    def test_candidate_section_is_explicitly_headed(self):
        """A reader must never mistake candidates for history (AC3)."""
        text = render_dossier_text(pack_dossier([], [_hit("adr:candidate:b", origin="inferred")]))
        assert "INFERRED" in text
        assert "Candidates (INFERRED" in text
        assert "Documented decisions" in text
        # The documented group is empty — that absence must be explicit.
        doc_section, _, candidate_section = text.partition("Candidates (INFERRED")
        assert "(none)" in doc_section
        assert "adr:candidate:b" in candidate_section
