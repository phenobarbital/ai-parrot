"""optimizer_eval: report over the arxiv fixture and the tuned_target rule (FEAT-846 M6)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.pageindex import optimizer_eval
from parrot.knowledge.pageindex.optimizer import OptimizerSettings
from parrot.knowledge.pageindex.optimizer_eval import EvalReport, EvalSettings, TreeMetrics, main, tuned_target
from parrot.knowledge.pageindex.optimizer_llm import HeadingProposals, KeyItemProposals, SummaryOut
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex.utils import structure_to_list

FIXTURES = Path(__file__).parent / "fixtures"
PDF = FIXTURES / "arxiv_2408_09869.pdf"


@pytest.fixture(autouse=True)
def _offline_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep PageIndex token counting deterministic and offline."""
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.get_encoder", lambda model="gpt-4o": None)
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.utils.count_tokens", lambda text, model="gpt-4o": max(1, len(text) // 4)
    )


def _fake_adapter() -> MagicMock:
    """A live-looking adapter: proposes every sequence as a heading, no key items, a short summary."""

    async def ask_structured(prompt: str, schema: type, **kwargs: Any) -> Any:
        if schema is HeadingProposals:
            return HeadingProposals(seqs=list(range(5000)))
        if schema is KeyItemProposals:
            return KeyItemProposals(items=[])
        return SummaryOut(summary="three word summary")

    adapter = MagicMock(client=MagicMock(), model="fake-model")
    adapter.ask_structured = AsyncMock(side_effect=ask_structured)
    adapter.ask = AsyncMock(return_value="fake description")
    return adapter


def _metrics(label: str) -> TreeMetrics:
    """Minimal metrics row for report construction."""
    return TreeMetrics(
        label=label,
        pages=1,
        nodes_before=1,
        nodes_after=1,
        leaves_before=1,
        leaves_after=1,
        leaf_tokens_p50=1,
        leaf_tokens_p90=1,
        leaf_tokens_max=1,
        leaves_over_target_before=0,
        leaves_over_target_after=0,
        key_items=0,
        summary_words_mean=0.0,
        llm_calls=0,
        seconds=0.0,
        llm_heading_splits=0,
    )


def _report(suggested: int | None, trees: int = 3) -> EvalReport:
    """Report with ``trees`` rows and a fixed suggestion."""
    return EvalReport(
        created_at="2026-01-01T00:00:00+00:00",
        settings=EvalSettings(target_leaf_tokens=1500, min_leaf_tokens=200),
        results=[_metrics(f"t{i}") for i in range(trees)],
        suggested_target_leaf_tokens=suggested,
    )


def test_optimizer_eval_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """Metrics and suggested target over the arxiv fixture; llm splits counted; no node title in the JSON."""
    monkeypatch.setattr(optimizer_eval, "_make_adapter", lambda llm: _fake_adapter() if llm else None)

    reports: list[dict] = []
    titles: set[str] = set()
    original_optimize = PageIndexToolkit.optimize
    original_import = PageIndexToolkit.import_pdf

    async def capture_optimize(self: PageIndexToolkit, *args: Any, **kwargs: Any) -> dict:
        report = await original_optimize(self, *args, **kwargs)
        reports.append(report)
        tree = await self.get_tree(args[0])
        titles.update(str(node.get("title")) for node in structure_to_list(tree.get("structure") or []))
        return report

    async def capture_import(self: PageIndexToolkit, tree_name: str, *args: Any, **kwargs: Any) -> dict:
        assert self._optimize_on_import is False
        result = await original_import(self, tree_name, *args, **kwargs)
        tree = await self.get_tree(tree_name)
        titles.update(str(node.get("title")) for node in structure_to_list(tree.get("structure") or []))
        return result

    leaf_threads: list[int] = []
    original_leaf_tokens = optimizer_eval._leaf_tokens

    def tracked_leaf_tokens(*args: Any) -> list[int]:
        leaf_threads.append(threading.get_ident())
        return original_leaf_tokens(*args)

    monkeypatch.setattr(PageIndexToolkit, "optimize", capture_optimize)
    monkeypatch.setattr(PageIndexToolkit, "import_pdf", capture_import)
    monkeypatch.setattr(optimizer_eval, "_leaf_tokens", tracked_leaf_tokens)

    out = tmp_path / "out"
    # min_leaf_tokens=0 keeps normalization from absorbing nodes, so optimize(apply=True) publishes and the
    # post-optimize metrics reflect the LLM passes rather than a rejected candidate.
    code = main([str(PDF), str(PDF), str(FIXTURES), "--llm", "fake:model", "--min-leaf-tokens", "0", "--out", str(out)])
    assert code == 0
    assert reports and all(report["errors"] == [] for report in reports)

    # A directory input expands to its *.pdf files (the fixture itself here).
    json_paths = list(out.glob("optimizer_eval-*.json"))
    assert len(json_paths) == 1
    printed = capsys.readouterr().out
    assert f"report: {json_paths[0]}" in printed
    assert "tuned_target:" in printed

    json_text = json_paths[0].read_text(encoding="utf-8")
    data = json.loads(json_text)
    assert len(data["results"]) == len(reports) >= 3
    assert set(data["results"][0]) == set(TreeMetrics.model_fields)
    assert "_layout_leaf_tokens" not in json_text

    for row, report in zip(data["results"], reports, strict=True):
        assert row["label"] == PDF.stem
        assert row["pages"] and row["pages"] > 0
        assert row["nodes_before"] == report["nodes_before"]
        assert row["nodes_after"] == report["nodes_after"]
        assert row["leaves_over_target_before"] == report["leaves_over_target_before"]
        assert row["leaves_over_target_after"] == report["leaves_over_target_after"]
        assert row["llm_calls"] == report["llm_calls_made"] > 0
        assert row["llm_heading_splits"] == sum(1 for action in report["expanded"] if action["source"] == "llm")
        assert row["leaves_before"] > 0 and row["leaves_after"] > 0
        assert 0 < row["leaf_tokens_p50"] <= row["leaf_tokens_p90"] <= row["leaf_tokens_max"]
        assert row["summary_words_mean"] > 0
    assert any(row["llm_heading_splits"] > 0 for row in data["results"])

    suggested = data["suggested_target_leaf_tokens"]
    assert isinstance(suggested, int) and suggested > 0 and suggested % 100 == 0

    # CPU-bound token measurement runs off the event-loop thread.
    assert leaf_threads and all(ident != threading.get_ident() for ident in leaf_threads)

    titles.discard("")
    titles.discard("None")
    assert titles
    for title in titles:
        # A bare numbered heading ("5") would collide with digits of the numeric fields, so short titles are checked
        # as JSON string tokens and longer ones as raw substrings.
        assert json.dumps(title) not in json_text
        if len(title) >= 4:
            assert title not in json_text


def test_tuned_target_bounds() -> None:
    """Suggestion returned inside [2*min, 2*target]; None below, above, or with fewer than three trees."""
    current = OptimizerSettings(target_leaf_tokens=1500, min_leaf_tokens=200)

    assert tuned_target(_report(400), current) == 400
    assert tuned_target(_report(1200), current) == 1200
    assert tuned_target(_report(3000), current) == 3000
    assert tuned_target(_report(300), current) is None
    assert tuned_target(_report(3100), current) is None
    assert tuned_target(_report(None), current) is None

    two = [_metrics("a"), _metrics("b")]
    for metrics in two:
        metrics._layout_leaf_tokens = [900, 1000, 1100]
    assert optimizer_eval.suggest_target(two) is None
    assert tuned_target(_report(optimizer_eval.suggest_target(two), trees=2), current) is None

    three = [_metrics("a"), _metrics("b"), _metrics("c")]
    for metrics in three:
        metrics._layout_leaf_tokens = [100, 1000, 1240, 2000]
    assert optimizer_eval.suggest_target(three) == 1400
