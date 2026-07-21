"""Graphify-parity tests: LLM-free community labels + ADR/RFC citation nodes.

These cover the two capabilities added to close the gap with Graphify:
deterministic community labels (no LLM) and design-reference citations
(``ADR-NNN`` / ``RFC-NNN``) promoted to first-class rationale nodes linked to
the code that cites them.
"""
from __future__ import annotations

import pytest

from parrot.knowledge.graphindex.communities import (
    derive_community_label,
    detect_communities,
)
from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.extractors.code import CodeExtractor
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)


# ---------------------------------------------------------------------------
# LLM-free community labels
# ---------------------------------------------------------------------------


class TestDeriveCommunityLabel:
    def test_ranks_by_frequency(self):
        label = derive_community_label(
            ["PaymentGateway", "payment_processor", "PaymentError", "refund_handler"]
        )
        # "payment" appears in 3 titles → leads the label.
        assert label.lower().startswith("payment")

    def test_handles_camel_and_snake_case(self):
        label = derive_community_label(["OrderService", "order_repository"])
        assert "Order" in label

    def test_all_stopwords_yields_empty(self):
        assert derive_community_label(["the", "get", "set", "data"]) == ""

    def test_deterministic_tie_break(self):
        # Two equally-frequent terms → alphabetical, stable across calls.
        a = derive_community_label(["alpha beta", "beta alpha"])
        b = derive_community_label(["beta alpha", "alpha beta"])
        assert a == b

    def test_respects_max_terms(self):
        label = derive_community_label(
            ["alpha bravo charlie delta echo"], max_terms=2
        )
        assert len(label.split()) <= 2


class TestCommunitiesCarryLabels:
    def test_detect_communities_populates_label(self):
        # Two rings with descriptive titles → each community gets a label.
        nodes = [
            UniversalNode(
                node_id=f"n{i}",
                kind=NodeKind.SYMBOL,
                title="PaymentGateway" if i < 4 else "ShippingTracker",
                source_uri="m.py",
            )
            for i in range(8)
        ]
        ring = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4)]
        edges = [
            UniversalEdge(source_id=f"n{a}", target_id=f"n{b}", kind=EdgeKind.REFERENCES)
            for a, b in ring
        ]
        asm = GraphAssembler(tenant_id="t")
        asm.add_nodes(nodes)
        asm.add_edges(edges)
        result = detect_communities(asm.graph, nodes, write_back_to_nodes=False)
        assert result.communities
        assert all(isinstance(c.label, str) for c in result.communities)
        assert any(c.label for c in result.communities)


# ---------------------------------------------------------------------------
# ADR/RFC citation nodes
# ---------------------------------------------------------------------------

_SRC = '''
# WHY: chosen per ADR-42 and RFC 4180
def parse_csv(path):
    """Parse a CSV file.

    See ADR/007 for rationale; also references ADR-42 again.
    """
    return path


class Loader:
    """Follows RFC-2119 keyword conventions."""
    pass
'''


async def _extract(src: str):
    return await CodeExtractor().extract("mod.py", src)


class TestCitationExtraction:
    @pytest.mark.asyncio
    async def test_citations_become_rationale_nodes(self):
        nodes, _edges = await _extract(_SRC)
        cites = {
            n.title for n in nodes if n.domain_tags.get("tag") == "CITATION"
        }
        assert cites == {"ADR-42", "ADR-7", "RFC-4180", "RFC-2119"}
        assert all(
            n.kind == NodeKind.RATIONALE
            for n in nodes
            if n.domain_tags.get("tag") == "CITATION"
        )

    @pytest.mark.asyncio
    async def test_identical_citation_deduplicated(self):
        nodes, _edges = await _extract(_SRC)
        adr42 = [n for n in nodes if n.title == "ADR-42"]
        assert len(adr42) == 1  # cited 3× → single node

    @pytest.mark.asyncio
    async def test_reference_edges_link_code_to_citations(self):
        nodes, edges = await _extract(_SRC)
        cite_ids = {
            n.node_id for n in nodes if n.domain_tags.get("tag") == "CITATION"
        }
        ref_edges = [
            e
            for e in edges
            if e.kind == EdgeKind.REFERENCES and e.target_id in cite_ids
        ]
        assert ref_edges  # code → citation links exist
        # Edges point FROM a symbol TO the citation node.
        symbol_ids = {n.node_id for n in nodes if n.kind == NodeKind.SYMBOL}
        assert all(e.source_id in symbol_ids for e in ref_edges)

    @pytest.mark.asyncio
    async def test_no_citations_when_absent(self):
        nodes, _edges = await _extract("def f():\n    return 1\n")
        assert not [n for n in nodes if n.domain_tags.get("tag") == "CITATION"]

    @pytest.mark.asyncio
    async def test_adr_slash_form_normalized(self):
        nodes, _edges = await _extract('# see ADR/007\ndef g():\n    return 2\n')
        titles = {n.title for n in nodes if n.domain_tags.get("tag") == "CITATION"}
        assert titles == {"ADR-7"}
