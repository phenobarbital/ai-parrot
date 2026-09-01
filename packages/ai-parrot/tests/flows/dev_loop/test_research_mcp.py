"""Unit tests for ResearchNode's explicit-MCP seam (FEAT-484/485 wiring).

Mirrors ``test_research_partner_seam.py``'s fixture shape (mocked Jira
toolkit + mocked dispatcher). The seam contract: with ``mcp_servers`` unset
the ``sdd-research`` dispatch profile is byte-identical to pre-seam
behavior; with servers set, the profile carries them plus the matching
``mcp__...`` allow rules (derived server-level, or the caller's explicit
``mcp_tools``).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.flows.dev_loop import (
    BugBrief,
    FlowtaskCriterion,
    ResearchOutput,
    ShellCriterion,
)
from parrot.flows.dev_loop.nodes.research import ResearchNode

_SERVERS = {
    "wikitoolkit": {"command": "/x/wikitoolkit", "args": ["mcp"], "env": {}},
    "parrot-repo": {"command": "/x/parrot", "args": ["mcp-local", "repo"], "env": {}},
}

_LEGACY_ALLOWED = ["Read", "Grep", "Glob", "Bash", "Write", "SlashCommand"]


@pytest.fixture
def good_brief() -> BugBrief:
    return BugBrief(
        summary="customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[
            FlowtaskCriterion(name="run", task_path="etl/customers/sync.yaml"),
            ShellCriterion(name="lint", command="ruff check ."),
        ],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


@pytest.fixture
def research_out_fixture(tmp_path) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix-customer-sync",
        worktree_path=str(tmp_path / "feat-130-fix-customer-sync"),
        log_excerpts=[],
    )


def _make_jira() -> MagicMock:
    jira = MagicMock()
    jira.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    jira.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    jira.jira_search_issues = AsyncMock(return_value={"status": "empty"})
    jira.jira_get_issue = AsyncMock(return_value={"status": "error"})
    jira.jira_find_user = AsyncMock(
        return_value={
            "found": True,
            "matches": [{"accountId": "557058:resolved", "emailAddress": "reporter@example.com"}],
        }
    )
    return jira


def _make_node(research_out_fixture, monkeypatch, tmp_path, **node_kwargs):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=research_out_fixture)
    node = ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=_make_jira(),
        log_toolkits={},
        **node_kwargs,
    )
    return node, dispatcher


class TestResearchMcpSeam:
    async def test_default_profile_byte_identical(self, good_brief, research_out_fixture, monkeypatch, tmp_path):
        """GUARD: no mcp kwargs => the exact legacy profile."""
        node, dispatcher = _make_node(research_out_fixture, monkeypatch, tmp_path)

        await node.execute(ctx={"run_id": "r1", "bug_brief": good_brief})

        profile = dispatcher.dispatch.call_args.kwargs["profile"]
        assert profile.mcp_servers is None
        assert profile.allowed_tools == _LEGACY_ALLOWED
        assert profile.strict_mcp_config is True

    async def test_servers_reach_profile_with_derived_rules(
        self, good_brief, research_out_fixture, monkeypatch, tmp_path
    ):
        node, dispatcher = _make_node(research_out_fixture, monkeypatch, tmp_path, mcp_servers=dict(_SERVERS))

        await node.execute(ctx={"run_id": "r1", "bug_brief": good_brief})

        profile = dispatcher.dispatch.call_args.kwargs["profile"]
        assert profile.mcp_servers == _SERVERS
        assert profile.allowed_tools == [
            *_LEGACY_ALLOWED,
            "mcp__parrot-repo",
            "mcp__wikitoolkit",
        ]
        # Isolation guard holds: explicit servers, not inherited .mcp.json.
        assert profile.strict_mcp_config is True

    async def test_explicit_mcp_tools_win_over_derivation(
        self, good_brief, research_out_fixture, monkeypatch, tmp_path
    ):
        explicit = ["mcp__wikitoolkit__wiki_query", "mcp__parrot-repo__read_file"]
        node, dispatcher = _make_node(
            research_out_fixture,
            monkeypatch,
            tmp_path,
            mcp_servers=dict(_SERVERS),
            mcp_tools=explicit,
        )

        await node.execute(ctx={"run_id": "r1", "bug_brief": good_brief})

        profile = dispatcher.dispatch.call_args.kwargs["profile"]
        assert profile.allowed_tools == [*_LEGACY_ALLOWED, *explicit]

    async def test_mcp_tools_ignored_without_servers(self, good_brief, research_out_fixture, monkeypatch, tmp_path):
        node, dispatcher = _make_node(
            research_out_fixture,
            monkeypatch,
            tmp_path,
            mcp_tools=["mcp__ghost"],
        )

        await node.execute(ctx={"run_id": "r1", "bug_brief": good_brief})

        profile = dispatcher.dispatch.call_args.kwargs["profile"]
        assert profile.mcp_servers is None
        assert profile.allowed_tools == _LEGACY_ALLOWED
