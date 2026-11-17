"""Unit tests for ExpertKnowledgeToolkit."""

from types import SimpleNamespace

import pytest
from parrot.experts.models import (
    ExpertCapabilityError,
    ExpertManifest,
    KnowledgeContext,
    KnowledgeLayer,
    KnowledgeMode,
)
from parrot_tools.experts import ExpertKnowledgeToolkit


def _manifest(caps: list[str]) -> ExpertManifest:
    return ExpertManifest(
        name="demo-expert",
        display_name="Demo",
        description="d",
        capabilities=caps,
        knowledge=[{"source": "wiki", "mode": "retrieval"}],
    )


def _layer(source: str, handle: dict) -> KnowledgeLayer:
    return KnowledgeLayer(layer="retrieval", source=source, mode=KnowledgeMode.RETRIEVAL, revision="r1", handle=handle)


class _Wiki:
    async def query(self, wiki_name, question, **kw):
        return {"results": [{"t": f"{wiki_name}:{question}"}]}


class _Books:
    async def search(self, query, **kw):
        return {"results": [{"t": "book"}]}


class _Boom:
    async def search(self, query, **kw):
        raise ValueError("down")


class _Decisions:
    async def generate(self, target):
        return SimpleNamespace(decision_ids=["d1"], reused=["d0"])


def _ctx() -> KnowledgeContext:
    return KnowledgeContext(
        expert="demo-expert",
        budget_tokens=100,
        layers=[_layer("wiki", {"wiki_name": "w"}), _layer("bookstore", {})],
    )


def test_tool_names_are_prefixed():
    tk = ExpertKnowledgeToolkit(_ctx(), _manifest([]))
    names = {t.name for t in tk.get_tools()}
    assert {"expert_knowledge_search", "expert_propose_adr"} <= names


async def test_knowledge_search_fans_out():
    tk = ExpertKnowledgeToolkit(_ctx(), _manifest([]), wiki=_Wiki(), bookstore=_Books())
    out = await tk.knowledge_search("q")
    assert [r["source"] for r in out["results"]] == ["wiki", "bookstore"]
    assert out["results"][0]["revision"] == "r1"
    assert out["errors"] == []
    assert len((await tk.knowledge_search("q", top_k=1))["results"]) == 1


async def test_knowledge_search_uses_real_wiki_source_layer_shape():
    """WikiSource emits ``source="wiki:<namespace>"``; the search must dispatch on it."""
    ctx = KnowledgeContext(
        expert="demo-expert",
        budget_tokens=100,
        layers=[_layer("wiki:expert-demo-expert", {"toolkit": "wiki", "wiki_name": "expert-demo-expert"})],
    )
    tk = ExpertKnowledgeToolkit(ctx, _manifest([]), wiki=_Wiki())
    out = await tk.knowledge_search("q")
    assert out["errors"] == []
    assert [r["source"] for r in out["results"]] == ["wiki:expert-demo-expert"]


async def test_knowledge_search_captures_backend_error():
    tk = ExpertKnowledgeToolkit(_ctx(), _manifest([]), wiki=_Wiki(), bookstore=_Boom())
    out = await tk.knowledge_search("q")
    assert len(out["results"]) == 1
    assert len(out["errors"]) == 1 and "down" in out["errors"][0]


async def test_propose_adr_requires_write_capability():
    tk = ExpertKnowledgeToolkit(_ctx(), _manifest([]), decisions=_Decisions())
    with pytest.raises(ExpertCapabilityError):
        await tk.propose_adr("t", "r")


async def test_propose_adr_returns_inferred_unreviewed():
    tk = ExpertKnowledgeToolkit(_ctx(), _manifest(["write"]), decisions=_Decisions())
    out = await tk.propose_adr("t", "r")
    assert out["decision_ids"] == ["d1"] and out["reused"] == ["d0"]
    assert out["origin"] == "inferred" and out["review_status"] == "unreviewed"
