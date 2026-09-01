"""Unit tests for ``ComplementaryResearchCoordinator`` (FEAT-482 Module 4).

Covers every degradation path (disabled, timeout, parse failure, empty
findings, commit failure) plus the success path's artifact write.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from parrot import conf
from parrot.flows.dev_flow.complementary_research import (
    ComplementaryResearchCoordinator,
)
from parrot.flows.dev_flow.research_partner import ResearchFinding, ResearchFindings
from pydantic import BaseModel

MODULE = "parrot.flows.dev_flow.complementary_research"


class _FakeBrief(BaseModel):
    title: str = "fake"


class _FakePartner:
    """Stand-in for a research partner — configurable behavior per test."""

    def __init__(self, findings=None, error=None, delay: float = 0.0):
        self._findings = findings
        self._error = error
        self._delay = delay

    async def research(self, **kwargs):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return self._findings


def _rich_findings() -> ResearchFindings:
    return ResearchFindings(
        summary="Found a relevant precedent.",
        findings=[
            ResearchFinding(
                id="F1",
                title="Existing pattern",
                detail="See module X for the established approach.",
                evidence=["module_x.py:42"],
                confidence="high",
            )
        ],
        options_considered=["Option A", "Option B"],
        could_not_determine=["Whether Y is still supported"],
        sources_examined=["module_x.py"],
    )


@pytest.fixture(autouse=True)
def _reset_timeout():
    """Restore the real timeout value after tests that monkeypatch it."""
    original = conf.DEV_FLOW_RESEARCH_PARTNER_TIMEOUT
    yield
    conf.DEV_FLOW_RESEARCH_PARTNER_TIMEOUT = original


class TestComplementaryResearchCoordinator:
    async def test_returns_none_when_disabled(self, tmp_path):
        """No partner constructed, no work performed."""
        coordinator = ComplementaryResearchCoordinator()
        with (
            patch(f"{MODULE}.resolve_research_partner_backend", return_value=""),
            patch(f"{MODULE}.ResearchPartnerFactory") as mock_factory,
        ):
            result = await coordinator.research(
                brief=_FakeBrief(),
                question="q",
                cwd=str(tmp_path),
                slug="my-feature",
                run_id="r",
                node_id="n",
            )
        assert result is None
        mock_factory.create.assert_not_called()

    async def test_soft_degrades_on_timeout(self, tmp_path):
        """Returns None, emits partner.degraded, does not raise."""
        conf.DEV_FLOW_RESEARCH_PARTNER_TIMEOUT = 0.01
        partner = _FakePartner(delay=1.0)
        coordinator = ComplementaryResearchCoordinator()
        with (
            patch(f"{MODULE}.resolve_research_partner_backend", return_value="gpt"),
            patch(f"{MODULE}.ResearchPartnerFactory.create", return_value=partner),
            patch.object(coordinator, "_emit") as mock_emit,
        ):
            result = await coordinator.research(
                brief=_FakeBrief(),
                question="q",
                cwd=str(tmp_path),
                slug="my-feature",
                run_id="r",
                node_id="n",
            )
        assert result is None
        degraded_events = [c for c in mock_emit.call_args_list if c.args[0] == "partner.degraded"]
        assert len(degraded_events) == 1

    async def test_soft_degrades_on_parse_failure(self, tmp_path):
        """Invalid structured output => None (NOT a fabricated passing result)."""
        partner = _FakePartner(error=ValueError("no valid ResearchFindings"))
        coordinator = ComplementaryResearchCoordinator()
        with (
            patch(f"{MODULE}.resolve_research_partner_backend", return_value="gpt"),
            patch(f"{MODULE}.ResearchPartnerFactory.create", return_value=partner),
        ):
            result = await coordinator.research(
                brief=_FakeBrief(),
                question="q",
                cwd=str(tmp_path),
                slug="my-feature",
                run_id="r",
                node_id="n",
            )
        assert result is None

    async def test_soft_degrades_on_credential_error(self, tmp_path):
        """Any infra exception (auth, outage) also degrades to None."""
        partner = _FakePartner(error=RuntimeError("Bedrock outage"))
        coordinator = ComplementaryResearchCoordinator()
        with (
            patch(f"{MODULE}.resolve_research_partner_backend", return_value="nova"),
            patch(f"{MODULE}.ResearchPartnerFactory.create", return_value=partner),
        ):
            result = await coordinator.research(
                brief=_FakeBrief(),
                question="q",
                cwd=str(tmp_path),
                slug="my-feature",
                run_id="r",
                node_id="n",
            )
        assert result is None

    async def test_writes_research_md_staging_only_that_path(self, tmp_path):
        """Artifact committed; `git add` receives exactly one path."""
        partner = _FakePartner(findings=_rich_findings())
        coordinator = ComplementaryResearchCoordinator()
        git_calls = []

        async def fake_run_git(repo_root, *args):
            git_calls.append(args)

        with (
            patch(f"{MODULE}.resolve_research_partner_backend", return_value="gpt"),
            patch(f"{MODULE}.ResearchPartnerFactory.create", return_value=partner),
            patch.object(ComplementaryResearchCoordinator, "_run_git", staticmethod(fake_run_git)),
        ):
            result = await coordinator.research(
                brief=_FakeBrief(),
                question="q",
                cwd=str(tmp_path),
                slug="my-feature",
                run_id="r",
                node_id="n",
            )

        assert result is not None
        assert result.document_path == "sdd/proposals/my-feature.research.md"
        written = tmp_path / "sdd" / "proposals" / "my-feature.research.md"
        assert written.exists()
        assert "Found a relevant precedent." in written.read_text()

        add_call = next(c for c in git_calls if c[0] == "add")
        # Exactly one path argument after "add --" — never "-A" or ".".
        assert add_call == ("add", "--", "sdd/proposals/my-feature.research.md")
        commit_call = next(c for c in git_calls if c[0] == "commit")
        assert commit_call[-1] == "sdd/proposals/my-feature.research.md"
        assert "-A" not in commit_call
        assert "." not in commit_call

    async def test_empty_findings_treated_as_absent(self, tmp_path):
        """Trivial findings => no file written, returns None."""
        partner = _FakePartner(findings=ResearchFindings(summary=""))
        coordinator = ComplementaryResearchCoordinator()
        with (
            patch(f"{MODULE}.resolve_research_partner_backend", return_value="gpt"),
            patch(f"{MODULE}.ResearchPartnerFactory.create", return_value=partner),
        ):
            result = await coordinator.research(
                brief=_FakeBrief(),
                question="q",
                cwd=str(tmp_path),
                slug="my-feature",
                run_id="r",
                node_id="n",
            )
        assert result is None
        assert not (tmp_path / "sdd" / "proposals").exists()

    async def test_commit_failure_still_returns_findings(self, tmp_path):
        """document_path == "" but findings survive; warning logged."""
        partner = _FakePartner(findings=_rich_findings())
        coordinator = ComplementaryResearchCoordinator()

        async def failing_run_git(repo_root, *args):
            raise RuntimeError("git commit failed (exit 1): fatal: no git repo")

        with (
            patch(f"{MODULE}.resolve_research_partner_backend", return_value="gpt"),
            patch(f"{MODULE}.ResearchPartnerFactory.create", return_value=partner),
            patch.object(ComplementaryResearchCoordinator, "_run_git", staticmethod(failing_run_git)),
        ):
            result = await coordinator.research(
                brief=_FakeBrief(),
                question="q",
                cwd=str(tmp_path),
                slug="my-feature",
                run_id="r",
                node_id="n",
            )
        assert result is not None
        assert result.document_path == ""
        assert result.findings.summary == "Found a relevant precedent."

    async def test_emits_started_and_completed_on_success(self, tmp_path):
        partner = _FakePartner(findings=_rich_findings())
        coordinator = ComplementaryResearchCoordinator()
        with (
            patch(f"{MODULE}.resolve_research_partner_backend", return_value="gpt"),
            patch(f"{MODULE}.ResearchPartnerFactory.create", return_value=partner),
            patch.object(coordinator, "_emit") as mock_emit,
        ):
            await coordinator.research(
                brief=_FakeBrief(),
                question="q",
                cwd=str(tmp_path),
                slug="my-feature",
                run_id="r",
                node_id="n",
            )
        events = [c.args[0] for c in mock_emit.call_args_list]
        assert events == ["partner.started", "partner.completed"]

    async def test_oversized_findings_truncated_in_payload_not_in_file(self, tmp_path):
        big_detail = "x" * 10_000
        findings = ResearchFindings(
            summary="s",
            findings=[ResearchFinding(id="F1", title="t", detail=big_detail)],
        )
        partner = _FakePartner(findings=findings)
        coordinator = ComplementaryResearchCoordinator()
        with (
            patch(f"{MODULE}.resolve_research_partner_backend", return_value="gpt"),
            patch(f"{MODULE}.ResearchPartnerFactory.create", return_value=partner),
            patch.object(ComplementaryResearchCoordinator, "_run_git", AsyncMock()),
        ):
            result = await coordinator.research(
                brief=_FakeBrief(),
                question="q",
                cwd=str(tmp_path),
                slug="my-feature",
                run_id="r",
                node_id="n",
            )
        assert result is not None
        assert "truncated" in result.rendered
        assert big_detail not in result.rendered
        written = tmp_path / "sdd" / "proposals" / "my-feature.research.md"
        assert big_detail in written.read_text()

    async def test_never_raises_on_unexpected_partner_construction_error(self, tmp_path):
        """Even a factory/construction-time error degrades, never raises."""
        coordinator = ComplementaryResearchCoordinator()
        with (
            patch(f"{MODULE}.resolve_research_partner_backend", return_value="gpt"),
            patch(f"{MODULE}.ResearchPartnerFactory.create", side_effect=RuntimeError("boom")),
        ):
            result = await coordinator.research(
                brief=_FakeBrief(),
                question="q",
                cwd=str(tmp_path),
                slug="my-feature",
                run_id="r",
                node_id="n",
            )
        assert result is None
