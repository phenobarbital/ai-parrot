"""The SDD branch policy follows sdd/config.json; an absent config keeps today's behaviour (TASK-4299)."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.sdd_meta import FlowMeta, emit, parse, parse_taxonomy, resolve_flow
from parrot.sdd.config import SddConfig
from parrot.sdd.scripts import ensure_worktree
from parrot.sdd.scripts.brief_meta import BriefMeta, brief_worktree_plan


def _make_repo(root: Path, config: dict | None) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    if config is not None:
        (root / "sdd").mkdir()
        (root / "sdd" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return root


@pytest.fixture
def foreign_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _make_repo(tmp_path, {"base_branch": "develop", "hotfix_base": "main"})
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _release_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _make_repo(tmp_path, {"base_branch": "develop", "hotfix_base": "release"})
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_resolve_flow_follows_config(foreign_repo: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert resolve_flow(kind="enhancement").base_branch == "develop"
        bug = resolve_flow(kind="bug")
        assert (bug.type, bug.base_branch) == ("hotfix", "main")
        assert resolve_flow().base_branch == "develop"
    assert "canonical branches" not in caplog.text
    with pytest.raises(ValueError):
        FlowMeta(type="hotfix", base_branch="develop", hotfix_base="main")


def test_parse_default_and_explicit_config(foreign_repo: Path) -> None:
    doc = foreign_repo / "d.md"
    doc.write_text("# no frontmatter\n", encoding="utf-8")
    assert parse(doc).base_branch == "develop"
    assert parse(doc, config=SddConfig(base_branch="trunk")).base_branch == "trunk"


def test_hotfix_base_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _release_repo(tmp_path, monkeypatch)
    ok = root / "ok.md"
    ok.write_text("---\ntype: hotfix\nbase_branch: release\n---\n", encoding="utf-8")
    assert parse(ok).base_branch == "release"
    bad = root / "bad.md"
    bad.write_text("---\ntype: hotfix\nbase_branch: main\n---\n", encoding="utf-8")
    with pytest.raises(ValueError):
        parse(bad)


def test_emit_has_no_hotfix_base(foreign_repo: Path) -> None:
    assert "hotfix_base" not in emit(resolve_flow(kind="bug"))


def test_absent_config_is_today(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_repo(tmp_path, None)
    monkeypatch.chdir(tmp_path)
    assert resolve_flow().base_branch == "dev"
    assert emit(resolve_flow(kind="bug")) == "---\ntype: hotfix\nbase_branch: main\n---\n"


def test_taxonomy_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    doc = tmp_path / "d.md"
    doc.write_text("---\nprojects: [billing]\n---\n", encoding="utf-8")
    _make_repo(tmp_path, {"projects": ["billing"]})
    monkeypatch.chdir(tmp_path)
    with caplog.at_level(logging.WARNING):
        assert parse_taxonomy(doc).projects == ["billing"]
    assert "Unknown SDD project" not in caplog.text
    # without a configured list the warning fires and nothing raises
    assert parse_taxonomy(doc, config=SddConfig()).projects == ["billing"]
    assert "Unknown SDD project" in caplog.text


def test_brief_follows_config(foreign_repo: Path) -> None:
    plan = brief_worktree_plan(slug="s", key="K-1", base_branch="develop")
    assert (plan.name, plan.base_ref) == ("fix-K-1-s", "origin/develop")
    data = {
        "kind": "brief",
        "slug": "s",
        "key": "K-1",
        "source": {"type": "ledger", "ref": "x"},
        "created": "2026-10-26",
    }
    cfg = SddConfig(base_branch="develop")
    assert BriefMeta.model_validate({**data, "source": {"type": "text", "ref": "x"}}, context={"sdd_config": cfg}).base_branch == "main"
    with pytest.raises(ValueError):
        BriefMeta.model_validate(data, context={"sdd_config": cfg})  # ledger requires develop, default is main
    assert BriefMeta.model_validate({**data, "base_branch": "develop"}, context={"sdd_config": cfg})


def _dry_run(args: list[str], capsys: pytest.CaptureFixture[str]) -> dict:
    assert ensure_worktree.main([*args, "--dry-run", "--json", "--no-sync"]) == 0
    return json.loads(capsys.readouterr().out)


def test_ensure_worktree_defaults(foreign_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _dry_run(["--slug", "s", "--brief-key", "K"], capsys)["base_ref"] == "origin/main"
    assert _dry_run(["--slug", "s", "--jira-key", "K"], capsys)["base_ref"] == "origin/main"


def test_ensure_worktree_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _release_repo(tmp_path, monkeypatch)
    assert _dry_run(["--slug", "s", "--brief-key", "K"], capsys)["base_ref"] == "origin/release"
    assert _dry_run(["--slug", "s", "--jira-key", "K"], capsys)["base_ref"] == "origin/release"
