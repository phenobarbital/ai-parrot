"""Unit tests for the console flow-type/base-branch override — FEAT-466 /
TASK-2508."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.models.base import (
    FlowtaskCriterion,
    ResearchOutput,
    WorkBrief,
)
from parrot.flows.dev_loop.nodes.research import ResearchNode


def _brief(**over) -> WorkBrief:
    base = dict(
        kind="bug",
        summary="something broke badly",
        affected_component="x",
        log_sources=[],
        acceptance_criteria=[FlowtaskCriterion(name="run", task_path="x.yaml")],
        escalation_assignee="a",
        reporter="b",
    )
    base.update(over)
    return WorkBrief(**base)


class TestBriefFields:
    def test_defaults_are_none(self):
        b = _brief()
        assert b.flow_type is None and b.base_branch is None

    def test_legacy_brief_still_validates(self):
        """Regression guard — every existing caller omits both fields."""
        assert _brief().kind == "bug"

    def test_flow_type_is_a_closed_set(self):
        with pytest.raises(ValidationError):
            _brief(flow_type="hotfixx")

    def test_base_branch_is_open(self):
        """Sub-feature branches are legal bases (CLAUDE.md)."""
        assert _brief(base_branch="feat/parent").base_branch == "feat/parent"

    def test_fields_survive_json_round_trip(self):
        """The dispatcher sends brief.model_dump_json() to the subagent."""
        data = json.loads(_brief(flow_type="feature", base_branch="dev").model_dump_json())
        assert data["flow_type"] == "feature"
        assert data["base_branch"] == "dev"


def _spec(worktree_path: Path, *, type_: str = "hotfix", base: str = "main") -> Path:
    d = worktree_path / "sdd" / "specs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "x.spec.md"
    p.write_text(f"---\ntype: {type_}\nbase_branch: {base}\n---\n# Spec\n")
    return p


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
    empty_base = tmp_path / "wtbase"
    empty_base.mkdir()
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(empty_base),
    )


@pytest.mark.asyncio
class TestOverrideReachesResolution:
    async def test_bug_with_dev_override_resolves_to_dev(self, tmp_path, monkeypatch):
        """PR #1250's motivating case: a `kind='bug'` run whose spec defaults
        to hotfix/main, but the operator overrides the base branch to dev."""
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
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dispatch_out)
        node = _build_node(dispatcher)

        result = await node.execute({"bug_brief": _brief(base_branch="dev"), "run_id": "r1"})

        assert result.base_branch == "dev"

    async def test_empty_base_branch_is_not_an_override(self, tmp_path, monkeypatch):
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
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dispatch_out)
        node = _build_node(dispatcher)

        # No override supplied (default None) -> spec frontmatter wins.
        result = await node.execute({"bug_brief": _brief(), "run_id": "r1"})

        assert result.base_branch == "main"

    async def test_hotfix_off_main_override_reaches_output_verbatim(self, tmp_path, monkeypatch):
        """_resolve_base_branch itself does not validate hotfix/main — it
        just records the requested base branch; the FlowMeta-style
        validation lives at the SDD-command layer (TASK-2507) and the
        sibling-overlap guard (TASK-2505), not here."""
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
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dispatch_out)
        node = _build_node(dispatcher)

        result = await node.execute({"bug_brief": _brief(base_branch="dev"), "run_id": "r1"})

        assert result.base_branch == "dev"


class TestServerPayloadParsing:
    """Import the payload helper from examples/dev_loop/server.py and feed
    it dicts directly."""

    def _load_server_module(self):
        """Load examples/dev_loop/server.py via importlib without package
        import — mirrors test_examples_form.py's ``_load_server``.

        Test file is at:
            packages/ai-parrot/tests/flows/dev_loop/test_flow_type_override.py
        ``parents[5]`` resolves to the repository root, then examples/
        lives at: ``<repo_root>/examples/dev_loop/server.py``
        """
        import importlib.util
        from pathlib import Path as _Path

        server_path = _Path(__file__).resolve().parents[5] / "examples" / "dev_loop" / "server.py"
        spec = importlib.util.spec_from_file_location("dev_loop_example_server", server_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_invalid_flow_type_is_omitted(self):
        server = self._load_server_module()
        payload: dict = {}
        server._apply_flow_override(payload, {"flow_type": "hotfixx", "base_branch": ""})
        assert "flow_type" not in payload

    def test_auto_never_reaches_the_payload(self):
        server = self._load_server_module()
        payload: dict = {}
        server._apply_flow_override(payload, {"flow_type": "", "base_branch": ""})
        assert "flow_type" not in payload
        assert "base_branch" not in payload

    def test_valid_values_are_applied(self):
        server = self._load_server_module()
        payload: dict = {}
        server._apply_flow_override(payload, {"flow_type": "hotfix", "base_branch": "main"})
        assert payload["flow_type"] == "hotfix"
        assert payload["base_branch"] == "main"
