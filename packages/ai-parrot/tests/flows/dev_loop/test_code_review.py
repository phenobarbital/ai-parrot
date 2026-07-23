"""Tests for the multi-dispatcher code review gate (FEAT-270)."""

import importlib.util
import sys
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.flows.dev_loop import BugBrief, FlowtaskCriterion, QAReport, ResearchOutput
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    ClaudeCodeReviewDispatcher,
    CodeReviewDispatcherFactory,
    CodexCodeReviewDispatcher,
    GeminiCodeReviewDispatcher,
)
from parrot.flows.dev_loop.models import (
    ClaudeCodeReviewProfile,
    CodeReviewFinding,
    CodeReviewVerdict,
    CodexCodeReviewProfile,
    GeminiCodeReviewProfile,
)
from parrot.flows.dev_loop.nodes.qa import QANode


class _DummyReviewer(AbstractCodeReviewDispatcher):
    agent_name = "dummy"

    async def review(self, *, brief, run_id, node_id, cwd):
        return None  # placeholder

    def build_review_profile(self):
        return None  # placeholder


class TestCodeReviewDispatcherFactory:
    def test_register_and_create(self):
        CodeReviewDispatcherFactory.register("dummy")(_DummyReviewer)
        instance = CodeReviewDispatcherFactory.create("dummy")
        assert isinstance(instance, _DummyReviewer)

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown code review dispatcher"):
            CodeReviewDispatcherFactory.create("nonexistent")

    def test_abc_cannot_instantiate(self):
        with pytest.raises(TypeError):
            AbstractCodeReviewDispatcher()


class TestCodeReviewFinding:
    def test_valid_finding(self):
        f = CodeReviewFinding(
            message="Missing guard", severity="critical", file="sync.py", line=88
        )
        assert f.severity == "critical"
        assert f.file == "sync.py"
        assert f.line == 88

    def test_invalid_severity_rejected(self):
        with pytest.raises(Exception):
            CodeReviewFinding(message="x", severity="blocker")

    def test_defaults(self):
        f = CodeReviewFinding(message="x", severity="nit")
        assert f.file == ""
        assert f.line == 0


class TestCodeReviewVerdict:
    def test_default_is_pass(self):
        v = CodeReviewVerdict()
        assert v.passed is True
        assert v.findings == []
        assert v.files_modified == []

    def test_with_findings(self):
        f = CodeReviewFinding(message="issue", severity="major")
        v = CodeReviewVerdict(passed=False, findings=[f], summary="Has issues")
        assert not v.passed
        assert len(v.findings) == 1


class TestReviewProfiles:
    def test_claude_profile_has_write_tools(self):
        p = ClaudeCodeReviewProfile()
        assert "Edit" in p.allowed_tools
        assert "Write" in p.allowed_tools
        assert p.permission_mode == "default"

    def test_codex_profile_write_sandbox(self):
        p = CodexCodeReviewProfile()
        assert p.sandbox == "workspace-write"
        assert p.approval_policy == "on-request"

    def test_gemini_profile_no_sandbox(self):
        p = GeminiCodeReviewProfile()
        assert p.sandbox is False
        assert p.approval_mode == "auto_edit"


class TestClaudeCodeReviewDispatcher:
    def test_agent_name(self):
        d = ClaudeCodeReviewDispatcher(dispatcher=MagicMock())
        assert d.agent_name == "claude-code"

    def test_registered_in_factory(self):
        d = CodeReviewDispatcherFactory.create("claude-code", dispatcher=MagicMock())
        assert isinstance(d, ClaudeCodeReviewDispatcher)

    def test_build_review_profile(self):
        d = ClaudeCodeReviewDispatcher(dispatcher=MagicMock())
        p = d.build_review_profile()
        assert isinstance(p, ClaudeCodeReviewProfile)
        assert p.permission_mode == "default"
        assert "Edit" in p.allowed_tools

    @pytest.mark.asyncio
    async def test_review_delegates(self):
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(return_value=CodeReviewVerdict(passed=True))
        d = ClaudeCodeReviewDispatcher(dispatcher=mock_disp)
        result = await d.review(brief=MagicMock(), run_id="r1", node_id="qa", cwd="/tmp")
        assert result.passed is True
        mock_disp.dispatch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_review_forwards_session_host(self):
        """FEAT-322: review(session_host=...) must reach dispatch()."""
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(return_value=CodeReviewVerdict(passed=True))
        d = ClaudeCodeReviewDispatcher(dispatcher=mock_disp)
        sentinel_host = object()

        await d.review(
            brief=MagicMock(), run_id="r1", node_id="qa", cwd="/tmp",
            session_host=sentinel_host,
        )

        assert mock_disp.dispatch.await_args.kwargs["session_host"] is sentinel_host

    @pytest.mark.asyncio
    async def test_review_session_host_defaults_to_none(self):
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(return_value=CodeReviewVerdict(passed=True))
        d = ClaudeCodeReviewDispatcher(dispatcher=mock_disp)

        await d.review(brief=MagicMock(), run_id="r1", node_id="qa", cwd="/tmp")

        assert mock_disp.dispatch.await_args.kwargs["session_host"] is None

    @pytest.mark.asyncio
    async def test_review_degrades_on_error(self):
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(side_effect=RuntimeError("boom"))
        d = ClaudeCodeReviewDispatcher(dispatcher=mock_disp)
        result = await d.review(brief=MagicMock(), run_id="r1", node_id="qa", cwd="/tmp")
        assert result.passed is True
        assert any("code-review could not run" in f.message for f in result.findings)


class TestCodexCodeReviewDispatcher:
    def test_agent_name(self):
        d = CodexCodeReviewDispatcher(dispatcher=MagicMock())
        assert d.agent_name == "codex"

    def test_registered_in_factory(self):
        d = CodeReviewDispatcherFactory.create("codex", dispatcher=MagicMock())
        assert isinstance(d, CodexCodeReviewDispatcher)

    def test_build_review_profile(self):
        d = CodexCodeReviewDispatcher(dispatcher=MagicMock())
        p = d.build_review_profile()
        assert isinstance(p, CodexCodeReviewProfile)
        assert p.sandbox == "workspace-write"
        assert p.approval_policy == "on-request"

    @pytest.mark.asyncio
    async def test_review_delegates(self):
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(return_value=CodeReviewVerdict(passed=True))
        d = CodexCodeReviewDispatcher(dispatcher=mock_disp)
        result = await d.review(brief=MagicMock(), run_id="r1", node_id="qa", cwd="/tmp")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_review_degrades_on_error(self):
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(side_effect=RuntimeError("boom"))
        d = CodexCodeReviewDispatcher(dispatcher=mock_disp)
        result = await d.review(brief=MagicMock(), run_id="r1", node_id="qa", cwd="/tmp")
        assert result.passed is True
        assert any("code-review could not run" in f.message for f in result.findings)


class TestGeminiCodeReviewDispatcher:
    def test_agent_name(self):
        d = GeminiCodeReviewDispatcher(dispatcher=MagicMock())
        assert d.agent_name == "gemini"

    def test_registered_in_factory(self):
        d = CodeReviewDispatcherFactory.create("gemini", dispatcher=MagicMock())
        assert isinstance(d, GeminiCodeReviewDispatcher)

    def test_build_review_profile(self):
        d = GeminiCodeReviewDispatcher(dispatcher=MagicMock())
        p = d.build_review_profile()
        assert isinstance(p, GeminiCodeReviewProfile)
        assert p.sandbox is False
        assert p.approval_mode == "auto_edit"

    @pytest.mark.asyncio
    async def test_review_delegates(self):
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(return_value=CodeReviewVerdict(passed=True))
        d = GeminiCodeReviewDispatcher(dispatcher=mock_disp)
        result = await d.review(brief=MagicMock(), run_id="r1", node_id="qa", cwd="/tmp")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_review_degrades_on_error(self):
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(side_effect=RuntimeError("boom"))
        d = GeminiCodeReviewDispatcher(dispatcher=mock_disp)
        result = await d.review(brief=MagicMock(), run_id="r1", node_id="qa", cwd="/tmp")
        assert result.passed is True
        assert any("code-review could not run" in f.message for f in result.findings)


class TestServerWiring:
    """FEAT-270 Module 7 — factory-level wiring smoke tests."""

    def test_factory_creates_claude(self):
        d = CodeReviewDispatcherFactory.create("claude-code", dispatcher=MagicMock())
        assert d.agent_name == "claude-code"

    def test_factory_creates_codex(self):
        d = CodeReviewDispatcherFactory.create("codex", dispatcher=MagicMock())
        assert d.agent_name == "codex"

    def test_factory_creates_gemini(self):
        d = CodeReviewDispatcherFactory.create("gemini", dispatcher=MagicMock())
        assert d.agent_name == "gemini"


class TestBuildDevLoopNodeFactoriesWiring:
    """FEAT-270 — codereview_dispatcher threads through the factory chain."""

    def test_qa_factory_uses_explicit_codereview_dispatcher(self):
        from parrot.bots.flows.flow.definition import NodeDefinition
        from parrot.flows.dev_loop.factories import build_dev_loop_node_factories

        mock_reviewer = MagicMock()
        factories = build_dev_loop_node_factories(
            dispatcher=MagicMock(),
            jira_toolkit=MagicMock(),
            redis_url="redis://localhost:6379/0",
            codereview_dispatcher=mock_reviewer,
        )
        nd = NodeDefinition(id="qa", type="dev_loop.qa")
        node = factories["dev_loop.qa"](nd, set(), set())
        assert node._codereview_dispatcher is mock_reviewer

    def test_qa_factory_defaults_codereview_dispatcher(self):
        from parrot.bots.flows.flow.definition import NodeDefinition
        from parrot.flows.dev_loop.factories import build_dev_loop_node_factories

        factories = build_dev_loop_node_factories(
            dispatcher=MagicMock(),
            jira_toolkit=MagicMock(),
            redis_url="redis://localhost:6379/0",
        )
        nd = NodeDefinition(id="qa", type="dev_loop.qa")
        node = factories["dev_loop.qa"](nd, set(), set())
        assert isinstance(node._codereview_dispatcher, ClaudeCodeReviewDispatcher)


class TestBuildDevLoopNodeFactoriesRequireDeploymentApproval:
    """FEAT-322 code-review follow-up: require_deployment_approval threads
    through the factory chain to a real, production-reachable
    DeploymentHandoffNode instance (previously only settable via
    object.__setattr__ from a test)."""

    def test_handoff_factory_defaults_to_false(self):
        from parrot.bots.flows.flow.definition import NodeDefinition
        from parrot.flows.dev_loop.factories import build_dev_loop_node_factories

        factories = build_dev_loop_node_factories(
            dispatcher=MagicMock(),
            jira_toolkit=MagicMock(),
            redis_url="redis://localhost:6379/0",
        )
        nd = NodeDefinition(id="deployment_handoff", type="dev_loop.deployment_handoff")
        node = factories["dev_loop.deployment_handoff"](nd, set(), set())
        assert node._require_deployment_approval is False

    def test_handoff_factory_forwards_true(self):
        from parrot.bots.flows.flow.definition import NodeDefinition
        from parrot.flows.dev_loop.factories import build_dev_loop_node_factories

        factories = build_dev_loop_node_factories(
            dispatcher=MagicMock(),
            jira_toolkit=MagicMock(),
            redis_url="redis://localhost:6379/0",
            require_deployment_approval=True,
        )
        nd = NodeDefinition(id="deployment_handoff", type="dev_loop.deployment_handoff")
        node = factories["dev_loop.deployment_handoff"](nd, set(), set())
        assert node._require_deployment_approval is True

    def test_build_dev_loop_flow_forwards_require_deployment_approval(self):
        from parrot.flows.dev_loop.flow import build_dev_loop_flow

        flow = build_dev_loop_flow(
            dispatcher=MagicMock(),
            jira_toolkit=MagicMock(),
            log_toolkits={},
            redis_url="redis://localhost:6379/0",
            publish_flow_events=False,
            require_deployment_approval=True,
        )
        assert flow._nodes["deployment_handoff"]._require_deployment_approval is True


@pytest.fixture
def qa_ctx() -> dict:
    """Minimal QANode.execute() context, mirroring test_qa_codereview.py."""
    return {
        "run_id": "r1",
        "research_output": ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="x",
            feat_id="FEAT-130",
            branch_name="feat-130-fix",
            worktree_path="/abs/.claude/worktrees/feat-130-fix",
        ),
        "bug_brief": BugBrief(
            summary="x" * 20,
            affected_component="y",
            log_sources=[],
            acceptance_criteria=[FlowtaskCriterion(name="run", task_path="a.yaml")],
            escalation_assignee="a",
            reporter="b",
        ),
    }


class TestFullQAFlowIntegration:
    """FEAT-270 Module 9 — end-to-end deterministic QA -> review -> fix -> rerun."""

    @pytest.mark.asyncio
    async def test_claude_review_fix_rerun(self, qa_ctx):
        """Full QA -> Claude review -> fix -> rerun cycle."""
        underlying = MagicMock()
        underlying.dispatch = AsyncMock(
            side_effect=[
                QAReport(passed=True, criterion_results=[], lint_passed=True),
                CodeReviewVerdict(
                    passed=True,
                    findings=[
                        CodeReviewFinding(message="fixed null guard", severity="minor")
                    ],
                    files_modified=["sync.py"],
                ),
                QAReport(passed=True, criterion_results=[], lint_passed=True),
            ]
        )
        reviewer = ClaudeCodeReviewDispatcher(dispatcher=underlying)
        node = QANode(dispatcher=underlying, codereview_dispatcher=reviewer)
        report = await node.execute(qa_ctx)
        assert report.passed is True
        assert report.code_review_findings == ["fixed null guard"]
        assert underlying.dispatch.await_count == 3

    @pytest.mark.asyncio
    async def test_codex_review_fix_rerun(self, qa_ctx):
        """Full QA -> Codex review -> fix -> rerun cycle (separate dispatcher)."""
        qa_dispatcher = MagicMock()
        qa_dispatcher.dispatch = AsyncMock(
            side_effect=[
                QAReport(passed=True, criterion_results=[], lint_passed=True),
                QAReport(passed=True, criterion_results=[], lint_passed=True),
            ]
        )
        codex_dispatcher = MagicMock()
        codex_dispatcher.dispatch = AsyncMock(
            return_value=CodeReviewVerdict(
                passed=True, findings=[], files_modified=["sync.py"]
            )
        )
        reviewer = CodexCodeReviewDispatcher(dispatcher=codex_dispatcher)
        node = QANode(dispatcher=qa_dispatcher, codereview_dispatcher=reviewer)
        report = await node.execute(qa_ctx)
        assert report.passed is True
        assert qa_dispatcher.dispatch.await_count == 2
        codex_dispatcher.dispatch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_gemini_review_pass_no_fix(self, qa_ctx):
        """Full QA -> Gemini review passes -> no rerun needed."""
        qa_dispatcher = MagicMock()
        qa_dispatcher.dispatch = AsyncMock(
            return_value=QAReport(passed=True, criterion_results=[], lint_passed=True)
        )
        gemini_dispatcher = MagicMock()
        gemini_dispatcher.dispatch = AsyncMock(
            return_value=CodeReviewVerdict(passed=True, findings=[], files_modified=[])
        )
        reviewer = GeminiCodeReviewDispatcher(dispatcher=gemini_dispatcher)
        node = QANode(dispatcher=qa_dispatcher, codereview_dispatcher=reviewer)
        report = await node.execute(qa_ctx)
        assert report.passed is True
        qa_dispatcher.dispatch.assert_awaited_once()
        gemini_dispatcher.dispatch.assert_awaited_once()


class _FakeApp(dict):
    """Minimal stand-in for ``aiohttp.web.Application``."""


def _make_fake_redis() -> MagicMock:
    redis = MagicMock()
    redis.aclose = AsyncMock()
    return redis


def _load_server_module():
    """Load examples/dev_loop/server.py as a Python module.

    Mirrors the helper in test_server_repo_wiring.py (FEAT-253 TASK-004) —
    duplicated locally so this file has no cross-test-module dependency.
    """
    server_path = Path(__file__).parents[5] / "examples" / "dev_loop" / "server.py"
    if not server_path.exists():
        pytest.skip(f"server.py not found at {server_path}")
    module_name = "_dev_loop_server_under_test_codereview"
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, server_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _CodeReviewAgentConfig:
    """Fake ``conf.config`` returning a fixed DEV_LOOP_CODEREVIEW_AGENT."""

    def __init__(self, codereview_agent: str) -> None:
        self._codereview_agent = codereview_agent

    def get(self, name: str, fallback=None):
        if name == "DEV_LOOP_CODEREVIEW_AGENT":
            return self._codereview_agent
        return fallback

    def getint(self, name: str, fallback=None):
        return fallback

    def getboolean(self, name: str, fallback=None):
        return fallback


class TestServerWiringIntegration:
    """FEAT-270 — DEV_LOOP_CODEREVIEW_AGENT selects the reviewer at boot."""

    @staticmethod
    def _patch_common(monkeypatch, server_mod, captured):
        def fake_build_flow(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(server_mod, "build_dev_loop_flow", fake_build_flow)
        monkeypatch.setattr(server_mod, "_build_log_toolkits", lambda: {})
        monkeypatch.setattr(server_mod, "_build_jira_toolkit", lambda: MagicMock())
        monkeypatch.setattr(server_mod, "_build_git_toolkit", lambda: MagicMock())
        monkeypatch.setattr(
            server_mod.aioredis, "from_url", lambda url, **kw: _make_fake_redis()
        )
        monkeypatch.setattr(
            server_mod, "ClaudeCodeDispatcher", MagicMock(return_value=MagicMock())
        )
        monkeypatch.setattr(
            server_mod,
            "DevLoopRunner",
            MagicMock(return_value=MagicMock(max_concurrent_runs=1)),
        )

    @pytest.mark.asyncio
    async def test_server_wiring_default(self, monkeypatch):
        """No DEV_LOOP_CODEREVIEW_AGENT set -> default Claude reviewer."""
        captured: dict = {}
        server_mod = _load_server_module()
        self._patch_common(monkeypatch, server_mod, captured)
        monkeypatch.setattr(
            server_mod.conf, "config", _CodeReviewAgentConfig("claude-code")
        )

        app = _FakeApp()
        app["redis_url"] = "redis://localhost:6379/0"
        await server_mod._on_startup(app)

        assert isinstance(captured["codereview_dispatcher"], ClaudeCodeReviewDispatcher)

    @pytest.mark.asyncio
    async def test_server_wiring_codex(self, monkeypatch):
        """DEV_LOOP_CODEREVIEW_AGENT=codex -> Codex reviewer."""
        captured: dict = {}
        server_mod = _load_server_module()
        self._patch_common(monkeypatch, server_mod, captured)
        monkeypatch.setattr(server_mod.conf, "config", _CodeReviewAgentConfig("codex"))

        app = _FakeApp()
        app["redis_url"] = "redis://localhost:6379/0"
        await server_mod._on_startup(app)

        assert isinstance(captured["codereview_dispatcher"], CodexCodeReviewDispatcher)

    @pytest.mark.asyncio
    async def test_server_wiring_gemini(self, monkeypatch):
        """DEV_LOOP_CODEREVIEW_AGENT=gemini -> Gemini reviewer."""
        captured: dict = {}
        server_mod = _load_server_module()
        self._patch_common(monkeypatch, server_mod, captured)
        monkeypatch.setattr(server_mod.conf, "config", _CodeReviewAgentConfig("gemini"))

        app = _FakeApp()
        app["redis_url"] = "redis://localhost:6379/0"
        await server_mod._on_startup(app)

        assert isinstance(captured["codereview_dispatcher"], GeminiCodeReviewDispatcher)

    @pytest.mark.asyncio
    async def test_server_wiring_invalid(self, monkeypatch):
        """Invalid DEV_LOOP_CODEREVIEW_AGENT raises RuntimeError."""
        captured: dict = {}
        server_mod = _load_server_module()
        self._patch_common(monkeypatch, server_mod, captured)
        monkeypatch.setattr(
            server_mod.conf, "config", _CodeReviewAgentConfig("not-a-real-agent")
        )

        app = _FakeApp()
        app["redis_url"] = "redis://localhost:6379/0"
        with pytest.raises(RuntimeError):
            await server_mod._on_startup(app)
