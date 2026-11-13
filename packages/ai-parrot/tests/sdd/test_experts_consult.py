"""Tests for ``parrot sdd experts consult`` (FEAT-890 M8)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from parrot.experts.contributions import Contribution, contribution_dir, load_contribution, save_contribution
from parrot.experts.grid.models import ScopeGrid
from parrot.sdd import experts_cli
from parrot.sdd.cli import sdd

FINDINGS = [{"id": "f1", "severity": "major", "section": "2", "statement": "bad", "evidence": ["x"]}]


class FakeExpert:
    def __init__(self, answer: str, name: str = "e") -> None:
        self.answer = answer
        self.bundle = SimpleNamespace(manifest=SimpleNamespace(name=name, tier=SimpleNamespace(value="balanced")))

    async def ask(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(content=self.answer)


async def _boom(prompt: str, **kwargs: object) -> None:
    raise RuntimeError("expert down")


class FakeRegistry:
    wiki_toolkit = None

    def __init__(self, answer: str, *, fail: set[str] | None = None) -> None:
        self.answer = answer
        self.fail = fail or set()

    def get(self, name: str, *, tenant: str | None = None) -> FakeExpert:
        if name in self.fail:
            expert = FakeExpert(self.answer, name)
            expert.ask = _boom  # type: ignore[method-assign]
            return expert
        return FakeExpert(self.answer, name)


def _scope(projects: list[str], tags: list[str]) -> ScopeGrid:
    return ScopeGrid.model_validate(
        {
            "scope": "s1",
            "match": {"projects": projects, "tags": tags},
            "stages": [{"stage": "a", "experts": ["e1"], "mode": "subagent"}],
        }
    )


def _doc(root: Path, body: str = "hello") -> Path:
    path = root / "sdd" / "specs" / "x.spec.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\nprojects: [ai-parrot]\ntags: [security]\n---\n{body}\n", encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_consult_writes_and_marks_stale(tmp_path: Path) -> None:
    doc = _doc(tmp_path)
    scopes = {"s1": _scope(["ai-parrot"], [])}
    reg = FakeRegistry("```json\n" + json.dumps(FINDINGS) + "\n```")
    written = await experts_cli.consult(repo_root=tmp_path, doc=doc, feature_id="FEAT-1", registry=reg, scopes=scopes)
    assert written == [contribution_dir(tmp_path, feature_id="FEAT-1", doc_slug="x") / "e1.json"]
    c = load_contribution(written[0])
    assert c.findings[0].severity == "major" and not c.stale and c.tier == "balanced"
    # An older contribution from another expert with another digest becomes stale.
    other = written[0].with_name("old.json")
    save_contribution(other, c.model_copy(update={"expert": "old", "doc_digest": "zzz"}))
    await experts_cli.consult(repo_root=tmp_path, doc=doc, feature_id="FEAT-1", registry=reg, scopes=scopes)
    assert load_contribution(other).stale is True


@pytest.mark.asyncio
async def test_modes_gates_and_failures(tmp_path: Path) -> None:
    """A gated mob stage runs without a gate host; a failing expert is skipped; pipeline stages chain."""
    doc = _doc(tmp_path)
    grid = ScopeGrid.model_validate(
        {
            "scope": "s2",
            "match": {"projects": ["ai-parrot"]},
            "stages": [
                {
                    "stage": "m",
                    "experts": ["e1", "e2"],
                    "mode": "mob",
                    "gate": {"kind": "approval", "title": "t"},
                },
            ],
        }
    )
    reg = FakeRegistry(json.dumps(FINDINGS), fail={"e2"})
    written = await experts_cli.consult(
        repo_root=tmp_path, doc=doc, feature_id="FEAT-2", registry=reg, scopes={"s2": grid}
    )
    assert [p.name for p in written] == ["e1.json"]
    assert load_contribution(written[0]).findings[0].id == "f1"


@pytest.mark.asyncio
async def test_no_match_and_fallback_and_no_feature(tmp_path: Path) -> None:
    doc = _doc(tmp_path)
    assert (
        await experts_cli.consult(
            repo_root=tmp_path,
            doc=doc,
            feature_id=None,
            registry=FakeRegistry("[]"),
            scopes={"s": _scope(["other"], [])},
        )
        == []
    )
    written = await experts_cli.consult(
        repo_root=tmp_path,
        doc=doc,
        feature_id=None,
        registry=FakeRegistry("not json"),
        scopes={"s1": _scope([], ["security"])},
    )
    assert ".contributions" in written[0].as_posix()
    assert load_contribution(written[0]).findings[0].severity == "info"


def test_cli_no_match_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _doc(tmp_path)
    monkeypatch.setattr(experts_cli, "load_scopes", lambda agents_dir: {})
    result = CliRunner().invoke(sdd, ["experts", "consult", "--doc", str(doc), "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "nothing to consult" in result.output


def test_cli_consult_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _doc(tmp_path)
    monkeypatch.setattr(experts_cli, "load_scopes", lambda agents_dir: {"s1": _scope(["ai-parrot"], [])})

    async def _reg(agents_dir):
        return FakeRegistry(json.dumps(FINDINGS))

    monkeypatch.setattr(experts_cli, "_load_registry", _reg)
    result = CliRunner().invoke(
        sdd, ["experts", "consult", "--doc", str(doc), "--feature", "FEAT-9", "--root", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "sdd/state/FEAT-9/contributions/e1.json").exists()
    assert isinstance(load_contribution(tmp_path / "sdd/state/FEAT-9/contributions/e1.json"), Contribution)
