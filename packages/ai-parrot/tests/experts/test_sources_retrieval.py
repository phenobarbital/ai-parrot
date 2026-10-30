"""Tests for the FEAT-778 retrieval-handle knowledge sources."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from parrot.experts.knowledge.sources.bookstore import BookstoreSource
from parrot.experts.knowledge.sources.graphindex import GraphIndexSource
from parrot.experts.knowledge.sources.kb import LegacyKBSource
from parrot.experts.models import KnowledgeMode, KnowledgeSourceSpec


def _run(source, spec, workspace=None):
    return asyncio.run(source.layers(spec, None, workspace=workspace, counter=None))


def _spec(kind: str, **kw) -> KnowledgeSourceSpec:
    return KnowledgeSourceSpec(source=kind, mode="retrieval", **kw)


def _check(layer, source: str) -> None:
    assert layer.layer == "retrieval"
    assert layer.mode is KnowledgeMode.RETRIEVAL
    assert layer.tokens == 0
    assert layer.content is None
    assert layer.source == source


def test_bookstore_handle_carries_scope():
    [layer] = _run(BookstoreSource(), _spec("bookstore", scope={"topics": ["sales"]}))
    _check(layer, "bookstore")
    assert layer.handle == {"toolkit": "bookstore", "scope": {"topics": ["sales"]}}


def test_graphindex_handle_shape(tmp_path):
    [layer] = _run(GraphIndexSource(), _spec("graphindex"), workspace=tmp_path)
    _check(layer, "graphindex")
    assert layer.handle == {"toolkit": "graphindex", "scope": {}, "workspace": str(tmp_path),
                            "budget": {"max_tokens": 4000, "max_llm_calls": 0}}
    [none_ws] = _run(GraphIndexSource(), _spec("graphindex"))
    assert none_ws.handle["workspace"] is None


def test_legacy_kb_handle_names():
    bot = SimpleNamespace(knowledge_bases=[SimpleNamespace(name="low", priority=1),
                                           SimpleNamespace(name="high", priority=9)])
    [layer] = _run(LegacyKBSource(bot), _spec("kb"))
    _check(layer, "kb")
    assert layer.handle == {"toolkit": "kb", "names": ["high", "low"]}


def test_legacy_kb_without_kbs_is_empty():
    assert _run(LegacyKBSource(SimpleNamespace(knowledge_bases=[])), _spec("kb")) == []


def test_revisions_are_deterministic(tmp_path):
    spec = _spec("bookstore", scope={"a": ["1"]})
    assert _run(BookstoreSource(), spec)[0].revision == _run(BookstoreSource(), spec)[0].revision
    g1 = _run(GraphIndexSource(), _spec("graphindex"), workspace=tmp_path)[0].revision
    assert g1 == _run(GraphIndexSource(), _spec("graphindex"), workspace=tmp_path)[0].revision
    other = _run(BookstoreSource(), _spec("bookstore", scope={"a": ["2"]}))[0].revision
    assert other != _run(BookstoreSource(), spec)[0].revision
