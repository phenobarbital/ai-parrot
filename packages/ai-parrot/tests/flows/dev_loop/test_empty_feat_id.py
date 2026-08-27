"""Unit tests for empty ``feat_id`` fallback handling — FEAT-466 / TASK-2503."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from parrot.flows.dev_loop import BugBrief, FlowtaskCriterion, ResearchOutput
from parrot.flows.dev_loop.nodes.base import run_label
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.nodes.development import DevelopmentNode


def _research(**over) -> ResearchOutput:
    base = dict(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-466",
        branch_name="feat-466-x",
        worktree_path="/tmp/wt",
        log_excerpts=[],
    )
    base.update(over)
    return ResearchOutput(**base)


class TestRunLabel:
    def test_prefers_feat_id(self):
        assert run_label(_research()) == "FEAT-466"

    def test_falls_back_to_jira_key(self):
        assert run_label(_research(feat_id="")) == "OPS-1"

    def test_falls_back_to_default(self):
        out = _research(feat_id="", jira_issue_key="")
        assert run_label(out, default="run") == "run"

    def test_strips_whitespace_only_values(self):
        assert run_label(_research(feat_id="   ")) == "OPS-1"


class TestEmptyFeatIdValidates:
    def test_research_output_accepts_empty_feat_id(self):
        """runner.py:1378 already relies on this."""
        assert _research(feat_id="").feat_id == ""


class TestFindFeatureSlug:
    def test_empty_feat_id_returns_none_without_matching(self, tmp_path):
        """An index whose feature_id is literally "" must NOT be matched by
        a hotfix run's empty feat_id."""
        idx = tmp_path / "sdd" / "tasks" / "index"
        idx.mkdir(parents=True)
        (idx / "unrelated.json").write_text(
            json.dumps({"feature_id": "", "feature": "unrelated"})
        )
        assert DevelopmentNode._find_feature_slug(str(tmp_path), "") is None

    def test_matching_feat_id_still_resolves(self, tmp_path):
        idx = tmp_path / "sdd" / "tasks" / "index"
        idx.mkdir(parents=True)
        (idx / "x.json").write_text(
            json.dumps(
                {"feature_id": "FEAT-466", "feature": "dev-loop-run-fidelity"}
            )
        )
        got = DevelopmentNode._find_feature_slug(str(tmp_path), "FEAT-466")
        assert got == "dev-loop-run-fidelity"


def _build_node(jira, **kwargs) -> DeploymentHandoffNode:
    return DeploymentHandoffNode(jira_toolkit=jira, **kwargs)


def _bug_brief() -> BugBrief:
    return BugBrief(
        summary="replace SHA-1 with SHA-256",
        affected_component="arango/store.py",
        log_sources=[],
        acceptance_criteria=[
            FlowtaskCriterion(name="run", task_path="x.yaml"),
        ],
        escalation_assignee="a",
        reporter="b",
    )


class TestPrTitle:
    def test_title_uses_jira_key_when_no_feat_id(self):
        node = _build_node(MagicMock())
        title = node._build_title(
            _bug_brief(), _research(feat_id="", jira_issue_key="OPS-1")
        )
        assert title.startswith("OPS-1:")
        assert "sha-256" in title.lower()

    def test_title_has_no_dangling_colon_when_both_empty(self):
        node = _build_node(MagicMock())
        title = node._build_title(
            _bug_brief(), _research(feat_id="", jira_issue_key="")
        )
        assert not title.startswith(":")
        assert "sha-256" in title.lower()

    def test_title_unchanged_when_feat_id_present(self):
        node = _build_node(MagicMock())
        title = node._build_title(_bug_brief(), _research())
        assert title.startswith("FEAT-466:")
