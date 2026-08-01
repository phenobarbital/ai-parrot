"""Unit tests for `parrot.security.groundedness.scorer` + `.evidence`
(FEAT-398, TASK-2044).

Covers exact match, the precision-aware tolerance rule, the
`contradicted_band`, determinism, and the five canonical prototype cases
from the brainstorm's Appendix A (loaded from
``tests/fixtures/groundedness/canonical_cases.yaml``) — spec §4 test
matrix, Module 2.
"""
from pathlib import Path

import pytest
import yaml

from parrot.models.basic import ToolCall
from parrot.security.groundedness.evidence import EvidenceIndex
from parrot.security.groundedness.models import AtomKind
from parrot.security.groundedness.policy import GroundednessPolicy
from parrot.security.groundedness.scorer import GroundednessScorer

FIXTURES_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "groundedness" / "canonical_cases.yaml"
)


def _load_canonical_cases() -> dict:
    with FIXTURES_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _tool_call(result: str, call_id: str = "1", name: str = "tool") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={}, result=result)


def _verdict_map(report) -> dict[tuple[AtomKind, str], str]:
    """Map (kind, raw) -> verdict for every scored atom in *report*."""
    mapping: dict[tuple[AtomKind, str], str] = {}
    for bucket in (report.supported, report.contradicted, report.unsupported):
        for entry in bucket:
            mapping[(entry.atom.kind, entry.atom.raw)] = entry.verdict
    return mapping


class TestExactMatch:
    def test_supported_exact_money_match(self):
        policy = GroundednessPolicy()
        evidence = EvidenceIndex.from_tool_calls(
            [_tool_call("Total revenue was $1,243,500 this quarter.")], policy,
        )
        scorer = GroundednessScorer(policy)
        report = scorer.score("Revenue reached $1,243,500.", evidence)

        assert report.score == 1.0
        assert report.total_atoms == 1
        assert len(report.supported) == 1
        assert report.supported[0].verdict == "supported"

    def test_supported_exact_date_match(self):
        policy = GroundednessPolicy()
        evidence = EvidenceIndex.from_tool_calls(
            [_tool_call("Closed the quarter on 2026-06-30.")], policy,
        )
        scorer = GroundednessScorer(policy)
        report = scorer.score("The quarter closed on 2026-06-30.", evidence)

        assert report.score == 1.0
        assert report.supported[0].atom.kind == AtomKind.DATE


class TestKindIsolation:
    def test_money_claim_not_matched_by_same_valued_percent_evidence(self):
        """A money claim must never be 'supported' by a same-valued percent
        (or bare number) atom in the evidence — evidence.py keeps
        numeric_by_kind separate per AtomKind precisely for this."""
        policy = GroundednessPolicy()
        evidence = EvidenceIndex.from_tool_calls(
            [_tool_call("Growth was 500% year over year.")], policy,
        )
        scorer = GroundednessScorer(policy)
        report = scorer.score("Revenue was $500 today.", evidence)

        assert report.total_atoms == 1
        assert len(report.unsupported) == 1
        assert report.unsupported[0].atom.kind == AtomKind.MONEY


class TestPrecisionAwareTolerance:
    def test_rounded_value_within_tolerance_is_supported(self):
        policy = GroundednessPolicy()
        evidence = EvidenceIndex.from_tool_calls(
            [_tool_call("Total revenue was $1,243,500 this quarter.")], policy,
        )
        scorer = GroundednessScorer(policy)
        report = scorer.score("Revenue was approximately $1.24M.", evidence)

        assert report.score == 1.0
        assert report.supported[0].verdict == "supported"

    def test_fully_written_transposed_digit_is_contradicted_not_swallowed(self):
        """Design finding from the brainstorm prototype: a fixed 2% tolerance
        let a transposed digit hide inside the rounding allowance. The
        precision-aware rule (tolerance from the ANSWER's own stated
        significant digits) must catch it."""
        policy = GroundednessPolicy()
        evidence = EvidenceIndex.from_tool_calls(
            [_tool_call("Total revenue was $1,243,500 this quarter.")], policy,
        )
        scorer = GroundednessScorer(policy)
        report = scorer.score("Revenue was $1,234,500 this quarter.", evidence)

        assert len(report.contradicted) == 1
        assert report.contradicted[0].verdict == "contradicted"
        assert report.contradicted[0].nearest_evidence == "$1,243,500"


class TestContradictedBand:
    def test_within_band_is_contradicted(self):
        policy = GroundednessPolicy(contradicted_band=0.15)
        evidence = EvidenceIndex.from_tool_calls(
            [_tool_call("Total revenue was $1,243,500 this quarter.")], policy,
        )
        scorer = GroundednessScorer(policy)
        report = scorer.score("Revenue was $1,234,500 this quarter.", evidence)

        assert report.contradicted[0].verdict == "contradicted"

    def test_outside_band_is_unsupported(self):
        policy = GroundednessPolicy(contradicted_band=0.15)
        evidence = EvidenceIndex.from_tool_calls(
            [_tool_call("Total revenue was $1,243,500 this quarter.")], policy,
        )
        scorer = GroundednessScorer(policy)
        # ~60% off the evidence value -> well outside the 15% band.
        report = scorer.score("Revenue was $2,000,000 this quarter.", evidence)

        assert len(report.unsupported) == 1
        assert report.unsupported[0].verdict == "unsupported"


class TestEdgeCases:
    def test_no_evidence_scores_full_marks(self):
        evidence = EvidenceIndex()
        scorer = GroundednessScorer()

        report = scorer.score("Revenue was $1,243,500.", evidence)

        assert report.score == 1.0
        assert report.no_evidence is True
        assert report.total_atoms == 0

    def test_no_factual_content_scores_full_marks(self):
        policy = GroundednessPolicy()
        evidence = EvidenceIndex.from_tool_calls([_tool_call("some data")], policy)
        scorer = GroundednessScorer(policy)

        report = scorer.score("Thank you for your question.", evidence)

        assert report.score == 1.0
        assert report.no_factual_content is True
        assert report.total_atoms == 0

    def test_default_policy_used_when_none_provided(self):
        scorer = GroundednessScorer(policy=None)
        assert isinstance(scorer.policy, GroundednessPolicy)


class TestDeterminism:
    def test_100_runs_produce_identical_json(self):
        policy = GroundednessPolicy()
        evidence = EvidenceIndex.from_tool_calls(
            [_tool_call("Revenue was $1,243,500 and grew 15% with 4812 orders.")],
            policy,
        )
        scorer = GroundednessScorer(policy)
        answer = "Revenue reached $1,243,500, up 15%, across 4812 orders."

        first = scorer.score(answer, evidence).model_dump_json()
        for _ in range(99):
            assert scorer.score(answer, evidence).model_dump_json() == first


class TestCanonicalPrototypeCases:
    """The 5 canonical cases validated in the brainstorm's Appendix A
    prototype (2/2 evidence sources, 5/5 cases correct)."""

    @pytest.fixture(scope="class")
    def fixture_data(self):
        return _load_canonical_cases()

    @pytest.fixture
    def evidence(self, fixture_data):
        policy = GroundednessPolicy()
        tool_calls = [
            _tool_call(text, call_id=str(i))
            for i, text in enumerate(fixture_data["tool_outputs"])
        ]
        return EvidenceIndex.from_tool_calls(tool_calls, policy)

    @pytest.fixture
    def scorer(self):
        return GroundednessScorer(GroundednessPolicy())

    @pytest.mark.parametrize(
        "case_name",
        ["faithful", "transposed_digits", "invented_identifiers", "no_hard_data", "rounded_paraphrase"],
    )
    def test_canonical_case(self, case_name, fixture_data, evidence, scorer):
        case = next(c for c in fixture_data["cases"] if c["name"] == case_name)

        report = scorer.score(case["answer"], evidence)

        assert report.score == pytest.approx(case["expected_score"])
        assert report.no_factual_content is case["expected_no_factual_content"]

        verdicts = _verdict_map(report)
        for expected in case["expected_verdicts"]:
            key = (AtomKind(expected["kind"]), expected["raw"])
            assert key in verdicts, f"{case_name}: missing atom {key}"
            assert verdicts[key] == expected["verdict"], (
                f"{case_name}: atom {key} expected {expected['verdict']!r}, "
                f"got {verdicts[key]!r}"
            )
