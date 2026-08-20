"""Tests for TASK-2270: `NodeRef` + `parrot-graph://` URI parse/serialize.

Spec: sdd/specs/graphindex-retriever.spec.md §3.1.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind
from parrot.knowledge.retrieval.models import EdgeRef, NodeRef
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
