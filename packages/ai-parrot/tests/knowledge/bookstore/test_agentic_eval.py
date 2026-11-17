"""Deterministic evaluation-plan, scoring, coverage and privacy regressions."""

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from parrot.knowledge.bookstore import agentic_eval as ae
from parrot.knowledge.bookstore.agentic_eval import (
    EvalQuestion,
    EvalSettings,
    evaluate_library,
    generate_questions,
)
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError
from parrot.knowledge.pageindex.agentic import EvidenceBundle
from parrot.knowledge.pageindex.citations import Citation

SECRET = "SECRET-SOURCE-TEXT-do-not-persist"
BOOKS = [f"book{i}" for i in range(7)]


def _q(book: str, n: int, provenance: str = "handwritten", **over: Any) -> EvalQuestion:
    data: dict[str, Any] = {
        "question_id": f"{book}-{provenance[0]}{n}",
        "book_id": book,
        "question": f"Question {n} about {book}?",
        "provenance": provenance,
        "doc_id": f"doc-{book}",
        "revision": "rev1",
        "generation": 2,
        "gold_kind": "seq",
        "gold_seq": 3,
    }
    data.update(over)
    return EvalQuestion(**data)


def _fixture() -> list[EvalQuestion]:
    out: list[EvalQuestion] = []
    for book in BOOKS:
        out += [_q(book, n) for n in range(3)]
        out += [_q(book, n, "generated") for n in range(5)]
    return out


def _tree() -> dict[str, Any]:
    return {
        "generation": {"id": 2},
        "structure": [{"node_id": "n1", "owned": [[0, 5]], "nodes": [{"node_id": "n2", "owned": [], "nodes": []}]}],
    }


def _bundle(doc_id: str = "doc", seq: int = 3, stopped: str = "answered", grounded: bool = True) -> dict[str, Any]:
    cit = Citation(
        doc_id=doc_id,
        revision="rev1",
        seq=seq,
        ordinal=0,
        start=0,
        end=5,
        excerpt=SECRET,
        label="p. 1",
        document="Book",
    )
    return EvidenceBundle(
        tree_name="t",
        query="q",
        generation=2,
        citations=[cit],
        grounded=grounded,
        stopped=stopped,
        chars_read=100,
        tool_calls=2,
        answer=SECRET,
        usage={"total_tokens": 5},
    ).model_dump()


class _Card:
    def __init__(self, book_id: str) -> None:
        self.book_id = book_id
        self.tree_name = book_id


class _Toolkit:
    def __init__(self, book_id: str, generation: int = 2) -> None:
        self.book_id = book_id
        self.generation = generation

    async def list_documents(self, tree_name: str) -> list[dict[str, Any]]:
        return [{"doc_id": f"doc-{self.book_id}", "revision": "rev1", "segments": 10}]

    async def get_tree(self, tree_name: str) -> dict[str, Any]:
        tree = _tree()
        tree["generation"]["id"] = self.generation
        return tree


class _Loc:
    scope = "project"


class _FakeStore:
    calls = 0

    def __init__(self, stale_book: str | None = None, fail: bool = False, gone: str | None = None) -> None:
        self.stale_book = stale_book
        self.fail = fail
        self.gone = gone

    def resolve_book(self, book_id: str):
        if book_id == self.gone:
            raise BookstoreError("missing")
        return _Card(book_id), _Loc()

    def _toolkit(self, scope: str):
        # one toolkit per call is enough: tree shape does not depend on the book
        store = self

        class T(_Toolkit):
            async def get_tree(self, tree_name: str) -> dict[str, Any]:
                self.generation = 3 if tree_name == store.stale_book else 2
                return await super().get_tree(tree_name)

            async def list_documents(self, tree_name: str) -> list[dict[str, Any]]:
                return [{"doc_id": f"doc-{tree_name}", "revision": "rev1", "segments": 10}]

        return T(self.stale_book or "x")

    async def agentic_retrieve(self, book_id: str, query: str, **kwargs: Any) -> dict[str, Any]:
        type(self).calls += 1
        if self.fail:
            raise RuntimeError(f"provider said {SECRET}")
        return _bundle(f"doc-{book_id}")


def _write_fixture(path: Path) -> None:
    path.write_text(json.dumps({"questions": [q.model_dump() for q in _fixture()]}))


def _settings(tmp_path: Path, concurrency: int = 1) -> EvalSettings:
    return EvalSettings(
        library=tmp_path / "lib", questions=tmp_path / "q.json", out_dir=tmp_path / "out", concurrency=concurrency
    )


def test_models_validate_gold_and_concurrency(tmp_path: Path) -> None:
    """Exactly one gold kind, nonempty ids and positive concurrency are enforced."""
    with pytest.raises(ValidationError):
        _q("b", 0, gold_page=4)  # two gold addresses
    with pytest.raises(ValidationError):
        _q("b", 0, gold_kind="node")  # kind without matching address
    with pytest.raises(ValidationError):
        _q("b", 0, doc_id=" ")
    assert _q("b", 0, gold_kind="node", gold_seq=None, gold_node_id="n1").gold_node_id == "n1"
    with pytest.raises(ValidationError):
        EvalSettings(library=tmp_path, questions=tmp_path / "q", concurrency=0)


def test_frozen_plan_has_140_rows() -> None:
    """Baseline and one-dimensional sweeps use exact denominators/provenance."""
    plan = ae.build_plan(_fixture())
    assert len(plan) == 140
    assert sum(1 for p in plan if p["setting"] == "baseline") == 56
    for name, _, _ in ae.SWEEPS:
        rows = [p for p in plan if p["setting"] == name]
        assert len(rows) == 21 and all(p["question"].provenance == "handwritten" for p in rows)
    with pytest.raises(BookstoreError):
        ae.build_plan(_fixture()[:-1])


def _rows(spec: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Build 140 synthetic rows; spec maps setting -> overrides for its handwritten rows."""
    rows: list[dict[str, Any]] = []
    for item in ae.build_plan(_fixture()):
        row = ae._row_base(item)  # noqa: SLF001
        row.update(status="completed", grounded=True, gold_hit=True, chars_read=100, wall_s=2.0)
        if item["question"].provenance == "handwritten":
            row.update(spec.get(item["setting"], {}))
        rows.append(row)
    return rows


def test_coverage_quality_and_tie_policy() -> None:
    """Insufficient evidence cannot tune and untested knob combinations never win."""
    # complete tie with baseline -> retain baseline
    assert ae.select_recommendation(_rows({}))["status"] == "retain_baseline"
    # one cheaper, equally good candidate wins
    rec = ae.select_recommendation(_rows({"c20000_r12": {"chars_read": 50}}))
    assert (rec["status"], rec["setting"]) == ("candidate", "c20000_r12")
    # tie on chars and wall: fewer max_reads wins, then smaller budget
    rec = ae.select_recommendation(
        _rows({"c20000_r12": {"chars_read": 50}, "c40000_r8": {"chars_read": 50}, "c60000_r12": {"chars_read": 50}})
    )
    assert rec["setting"] == "c40000_r8"
    # cheaper but worse gold hits is disqualified
    assert (
        ae.select_recommendation(_rows({"c60000_r12": {"chars_read": 1, "gold_hit": False}}))["status"]
        == "retain_baseline"
    )
    # candidate with 16/21 completed (boundary below 17) is disqualified
    rows = _rows({"c20000_r12": {"chars_read": 50}})
    hits = [r for r in rows if r["setting"] == "c20000_r12"][:5]
    for r in hits:
        r["status"] = "error"
    assert ae.select_recommendation(rows)["status"] == "retain_baseline"
    # exactly 4 errors (17/21) still qualifies on coverage; quality compares to baseline, errors count as misses
    for r in hits[4:]:
        r["status"] = "completed"
    # fewer than 112 completed rows -> insufficient, no recommendation
    rows = _rows({})
    for r in rows[:29]:
        r["status"] = "error"
    assert ae.select_recommendation(rows) == {
        "status": "insufficient_coverage",
        "setting": None,
        "completed_total": 111,
    }
    rows = _rows({})
    for r in rows[:28]:
        r["status"] = "error"
    assert ae.select_recommendation(rows)["completed_total"] == 112
    # baseline handwritten coverage below 17 is insufficient regardless of the total
    rows = _rows({})
    for r in [r for r in rows if r["setting"] == "baseline" and r["provenance"] == "handwritten"][:5]:
        r["status"] = "error"
    assert ae.select_recommendation(rows)["status"] == "insufficient_coverage"


def test_gold_hit_rules() -> None:
    """Seq, node-range and page gold use validated citations pinned to doc/revision."""
    ctx = {"owned": {"n1": [(0, 5)]}}
    cit = {"doc_id": "doc-b", "revision": "rev1", "seq": 3, "page": 9}
    assert ae.gold_hit(_q("b", 0), [cit], ctx)
    assert not ae.gold_hit(_q("b", 0, gold_seq=4), [cit], ctx)
    assert ae.gold_hit(_q("b", 0, gold_kind="node", gold_seq=None, gold_node_id="n1"), [cit], ctx)
    assert ae.gold_hit(_q("b", 0, gold_kind="page", gold_seq=None, gold_page=9), [cit], ctx)
    assert not ae.gold_hit(_q("b", 0), [{**cit, "revision": "other"}], ctx)


@pytest.mark.asyncio
async def test_stale_fixture_and_report_privacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stale gold is not scored and unsafe provider payloads never persist."""
    _write_fixture(tmp_path / "q.json")
    _FakeStore.calls = 0
    monkeypatch.setattr(ae, "_make_bookstore", lambda settings: _FakeStore(stale_book="book1", fail=True, gone="book2"))
    result = await evaluate_library(_settings(tmp_path, concurrency=3))
    metrics = json.loads(Path(result["metrics"]).read_text())
    assert metrics["experiment_count"] == 140
    by_book = metrics["by_book"]
    assert by_book["book1"]["stale"] == by_book["book1"]["planned"] > 0
    assert by_book["book2"]["skipped"] == by_book["book2"]["planned"] > 0
    assert by_book["book0"]["error"] == by_book["book0"]["planned"]
    assert _FakeStore.calls <= 140 and _FakeStore.calls < 140  # stale/skipped rows never invoke
    assert metrics["recommendation"]["status"] == "insufficient_coverage"
    for artifact in Path(result["report"]).parent.iterdir():
        text = artifact.read_text()
        assert SECRET not in text and "provider said" not in text
    assert {r["error_category"] for r in metrics["rows"] if r["status"] == "error"} == {"provider_error"}


@pytest.mark.asyncio
async def test_successful_run_scores_and_hides_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A clean run scores gold hits from real EvidenceBundle output and never stores excerpts."""
    _write_fixture(tmp_path / "q.json")
    monkeypatch.setattr(ae, "_make_bookstore", lambda settings: _FakeStore())
    result = await evaluate_library(_settings(tmp_path))
    metrics = json.loads(Path(result["metrics"]).read_text())
    assert metrics["by_provenance"]["handwritten"]["planned"] == 105
    assert metrics["by_provenance"]["generated"]["planned"] == 35
    assert all(r["gold_hit"] and r["grounded"] for r in metrics["rows"])
    assert metrics["recommendation"]["status"] == "retain_baseline"
    for artifact in Path(result["report"]).parent.iterdir():
        assert SECRET not in artifact.read_text()


@pytest.mark.asyncio
async def test_generate_never_overwrites(tmp_path: Path) -> None:
    """An existing fixture is refused before any model/corpus work happens."""
    (tmp_path / "q.json").write_text("[]")
    with pytest.raises(BookstoreError):
        await generate_questions(_settings(tmp_path))
    assert (tmp_path / "q.json").read_text() == "[]"


# Numeric evidence recorded from the owner-host run 20261109T190824Z (report.md sha256
# 1a62ca75295dfeb96e9f3e3fa88dc7a6d488eb91fed20007a9ecc82d28b72f56, fixture sha256
# 393e8facd6bcb427790ccb96d39b9466e40376642805c2028790b5ddf2bc86d5): per handwritten setting,
# (grounded of 21, gold hits of 21, median chars read, median wall seconds).
_RECORDED_HANDWRITTEN = {
    "baseline": (16, 8, 12000, 4.6749),
    "c20000_r12": (17, 10, 12000, 4.8523),
    "c60000_r12": (13, 9, 12000, 4.6998),
    "c40000_r8": (14, 10, 12000, 4.745),
    "c40000_r16": (13, 9, 12000, 5.1955),
}


def test_bookstore_defaults_match_recorded_recommendation() -> None:
    """The recorded host numbers retain the baseline, so Bookstore adds no local defaults."""
    rows = _rows({})
    for name, (grounded, hits, chars, wall) in _RECORDED_HANDWRITTEN.items():
        own = [r for r in rows if r["setting"] == name and r["provenance"] == "handwritten"]
        assert len(own) == 21
        for index, row in enumerate(own):
            row.update(grounded=index < grounded, gold_hit=index < hits, chars_read=chars, wall_s=wall)
    rec = ae.select_recommendation(rows)
    assert (rec["status"], rec["setting"], rec["completed_total"]) == ("retain_baseline", "baseline", 140)

    # Retaining the baseline means no promotion: None arguments still reach PageIndex unchanged.
    params = inspect.signature(Bookstore.agentic_retrieve).parameters
    assert all(params[name].default is None for name in ("budget_chars", "max_reads", "timeout_s"))
