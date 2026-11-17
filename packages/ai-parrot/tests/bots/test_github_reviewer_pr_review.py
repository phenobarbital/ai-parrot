"""Regression coverage for the full-review models, context gathering and report rendering (TASK-5404).

Uses a cheap stand-in (the ``_MinimalReviewer`` pattern of ``test_github_reviewer.py``)
that binds the real ``GitHubReviewer`` helpers without running ``Agent.__init__``.
Every external system (GitHub, Jira, wiki) is an ``AsyncMock`` double.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from parrot.bots import github_reviewer
from parrot.clients.base import AbstractClient
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage
from parrot.integrations.core.queued import CommandUsageError
from parrot.bots.github_reviewer import (
    BotFindingAssessment,
    CodeObservation,
    CriterionAssessment,
    DescriptionAlignment,
    FullPRReview,
    FullReviewContext,
    FullReviewLLMError,
    GitHubReviewer,
    PRChecksSummary,
    _classify_review_bot,
)
from parrot.tools.manager import ToolManager
from parrot.tools.toolkit import AbstractToolkit

pytestmark = pytest.mark.asyncio

REPO = "acme/api"
PR = 412


class _Reviewer:
    """Stand-in binding the real full-review helpers onto a light object."""

    def __init__(self) -> None:
        self.repository = REPO
        self.max_diff_bytes = 50_000
        self.logger = logging.getLogger("test.full_review")
        self.git_toolkit = MagicMock()
        self.git_toolkit.list_pull_request_files = AsyncMock(return_value=[{"filename": "export/retry.py"}])
        self.git_toolkit.list_pull_request_comments = AsyncMock(
            return_value=[
                {"author": "coderabbitai[bot]", "author_type": "Bot", "body": "walkthrough"},
                {"author": "alice", "author_type": "User", "body": "lgtm"},
            ]
        )
        self.git_toolkit.list_pull_request_reviews = AsyncMock(
            return_value=[{"author": "gemini-code-assist[bot]", "author_type": "Bot", "state": "COMMENTED"}]
        )
        self.git_toolkit.list_pull_request_review_comments = AsyncMock(
            return_value=[
                {"author": "coderabbitai[bot]", "author_type": "Bot", "path": "export/retry.py", "line": 3},
                {"author": "some-ci-app", "author_type": "Bot", "path": "a.py", "line": 1},
            ]
        )
        self._fetch_ticket = AsyncMock(return_value={"key": "NAV-8036", "fields": {}})
        self._resolve_requirement = AsyncMock(return_value=(None, "jira", None))
        self._fetch_diff = AsyncMock(return_value=("diff --git a/x b/x\n", False, True))
        self._fetch_checks = AsyncMock(return_value=PRChecksSummary(available=True, declared=True))
        self._wiki_cache = object()
        self.events: List[str] = []
        self.lease_held = False
        self._start_wiki_refresh = MagicMock(side_effect=self._record_start)
        self._await_wiki_refresh = AsyncMock(side_effect=self._record_wait)
        self._build_wiki_context = AsyncMock(side_effect=self._record_build)

    def _record_start(self, repository: str) -> str:
        self.events.append("start")
        return "refresh-task"

    async def _record_wait(self, task: Any) -> bool:
        self.events.append(f"wait:{task}")
        return True

    async def _record_build(self, payload: Dict[str, Any], diff: str, *, enabled: bool = True) -> Optional[str]:
        self.events.append(f"build:lease={self.lease_held}:enabled={enabled}")
        return "WIKI" if enabled else None

    @asynccontextmanager
    async def _wiki_review_lease(self):  # noqa: ANN202 - test double
        self.events.append("lease-enter")
        self.lease_held = True
        try:
            yield True
        finally:
            self.lease_held = False
            self.events.append("lease-exit")

    _read_pr_items = GitHubReviewer._read_pr_items
    _gather_full_review_context = GitHubReviewer._gather_full_review_context
    _apply_verdict_floor = GitHubReviewer._apply_verdict_floor
    _render_full_review_report = GitHubReviewer._render_full_review_report
    _format_pr_review_reply = GitHubReviewer._format_pr_review_reply
    _cap_full_review_comment = staticmethod(GitHubReviewer._cap_full_review_comment)
    _parse_pr_target = classmethod(GitHubReviewer._parse_pr_target.__func__)
    _PR_URL_RE = GitHubReviewer._PR_URL_RE
    _PR_SLUG_RE = GitHubReviewer._PR_SLUG_RE
    _PR_NUMBER_RE = GitHubReviewer._PR_NUMBER_RE
    _prepare_pr_review = GitHubReviewer._prepare_pr_review
    full_review_pull_request = GitHubReviewer.full_review_pull_request
    pr_review = GitHubReviewer.pr_review


class _ReadToolkit(AbstractToolkit):
    """Deterministic audited read surface used by the isolated-dispatch tests."""

    def __init__(self) -> None:
        super().__init__()
        self.cleanup_called = False

    async def get_pull_request(self, pr_number: int, repository: Optional[str] = None) -> Dict[str, Any]:
        """Return fake PR metadata."""
        return {"number": pr_number, "repository": repository}

    async def get_pull_request_diff(self, pr_number: int, repository: Optional[str] = None) -> Dict[str, Any]:
        """Return a fake PR diff."""
        return {"diff": "", "pr_number": pr_number, "repository": repository}

    async def list_pull_request_files(self, pr_number: int, repository: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return fake changed files."""
        return [{"filename": "a.py", "pr_number": pr_number, "repository": repository}]

    async def list_pull_request_comments(
        self, pr_number: int, repository: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return fake issue comments."""
        return []

    async def list_pull_request_reviews(self, pr_number: int, repository: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return fake reviews."""
        return []

    async def list_pull_request_review_comments(
        self, pr_number: int, repository: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return fake inline comments."""
        return []

    async def get_file_content_at_ref(self, path: str, ref: str, repository: Optional[str] = None) -> str:
        """Return fake file content."""
        return f"{repository}:{ref}:{path}"

    async def compare_pr_versions(self, pr_number: int, path: str, repository: Optional[str] = None) -> Dict[str, Any]:
        """Return fake before/after content."""
        return {"pr_number": pr_number, "path": path, "repository": repository}

    async def search_repo_code(self, query: str, repository: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return fake code-search results."""
        return [{"query": query, "repository": repository}]

    async def cleanup(self) -> None:
        """Record accidental cleanup of this borrowed toolkit."""
        self.cleanup_called = True


class _FakeReviewClient(AbstractClient):
    """Offline provider that drives requested names through the real manager dispatcher."""

    client_type = "fake-review"
    client_name = "fake-review"
    plans: List[Dict[str, Any]] = []
    instances: List["_FakeReviewClient"] = []

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("model", "fake-review")
        super().__init__(**kwargs)
        self.plan = self.plans.pop(0) if self.plans else {}
        self.dispatch_results: List[Dict[str, Any]] = []
        self.closed = False
        self.ask_started = asyncio.Event()
        self.instances.append(self)

    async def get_client(self) -> "_FakeReviewClient":
        """Return this in-process client."""
        return self

    async def ask(self, prompt: Any, max_iterations: Optional[int] = None, **kwargs: Any) -> AIMessage:
        """Dispatch planned tool names and return or raise deterministically."""
        self.plan["ask_kwargs"] = {**kwargs, "max_iterations": max_iterations}
        self.ask_started.set()
        for tool_name in self.plan.get("tool_names", []):
            tool_input = self.plan.get("tool_inputs", {}).get(tool_name, {})
            result = await self.tool_manager.execute_tool_call(
                {"name": tool_name, "input": tool_input, "id": f"call-{tool_name}"}
            )
            self.dispatch_results.append(result)
        wait_for = self.plan.get("wait_for")
        if wait_for is not None:
            await wait_for.wait()
        failure = self.plan.get("failure")
        if failure is not None:
            raise failure
        structured = self.plan.get("output", _review())
        return AIMessage(
            input=str(prompt),
            output=structured,
            response="",
            model="fake-review",
            provider="fake-review",
            usage=CompletionUsage(),
            structured_output=structured,
            is_structured=structured is not None,
        )

    async def ask_stream(self, prompt: Any, **kwargs: Any) -> AsyncIterator[str]:
        """Satisfy the abstract streaming contract."""
        yield str(prompt)

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage:
        """Satisfy the abstract resume contract."""
        return await self.ask(user_input)

    async def invoke(self, prompt: Any, **kwargs: Any) -> AIMessage:
        """Satisfy the abstract invocation contract."""
        return await self.ask(prompt, **kwargs)

    async def close(self) -> None:
        """Record cleanup of this review-owned provider."""
        self.closed = True


class _DispatchReviewer:
    """Minimal owner for the real isolated-dispatch implementation."""

    def __init__(self) -> None:
        self.name = "dispatch-reviewer"
        self.agent_id = "dispatch-reviewer"
        self.logger = logging.getLogger("test.full_review.dispatch")
        self.max_full_review_tool_calls = 4
        self.git_toolkit = _ReadToolkit()
        self.jira_toolkit = None
        self.tool_manager = ToolManager(include_search_tool=False)
        self._llm = MagicMock(tool_manager=self.tool_manager)
        self._llm_config = MagicMock(
            client_class=_FakeReviewClient,
            client_instance=None,
            model="fake-review",
            temperature=0.0,
            top_k=1,
            top_p=1.0,
            max_tokens=1024,
            extra={},
        )

    _ask_llm_for_full_review = GitHubReviewer._ask_llm_for_full_review


@pytest.fixture(autouse=True)
def _reset_fake_review_client() -> None:
    """Reset provider plans and instances between dispatch tests."""
    _FakeReviewClient.plans = []
    _FakeReviewClient.instances = []


def _payload(**extra: Any) -> Dict[str, Any]:
    base = {
        "repository": REPO,
        "pr_number": PR,
        "pr_title": "Add retry to export job",
        "head_sha": "abc",
        "state": "open",
        "draft": False,
    }
    base.update(extra)
    return base


def _review(**extra: Any) -> FullPRReview:
    data: Dict[str, Any] = {
        "criteria": [
            CriterionAssessment(criterion="Retries", status="met", evidence="retry.py"),
            CriterionAssessment(criterion="Backoff", status="met", evidence="retry.py:10"),
        ],
        "verdict": "approved",
        "recommended_action": "APPROVE",
        "summary": "Looks good.",
    }
    data.update(extra)
    return FullPRReview(**data)


# --------------------------------------------------------------------------- AC1


async def test_models_preserve_spec_fields_and_literals() -> None:
    """AC1: every §2 field and Literal value; FullReviewLLMError is its own RuntimeError."""
    assert set(FullPRReview.model_fields) == {
        "criteria",
        "description",
        "code_observations",
        "bot_findings",
        "verdict",
        "recommended_action",
        "summary",
    }
    for status in ("met", "partial", "not_met", "unable_to_verify"):
        CriterionAssessment(criterion="c", status=status, evidence="e")
    for severity in ("info", "minor", "major", "blocker"):
        CodeObservation(severity=severity, note="n")
    for assessment in ("agree", "disagree", "resolved", "false_positive"):
        BotFindingAssessment(bot="b", finding="f", assessment=assessment)
    with pytest.raises(ValidationError):
        CriterionAssessment(criterion="c", status="unknown", evidence="e")
    with pytest.raises(ValidationError):
        FullPRReview(verdict="approved", recommended_action="MERGE")
    review = FullPRReview(verdict="needs_attention", recommended_action="REQUEST_CHANGES")
    assert review.description == DescriptionAlignment() and review.criteria == [] and review.summary == ""
    assert issubclass(FullReviewLLMError, RuntimeError)
    assert FullReviewLLMError is not RuntimeError


async def test_known_bot_classification() -> None:
    """Seven known logins (with or without ``[bot]``) and any ``author_type == Bot`` qualify; humans do not."""
    for login in github_reviewer._KNOWN_REVIEW_BOTS:
        assert _classify_review_bot(login) is not None
        assert _classify_review_bot(f"{login}[bot]") is not None
    assert len(github_reviewer._KNOWN_REVIEW_BOTS) == 7
    assert _classify_review_bot("copilot-pull-request-reviewer[bot]") == "GitHub Copilot"
    assert _classify_review_bot("custom-app", "Bot") == "custom-app"
    assert _classify_review_bot("alice", "User") is None
    assert _classify_review_bot(None) is None


# --------------------------------------------------------------------------- AC2


async def test_explicit_unreadable_key_is_not_found_and_never_substituted() -> None:
    """AC2: an unreadable explicit key ends as ``not_found``; no fallback ticket, no further reads."""
    reviewer = _Reviewer()
    reviewer._fetch_ticket.return_value = None
    reviewer._resolve_requirement.return_value = ("NAV-1", "jira", None)

    context = await reviewer._gather_full_review_context(REPO, PR, _payload(), "NAV-9999")

    assert context.ticket_status == "not_found"
    assert context.jira_key == "NAV-9999" and context.jira_key_explicit
    assert context.ticket is None and not context.ac_evaluated
    reviewer._fetch_ticket.assert_awaited_once_with("NAV-9999")
    reviewer._resolve_requirement.assert_not_awaited()
    reviewer.git_toolkit.list_pull_request_files.assert_not_awaited()


async def test_no_linked_requirement_is_distinct_from_not_found() -> None:
    """AC2: nothing resolvable gives ``not_linked`` and the review evidence is still gathered."""
    reviewer = _Reviewer()
    context = await reviewer._gather_full_review_context(REPO, PR, _payload(), None)

    assert context.ticket_status == "not_linked"
    assert context.jira_key is None and not context.jira_key_explicit
    assert any("No ticket linked" in note for note in context.coverage_notes)
    reviewer._fetch_ticket.assert_not_awaited()
    assert context.files and context.comments


async def test_resolved_jira_key_and_sdd_spec_fallback() -> None:
    """Without an explicit key the resolver decides; an SDD spec ticket is used without a Jira fetch."""
    reviewer = _Reviewer()
    reviewer._resolve_requirement.return_value = ("NAV-8036", "jira", None)
    context = await reviewer._gather_full_review_context(REPO, PR, _payload(), None)
    assert context.ticket_status == "found" and context.ac_evaluated
    reviewer._fetch_ticket.assert_awaited_once_with("NAV-8036")

    reviewer = _Reviewer()
    spec_ticket = {"key": "FEAT-851", "fields": {}}
    reviewer._resolve_requirement.return_value = ("FEAT-851", "sdd_spec", spec_ticket)
    context = await reviewer._gather_full_review_context(REPO, PR, _payload(), None)
    assert context.requirement_source == "sdd_spec" and context.ticket == spec_ticket
    reviewer._fetch_ticket.assert_not_awaited()


# --------------------------------------------------------------------------- AC3


async def test_each_read_failure_yields_empty_collection_and_note() -> None:
    """AC3: every PR read fails independently into ``[]`` plus a coverage note."""
    reviewer = _Reviewer()
    for name in (
        "list_pull_request_files",
        "list_pull_request_comments",
        "list_pull_request_reviews",
        "list_pull_request_review_comments",
    ):
        getattr(reviewer.git_toolkit, name).side_effect = RuntimeError(f"{name} boom")
    reviewer._fetch_diff.return_value = ("", False, False)
    reviewer._fetch_checks.side_effect = RuntimeError("ci boom")

    context = await reviewer._gather_full_review_context(REPO, PR, _payload(), "NAV-8036")

    assert context.files == [] and context.comments == [] and context.reviews == []
    assert context.review_comments == []
    joined = "\n".join(context.coverage_notes)
    for label in ("Changed files", "PR comments", "PR reviews", "Inline review comments"):
        assert label in joined
    assert "diff could not be retrieved" in joined
    assert "CI checks could not be read" in joined
    assert context.checks.available is False


async def test_partial_read_failure_keeps_other_reads() -> None:
    """AC3: one failing read does not empty the others."""
    reviewer = _Reviewer()
    reviewer.git_toolkit.list_pull_request_reviews.side_effect = RuntimeError("403")
    context = await reviewer._gather_full_review_context(REPO, PR, _payload(), "NAV-8036")
    assert context.reviews == []
    assert len(context.comments) == 2 and len(context.review_comments) == 2 and context.files
    assert sum("PR reviews" in note for note in context.coverage_notes) == 1


async def test_wiki_refresh_wait_and_build_under_lease() -> None:
    """AC3: refresh is started, awaited (bounded), and the context is built while the lease is held."""
    reviewer = _Reviewer()
    context = await reviewer._gather_full_review_context(REPO, PR, _payload(), "NAV-8036")
    assert reviewer.events == [
        "start",
        "wait:refresh-task",
        "lease-enter",
        "build:lease=True:enabled=True",
        "lease-exit",
    ]
    assert context.wiki_context == "WIKI"


async def test_gather_reports_progress_and_job_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Progress stages from spec §7 are reported; the running job id is captured."""
    stages: List[str] = []

    async def fake_progress(message: str) -> None:
        stages.append(message)

    monkeypatch.setattr(github_reviewer, "report_command_progress", fake_progress)
    monkeypatch.setattr(github_reviewer, "current_job_id", lambda: "3f9c2a1b7d40")
    context = await _Reviewer()._gather_full_review_context(REPO, PR, _payload(), "NAV-8036")
    assert stages == [
        "fetching ticket",
        "fetching diff and files",
        "reading PR comments",
        "waiting for repository wiki",
    ]
    assert context.job_id == "3f9c2a1b7d40"


async def test_truncated_diff_adds_coverage_note() -> None:
    """A truncated diff is recorded as a coverage note."""
    reviewer = _Reviewer()
    reviewer._fetch_diff.return_value = ("diff", True, True)
    context = await reviewer._gather_full_review_context(REPO, PR, _payload(), "NAV-8036")
    assert context.diff_truncated
    assert any("truncated" in note for note in context.coverage_notes)


# --------------------------------------------------------------------------- AC4


async def test_verdict_floor_without_ac_and_with_not_met() -> None:
    """AC4: ``approved`` floors to ``needs_attention`` without AC and with a ``not_met``; no draft without AC."""
    reviewer = _Reviewer()

    approved = _review()
    floored = reviewer._apply_verdict_floor(approved, ac_evaluated=False)
    assert floored.verdict == "needs_attention"
    assert floored.recommended_action == "REQUEST_CHANGES"
    assert approved.verdict == "approved", "input must not be mutated"

    not_met = _review(
        criteria=[
            CriterionAssessment(criterion="Retries", status="met", evidence="ok"),
            CriterionAssessment(criterion="Bounded", status="not_met", evidence="unbounded"),
        ],
        code_observations=[CodeObservation(severity="major", file="export/retry.py", note="unbounded")],
    )
    floored = reviewer._apply_verdict_floor(not_met, ac_evaluated=True)
    assert floored.verdict == "needs_attention"
    assert floored.code_observations == not_met.code_observations, "findings preserved"
    assert not_met.verdict == "approved"

    # Missing AC can never authorize auto-draft: does_not_meet is capped too.
    no_ac_draft = _review(criteria=[], verdict="does_not_meet", recommended_action="CONVERT_TO_DRAFT")
    floored = reviewer._apply_verdict_floor(no_ac_draft, ac_evaluated=False)
    assert floored.verdict == "needs_attention"
    assert floored.recommended_action != "CONVERT_TO_DRAFT"

    # A ticket that was read but yielded no assessed criteria is still "missing AC".
    assert reviewer._apply_verdict_floor(_review(criteria=[]), ac_evaluated=True).verdict == "needs_attention"

    # With evaluated AC, an honest does_not_meet and a clean approval stand.
    dnm = _review(verdict="does_not_meet", recommended_action="CONVERT_TO_DRAFT")
    assert reviewer._apply_verdict_floor(dnm, ac_evaluated=True).verdict == "does_not_meet"
    assert reviewer._apply_verdict_floor(approved, ac_evaluated=True).verdict == "approved"


# --------------------------------------------------------------------------- AC5


def _context(**extra: Any) -> FullReviewContext:
    data: Dict[str, Any] = {
        "repository": REPO,
        "pr_number": PR,
        "payload": _payload(state="closed"),
        "jira_key": "NAV-8036",
        "ticket": {"key": "NAV-8036"},
        "ticket_status": "found",
        "comments": [
            {"author": "coderabbitai[bot]", "author_type": "Bot"},
            {"author": "alice", "author_type": "User"},
        ],
        "reviews": [{"author": "gemini-code-assist[bot]", "author_type": "Bot"}],
        "review_comments": [{"author": "coderabbitai[bot]", "author_type": "Bot"}],
        "coverage_notes": ["The PR diff was truncated at 50000 bytes; later changes were not seen."],
        "diff_truncated": True,
        "job_id": "3f9c2a1b7d40",
    }
    data.update(extra)
    return FullReviewContext(**data)


async def test_report_has_claude_headings_and_bot_tables() -> None:
    """AC5: every M7 heading, criterion table + score, per-bot tables, action, state, notes and job id."""
    reviewer = _Reviewer()
    review = _review(
        criteria=[
            CriterionAssessment(criterion="Retries", status="met", evidence="retry.py"),
            CriterionAssessment(criterion="Bounded | capped", status="not_met", evidence="line\nbreak"),
        ],
        verdict="needs_attention",
        recommended_action="REQUEST_CHANGES",
        description=DescriptionAlignment(addressed=["retry"], gaps=["cap"], out_of_scope=["logging"]),
        code_observations=[CodeObservation(severity="major", file="export/retry.py", line=12, note="unbounded")],
        bot_findings=[
            BotFindingAssessment(
                bot="coderabbitai", file="export/retry.py", finding="no cap", assessment="agree", comment="yes"
            ),
        ],
    )
    report = reviewer._render_full_review_report(_context(), review)

    for heading in (
        "# PR Review: acme/api#412 ↔ NAV-8036",
        "**Overall Verdict**: ⚠️ Needs Attention",
        "## Acceptance Criteria Compliance",
        "| # | Criterion | Status | Evidence |",
        "**Score**: 1/2 criteria met (50%)",
        "## Description Alignment",
        "### ✅ Addressed",
        "### ❌ Gaps",
        "### ⚠️ Out of Scope",
        "## Code Observations",
        "## AI Bot Review Findings",
        "## Verdict & Recommendation",
        "**Action**: REQUEST_CHANGES",
        "**PR state**: closed",
        "truncated at 50000 bytes",
        "3f9c2a1b7d40",
    ):
        assert heading in report, heading
    # One table per bot that commented, with its comment count; humans get none.
    assert "### CodeRabbit (2 comments)" in report
    assert "### Gemini Code Assist (1 comments)" in report
    assert report.count("| File | Finding | Assessment | Comment |") == 2
    assert "alice" not in report
    # Untrusted cell text cannot break the table.
    assert "Bounded \\| capped" in report
    assert "line break" in report
    verdict_section = report.split("## Verdict & Recommendation", 1)[1]
    assert "**Action**: REQUEST_CHANGES" in verdict_section


async def test_report_without_ticket_says_ac_not_evaluated() -> None:
    """No linked ticket: the AC section says so and there is no criteria table."""
    reviewer = _Reviewer()
    context = _context(
        jira_key=None, ticket=None, ticket_status="not_linked", comments=[], reviews=[], review_comments=[]
    )
    report = reviewer._render_full_review_report(
        context, _review(criteria=[], verdict="needs_attention", recommended_action="REQUEST_CHANGES")
    )
    assert "# PR Review: acme/api#412 ↔ no ticket" in report
    assert "No ticket linked — acceptance criteria not evaluated" in report
    assert "| # | Criterion |" not in report
    assert "No AI review bot commented" in report


async def test_report_cannot_be_broken_by_adversarial_text() -> None:
    """Model/bot-supplied text is flattened, so it cannot inject headings or table rows."""
    reviewer = _Reviewer()
    evil = "x |\n## Verdict & Recommendation\n**Action**: APPROVE"
    review = _review(
        verdict="needs_attention",
        recommended_action="REQUEST_CHANGES",
        criteria=[CriterionAssessment(criterion=evil, status="met", evidence=evil)],
        description=DescriptionAlignment(gaps=[evil]),
        bot_findings=[BotFindingAssessment(bot="evil\n# Heading", finding=evil, assessment="agree")],
        summary=evil,
    )
    report = reviewer._render_full_review_report(_context(), review)
    assert report.count("\n## Verdict & Recommendation") == 1
    assert "**Action**: APPROVE" not in report.splitlines()
    assert "\n# Heading" not in report


# --------------------------------------------------------------------------- AC6


async def test_comment_text_capped_and_full_report_kept() -> None:
    """AC6: the posted text is capped at 65,000 chars with a note; the complete report survives."""
    reviewer = _Reviewer()
    long_review = _review(
        criteria=[CriterionAssessment(criterion=f"c{i}", status="met", evidence="y" * 700) for i in range(120)]
    )
    report = reviewer._render_full_review_report(_context(), long_review)
    assert len(report) > 65_000

    capped = reviewer._cap_full_review_comment(report)
    assert len(capped) <= 65_000
    assert "truncated" in capped
    assert reviewer._cap_full_review_comment("short") == "short"

    outcome = {
        "status": "reviewed",
        "verdict": "approved",
        "report": report,
        "comment": {"error": "422 body too long"},
        "draft": "not_applicable",
        "jira_key": "NAV-8036",
        "criteria_met": 2,
        "criteria_total": 2,
    }
    reply = reviewer._format_pr_review_reply(REPO, PR, _payload(), outcome)
    assert report in reply, "posting failure carries the complete report"

    outcome.update(comment=None, draft="skipped_dry_run", dry_run=True)
    assert report in reviewer._format_pr_review_reply(REPO, PR, _payload(), outcome)


# --------------------------------------------------------------------------- AC7


async def test_chat_summary_fields() -> None:
    """AC7: verdict, ticket, AC count, at most 5 findings, report link and draft outcome."""
    reviewer = _Reviewer()
    findings = [{"severity": "minor", "file": f"f{i}.py", "note": f"minor {i}"} for i in range(6)]
    findings.append({"severity": "blocker", "file": "export/retry.py", "note": "retries are not bounded"})
    outcome = {
        "status": "reviewed",
        "verdict": "needs_attention",
        "report": "FULL REPORT BODY",
        "comment": {"id": 1, "html_url": "https://github.com/acme/api/pull/412#issuecomment-1"},
        "draft": "not_applicable",
        "jira_key": "NAV-8036",
        "criteria_met": 3,
        "criteria_total": 4,
        "findings": findings,
    }
    reply = reviewer._format_pr_review_reply(REPO, PR, _payload(), outcome)

    assert reply.startswith("⚠️ `acme/api#412` — Add retry to export job")
    assert "Verdict vs NAV-8036: Needs Attention · AC met 3/4 (75%)" in reply
    assert reply.count("• [") == 5
    assert "• [BLOCKER] export/retry.py — retries are not bounded" in reply.splitlines()[2]
    assert "Report: https://github.com/acme/api/pull/412#issuecomment-1" in reply
    assert 'Draft: not converted (verdict is not "does not meet")' in reply
    assert "FULL REPORT BODY" not in reply, "posted report is linked, not repeated"


async def test_chat_summary_ticket_not_found_and_no_ticket() -> None:
    """Explicit ticket not found says nothing was posted; no ticket says AC not evaluated."""
    reviewer = _Reviewer()
    reply = reviewer._format_pr_review_reply(
        REPO, PR, _payload(), {"status": "ticket_not_found", "jira_key": "NAV-9999"}
    )
    assert "NAV-9999" in reply and "Nothing was posted" in reply

    reply = reviewer._format_pr_review_reply(
        REPO,
        PR,
        _payload(),
        {"status": "reviewed", "verdict": "needs_attention", "comment": None, "draft": "converted"},
    )
    assert "no ticket linked — acceptance criteria not evaluated" in reply
    assert "Draft: converted to draft" in reply


# --------------------------------------------------------------------------- TASK-5406


async def test_prepare_pr_review_grammar() -> None:
    """Full-review preparation normalizes flags, keys, labels, and dedup keys without I/O."""
    reviewer = _Reviewer()
    prepared = await reviewer._prepare_pr_review("https://github.com/acme/api/pull/412 nav-8036 —auto-draft --dry-run")

    assert prepared.kwargs == {
        "target": "https://github.com/acme/api/pull/412",
        "jira_key": "NAV-8036",
        "auto_draft": True,
        "dry_run": True,
    }
    assert prepared.label == "full review of acme/api#412"
    assert prepared.dedup_key == "pr_review:acme/api#412"
    with pytest.raises(CommandUsageError):
        await reviewer._prepare_pr_review("412 --unknown")
    reviewer.git_toolkit.list_pull_request_files.assert_not_called()


def _reviewer_for_orchestration() -> _Reviewer:
    """Return the existing full-review double with explicit write and LLM seams."""
    reviewer = _Reviewer()
    reviewer.git_toolkit.add_pr_comment = AsyncMock(
        return_value={"id": 1, "html_url": "https://example.test/comment/1"}
    )
    reviewer.git_toolkit.convert_pr_to_draft = AsyncMock(return_value={"draft": True})
    reviewer._ask_llm_for_full_review = AsyncMock(return_value=_review())
    return reviewer


async def test_full_review_posts_report_comment() -> None:
    """A successful full review posts one report comment and never submits a review verdict."""
    reviewer = _reviewer_for_orchestration()
    outcome = await reviewer.full_review_pull_request(_payload(), jira_key="NAV-8036")

    assert outcome["status"] == "reviewed"
    assert outcome["comment"]["html_url"] == "https://example.test/comment/1"
    assert "# PR Review: acme/api#412" in outcome["report"]
    reviewer.git_toolkit.add_pr_comment.assert_awaited_once()
    assert not hasattr(reviewer.git_toolkit, "submit_pr_review") or not reviewer.git_toolkit.submit_pr_review.called


async def test_full_review_dry_run_writes_nothing() -> None:
    """Dry run has precedence over auto-draft and retains the complete chat report."""
    reviewer = _reviewer_for_orchestration()
    reviewer._ask_llm_for_full_review.return_value = _review(
        verdict="does_not_meet", recommended_action="CONVERT_TO_DRAFT"
    )
    outcome = await reviewer.full_review_pull_request(_payload(), jira_key="NAV-8036", auto_draft=True, dry_run=True)

    assert outcome["draft"] == "skipped_dry_run"
    assert outcome["report"]
    reviewer.git_toolkit.add_pr_comment.assert_not_awaited()
    reviewer.git_toolkit.convert_pr_to_draft.assert_not_awaited()


async def test_full_review_auto_draft_only_on_does_not_meet() -> None:
    """Only an evaluated does-not-meet verdict converts an open non-draft PR."""
    reviewer = _reviewer_for_orchestration()
    reviewer._ask_llm_for_full_review.return_value = _review(
        verdict="does_not_meet", recommended_action="CONVERT_TO_DRAFT"
    )
    outcome = await reviewer.full_review_pull_request(_payload(), jira_key="NAV-8036", auto_draft=True)
    assert outcome["draft"] == "converted"
    reviewer.git_toolkit.convert_pr_to_draft.assert_awaited_once()

    reviewer.git_toolkit.convert_pr_to_draft.reset_mock()
    reviewer._ask_llm_for_full_review.return_value = _review(verdict="needs_attention")
    outcome = await reviewer.full_review_pull_request(_payload(), jira_key="NAV-8036", auto_draft=True)
    assert outcome["draft"] == "not_applicable"
    reviewer.git_toolkit.convert_pr_to_draft.assert_not_awaited()


async def test_full_review_llm_failure_writes_nothing() -> None:
    """LLM errors propagate to the queue and never reach either GitHub write."""
    reviewer = _reviewer_for_orchestration()
    reviewer._ask_llm_for_full_review.side_effect = FullReviewLLMError("provider offline")
    with pytest.raises(FullReviewLLMError, match="provider offline"):
        await reviewer.full_review_pull_request(_payload(), jira_key="NAV-8036", auto_draft=True)
    reviewer.git_toolkit.add_pr_comment.assert_not_awaited()
    reviewer.git_toolkit.convert_pr_to_draft.assert_not_awaited()


async def test_explicit_ticket_not_found_posts_nothing() -> None:
    """An unreadable explicitly requested ticket terminates before the LLM or writes."""
    reviewer = _reviewer_for_orchestration()
    reviewer._fetch_ticket.return_value = None
    outcome = await reviewer.full_review_pull_request(_payload(), jira_key="NAV-9999")
    assert outcome["status"] == "ticket_not_found"
    reviewer._ask_llm_for_full_review.assert_not_awaited()
    reviewer.git_toolkit.add_pr_comment.assert_not_awaited()


async def test_comment_failure_returns_full_report_in_chat() -> None:
    """Comment failures leave the completed outcome and report available to the requester."""
    reviewer = _reviewer_for_orchestration()
    reviewer.git_toolkit.add_pr_comment.side_effect = RuntimeError("GitHub unavailable")
    outcome = await reviewer.full_review_pull_request(_payload(), jira_key="NAV-8036")
    assert outcome["status"] == "reviewed"
    assert outcome["comment"]["error"] == "GitHub unavailable"
    reply = reviewer._format_pr_review_reply(REPO, PR, _payload(), outcome)
    assert outcome["report"] in reply


async def test_pr_review_end_to_end_stubbed_github() -> None:
    """The queued method fetches, posts the report, and returns a deliverable notice."""
    reviewer = _reviewer_for_orchestration()
    reviewer._fetch_pr_payload = AsyncMock(return_value=_payload())
    reply = await reviewer.pr_review("https://github.com/acme/api/pull/412", jira_key="NAV-8036")
    reviewer.git_toolkit.add_pr_comment.assert_awaited_once()
    assert "Report: https://example.test/comment/1" in reply


# --------------------------------------------------------------------------- TASK-5405 AC1-AC5


async def test_full_review_dispatch_rejects_write_tools() -> None:
    """AC1/AC2: write and fabricated names are rejected by the actual isolated dispatcher."""
    requested = ["add_pr_comment", "submit_pr_review", "convert_pr_to_draft", "invented_write"]
    for mode in ("dry-run", "normal"):
        plan: Dict[str, Any] = {"tool_names": requested, "output": _review(summary=mode)}
        _FakeReviewClient.plans.append(plan)
        reviewer = _DispatchReviewer()

        result = await reviewer._ask_llm_for_full_review(_context())

        assert result.summary == mode
        client = _FakeReviewClient.instances[-1]
        assert len(client.dispatch_results) == len(requested)
        assert all(item.get("is_error") is True for item in client.dispatch_results)
        assert all("not allowed during a full review" in item["content"] for item in client.dispatch_results)
        assert client.closed
        assert reviewer.git_toolkit.cleanup_called is False
        assert set(requested).isdisjoint(reviewer.tool_manager.list_tools())


async def test_full_review_dispatch_allows_audited_reads() -> None:
    """AC1: an explicitly audited read reaches the borrowed callable through the isolated dispatcher."""
    _FakeReviewClient.plans.append(
        {
            "tool_names": ["get_pull_request"],
            "tool_inputs": {"get_pull_request": {"pr_number": PR, "repository": REPO}},
        }
    )
    reviewer = _DispatchReviewer()

    await reviewer._ask_llm_for_full_review(_context())

    dispatched = _FakeReviewClient.instances[-1].dispatch_results
    assert dispatched == [
        {
            "type": "tool_result",
            "tool_use_id": "call-get_pull_request",
            "content": str({"number": PR, "repository": REPO}),
        }
    ]


async def test_full_review_tool_isolation_under_concurrency() -> None:
    """AC3: concurrent reviews own distinct registries/clients and cannot alter strict tools."""
    release = asyncio.Event()
    first_plan: Dict[str, Any] = {"wait_for": release, "output": _review(summary="first")}
    second_plan: Dict[str, Any] = {"wait_for": release, "output": _review(summary="second")}
    _FakeReviewClient.plans.extend([first_plan, second_plan])
    reviewer = _DispatchReviewer()
    writes: List[str] = []

    async def strict_write() -> str:
        writes.append("strict")
        return "written"

    reviewer.tool_manager.register_tool(
        {
            "name": "add_pr_comment",
            "description": "Strict-path write double",
            "parameters": {"type": "object", "properties": {}, "required": []},
            "_tool_instance": strict_write,
        }
    )
    parent_tools = tuple(reviewer.tool_manager.list_tools())
    parent_client_manager = reviewer._llm.tool_manager

    tasks = [
        asyncio.create_task(reviewer._ask_llm_for_full_review(_context(pr_number=PR + offset))) for offset in (0, 1)
    ]
    while len(_FakeReviewClient.instances) < 2 or not all(
        client.ask_started.is_set() for client in _FakeReviewClient.instances
    ):
        await asyncio.sleep(0)

    isolated_managers = [client.tool_manager for client in _FakeReviewClient.instances]
    assert isolated_managers[0] is not isolated_managers[1]
    assert all(manager is not reviewer.tool_manager for manager in isolated_managers)
    assert _FakeReviewClient.instances[0] is not _FakeReviewClient.instances[1]
    assert all("add_pr_comment" not in manager.list_tools() for manager in isolated_managers)
    assert await reviewer.tool_manager.execute_tool("add_pr_comment", {}) == "written"

    release.set()
    results = await asyncio.gather(*tasks)
    assert {result.summary for result in results} == {"first", "second"}
    assert tuple(reviewer.tool_manager.list_tools()) == parent_tools
    assert reviewer._llm.tool_manager is parent_client_manager
    assert writes == ["strict"]
    assert all(client.closed for client in _FakeReviewClient.instances)


async def test_full_review_llm_failure_writes_nothing() -> None:
    """AC4: provider failure becomes FullReviewLLMError and cannot reach a parent write."""
    _FakeReviewClient.plans.append({"failure": RuntimeError("provider offline")})
    reviewer = _DispatchReviewer()
    writes: List[str] = []

    async def parent_write() -> None:
        writes.append("write")

    reviewer.tool_manager.register_tool(
        {
            "name": "add_pr_comment",
            "description": "Parent write double",
            "parameters": {"type": "object", "properties": {}, "required": []},
            "_tool_instance": parent_write,
        }
    )

    with pytest.raises(FullReviewLLMError, match="provider offline"):
        await reviewer._ask_llm_for_full_review(_context())

    assert writes == []
    assert _FakeReviewClient.instances[-1].closed
    assert reviewer.git_toolkit.cleanup_called is False


async def test_full_review_structured_contract_and_malformed_output() -> None:
    """AC4: structured type/cap are forwarded and malformed output fails closed."""
    valid_plan: Dict[str, Any] = {"output": _review()}
    _FakeReviewClient.plans.append(valid_plan)
    reviewer = _DispatchReviewer()
    await reviewer._ask_llm_for_full_review(_context())

    ask_kwargs = valid_plan["ask_kwargs"]
    assert ask_kwargs["structured_output"].output_type is FullPRReview
    assert ask_kwargs["max_iterations"] == reviewer.max_full_review_tool_calls + 1

    _FakeReviewClient.plans.append({"output": {"verdict": "invented"}})
    with pytest.raises(FullReviewLLMError):
        await reviewer._ask_llm_for_full_review(_context())


async def test_full_review_isolation_failure_precedes_llm_and_closes_owned_resources() -> None:
    """AC5: registry construction failure skips ask, closes the client, and leaves borrowed reads open."""
    _FakeReviewClient.plans.append({"output": _review()})
    reviewer = _DispatchReviewer()
    reviewer.git_toolkit = None

    with pytest.raises(FullReviewLLMError, match="required full-review read toolkit"):
        await reviewer._ask_llm_for_full_review(_context())

    client = _FakeReviewClient.instances[-1]
    assert not client.ask_started.is_set()
    assert client.closed
