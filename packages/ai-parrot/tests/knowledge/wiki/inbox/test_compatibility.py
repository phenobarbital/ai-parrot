"""Focused FEAT-626 regression tests for the duplicate-bypass and tags seams."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from parrot.knowledge.wiki.export import page_frontmatter
from parrot.knowledge.wiki.review import DimensionScores, TriageOutput
from parrot.knowledge.wiki.triage import IngestTriageRouter


class _FakeAdapter:
    """Adapter spy returning a canned TriageOutput."""

    def __init__(self, sensitive: bool = False, score: float = 0.9) -> None:
        self.calls = 0
        self.sensitive = sensitive
        self.score = score

    async def ask_structured(self, prompt: str, model: type[TriageOutput]) -> TriageOutput:
        self.calls += 1
        return TriageOutput(
            scores=DimensionScores(density=self.score, novelty=self.score, durability=self.score),
            claims=[],
            sensitive=self.sensitive,
            briefing="brief",
        )


class _FakeNovelty:
    def __init__(self) -> None:
        self.calls = 0

    async def score(self, claims: list[Any], text: str) -> tuple[float, str]:
        self.calls += 1
        return 0.9, "fake"


class _FakeSources:
    """Source manager fake: one known URI plus one entry with the same hash elsewhere."""

    def __init__(self, uri_hash: str | None = None, other_hash: str | None = None, uri: str = "") -> None:
        self._uri = uri
        self._uri_hash = uri_hash
        self._other_hash = other_hash

    def find_by_uri(self, uri: str) -> str | None:
        return "id1" if self._uri_hash is not None and uri == self._uri else None

    def get_source(self, sid: str) -> Any:
        return SimpleNamespace(file_hash=self._uri_hash)

    def list_sources(self) -> list[Any]:
        if self._other_hash is None:
            return []
        return [SimpleNamespace(file_hash=self._other_hash, source_uri="other.md")]


def _charter() -> Any:
    thresholds = SimpleNamespace(route=lambda c: "admit" if c >= 0.7 else ("gray" if c >= 0.3 else "reject"))
    return SimpleNamespace(
        weights={"density": 1 / 3, "novelty": 1 / 3, "durability": 1 / 3},
        thresholds=thresholds,
        scope=SimpleNamespace(include=[], exclude=[]),
        examples=[],
    )


def _router(
    sources: _FakeSources,
    adapter: _FakeAdapter,
    heavy: _FakeAdapter | None = None,
    novelty: _FakeNovelty | None = None,
    **kwargs: Any,
) -> IngestTriageRouter:
    return IngestTriageRouter(
        _charter(), adapter, sources, novelty or _FakeNovelty(), heavy_adapter=heavy, **kwargs  # type: ignore[arg-type]
    )


def _hash(content: str) -> str:
    return _router(_FakeSources(), _FakeAdapter())._hash_content(content)


@pytest.mark.asyncio
async def test_force_skips_only_duplicate_check(tmp_path: Path) -> None:
    """Bypass both duplicate cases but preserve size, suffix and sensitivity rejection."""
    content = "hello world"
    path = tmp_path / "a.md"
    h = _hash(content)

    # Same-URI duplicate.
    adapter = _FakeAdapter()
    router = _router(_FakeSources(uri_hash=h, uri=str(path)), adapter)
    assert (await router.triage(path, content)).decision_source == "heuristic"
    assert adapter.calls == 0
    entry = await router.triage(path, content, skip_duplicate_check=True)
    assert entry.decision_source == "model" and entry.proposed_action == "admit"
    assert adapter.calls == 1

    # Other-URI duplicate.
    adapter = _FakeAdapter()
    router = _router(_FakeSources(other_hash=h), adapter)
    default = await router.triage(path, content)
    assert "duplicate content of other.md" in default.briefing and adapter.calls == 0
    assert (await router.triage(path, content, skip_duplicate_check=True)).decision_source == "model"

    # Size and suffix still reject without model calls.
    adapter = _FakeAdapter()
    router = _router(_FakeSources(), adapter, max_size_bytes=3, allowed_suffixes=frozenset({".md"}))
    big = await router.triage(path, content, skip_duplicate_check=True)
    assert "exceeds max size" in big.briefing
    router.max_size_bytes = 10_000
    bad = await router.triage(tmp_path / "a.txt", content, skip_duplicate_check=True)
    assert "not in the allowed set" in bad.briefing
    assert adapter.calls == 0

    # Sensitivity still discards.
    adapter = _FakeAdapter(sensitive=True)
    router = _router(_FakeSources(other_hash=h), adapter)
    sens = await router.triage(path, content, skip_duplicate_check=True)
    assert sens.proposed_action == "discard" and sens.decision_source == "model"
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_force_retains_llm_stages(tmp_path: Path) -> None:
    """Both model tiers and novelty remain available after duplicate bypass."""
    content = "gray doc"
    h = _hash(content)
    adapter, heavy, novelty = _FakeAdapter(score=0.5), _FakeAdapter(score=0.8), _FakeNovelty()
    router = _router(_FakeSources(other_hash=h), adapter, heavy, novelty)
    # Novelty scorer overrides novelty to 0.9; stage1 composite = (0.5+0.9+0.5)/3 ~ 0.63 -> gray.
    entry = await router.triage(tmp_path / "g.md", content, skip_duplicate_check=True)
    assert adapter.calls == 1 and heavy.calls == 1 and novelty.calls == 2
    assert entry.proposed_action == "admit"


def test_page_frontmatter_tags_param() -> None:
    """Default bytes remain identical; explicit tags dedupe in order and empty stays empty."""
    page = {"concept_id": "c1", "title": "T", "category": "concept", "updated_at": "now"}

    def tags_of(**kw: Any) -> Any:
        text = page_frontmatter(page, [], **kw)
        return yaml.safe_load(text.split("---\n")[1])["tags"]

    default = page_frontmatter(page, [])
    assert page_frontmatter(page, [], None) == default
    assert "tags:\n- concept\n" in default
    assert tags_of(tags=["b", "a", "b", "c", "a"]) == ["b", "a", "c"]
    assert tags_of(tags=[]) == []
    assert tags_of(tags=("x",)) == ["x"]
