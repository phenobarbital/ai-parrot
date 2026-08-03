"""Unit tests for NovaAdversarialReviewDispatcher (FEAT-405, TASK-2087)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory
from parrot.flows.dev_loop.dispatchers.nova import NovaAdversarialReviewDispatcher
from parrot.flows.dev_loop.models import (
    AdversarialFinding,
    CodeReviewFinding,
    CodeReviewVerdict,
)
from pydantic import BaseModel


class _FakeBrief(BaseModel):
    acceptance_criteria: list[str] = ["criterion 1"]
    worktree_path: str = "."


@pytest.fixture
def reviewer():
    return CodeReviewDispatcherFactory.create("nova-adversarial")


@pytest.fixture(autouse=True)
def _stub_git_diff(monkeypatch):
    """Skip real subprocess git-diff invocation in every test by default."""

    async def _fake_collect_diff(self, cwd, profile):
        return "diff --git a/foo.py b/foo.py\n+print('hi')\n"

    monkeypatch.setattr(NovaAdversarialReviewDispatcher, "_collect_diff", _fake_collect_diff)


class TestRegistration:
    def test_registered_in_factory(self, reviewer):
        assert isinstance(reviewer, NovaAdversarialReviewDispatcher)
        assert reviewer.agent_name == "nova-adversarial"

    def test_is_advisory(self, reviewer):
        assert reviewer.advisory is True

    def test_build_review_profile_defaults(self, reviewer):
        profile = reviewer.build_review_profile()
        assert profile.model == "us.anthropic.claude-opus-5"
        assert profile.review_scope == "uncommitted"


class TestNoTools:
    async def test_ask_called_without_tools(self, reviewer, monkeypatch):
        fake_ask = AsyncMock(
            return_value=SimpleNamespace(
                structured_output=CodeReviewVerdict(passed=True, findings=[])
            )
        )
        monkeypatch.setattr(reviewer, "_client", SimpleNamespace(ask=fake_ask))
        await reviewer.review(brief=_FakeBrief(), run_id="r", node_id="n", cwd=".")
        kwargs = fake_ask.await_args.kwargs
        assert kwargs.get("use_tools") is False
        assert "tools" not in kwargs


class TestHardening:
    async def test_files_modified_always_empty(self, reviewer, monkeypatch):
        fake_ask = AsyncMock(
            return_value=SimpleNamespace(
                structured_output=CodeReviewVerdict(
                    passed=False,
                    files_modified=["should-be-cleared.py"],
                    findings=[CodeReviewFinding(message="issue", severity="minor")],
                )
            )
        )
        monkeypatch.setattr(reviewer, "_client", SimpleNamespace(ask=fake_ask))
        verdict = await reviewer.review(brief=_FakeBrief(), run_id="r", node_id="n", cwd=".")
        assert verdict.files_modified == []

    async def test_findings_tagged_with_source(self, reviewer, monkeypatch):
        fake_ask = AsyncMock(
            return_value=SimpleNamespace(
                structured_output=CodeReviewVerdict(
                    passed=False,
                    findings=[CodeReviewFinding(message="issue", severity="minor")],
                )
            )
        )
        monkeypatch.setattr(reviewer, "_client", SimpleNamespace(ask=fake_ask))
        verdict = await reviewer.review(brief=_FakeBrief(), run_id="r", node_id="n", cwd=".")
        assert all(
            isinstance(f, AdversarialFinding) and f.source == "nova-adversarial"
            for f in verdict.findings
        )

    async def test_existing_adversarial_finding_source_preserved(self, reviewer, monkeypatch):
        """A finding already shaped as AdversarialFinding is passed through unchanged."""
        existing = AdversarialFinding(message="issue", severity="minor", source="other-source")
        fake_ask = AsyncMock(
            return_value=SimpleNamespace(
                structured_output=CodeReviewVerdict(passed=False, findings=[existing])
            )
        )
        monkeypatch.setattr(reviewer, "_client", SimpleNamespace(ask=fake_ask))
        verdict = await reviewer.review(brief=_FakeBrief(), run_id="r", node_id="n", cwd=".")
        assert verdict.findings[0].source == "other-source"


class TestDiffTruncation:
    def test_diff_truncated_with_marker(self, reviewer):
        """A huge diff is cut deterministically, never silently."""
        huge = "x" * 500_000
        truncated = reviewer._truncate_diff(huge, max_diff_chars=1000)
        assert len(truncated) > 1000  # marker text pushes it slightly over
        assert truncated.startswith("x" * 1000)
        assert "truncated at 1000 characters" in truncated

    def test_diff_under_limit_not_truncated(self, reviewer):
        small = "small diff"
        assert reviewer._truncate_diff(small, max_diff_chars=1000) == small


class TestDegradeOnError:
    async def test_infra_error_degrades_to_passing_verdict(self, reviewer, monkeypatch):
        """DOCUMENTS a known property: a Bedrock outage PASSES the adversarial gate."""
        fake_ask = AsyncMock(side_effect=RuntimeError("Bedrock outage"))
        monkeypatch.setattr(reviewer, "_client", SimpleNamespace(ask=fake_ask))
        verdict = await reviewer.review(brief=_FakeBrief(), run_id="r", node_id="n", cwd=".")
        assert verdict.passed is True
        assert any(f.severity == "nit" for f in verdict.findings)
        assert "Bedrock outage" in verdict.findings[0].message

    async def test_non_verdict_structured_output_degrades(self, reviewer, monkeypatch):
        """A malformed/non-CodeReviewVerdict response also degrades, not crashes."""
        fake_ask = AsyncMock(return_value=SimpleNamespace(structured_output="not a verdict"))
        monkeypatch.setattr(reviewer, "_client", SimpleNamespace(ask=fake_ask))
        verdict = await reviewer.review(brief=_FakeBrief(), run_id="r", node_id="n", cwd=".")
        assert verdict.passed is True
        assert any(f.severity == "nit" for f in verdict.findings)

    async def test_diff_collection_error_degrades(self, reviewer, monkeypatch):
        async def _boom(self, cwd, profile):
            raise RuntimeError("git diff failed")

        monkeypatch.setattr(NovaAdversarialReviewDispatcher, "_collect_diff", _boom)
        verdict = await reviewer.review(brief=_FakeBrief(), run_id="r", node_id="n", cwd=".")
        assert verdict.passed is True
        assert any(f.severity == "nit" for f in verdict.findings)
