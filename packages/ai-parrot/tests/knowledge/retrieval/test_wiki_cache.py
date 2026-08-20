"""Tests for TASK-2283: `WikiSection`/`WikiPage` + per-section invalidation.

Spec: sdd/specs/graphindex-retriever.spec.md §6, OQ-5, RQ-2.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from parrot.knowledge.graphindex.schema import NodeKind
from parrot.knowledge.retrieval.digest import DigestScope
from parrot.knowledge.retrieval.models import NodeRef
from parrot.knowledge.retrieval.sections import SectionKind
from parrot.knowledge.retrieval.wiki_cache import (
    GeneratorInfo,
    ServingDecision,
    SourceDigest,
    WikiPage,
    WikiSection,
    compute_coherence_group,
    compute_mixed_freshness,
    compute_page_id,
    invalidate_ancestors,
    invalidate_page,
    resolve_serving_decision,
)


def _node_ref(qualname: str) -> NodeRef:
    return NodeRef(
        repo="ai-parrot",
        rev="a1b2c3d",
        path="mod.py",
        kind=NodeKind.SYMBOL,
        symbol_type="class",
        qualname=qualname,
    )


def _section(
    kind: SectionKind, sources: tuple[SourceDigest, ...], *, state: str = "FRESH"
) -> WikiSection:
    return WikiSection(
        kind=kind,
        body=f"{kind.value} body",
        sources=sources,
        token_estimate=10,
        generated_at=datetime.now(UTC),
        generator=GeneratorInfo(model="test-model"),
        state=state,
        coherence_group=compute_coherence_group(sources),
    )


def test_method_edit_stales_only_contracts_section() -> None:
    contracts_sources = (SourceDigest(node_id="method_1", digest="digest_v1", digest_scope=DigestScope.SPAN),)
    rationale_sources = (SourceDigest(node_id="rationale_1", digest="rat_digest", digest_scope=DigestScope.FILE),)
    gotchas_sources = (SourceDigest(node_id="gotcha_1", digest="gotcha_digest", digest_scope=DigestScope.FILE),)

    page = WikiPage(
        page_id=compute_page_id("ai-parrot", _node_ref("MyClass").uri),
        scope=_node_ref("MyClass"),
        sections={
            SectionKind.CONTRACTS: _section(SectionKind.CONTRACTS, contracts_sources),
            SectionKind.RATIONALE: _section(SectionKind.RATIONALE, rationale_sources),
            SectionKind.GOTCHAS: _section(SectionKind.GOTCHAS, gotchas_sources),
        },
    )

    # method_1's content changed; rationale_1/gotcha_1 did not.
    current_digests = {"method_1": "digest_v2", "rationale_1": "rat_digest", "gotcha_1": "gotcha_digest"}
    updated = invalidate_page(page, current_digests)

    assert updated.sections[SectionKind.CONTRACTS].state == "STALE"
    assert updated.sections[SectionKind.RATIONALE].state == "FRESH"
    assert updated.sections[SectionKind.GOTCHAS].state == "FRESH"


def test_siblings_not_invalidated() -> None:
    sibling_a_sources = (SourceDigest(node_id="method_a", digest="a1", digest_scope=DigestScope.SPAN),)
    sibling_b_sources = (SourceDigest(node_id="method_b", digest="b1", digest_scope=DigestScope.SPAN),)

    page_a = WikiPage(
        page_id="page-a",
        scope=_node_ref("ClassA"),
        sections={SectionKind.CONTRACTS: _section(SectionKind.CONTRACTS, sibling_a_sources)},
    )
    page_b = WikiPage(
        page_id="page-b",
        scope=_node_ref("ClassB"),
        sections={SectionKind.CONTRACTS: _section(SectionKind.CONTRACTS, sibling_b_sources)},
    )

    # method_a changed; method_b (sibling) did not.
    current_digests = {"method_a": "a2", "method_b": "b1"}
    updated_a = invalidate_page(page_a, current_digests)
    updated_b = invalidate_page(page_b, current_digests)

    assert updated_a.sections[SectionKind.CONTRACTS].state == "STALE"
    assert updated_b.sections[SectionKind.CONTRACTS].state == "FRESH"


def test_ancestor_depth_capped_and_cycle_safe() -> None:
    sources = (SourceDigest(node_id="leaf", digest="v1", digest_scope=DigestScope.SPAN),)
    pages = {
        "leaf": WikiPage(page_id="p-leaf", scope=_node_ref("leaf"), sections={SectionKind.CONTRACTS: _section(SectionKind.CONTRACTS, sources)}),
        "parent": WikiPage(page_id="p-parent", scope=_node_ref("parent"), sections={SectionKind.CONTRACTS: _section(SectionKind.CONTRACTS, sources)}),
        "grandparent": WikiPage(page_id="p-gp", scope=_node_ref("grandparent"), sections={SectionKind.CONTRACTS: _section(SectionKind.CONTRACTS, sources)}),
    }
    parent_of = {"leaf": "parent", "parent": "grandparent", "grandparent": None}
    current_digests = {"leaf": "v2"}

    updated = invalidate_ancestors(
        changed_node_id="leaf",
        pages_by_scope_node_id=pages,
        parent_of=parent_of,
        current_digests=current_digests,
        max_ancestor_depth=5,
    )
    assert set(updated) == {"leaf", "parent", "grandparent"}
    for page in updated.values():
        assert page.sections[SectionKind.CONTRACTS].state == "STALE"


def test_ancestor_depth_cap_stops_early() -> None:
    sources = (SourceDigest(node_id="leaf", digest="v1", digest_scope=DigestScope.SPAN),)
    pages = {
        "leaf": WikiPage(page_id="p-leaf", scope=_node_ref("leaf"), sections={SectionKind.CONTRACTS: _section(SectionKind.CONTRACTS, sources)}),
        "parent": WikiPage(page_id="p-parent", scope=_node_ref("parent"), sections={SectionKind.CONTRACTS: _section(SectionKind.CONTRACTS, sources)}),
        "grandparent": WikiPage(page_id="p-gp", scope=_node_ref("grandparent"), sections={SectionKind.CONTRACTS: _section(SectionKind.CONTRACTS, sources)}),
    }
    parent_of = {"leaf": "parent", "parent": "grandparent", "grandparent": None}
    current_digests = {"leaf": "v2"}

    updated = invalidate_ancestors(
        changed_node_id="leaf",
        pages_by_scope_node_id=pages,
        parent_of=parent_of,
        current_digests=current_digests,
        max_ancestor_depth=0,
    )
    assert set(updated) == {"leaf"}


def test_cyclic_parent_chain_terminates() -> None:
    sources = (SourceDigest(node_id="a", digest="v1", digest_scope=DigestScope.SPAN),)
    pages = {
        "a": WikiPage(page_id="p-a", scope=_node_ref("a"), sections={SectionKind.CONTRACTS: _section(SectionKind.CONTRACTS, sources)}),
        "b": WikiPage(page_id="p-b", scope=_node_ref("b"), sections={SectionKind.CONTRACTS: _section(SectionKind.CONTRACTS, sources)}),
    }
    parent_of = {"a": "b", "b": "a"}  # cycle
    current_digests = {"a": "v2"}

    updated = invalidate_ancestors(
        changed_node_id="a",
        pages_by_scope_node_id=pages,
        parent_of=parent_of,
        current_digests=current_digests,
        max_ancestor_depth=100,
    )
    assert set(updated) == {"a", "b"}  # terminates, does not hang


@pytest.mark.asyncio
async def test_stale_does_not_eager_regenerate(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise AssertionError("marking STALE must not trigger any LLM call")

    monkeypatch.setattr("builtins.open", _raise)

    sources = (SourceDigest(node_id="method_1", digest="v1", digest_scope=DigestScope.SPAN),)
    page = WikiPage(
        page_id="p1",
        scope=_node_ref("MyClass"),
        sections={SectionKind.CONTRACTS: _section(SectionKind.CONTRACTS, sources)},
    )
    updated = invalidate_page(page, {"method_1": "v2"})
    assert updated.sections[SectionKind.CONTRACTS].state == "STALE"


def test_mixed_freshness_flag() -> None:
    sources_a = (SourceDigest(node_id="a", digest="va", digest_scope=DigestScope.SPAN),)
    sources_b = (SourceDigest(node_id="b", digest="vb", digest_scope=DigestScope.SPAN),)
    section_a = _section(SectionKind.CONTRACTS, sources_a)
    section_b_same_group = _section(SectionKind.USAGE, sources_a)  # same sources -> same group
    section_c_diff_group = _section(SectionKind.RATIONALE, sources_b)

    assert compute_mixed_freshness((section_a, section_b_same_group)) is False
    assert compute_mixed_freshness((section_a, section_c_diff_group)) is True


@pytest.mark.parametrize(
    ("allow_stale", "max_llm_calls", "expected"),
    [
        (True, 0, ServingDecision.SERVE_STALE),
        (True, 1, ServingDecision.REGENERATE_THEN_STALE_FALLBACK),
        (False, 0, ServingDecision.SKIP_TO_L0),
        (False, 1, ServingDecision.BLOCK_REGENERATE_THEN_L0_FALLBACK),
    ],
)
def test_serving_matrix(allow_stale: bool, max_llm_calls: int, expected: ServingDecision) -> None:
    assert resolve_serving_decision(allow_stale=allow_stale, max_llm_calls=max_llm_calls) == expected


def test_no_import_from_knowledge_wiki() -> None:
    import parrot.knowledge.retrieval.wiki_cache as module

    source = Path(module.__file__).read_text()
    import_lines = [
        line
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from ")) and "wiki" in line
    ]
    assert import_lines == []


def test_wiki_page_frozen_and_forbid_extra() -> None:
    from pydantic import ValidationError

    sources = (SourceDigest(node_id="a", digest="va", digest_scope=DigestScope.SPAN),)
    page = WikiPage(
        page_id="p1", scope=_node_ref("MyClass"), sections={SectionKind.CONTRACTS: _section(SectionKind.CONTRACTS, sources)}
    )
    with pytest.raises(ValidationError):
        page.page_id = "changed"  # type: ignore[misc]
