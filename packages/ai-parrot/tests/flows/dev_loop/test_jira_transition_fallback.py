"""Regression tests for the workflow-agnostic Jira transition helper.

Covers the dev-loop bugfix where nodes hard-coded transition labels
(``"Ready to Deploy"`` / ``"Deployment Blocked"`` / ``"In Review – revised"``)
that don't exist in every Jira project's workflow. The helper now tries an
ordered list of candidate labels and applies the first the workflow exposes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import pytest

from parrot.flows.dev_loop.nodes.base import transition_issue_with_candidates


_LOG = logging.getLogger("test.jira_transition_fallback")


class _FakeJira:
    """Jira double whose transition resolves only a known label set.

    Mirrors ``JiraToolkit.jira_transition_issue``: a non-matching label raises
    ``ValueError`` (the real toolkit lists available transitions in the
    message); a matching one returns the post-transition issue envelope.
    """

    def __init__(self, available: List[str]) -> None:
        self._available = {a.lower() for a in available}
        self.calls: List[str] = []

    async def jira_transition_issue(
        self, *, issue: str, transition: str, **kwargs: Any
    ) -> Dict[str, Any]:
        self.calls.append(transition)
        if transition.lower() not in self._available:
            raise ValueError(f"Invalid transition '{transition}' for issue {issue}.")
        return {"ok": True, "issue": issue, "applied": transition, "kwargs": kwargs}


@pytest.mark.asyncio
async def test_falls_back_to_second_candidate():
    # Workflow exposes only "Resolve Issue" — the dev-loop's preferred
    # "Ready to Deploy" must fall through to it.
    jira = _FakeJira(available=["Resolve Issue"])
    result = await transition_issue_with_candidates(
        jira, "NAV-1", ["Ready to Deploy", "Resolve Issue", "Done"], logger=_LOG
    )
    assert result is not None and result["applied"] == "Resolve Issue"
    assert jira.calls == ["Ready to Deploy", "Resolve Issue"]


@pytest.mark.asyncio
async def test_returns_none_when_no_candidate_matches():
    jira = _FakeJira(available=["Backlog"])
    result = await transition_issue_with_candidates(
        jira, "NAV-1", ["Ready to Deploy", "Resolved"], logger=_LOG
    )
    assert result is None
    assert jira.calls == ["Ready to Deploy", "Resolved"]


@pytest.mark.asyncio
async def test_first_candidate_short_circuits_and_forwards_kwargs():
    jira = _FakeJira(available=["Ready to Deploy", "Resolved"])
    result = await transition_issue_with_candidates(
        jira,
        "NAV-1",
        ["Ready to Deploy", "Resolved"],
        logger=_LOG,
        resolution="Fixed",
    )
    assert result is not None and result["applied"] == "Ready to Deploy"
    assert result["kwargs"] == {"resolution": "Fixed"}
    assert jira.calls == ["Ready to Deploy"]  # second candidate never tried


@pytest.mark.asyncio
async def test_non_value_error_propagates():
    class _Boom:
        async def jira_transition_issue(self, **_kw: Any) -> Dict[str, Any]:
            raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        await transition_issue_with_candidates(
            _Boom(), "NAV-1", ["X"], logger=_LOG
        )


@pytest.mark.asyncio
async def test_empty_candidate_labels_skipped():
    jira = _FakeJira(available=["Resolved"])
    result = await transition_issue_with_candidates(
        jira, "NAV-1", ["", "Resolved"], logger=_LOG
    )
    assert result is not None and result["applied"] == "Resolved"
    assert jira.calls == ["Resolved"]
