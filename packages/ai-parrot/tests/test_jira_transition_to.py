"""Tests for JiraToolkit.jira_transition_to — the workflow-path walker.

Jira only exposes the transitions available from an issue's *current* status,
so reaching a status several hops away (e.g. Backlog → Open → To Do →
In Progress → Resolved in a custom workflow) requires walking a *declared*
path. These tests cover the path parsing, project resolution, hop computation,
and the multi-hop walk (including kwargs applied only on the final hop and the
zero-config single-hop fallback).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def make_toolkit():
    """Factory building a JiraToolkit with a mocked JIRA client.

    Accepts ``env`` (extra environment) and ``workflow_paths`` kwargs so each
    test can declare its own workflow configuration.
    """
    pytest.importorskip("jira")
    from parrot.tools.jiratoolkit import JiraToolkit

    def _build(env=None, **kwargs):
        import os
        # Hermetic: drop any real JIRA_WORKFLOW_PATH* vars the host shell or
        # navconfig (env/.env) injected, so the test owns the full config.
        clean = {
            k: v for k, v in os.environ.items()
            if not k.startswith("JIRA_WORKFLOW_PATH")
        }
        clean.update(env or {})
        with patch("parrot.tools.jiratoolkit.JIRA") as mock_jira, \
                patch.dict("os.environ", clean, clear=True):
            mock_jira.return_value = MagicMock()
            return JiraToolkit(
                server_url="https://test.atlassian.net",
                auth_type="basic_auth",
                username="u@example.com",
                password="tok",
                **kwargs,
            )

    return _build


# ── pure helpers ──────────────────────────────────────────────────────────


def test_parse_workflow_path_separators(make_toolkit):
    tk = make_toolkit()
    assert tk._parse_workflow_path("Backlog > Open > Resolved") == [
        "Backlog", "Open", "Resolved",
    ]
    assert tk._parse_workflow_path("A -> B -> C") == ["A", "B", "C"]
    assert tk._parse_workflow_path("A → B → C") == ["A", "B", "C"]
    assert tk._parse_workflow_path("  Solo  ") == ["Solo"]


def test_project_of():
    from parrot.tools.jiratoolkit import JiraToolkit
    assert JiraToolkit._project_of("NAV-8350") == "NAV"
    assert JiraToolkit._project_of("troc-12") == "TROC"
    assert JiraToolkit._project_of("nokey") is None


def test_path_steps_forward_and_backward():
    from parrot.tools.jiratoolkit import JiraToolkit
    path = ["Backlog", "Open", "To Do", "In Progress", "Resolved"]
    assert JiraToolkit._path_steps(path, "Backlog", "Resolved") == [
        "Open", "To Do", "In Progress", "Resolved",
    ]
    assert JiraToolkit._path_steps(path, "in progress", "open") == [
        "To Do", "Open",
    ]
    assert JiraToolkit._path_steps(path, "Open", "Open") == []
    # Endpoint not on the path → None (caller falls back to a single hop).
    assert JiraToolkit._path_steps(path, "Open", "Cancelled") is None


# ── config resolution ─────────────────────────────────────────────────────


def test_per_project_env_overrides_default(make_toolkit):
    tk = make_toolkit(env={
        "JIRA_WORKFLOW_PATH": "Open > Done",
        "JIRA_WORKFLOW_PATH_TROC": "Backlog > Open > In Progress > Resolved",
    })
    assert tk._workflow_path_for("TROC-1") == [
        "Backlog", "Open", "In Progress", "Resolved",
    ]
    # A project with no specific path uses the default.
    assert tk._workflow_path_for("NAV-9") == ["Open", "Done"]


def test_constructor_workflow_paths(make_toolkit):
    tk = make_toolkit(workflow_paths={
        "TROC": "Backlog > Open > Resolved",
        "": ["Open", "Done"],  # default
    })
    assert tk._workflow_path_for("TROC-5") == ["Backlog", "Open", "Resolved"]
    assert tk._workflow_path_for("ZZZ-1") == ["Open", "Done"]


# ── the walk ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_walks_full_path_applying_kwargs_on_final_hop(make_toolkit):
    tk = make_toolkit(env={
        "JIRA_WORKFLOW_PATH_TROC": "Backlog > Open > To Do > In Progress > Resolved",
    })
    tk._current_status = AsyncMock(return_value="Backlog")
    tk.jira_transition_issue = AsyncMock(return_value={"ok": True})

    await tk.jira_transition_to(
        "TROC-1", "Resolved", resolution={"id": "3"},
    )

    calls = tk.jira_transition_issue.await_args_list
    # Four hops, in order; only the final carries the resolution kwarg.
    assert [c.args[1] for c in calls] == [
        "Open", "To Do", "In Progress", "Resolved",
    ]
    for c in calls[:-1]:
        assert c.kwargs == {}
    assert calls[-1].kwargs == {
        "fields": None, "assignee": None, "resolution": {"id": "3"},
    }


@pytest.mark.asyncio
async def test_noop_when_already_in_target(make_toolkit):
    tk = make_toolkit(env={"JIRA_WORKFLOW_PATH_TROC": "Backlog > Open > Resolved"})
    tk._current_status = AsyncMock(return_value="Resolved")
    tk.jira_transition_issue = AsyncMock()
    tk.jira_get_issue = AsyncMock(return_value={"status": "ok"})

    await tk.jira_transition_to("TROC-1", "resolved")

    tk.jira_transition_issue.assert_not_awaited()
    tk.jira_get_issue.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_path_falls_back_to_single_hop(make_toolkit):
    tk = make_toolkit()  # no workflow path declared
    tk._current_status = AsyncMock(return_value="Backlog")
    tk.jira_transition_issue = AsyncMock(return_value={"ok": True})

    await tk.jira_transition_to("NAV-1", "Done", resolution={"id": "1"})

    tk.jira_transition_issue.assert_awaited_once_with(
        "NAV-1", "Done", fields=None, assignee=None, resolution={"id": "1"},
    )


@pytest.mark.asyncio
async def test_stalled_hop_raises_clear_error(make_toolkit):
    tk = make_toolkit(env={"JIRA_WORKFLOW_PATH_TROC": "Backlog > Open > Resolved"})
    tk._current_status = AsyncMock(return_value="Backlog")
    # First hop (Open) works, second (Resolved) is not actually available.
    tk.jira_transition_issue = AsyncMock(
        side_effect=[{"ok": True}, ValueError("Invalid transition 'Resolved'")]
    )

    with pytest.raises(ValueError, match="stalled at hop 2/2"):
        await tk.jira_transition_to("TROC-1", "Resolved")
