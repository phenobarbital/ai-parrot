"""Unit tests for the Haiku PR-body enrichment (FEAT-405, TASK-2092, Module 8).

"Enrich, never replace" ([R2]): the deterministic template stays the
skeleton *and* the fallback. Tests cover both handoff nodes
(``FeatureHandoffNode``, ``DeploymentHandoffNode``) and the mechanical-seat
helper (``summarize_pr_changes``) itself.

Every ``monkeypatch.setattr`` call below targets a module object resolved
via ``sys.modules[...]`` rather than monkeypatch's dotted-string form.
``test_lazy_import.py`` deletes and re-imports every
``parrot.flows.dev_loop.*`` module during its own test bodies, then
restores the ``sys.modules`` dict entries — but a dotted string resolves
through **parent-package attribute chains**
(``getattr(parrot.flows.dev_loop.nodes, "feature_handoff")``), and that
surgery can leave a parent package's attribute pointing at a module object
``sys.modules`` no longer holds, silently patching an orphaned object
instead of the live one (verified empirically: when
``test_lazy_import.py`` runs before this file, dotted-string patches
silently no-op and every real ``NovaClient()``/``ask()`` call is attempted
instead). Indexing ``sys.modules`` directly is immune to that.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock

import pytest
from parrot.flows.dev_loop.dispatchers.nova import summarize_pr_changes
from parrot.flows.dev_loop.models import (
    BugBrief,
    CriterionResult,
    DevelopmentOutput,
    FlowtaskCriterion,
    PlannerOutput,
    QAReport,
    ResearchOutput,
    SynthesisReport,
)
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.nodes.feature_handoff import FeatureHandoffNode


def _mod(name: str):
    """Resolve a module via ``sys.modules`` — see module docstring."""
    return sys.modules[name]


def _patch_feature_summary(monkeypatch, **mock_kwargs) -> AsyncMock:
    mock = AsyncMock(**mock_kwargs)
    monkeypatch.setattr(
        _mod("parrot.flows.dev_loop.nodes.feature_handoff"),
        "summarize_pr_changes",
        mock,
    )
    return mock


def _patch_deployment_summary(monkeypatch, **mock_kwargs) -> AsyncMock:
    mock = AsyncMock(**mock_kwargs)
    monkeypatch.setattr(
        _mod("parrot.flows.dev_loop.nodes.deployment_handoff"),
        "summarize_pr_changes",
        mock,
    )
    return mock


def _patch_nova_client(monkeypatch, factory) -> None:
    monkeypatch.setattr(
        _mod("parrot.flows.dev_loop.dispatchers.nova"), "NovaClient", factory
    )


@pytest.fixture
def planner(tmp_path) -> PlannerOutput:
    return PlannerOutput(
        spec_path="sdd/specs/my-feature.spec.md",
        task_index_path=str(tmp_path / "sdd/tasks/index/my-feature.json"),
        feat_id="FEAT-999",
        branch_name="feat-999-my-feature",
        worktree_path=str(tmp_path),
        jira_issue_key=None,
    )


@pytest.fixture
def development() -> DevelopmentOutput:
    return DevelopmentOutput(
        files_changed=["a.py", "b.py"], commit_shas=["abc"], summary="implemented"
    )


@pytest.fixture
def synthesis() -> SynthesisReport:
    return SynthesisReport(consistent=True, adjustments=["fixed import"], summary="clean")


@pytest.fixture
def qa_report() -> QAReport:
    return QAReport(
        passed=True,
        criterion_results=[
            CriterionResult(
                name="c1", kind="shell", exit_code=0, duration_seconds=0.1, passed=True,
            )
        ],
        lint_passed=True,
    )


@pytest.fixture
def feature_node() -> FeatureHandoffNode:
    return FeatureHandoffNode()


@pytest.fixture
def research() -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path="/tmp/feat-130-fix",
        log_excerpts=[],
    )


@pytest.fixture
def bug_brief() -> BugBrief:
    return BugBrief(
        summary="customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[FlowtaskCriterion(name="run", task_path="x.yaml")],
        escalation_assignee="a",
        reporter="b",
    )


@pytest.fixture
def deployment_dev_out() -> DevelopmentOutput:
    return DevelopmentOutput(files_changed=["a.py"], commit_shas=["abc"], summary="done")


@pytest.fixture
def deployment_qa_report() -> QAReport:
    return QAReport(passed=True, criterion_results=[], lint_passed=True)


@pytest.fixture
def deployment_node() -> DeploymentHandoffNode:
    return DeploymentHandoffNode(jira_toolkit=None)


class TestFallbackIsExact:
    """[R2]: the deterministic template survives byte-for-byte."""

    async def test_feature_body_unchanged_when_enrichment_empty(
        self, feature_node, planner, development, synthesis, qa_report, monkeypatch
    ):
        _patch_feature_summary(monkeypatch, return_value="")
        before = FeatureHandoffNode._build_body(planner, development, synthesis, qa_report, "")
        after = await feature_node._build_body_async(
            planner, development, synthesis, qa_report, ""
        )
        assert after == before
        assert "Summary of changes" not in after

    async def test_feature_llm_exception_falls_back(
        self, feature_node, planner, development, synthesis, qa_report, monkeypatch
    ):
        """Belt-and-suspenders: even if ``summarize_pr_changes`` itself
        somehow raises (its own contract says it never does, but the call
        site swallows too), the handoff must not break."""
        _patch_feature_summary(monkeypatch, side_effect=RuntimeError("boom"))
        before = FeatureHandoffNode._build_body(planner, development, synthesis, qa_report, "")
        body = await feature_node._build_body_async(
            planner, development, synthesis, qa_report, ""
        )
        assert body == before
        assert "Summary of changes" not in body

    async def test_feature_empty_response_falls_back(
        self, feature_node, planner, development, synthesis, qa_report, monkeypatch
    ):
        _patch_feature_summary(monkeypatch, return_value="")
        before = FeatureHandoffNode._build_body(planner, development, synthesis, qa_report, "")
        body = await feature_node._build_body_async(
            planner, development, synthesis, qa_report, ""
        )
        assert body == before
        assert "Summary of changes" not in body

    async def test_deployment_body_unchanged_when_enrichment_empty(
        self, deployment_node, research, deployment_dev_out, deployment_qa_report, monkeypatch
    ):
        _patch_deployment_summary(monkeypatch, return_value="")
        before = DeploymentHandoffNode._build_body(
            research, deployment_dev_out, deployment_qa_report
        )
        after = await deployment_node._build_body_async(
            research, deployment_dev_out, deployment_qa_report
        )
        assert after == before
        assert "Summary of changes" not in after


class TestEnrichment:
    async def test_feature_section_added_when_configured(
        self, feature_node, planner, development, synthesis, qa_report, monkeypatch
    ):
        _patch_feature_summary(monkeypatch, return_value="- did a thing")
        body = await feature_node._build_body_async(
            planner, development, synthesis, qa_report, ""
        )
        assert "Summary of changes" in body
        assert "did a thing" in body

    async def test_feature_enrichment_appended_after_template(
        self, feature_node, planner, development, synthesis, qa_report, monkeypatch
    ):
        _patch_feature_summary(monkeypatch, return_value="- did a thing")
        before = FeatureHandoffNode._build_body(planner, development, synthesis, qa_report, "")
        body = await feature_node._build_body_async(
            planner, development, synthesis, qa_report, ""
        )
        assert body.startswith(before)

    async def test_deployment_section_added_when_configured(
        self, deployment_node, research, deployment_dev_out, deployment_qa_report, monkeypatch
    ):
        _patch_deployment_summary(monkeypatch, return_value="- fixed the bug")
        body = await deployment_node._build_body_async(
            research, deployment_dev_out, deployment_qa_report
        )
        assert "Summary of changes" in body
        assert "fixed the bug" in body


class TestUntouched:
    def test_feature_build_title_unchanged(self, planner):
        assert FeatureHandoffNode._build_title(planner) == "FEAT-999: feat-999-my-feature"

    def test_deployment_build_title_unchanged(self, research, bug_brief):
        assert DeploymentHandoffNode._build_title(bug_brief, research) == (
            "FEAT-130: customer sync drops the last row"
        )


class TestSummarizePrChanges:
    """Direct tests of the mechanical-seat helper itself.

    All tests except ``TestCredentialShortCircuit`` explicitly configure a
    Nova credential — regardless of what a developer's local ``.env``
    happens to have set — so the mocked-``NovaClient`` path is
    deterministically exercised (code-review fix: ``summarize_pr_changes``
    now short-circuits before ever constructing a client when no
    credential is configured).
    """

    @pytest.fixture(autouse=True)
    def _configure_nova_credential(self, monkeypatch):
        from parrot import conf

        monkeypatch.setattr(conf, "AWS_NOVA_API_KEY", "ABSK-test-key")

    async def test_ask_called_without_tools(self, monkeypatch):
        fake_ask = AsyncMock(
            return_value=type("M", (), {"output": "- a bullet"})()
        )
        fake_client = type("C", (), {"ask": fake_ask})()
        _patch_nova_client(monkeypatch, lambda: fake_client)
        result = await summarize_pr_changes("some context")
        assert result == "- a bullet"
        kwargs = fake_ask.await_args.kwargs
        assert kwargs.get("use_tools") is False

    async def test_default_profile_uses_configured_mechanical_model(self, monkeypatch):
        """Code-review fix: DEV_LOOP_NOVA_MECHANICAL_MODEL must actually be
        consumed by the default profile, not just declared in conf.py."""
        from parrot import conf

        monkeypatch.setattr(
            conf, "DEV_LOOP_NOVA_MECHANICAL_MODEL", "us.anthropic.claude-haiku-9000"
        )
        fake_ask = AsyncMock(return_value=type("M", (), {"output": "- ok"})())
        fake_client = type("C", (), {"ask": fake_ask})()
        _patch_nova_client(monkeypatch, lambda: fake_client)

        await summarize_pr_changes("some context")

        assert fake_ask.await_args.kwargs.get("model") == "us.anthropic.claude-haiku-9000"

    async def test_client_exception_returns_empty_string(self, monkeypatch, caplog):
        def _raise():
            raise RuntimeError("no credentials")

        _patch_nova_client(monkeypatch, _raise)
        with caplog.at_level("WARNING"):
            result = await summarize_pr_changes("some context")
        assert result == ""
        assert any("enrichment failed" in r.message.lower() for r in caplog.records)

    async def test_timeout_returns_empty_string(self, monkeypatch):
        async def _slow_ask(*args, **kwargs):
            await asyncio.sleep(10)
            return type("M", (), {"output": "too late"})()

        fake_client = type("C", (), {"ask": _slow_ask})()
        _patch_nova_client(monkeypatch, lambda: fake_client)
        from parrot.flows.dev_loop.models import NovaMechanicalProfile

        result = await summarize_pr_changes(
            "some context", profile=NovaMechanicalProfile(timeout_seconds=5)
        )
        assert result == ""

    async def test_empty_model_response_returns_empty_string(self, monkeypatch):
        fake_ask = AsyncMock(return_value=type("M", (), {"output": "   "})())
        fake_client = type("C", (), {"ask": fake_ask})()
        _patch_nova_client(monkeypatch, lambda: fake_client)
        result = await summarize_pr_changes("some context")
        assert result == ""


class TestCredentialShortCircuit:
    """Code-review fix: no credential configured -> no network attempt at
    all (not even a NovaClient() construction), not just an eventual
    fallback after a real connection/DNS attempt."""

    async def test_no_credentials_skips_without_constructing_client(self, monkeypatch):
        from parrot import conf

        monkeypatch.setattr(conf, "AWS_NOVA_API_KEY", None)
        monkeypatch.setattr(conf, "AWS_ACCESS_KEY", None)
        monkeypatch.setattr(conf, "AWS_SECRET_KEY", None)

        client_constructed = False

        def _spy_client():
            nonlocal client_constructed
            client_constructed = True
            raise AssertionError("NovaClient must not be constructed at all")

        _patch_nova_client(monkeypatch, _spy_client)

        result = await summarize_pr_changes("some context")
        assert result == ""
        assert client_constructed is False

    async def test_bedrock_api_key_alone_is_sufficient(self, monkeypatch):
        from parrot import conf

        monkeypatch.setattr(conf, "AWS_NOVA_API_KEY", "ABSK-test-key")
        monkeypatch.setattr(conf, "AWS_ACCESS_KEY", None)
        monkeypatch.setattr(conf, "AWS_SECRET_KEY", None)
        fake_ask = AsyncMock(return_value=type("M", (), {"output": "- ok"})())
        fake_client = type("C", (), {"ask": fake_ask})()
        _patch_nova_client(monkeypatch, lambda: fake_client)

        result = await summarize_pr_changes("some context")
        assert result == "- ok"

    async def test_access_secret_keypair_alone_is_sufficient(self, monkeypatch):
        from parrot import conf

        monkeypatch.setattr(conf, "AWS_NOVA_API_KEY", None)
        monkeypatch.setattr(conf, "AWS_ACCESS_KEY", "AKIA...")
        monkeypatch.setattr(conf, "AWS_SECRET_KEY", "secret")
        fake_ask = AsyncMock(return_value=type("M", (), {"output": "- ok"})())
        fake_client = type("C", (), {"ask": fake_ask})()
        _patch_nova_client(monkeypatch, lambda: fake_client)

        result = await summarize_pr_changes("some context")
        assert result == "- ok"
