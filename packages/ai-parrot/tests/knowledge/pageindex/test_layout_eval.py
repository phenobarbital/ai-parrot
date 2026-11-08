"""layout_eval: fixture comparison, threshold rule, internal-pair privacy (FEAT-845 M10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.knowledge.pageindex.layout_eval import EvalPair, EvalResult, evaluate_pair, main, suggest_threshold
from parrot.knowledge.pageindex.layout_structure import CandidateScore

FIXTURES = Path(__file__).parent / "fixtures"
PDF = FIXTURES / "arxiv_2408_09869.pdf"
REFERENCE = FIXTURES / "docling_structure.json"


@pytest.fixture(autouse=True)
def _offline_tokens(monkeypatch):
    """Keep PageIndex token counting deterministic and offline."""
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.get_encoder", lambda model="gpt-4o": None)
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda text, model="gpt-4o": max(1, len(text)))


def _result(label: str, recall_all: float, confidence: float) -> EvalResult:
    """Build a minimal evaluation result for threshold tests."""
    return EvalResult(
        label=label,
        internal=False,
        pages=1,
        structure_source="bookmarks",
        chosen_confidence=confidence,
        candidates=[CandidateScore(source="bookmarks", confidence=confidence, entries=1, anchored=1)],
        reference_nodes=1,
        layout_nodes=1,
        recall_top=recall_all,
        recall_all=recall_all,
        page_agreement=1.0,
        seconds=0.0,
    )


async def test_evaluate_fixture_pair():
    """Fixture vs docling_structure.json has exact top-level recall and page agreement."""
    result = await evaluate_pair(EvalPair(label="arxiv", pdf=PDF, reference=REFERENCE), min_confidence=0.6)

    assert result.recall_top == 1.0
    assert result.page_agreement == 1.0
    assert result.structure_source in {"hybrid", "bookmarks"}


def test_suggest_threshold():
    """Threshold selection handles separable, non-separable, all-good, and no-good inputs."""
    assert suggest_threshold([_result("good", 0.9, 0.95), _result("bad", 0.4, 0.4)]) == 0.45
    assert suggest_threshold([_result("good", 0.9, 0.5), _result("bad", 0.4, 0.6)]) is None
    assert suggest_threshold([_result("good-a", 0.9, 0.83), _result("good-b", 0.97, 0.97)]) == 0.8
    assert suggest_threshold([_result("bad", 0.4, 0.95)]) is None


def test_cli_internal_hides_titles(tmp_path: Path):
    """An internal pair writes no reference title into either report format."""
    code = main(["--pair", f"secret={PDF}::{REFERENCE}", "--internal", "secret", "--out", str(tmp_path)])

    json_paths = list(tmp_path.glob("*.json"))
    markdown_paths = list(tmp_path.glob("*.md"))
    assert code == 0
    assert len(json_paths) == 1
    assert len(markdown_paths) == 1

    json_text = json_paths[0].read_text(encoding="utf-8")
    markdown_text = markdown_paths[0].read_text(encoding="utf-8")
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))["structure"]

    def titles(nodes: list[dict]) -> list[str]:
        found: list[str] = []
        for node in nodes:
            found.append(node["title"])
            found.extend(titles(node.get("nodes") or []))
        return found

    for title in titles(reference):
        assert title not in json_text
        assert title not in markdown_text
    assert json.loads(json_text)["results"][0]["unmatched_titles"] == []
