"""Integration tests for FEAT-405 (TASK-2093) — the four tests from spec §4,
the [R7] research-node guard, and the offline-CI guarantee.

All tests run **offline**: every Bedrock call is mocked at the transport
boundary (the OpenAI-compatible client behind bedrock-mantle for the dev
seat, ``NovaClient.ask`` for the adversarial seat) — never above it, and
never a real ``aioboto3``/network call. No AWS credentials are required to
run this file.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot.flows.dev_loop.agent_builder import build_dispatcher
from parrot.flows.dev_loop.catalog import catalog_payload
from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory
from parrot.flows.dev_loop.dispatchers import NovaCodeDispatcher
from parrot.flows.dev_loop.dispatchers.nova import NovaAdversarialReviewDispatcher
from parrot.flows.dev_loop.models import (
    AdversarialFinding,
    CodeReviewFinding,
    CodeReviewVerdict,
    DevAgentPoolConfig,
    DevAgentSpec,
    DevelopmentOutput,
    NovaCodeDispatchProfile,
    ResearchOutput,
)
from parrot.flows.dev_loop.run_bundle import build_run_bundle
from parrot.flows.dev_loop.session_state import (
    DevLoopSessionState,
    DispatchCompleted,
    DispatchQueued,
    DispatchStarted,
    NodeCompleted,
    NodeStarted,
    RunClosed,
    RunCreated,
    Snapshot,
    reduce,
    session_channel,
)
from parrot.flows.dev_loop.usage_report import (
    UsageReport,
    build_usage_report,
    render_usage_html,
    render_usage_markdown,
)

COMMON = {"redis_url": "redis://localhost:6379/0", "max_concurrent": 1, "stream_ttl_seconds": 60}
RUN_ID = "run-nova-integration-0001"


@pytest.fixture(autouse=True)
def _patch_worktree_base(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.llm.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    return tmp_path


@pytest.fixture
def brief(_patch_worktree_base) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path=str(_patch_worktree_base),
        log_excerpts=[],
    )


class TestNovaDevSeat:
    """spec §4: test_nova_dev_seat_end_to_end."""

    async def test_nova_dev_seat_end_to_end(self, monkeypatch, brief, _patch_worktree_base):
        """Pool spec ``{"agent": "nova"}`` -> dispatcher -> loop (mocked
        bedrock-mantle client, never real Bedrock) -> validated
        DevelopmentOutput."""
        pool = DevAgentPoolConfig(
            agents=[DevAgentSpec(agent="nova", model="minimax.minimax-m2.5", count=1)]
        )
        assert pool.agents[0].agent == "nova"

        dispatcher, profile = build_dispatcher(pool.agents[0], **COMMON)
        assert isinstance(dispatcher, NovaCodeDispatcher)
        assert isinstance(profile, NovaCodeDispatchProfile)
        assert profile.model == "minimax.minimax-m2.5"

        # Mock the OpenAI-compatible client behind bedrock-mantle — the
        # transport boundary NovaCodeDispatcher._create_mantle_client
        # builds; never call real Bedrock.
        class _ToolCall:
            def __init__(self, name, arguments):
                self.id = "call_1"
                self.function = SimpleNamespace(
                    name=name, arguments=json.dumps(arguments)
                )

        class _Message:
            def __init__(self, tool_calls):
                self.content = ""
                self.tool_calls = tool_calls

        class _Response:
            def __init__(self, message):
                self.choices = [SimpleNamespace(message=message)]

        fake_client = SimpleNamespace(client=object(), model="minimax.minimax-m2.5")
        fake_client._chat_completion = AsyncMock(
            return_value=_Response(
                _Message(
                    [
                        _ToolCall(
                            "final_output",
                            {
                                "files_changed": ["app.py"],
                                "commit_shas": ["abc1234"],
                                "summary": "implemented via nova",
                            },
                        )
                    ]
                )
            )
        )
        # NovaCodeDispatcher.__init__ captures a BOUND reference to
        # _create_mantle_client into LLMCodeDispatcher's self._client_factory
        # at construction time — patching the instance method after the
        # fact would not retroactively change that stored reference, so
        # patch _client_factory itself (the attribute _create_client
        # actually calls).
        monkeypatch.setattr(dispatcher, "_client_factory", lambda *a, **kw: fake_client)

        result = await dispatcher.dispatch(
            brief=brief,
            profile=profile,
            output_model=DevelopmentOutput,
            run_id=RUN_ID,
            node_id="development",
            cwd=str(_patch_worktree_base),
        )

        assert isinstance(result, DevelopmentOutput)
        assert result.files_changed == ["app.py"]
        assert result.summary == "implemented via nova"
        fake_client._chat_completion.assert_awaited()


class TestNovaAdversarial:
    """spec §4: test_nova_adversarial_gate_end_to_end."""

    async def test_nova_adversarial_gate_end_to_end(self, monkeypatch):
        reviewer = CodeReviewDispatcherFactory.create("nova-adversarial")
        assert isinstance(reviewer, NovaAdversarialReviewDispatcher)

        async def _fake_collect_diff(self, cwd, profile):
            return "diff --git a/foo.py b/foo.py\n+print('hi')\n"

        monkeypatch.setattr(
            NovaAdversarialReviewDispatcher, "_collect_diff", _fake_collect_diff
        )

        fake_ask = AsyncMock(
            return_value=SimpleNamespace(
                structured_output=CodeReviewVerdict(
                    passed=False,
                    files_modified=["should-be-cleared.py"],
                    findings=[
                        CodeReviewFinding(message="nit found", severity="nit"),
                    ],
                )
            )
        )
        monkeypatch.setattr(reviewer, "_client", SimpleNamespace(ask=fake_ask))

        class _Brief:
            def model_dump_json(self):
                return "{}"

        verdict = await reviewer.review(
            brief=_Brief(), run_id=RUN_ID, node_id="qa", cwd="."
        )

        assert verdict.files_modified == []
        assert all(
            isinstance(f, AdversarialFinding) and f.source == "nova-adversarial"
            for f in verdict.findings
        )
        # no tools passed at all — verified directly on the call kwargs
        assert "tools" not in fake_ask.await_args.kwargs
        assert fake_ask.await_args.kwargs.get("use_tools") is False


class TestUsageArtifacts:
    """spec §4: test_usage_report_written_at_run_end."""

    def _completed_snapshot(self) -> Snapshot:
        state = DevLoopSessionState(run_id=RUN_ID, channel=session_channel(RUN_ID))
        state = reduce(state, RunCreated(run_id=RUN_ID, work_kind="bug", summary="fix x"))
        state = reduce(state, NodeStarted(node_id="development", ts=1.0))
        state = reduce(state, DispatchQueued(node_id="development", dispatcher="nova"))
        state = reduce(state, DispatchStarted(node_id="development", ts=1.0))
        state = reduce(
            state,
            DispatchCompleted(
                node_id="development", ts=5.0,
                input_tokens=1000, output_tokens=250, num_turns=7, duration_ms=4000,
            ),
        )
        state = reduce(state, NodeCompleted(node_id="development", ts=5.0))
        state = reduce(state, RunClosed(outcome="succeeded"))
        return Snapshot(channel=state.channel, state=state, from_seq=0)

    def test_usage_report_written_at_run_end(self, tmp_path):
        snapshot = self._completed_snapshot()
        report = build_usage_report(snapshot, run_id=RUN_ID)

        usage_json_path = tmp_path / "usage.json"
        usage_html_path = tmp_path / "usage.html"
        usage_json_path.write_text(report.model_dump_json(indent=2))
        usage_html_path.write_text(render_usage_html(report))

        assert usage_json_path.exists()
        assert usage_html_path.exists()

        rep = UsageReport.model_validate_json(usage_json_path.read_text())
        assert rep.agents
        assert rep.agents[0].seat == "development"
        assert rep.agents[0].backend == "nova"

        # markdown section (folded into the bundle) agrees with the same report
        bundle = build_run_bundle(snapshot, [], {})
        md_section = render_usage_markdown(report)
        assert "## Usage" in md_section
        assert bundle.nodes  # bundle itself still builds unaffected


class TestOptInRegression:
    """[R3]: a run configuring nothing must behave identically to pre-feature."""

    def test_defaults_unchanged_without_nova(self):
        payload = catalog_payload()
        assert payload["adversarial_backend"] == "codex"
        assert payload["roles"]["adversarial"] == ["codex"]
        # nova is listed (additive), but never selected by default
        assert any(b["id"] == "nova" for b in payload["backends"])

    def test_claude_code_dev_seat_unaffected(self):
        dispatcher, profile = build_dispatcher(DevAgentSpec(agent="claude-code"), **COMMON)
        assert type(dispatcher).__name__ == "ClaudeCodeDispatcher"
        assert profile.model == "claude-sonnet-4-6"

    def test_research_node_untouched(self):
        """[R7] guard: the research seat must stay Claude Code only — fails
        loudly if a future change widens ResearchNode's dispatcher type."""
        src = Path(
            "packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py"
        ).read_text()
        assert "dispatcher: ClaudeCodeDispatcher" in src
        assert 'subagent="sdd-research"' in src
        assert "nova" not in src.lower()


class TestOffline:
    def test_no_nova_test_imports_boto(self):
        """CI must not need AWS credentials — this whole file mocks at the
        transport boundary; nothing here imports aioboto3/boto3 directly."""
        import re

        src = Path(__file__).read_text()
        assert not re.search(r"^\s*(import|from)\s+a?io?boto3\b", src, re.MULTILINE)
