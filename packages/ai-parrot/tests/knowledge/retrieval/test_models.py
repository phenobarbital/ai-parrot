"""Tests for TASK-2270/TASK-2271 retrieval-layer models.

Spec: sdd/specs/graphindex-retriever.spec.md §3.1, §3.2, §3.3.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind
from parrot.knowledge.retrieval.models import (
    ContextBundle,
    ContextUnit,
    EdgeRef,
    Evidence,
    EvidenceOrigin,
    NodeRef,
    RetrievalBudget,
    RetrievalRequest,
)
from pydantic import ValidationError

# Character sets deliberately excluding the URI's own delimiters where the
# grammar assumes their absence (rev never has '@'/'/', kind_part never has
# ':' outside the "[symbol_type]" bracket handled explicitly).
_SAFE_TEXT = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"),
        whitelist_characters="-_. ",
    ),
    min_size=1,
    max_size=12,
)
_REV = st.text(alphabet="0123456789abcdef", min_size=7, max_size=40)
_PATH_SEGMENT = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_."),
    min_size=1,
    max_size=8,
)
_PATH = st.lists(_PATH_SEGMENT, min_size=1, max_size=4).map(lambda segs: "/".join(segs))
_SYMBOL_TYPE = st.one_of(st.none(), st.sampled_from(["module", "class", "function"]))


def _node_ref_strategy():
    return st.builds(
        NodeRef,
        repo=_SAFE_TEXT,
        rev=_REV,
        path=_PATH,
        kind=st.sampled_from(list(NodeKind)),
        symbol_type=_SYMBOL_TYPE,
        qualname=_SAFE_TEXT,
    )


@given(_node_ref_strategy())
def test_uri_round_trip(ref: NodeRef) -> None:
    assert NodeRef.parse(ref.uri) == ref


def test_rejects_symbolic_rev() -> None:
    for bad in ("HEAD", "head", "main", "dev", "staging", "v1.0"):
        with pytest.raises(ValidationError):
            NodeRef(
                repo="ai-parrot",
                rev=bad,
                path="parrot/outputs/a2ui.py",
                kind=NodeKind.SYMBOL,
                symbol_type="function",
                qualname="EnvelopeProducer.emit",
            )


def test_accepts_concrete_sha() -> None:
    ref = NodeRef(
        repo="ai-parrot",
        rev="a1b2c3d",
        path="parrot/outputs/a2ui.py",
        kind=NodeKind.SYMBOL,
        symbol_type="function",
        qualname="EnvelopeProducer.emit",
    )
    assert ref.rev == "a1b2c3d"


def test_uri_format_matches_spec() -> None:
    ref = NodeRef(
        repo="ai-parrot",
        rev="a1b2c3d",
        path="parrot/outputs/a2ui.py",
        kind=NodeKind.SYMBOL,
        symbol_type="function",
        qualname="EnvelopeProducer.emit",
    )
    assert ref.uri == (
        "parrot-graph://ai-parrot@a1b2c3d/parrot/outputs/a2ui.py"
        "#symbol[function]:EnvelopeProducer.emit"
    )
    assert NodeRef.parse(ref.uri) == ref


def test_path_with_hash_and_at_round_trips() -> None:
    ref = NodeRef(
        repo="ai-parrot",
        rev="a1b2c3d",
        path="weird/pa#th/wi@th/special.py",
        kind=NodeKind.RATIONALE,
        symbol_type=None,
        qualname="module_docstring",
    )
    assert NodeRef.parse(ref.uri) == ref


def test_frozen_and_extra_forbid() -> None:
    ref = NodeRef(
        repo="ai-parrot",
        rev="a1b2c3d",
        path="parrot/outputs/a2ui.py",
        kind=NodeKind.SYMBOL,
        symbol_type="function",
        qualname="EnvelopeProducer.emit",
    )
    with pytest.raises(ValidationError):
        ref.qualname = "OtherName"  # type: ignore[misc]

    with pytest.raises(ValidationError):
        NodeRef(
            repo="ai-parrot",
            rev="a1b2c3d",
            path="parrot/outputs/a2ui.py",
            kind=NodeKind.SYMBOL,
            symbol_type="function",
            qualname="EnvelopeProducer.emit",
            unknown_field="nope",
        )


def test_parse_rejects_non_parrot_graph_uri() -> None:
    with pytest.raises(ValueError):
        NodeRef.parse("https://example.com/foo")


class TestEdgeRef:
    def _ref(self, repo: str = "ai-parrot") -> NodeRef:
        return NodeRef(
            repo=repo,
            rev="a1b2c3d",
            path="parrot/outputs/a2ui.py",
            kind=NodeKind.SYMBOL,
            symbol_type="function",
            qualname="EnvelopeProducer.emit",
        )

    def test_construct_ast_edge(self) -> None:
        edge = EdgeRef(
            source=self._ref(),
            target=self._ref(),
            kind=EdgeKind.REFERENCES,
            derivation="ast",
        )
        assert edge.derivation == "ast"

    def test_construct_package_metadata_edge(self) -> None:
        edge = EdgeRef(
            source=self._ref("ai-parrot"),
            target=self._ref("navigator-eventbus"),
            kind=EdgeKind.REFERENCES,
            derivation="package_metadata",
        )
        assert edge.derivation == "package_metadata"

    def test_frozen(self) -> None:
        edge = EdgeRef(
            source=self._ref(),
            target=self._ref(),
            kind=EdgeKind.REFERENCES,
            derivation="ast",
        )
        with pytest.raises(ValidationError):
            edge.derivation = "package_metadata"  # type: ignore[misc]

    def test_rejects_invalid_derivation_literal(self) -> None:
        with pytest.raises(ValidationError):
            EdgeRef(
                source=self._ref(),
                target=self._ref(),
                kind=EdgeKind.REFERENCES,
                derivation="magic",  # type: ignore[arg-type]
            )


def _sample_node_ref(repo: str = "ai-parrot") -> NodeRef:
    return NodeRef(
        repo=repo,
        rev="a1b2c3d",
        path="parrot/outputs/a2ui.py",
        kind=NodeKind.SYMBOL,
        symbol_type="function",
        qualname="EnvelopeProducer.emit",
    )


def _sample_evidence() -> Evidence:
    return Evidence(
        node=_sample_node_ref(),
        digest="deadbeef",
        digest_scope="span",
        line_span=(10, 20),
        edge_path=(),
        origin=EvidenceOrigin.L0_SOURCE,
        score=0.87,
    )


def _sample_context_unit() -> ContextUnit:
    return ContextUnit(
        text="def emit(self): ...",
        evidence=_sample_evidence(),
        token_estimate=5,
    )


def _sample_bundle() -> ContextBundle:
    return ContextBundle(
        units=(_sample_context_unit(),),
        decision=None,
        truncated=False,
        token_total=5,
        elapsed_ms=12.3,
    )


class TestEvidenceOrigin:
    def test_has_exactly_six_members(self) -> None:
        assert len(EvidenceOrigin) == 6

    def test_reserved_members_documented(self) -> None:
        assert "RESERVED" in EvidenceOrigin.__doc__

    def test_members(self) -> None:
        assert set(EvidenceOrigin) == {
            EvidenceOrigin.L0_SOURCE,
            EvidenceOrigin.L1_WIKI,
            EvidenceOrigin.L1_RATIONALE,
            EvidenceOrigin.L2_DOC,
            EvidenceOrigin.L2_NORM,
            EvidenceOrigin.L2_EXTERNAL,
        }


class TestEvidence:
    def test_construct(self) -> None:
        ev = _sample_evidence()
        assert ev.origin == EvidenceOrigin.L0_SOURCE
        assert ev.line_span == (10, 20)

    def test_frozen_and_forbid_extra(self) -> None:
        ev = _sample_evidence()
        with pytest.raises(ValidationError):
            ev.score = 0.5  # type: ignore[misc]
        with pytest.raises(ValidationError):
            Evidence(
                node=_sample_node_ref(),
                digest="deadbeef",
                digest_scope="span",
                origin=EvidenceOrigin.L0_SOURCE,
                score=0.87,
                unknown="nope",
            )

    def test_line_span_optional(self) -> None:
        ev = Evidence(
            node=_sample_node_ref(),
            digest="deadbeef",
            digest_scope="file",
            origin=EvidenceOrigin.L1_RATIONALE,
            score=0.5,
        )
        assert ev.line_span is None


class TestContextUnit:
    def test_construct_and_frozen(self) -> None:
        unit = _sample_context_unit()
        assert unit.token_estimate == 5
        with pytest.raises(ValidationError):
            unit.text = "changed"  # type: ignore[misc]


class TestContextBundle:
    def test_defaults(self) -> None:
        bundle = _sample_bundle()
        assert bundle.schema_version == 1
        assert bundle.stale_sources == ()
        assert bundle.mixed_freshness is False
        assert bundle.index_pin_mismatch is False
        assert bundle.boundary_truncation is False

    def test_json_round_trip_preserves_schema_version(self) -> None:
        bundle = _sample_bundle()
        dumped = bundle.model_dump_json()
        restored = ContextBundle.model_validate_json(dumped)
        assert restored.schema_version == 1
        assert restored == bundle

    def test_frozen_and_forbid_extra(self) -> None:
        bundle = _sample_bundle()
        with pytest.raises(ValidationError):
            bundle.truncated = True  # type: ignore[misc]


class TestRetrievalBudget:
    def test_defaults_match_spec(self) -> None:
        budget = RetrievalBudget()
        assert budget.deadline_ms == 800
        assert budget.max_tokens == 12_000
        assert budget.max_llm_calls == 0
        assert budget.max_expansion_nodes == 400
        assert budget.allow_stale is True

    def test_frozen(self) -> None:
        budget = RetrievalBudget()
        with pytest.raises(ValidationError):
            budget.deadline_ms = 100  # type: ignore[misc]


class TestRetrievalRequest:
    def test_construct_with_default_budget(self) -> None:
        req = RetrievalRequest(query="what does resolve() return?", workspace=None)
        assert req.budget == RetrievalBudget()
        assert req.policy_override is None

    def test_frozen_and_forbid_extra(self) -> None:
        req = RetrievalRequest(query="q", workspace=None)
        with pytest.raises(ValidationError):
            req.query = "changed"  # type: ignore[misc]
        with pytest.raises(ValidationError):
            RetrievalRequest(query="q", workspace=None, unknown="nope")
