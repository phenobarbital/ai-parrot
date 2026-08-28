"""Unit tests for ``ResearchOutput.base_branch`` — FEAT-466 / TASK-2504."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import BugBrief, FlowtaskCriterion, ResearchOutput
from parrot.flows.dev_loop.nodes.research import ResearchNode


def _spec(worktree_path: Path, *, type_: str = "hotfix", base: str = "main") -> Path:
    d = worktree_path / "sdd" / "specs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "x.spec.md"
    p.write_text(f"---\ntype: {type_}\nbase_branch: {base}\n---\n# Spec\n")
    return p


class TestModelField:
    def test_defaults_to_empty(self):
        out = ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="sdd/specs/x.spec.md",
            feat_id="FEAT-466",
            branch_name="b",
            worktree_path="/tmp/wt",
        )
        assert out.base_branch == ""

    def test_accepts_base_alias(self):
        out = ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="s",
            feat_id="F",
            branch_name="b",
            worktree_path="/w",
            base="main",
        )
        assert out.base_branch == "main"


def _brief(**over) -> BugBrief:
    base = dict(
        summary="replace SHA-1 with SHA-256",
        affected_component="arango/store.py",
        log_sources=[],
        acceptance_criteria=[
            FlowtaskCriterion(name="run", task_path="x.yaml"),
        ],
        escalation_assignee="a",
        reporter="b",
    )
    base.update(over)
    return BugBrief(**base)


def _build_node(dispatcher, jira=None, **kwargs) -> ResearchNode:
    jira = jira or MagicMock()
    jira.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    jira.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    jira.jira_search_issues = AsyncMock(return_value={"status": "empty"})
    jira.jira_get_issue = AsyncMock(return_value={"status": "error"})
    jira.jira_find_user = AsyncMock(return_value={"found": False, "matches": []})
    return ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
        **kwargs,
    )


def _pin_worktree_base(monkeypatch, tmp_path: Path) -> None:
    """Point WORKTREE_BASE_PATH at an empty sibling dir so
    ``_ensure_worktree_safe`` sees no path collision (it joins
    WORKTREE_BASE_PATH/branch_name) and returns False immediately —
    tests here exercise ``_resolve_base_branch``, not worktree reuse."""
    empty_base = tmp_path / "wtbase"
    empty_base.mkdir()
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(empty_base),
    )


@pytest.mark.asyncio
class TestResolveBaseBranch:
    async def test_spec_frontmatter_is_authoritative(self, tmp_path, monkeypatch):
        """Spec says hotfix/main; subagent claims dev. Spec must win."""
        _pin_worktree_base(monkeypatch, tmp_path)
        worktree = tmp_path / "actual" / "hotfix-ops-1-x"
        worktree.mkdir(parents=True)
        _spec(worktree, type_="hotfix", base="main")

        dispatch_out = ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="sdd/specs/x.spec.md",
            feat_id="",
            branch_name="hotfix-ops-1-x",
            worktree_path=str(worktree),
            base_branch="dev",
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dispatch_out)
        node = _build_node(dispatcher)

        result = await node.execute({"bug_brief": _brief(), "run_id": "r1"})

        assert result.base_branch == "main"

    async def test_warns_on_disagreement(self, tmp_path, monkeypatch, caplog):
        _pin_worktree_base(monkeypatch, tmp_path)
        worktree = tmp_path / "actual" / "hotfix-ops-1-x"
        worktree.mkdir(parents=True)
        _spec(worktree, type_="hotfix", base="main")

        dispatch_out = ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="sdd/specs/x.spec.md",
            feat_id="",
            branch_name="hotfix-ops-1-x",
            worktree_path=str(worktree),
            base_branch="dev",
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dispatch_out)
        node = _build_node(dispatcher)

        with caplog.at_level("WARNING"):
            await node.execute({"bug_brief": _brief(), "run_id": "r1"})

        assert "reported base_branch" in caplog.text

    async def test_relative_spec_path_resolved_against_worktree(self, tmp_path, monkeypatch):
        _pin_worktree_base(monkeypatch, tmp_path)
        worktree = tmp_path / "actual" / "feat-466-x"
        worktree.mkdir(parents=True)
        _spec(worktree, type_="feature", base="dev")

        dispatch_out = ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="sdd/specs/x.spec.md",  # relative
            feat_id="FEAT-466",
            branch_name="feat-466-x",
            worktree_path=str(worktree),
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dispatch_out)
        node = _build_node(dispatcher)

        result = await node.execute({"bug_brief": _brief(), "run_id": "r1"})

        assert result.base_branch == "dev"

    async def test_missing_spec_falls_back_to_kind_mapping(self, tmp_path, monkeypatch, caplog):
        """No spec file at all -> kind='bug' -> 'main', with a WARNING."""
        _pin_worktree_base(monkeypatch, tmp_path)
        worktree = tmp_path / "actual" / "hotfix-ops-1-x"
        worktree.mkdir(parents=True)
        # No sdd/specs/x.spec.md written.

        dispatch_out = ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="sdd/specs/x.spec.md",
            feat_id="",
            branch_name="hotfix-ops-1-x",
            worktree_path=str(worktree),
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dispatch_out)
        node = _build_node(dispatcher)

        with caplog.at_level("WARNING"):
            result = await node.execute({"bug_brief": _brief(), "run_id": "r1"})

        assert result.base_branch == "main"
        assert "falling back to the kind mapping" in caplog.text

    async def test_never_empty_after_execute(self, tmp_path, monkeypatch):
        _pin_worktree_base(monkeypatch, tmp_path)
        worktree = tmp_path / "actual" / "feat-466-x"
        worktree.mkdir(parents=True)
        # No spec written either -> falls back to kind mapping.

        dispatch_out = ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="sdd/specs/x.spec.md",
            feat_id="FEAT-466",
            branch_name="feat-466-x",
            worktree_path=str(worktree),
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dispatch_out)
        node = _build_node(dispatcher)

        result = await node.execute({"bug_brief": _brief(), "run_id": "r1"})

        assert result.base_branch != ""
