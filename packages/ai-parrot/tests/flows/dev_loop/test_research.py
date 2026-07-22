"""Unit tests for parrot.flows.dev_loop.nodes.research (TASK-881, TASK-900)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    FlowtaskCriterion,
    LogSource,
    ResearchOutput,
    ShellCriterion,
    WorkBrief,
)
from parrot.flows.dev_loop.nodes.research import ResearchNode


@pytest.fixture
def good_brief() -> BugBrief:
    return BugBrief(
        summary="customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[
            FlowtaskCriterion(
                name="run", task_path="etl/customers/sync.yaml"
            ),
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


@pytest.fixture
def node(research_out_fixture, monkeypatch, tmp_path):
    # Pin WORKTREE_BASE_PATH to a tmp dir so the duplicate-worktree
    # safety check has a stable target.
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )

    jira = MagicMock()
    jira.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    jira.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    # Duplicate-ticket lookup: no existing issue → the create path runs.
    jira.jira_search_issues = AsyncMock(return_value={"status": "empty"})
    jira.jira_get_issue = AsyncMock(return_value={"status": "error"})
    # Email reporters are resolved to an accountId via jira_find_user.
    jira.jira_find_user = AsyncMock(
        return_value={
            "found": True,
            "matches": [
                {
                    "accountId": "557058:resolved",
                    "emailAddress": "reporter@example.com",
                }
            ],
        }
    )

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=research_out_fixture)

    return ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={
            "cloudwatch": AsyncMock(),
            "elasticsearch": AsyncMock(),
        },
    )


@pytest.fixture
def sample_kwargs() -> dict:
    """Minimal WorkBrief keyword args (no acceptance_criteria)."""
    return {
        "summary": "Customer sync drops the last row when input has >1000 rows",
        "affected_component": "etl/customers/sync.yaml",
        "log_sources": [],
        "escalation_assignee": "oncall@example.com",
        "reporter": "reporter@example.com",
    }


class TestExecutionOrder:
    @pytest.mark.asyncio
    async def test_creates_jira_then_dispatches(self, node, good_brief):
        call_order = []

        async def _jira(**_kwargs):
            call_order.append("jira")
            return {"key": "OPS-1"}

        async def _dispatch(**_kwargs):
            call_order.append("dispatch")
            return ResearchOutput(
                jira_issue_key="OPS-1",
                spec_path="x",
                feat_id="FEAT-1",
                branch_name="feat-1-some-novel-slug",
                worktree_path="/tmp/feat-1-some-novel-slug",
            )

        node._jira.jira_create_issue = AsyncMock(side_effect=_jira)
        node._dispatcher.dispatch = AsyncMock(side_effect=_dispatch)

        await node.execute(
            prompt="",
            ctx={"run_id": "r1", "bug_brief": good_brief},
        )
        assert call_order == ["jira", "dispatch"]

    @pytest.mark.asyncio
    async def test_dispatch_forwards_session_host(self, node, good_brief):
        """FEAT-322: shared["session_host"] must reach dispatcher.dispatch()."""
        sentinel_host = object()

        await node.execute(
            prompt="",
            ctx={
                "run_id": "r1", "bug_brief": good_brief,
                "session_host": sentinel_host,
            },
        )

        kwargs = node._dispatcher.dispatch.await_args.kwargs
        assert kwargs["session_host"] is sentinel_host

    @pytest.mark.asyncio
    async def test_dispatch_session_host_none_when_absent(self, node, good_brief):
        """No "session_host" in shared state (legacy caller) → None default."""
        await node.execute(
            prompt="",
            ctx={"run_id": "r1", "bug_brief": good_brief},
        )

        kwargs = node._dispatcher.dispatch.await_args.kwargs
        assert kwargs["session_host"] is None


class TestReturnValue:
    @pytest.mark.asyncio
    async def test_returns_research_output(self, node, good_brief, tmp_path):
        # Override branch_name so the duplicate-worktree check passes
        node._dispatcher.dispatch = AsyncMock(
            return_value=ResearchOutput(
                jira_issue_key="OPS-2",
                spec_path="sdd/specs/x.spec.md",
                feat_id="FEAT-130",
                branch_name="feat-130-novel-branch",
                worktree_path=str(tmp_path / "feat-130-novel-branch"),
                log_excerpts=[],
            )
        )
        result = await node.execute(
            prompt="",
            ctx={"run_id": "r1", "bug_brief": good_brief},
        )
        assert isinstance(result, ResearchOutput)
        assert result.feat_id == "FEAT-130"


class TestDuplicateWorktree:
    @pytest.mark.asyncio
    async def test_existing_worktree_raises(
        self, node, good_brief, tmp_path
    ):
        # Pre-create the directory the dispatcher's output points at.
        existing = tmp_path / "feat-130-fix-customer-sync"
        existing.mkdir(parents=True)
        with pytest.raises(RuntimeError, match="already exists"):
            await node.execute(
                prompt="",
                ctx={"run_id": "r1", "bug_brief": good_brief},
            )


class TestDispatcherErrorPropagates:
    @pytest.mark.asyncio
    async def test_validation_error_propagates(self, node, good_brief):
        from parrot.flows.dev_loop import DispatchOutputValidationError

        node._dispatcher.dispatch = AsyncMock(
            side_effect=DispatchOutputValidationError(
                "bad payload", raw_payload="{}"
            )
        )
        with pytest.raises(DispatchOutputValidationError):
            await node.execute(
                prompt="",
                ctx={"run_id": "r1", "bug_brief": good_brief},
            )


# ---------------------------------------------------------------------------
# TASK-900 — issuetype routing + plan-summary comment
# ---------------------------------------------------------------------------


class TestIssueTypeRouting:
    """FEAT-132: jira_create_issue receives the correct issuetype per kind."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind, expected", [
        ("bug", "Bug"),
        ("enhancement", "Story"),
        ("new_feature", "New Feature"),
    ])
    async def test_issuetype_per_kind(
        self, node: ResearchNode, sample_kwargs: dict, kind: str, expected: str,
    ):
        """Each work kind maps to the correct Jira issuetype."""
        brief = WorkBrief(
            kind=kind,
            **sample_kwargs,
            acceptance_criteria=[
                ShellCriterion(name="r", command="ruff check ."),
            ],
        )
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "X-1"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        await node.execute({"bug_brief": brief, "run_id": "r1"})
        kwargs = node._jira.jira_create_issue.call_args.kwargs
        assert kwargs["issuetype"] == expected


class TestReporterResolution:
    """Reporter emails are resolved to an accountId before create_issue."""

    @pytest.mark.asyncio
    async def test_email_reporter_resolved_to_account_id(
        self, node: ResearchNode, sample_kwargs: dict
    ):
        """An email reporter is sent as the resolved accountId, not the email."""
        brief = WorkBrief(
            **sample_kwargs,
            acceptance_criteria=[ShellCriterion(name="r", command="ruff check .")],
        )
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "X-1"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        await node.execute({"bug_brief": brief, "run_id": "r1"})
        fields = node._jira.jira_create_issue.call_args.kwargs["fields"]
        assert fields == {"reporter": {"accountId": "557058:resolved"}}
        node._jira.jira_find_user.assert_awaited_once_with("reporter@example.com")

    @pytest.mark.asyncio
    async def test_accountid_reporter_passes_through(
        self, node: ResearchNode, good_brief: BugBrief
    ):
        """An accountId reporter is used verbatim — no lookup performed."""
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "X-1"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        await node.execute({"bug_brief": good_brief, "run_id": "r1"})
        fields = node._jira.jira_create_issue.call_args.kwargs["fields"]
        assert fields == {"reporter": {"accountId": "557058:def"}}
        node._jira.jira_find_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unresolvable_email_omits_reporter(
        self, node: ResearchNode, sample_kwargs: dict
    ):
        """A reporter email with no Jira match omits the field (service acct)."""
        brief = WorkBrief(
            **sample_kwargs,
            acceptance_criteria=[ShellCriterion(name="r", command="ruff check .")],
        )
        node._jira.jira_find_user = AsyncMock(
            return_value={"found": False, "matches": []}
        )
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "X-1"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        await node.execute({"bug_brief": brief, "run_id": "r1"})
        fields = node._jira.jira_create_issue.call_args.kwargs["fields"]
        assert fields is None


class TestPlanSummaryOnCreate:
    """FEAT-132: plan-summary comment is posted on the new-ticket path."""

    @pytest.mark.asyncio
    async def test_plan_comment_posted_on_create(
        self, node: ResearchNode, good_brief: BugBrief
    ):
        """When a new ticket is created, a 'Plan for run-' comment is posted."""
        node._jira.jira_search_issues = AsyncMock(return_value={"status": "empty"})
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "NAV-1"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        # Stub the plan client so no network call is made.
        fake_response = MagicMock(response="Step 1.\nStep 2.")
        node._plan_client = MagicMock()
        node._plan_client.ask = AsyncMock(return_value=fake_response)
        await node.execute({"bug_brief": good_brief, "run_id": "r2"})
        bodies = [
            c.kwargs["body"]
            for c in node._jira.jira_add_comment.call_args_list
        ]
        assert any(b.startswith("Plan for run-r2") for b in bodies)

    @pytest.mark.asyncio
    async def test_plan_comment_body_includes_llm_output(
        self, node: ResearchNode, good_brief: BugBrief
    ):
        """The comment body includes the LLM-generated plan text."""
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "NAV-1"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        fake_response = MagicMock(response="Fix the ETL pipeline.")
        node._plan_client = MagicMock()
        node._plan_client.ask = AsyncMock(return_value=fake_response)
        await node.execute({"bug_brief": good_brief, "run_id": "r2"})
        bodies = [
            c.kwargs["body"]
            for c in node._jira.jira_add_comment.call_args_list
        ]
        plan_bodies = [b for b in bodies if b.startswith("Plan for run-r2")]
        assert plan_bodies
        assert "Fix the ETL pipeline." in plan_bodies[0]


class TestPlanSummaryNotOnReuse:
    """FEAT-132: no plan-summary comment on the reuse (re-trigger) path."""

    @pytest.mark.asyncio
    async def test_no_plan_comment_when_reused(
        self, node: ResearchNode, good_brief: BugBrief
    ):
        """On the reuse path, only the re-triggered comment is posted."""
        brief = good_brief.model_copy(update={"existing_issue_key": "NAV-99"})
        node._jira.jira_get_issue = AsyncMock(return_value={"key": "NAV-99"})
        node._jira.jira_create_issue = AsyncMock(
            side_effect=AssertionError("jira_create_issue must not be called on reuse")
        )
        node._jira.jira_add_comment = AsyncMock(return_value={})
        await node.execute({"bug_brief": brief, "run_id": "r3"})
        bodies = [
            c.kwargs["body"]
            for c in node._jira.jira_add_comment.call_args_list
        ]
        # No "Plan for run-" comment on the reuse path.
        assert not any(b.startswith("Plan for run-") for b in bodies)


class TestPlanSummaryFallback:
    """FEAT-132: LLM failure falls back to a deterministic stub."""

    @pytest.mark.asyncio
    async def test_falls_back_to_stub_on_llm_error(
        self, node: ResearchNode, good_brief: BugBrief
    ):
        """When the plan LLM raises, a deterministic stub is posted instead."""
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "NAV-2"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        node._plan_client = MagicMock()
        node._plan_client.ask = AsyncMock(side_effect=RuntimeError("llm-error"))
        await node.execute({"bug_brief": good_brief, "run_id": "r4"})
        bodies = [
            c.kwargs["body"]
            for c in node._jira.jira_add_comment.call_args_list
        ]
        # The comment is still posted; the stub body starts with "Plan for run-".
        assert any("Plan for run-r4" in b for b in bodies)


class TestCloudWatchExcerptCleaning:
    """Clean + filter structured log payloads at the source.

    Raw CloudWatch Insights results were being ``str()``-dumped into the
    Jira ticket (and the research prompt), leaking base64 ``@ptr`` cursors
    and health-probe noise. ``_tail_text`` now reduces them to a compact
    ``[ts] message`` digest with the noise filtered out.
    """

    def _payload(self) -> dict:
        return {
            "log_group": "fluent-bit-cloudwatch",
            "results": [
                {
                    "@timestamp": "2026-06-23 23:35:55.427",
                    "@message": "INFO Rendered layouts/application.html.erb",
                    "@ptr": "Cp0BCl4KIjI5ODA1MTE4MDM5OD_base64_cursor_noise",
                },
                {
                    "@timestamp": "2026-06-23 23:35:55.342",
                    "@message": '1.2.3.4 - - "GET /health HTTP/1.1" 200 2 "kube-probe/1.33"',
                    "@ptr": "Cp0B_more_noise",
                },
                {
                    "@timestamp": "2026-06-23 23:35:55.406",
                    "@message": 'httplog.go:129 "HTTP" verb="GET" URI="/healthz" resp=200',
                    "@ptr": "Cp0B_noise",
                },
                {
                    "@timestamp": "2026-06-23 23:35:55.267",
                    "@message": 'E0623 cert-manager/challenges: propagation check failed err="404"',
                    "@ptr": "Cp0B_noise",
                },
            ],
            "count": 4,
        }

    def test_drops_ptr_cursors_and_probe_noise_keeps_errors(self):
        out = ResearchNode._tail_text(self._payload())
        assert len(out) == 1
        digest = out[0]
        # @ptr base64 cursors never reach the ticket.
        assert "Cp0B" not in digest and "base64" not in digest
        # Health-probe / framework chatter is filtered out.
        assert "kube-probe" not in digest
        assert "/healthz" not in digest
        assert "Rendered" not in digest
        # The real ERROR line survives, formatted as "[ts] message".
        assert "cert-manager" in digest
        assert digest.startswith("[2026-06-23 23:35:55.267]")

    def test_all_noise_falls_back_to_ptr_stripped_tail(self):
        payload = {
            "results": [
                {"@timestamp": "t1", "@message": "kube-probe ping", "@ptr": "X"},
            ]
        }
        out = ResearchNode._tail_text(payload)
        # Never emit an empty block; @ptr is still stripped on the fallback.
        assert out and "X" not in out[0]
        assert "kube-probe ping" in out[0]

    def test_non_dict_results_unchanged(self):
        assert ResearchNode._tail_text("plain log text") == ["plain log text"]
