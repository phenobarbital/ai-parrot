"""MantleAdversarialReviewDispatcher — read-only counter-reviewer tests.

FEAT-486 TASK-2654 / spec §4 rows ``test_mantle_adversarial_read_only``
(advisory, no tools, ``files_modified=[]`` forced) plus factory/triad
registration and the additivity guard on ``catalog.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from parrot import conf
from parrot.flows.dev_loop import catalog as llm_catalog
from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory
from parrot.flows.dev_loop.dispatchers.mantle import (
    MANTLE_DEFAULT_REVIEW_MODEL,
    MantleAdversarialReviewDispatcher,
    MantleAdversarialReviewProfile,
)
from parrot.flows.dev_loop.models import (
    CodeReviewFinding,
    CodeReviewVerdict,
    ResearchOutput,
)


class FakeAIMessage:
    def __init__(self, structured_output: Any) -> None:
        self.structured_output = structured_output


class FakeMantleClient:
    """Records every ``ask`` kwarg so the no-tools invariant is assertable."""

    def __init__(self, verdict: Any = None, raises: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._verdict = verdict
        self._raises = raises
        self._events_registry = None

    async def ask(self, prompt: str, **kwargs: Any):
        self.calls.append({"prompt": prompt, **kwargs})
        if self._raises is not None:
            raise self._raises
        return FakeAIMessage(self._verdict)


def _brief() -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-486",
        spec_path="sdd/specs/refactor-dev-flow.spec.md",
        feat_id="FEAT-486",
        branch_name="feat-486-refactor-dev-flow",
        worktree_path="/tmp/wt",
        log_excerpts=[],
    )


def _dispatcher(client: FakeMantleClient, **kwargs: Any) -> MantleAdversarialReviewDispatcher:
    node = MantleAdversarialReviewDispatcher(client=client, **kwargs)

    async def _no_git(_cwd, _profile):
        return "diff --git a/x b/x\n+one line\n"

    node._collect_diff = _no_git  # bypass the real git subprocess
    return node


class TestReadOnlyByConstruction:
    """The three independent read-only layers (module docstring)."""

    def test_advisory_flag(self):
        assert MantleAdversarialReviewDispatcher.advisory is True
        assert MantleAdversarialReviewDispatcher.agent_name == "mantle-adversarial"

    def test_profile_has_no_tool_fields(self):
        """A tool configuration must be inexpressible, not merely omitted."""
        fields = set(MantleAdversarialReviewProfile.model_fields)
        assert not fields & {"tools", "allowed_tools", "allowed_commands", "sandbox"}

    @pytest.mark.asyncio
    async def test_no_tools_passed_to_the_model(self):
        client = FakeMantleClient(verdict=CodeReviewVerdict(passed=True, findings=[]))
        await _dispatcher(client).review(
            brief=_brief(), run_id="r1", node_id="qa.counter", cwd="/tmp/wt"
        )
        call = client.calls[0]
        assert call["use_tools"] is False
        assert "tools" not in call

    @pytest.mark.asyncio
    async def test_files_modified_forced_empty(self):
        """Even a model claiming edits gets its claim stripped."""
        client = FakeMantleClient(
            verdict=CodeReviewVerdict(
                passed=False,
                findings=[CodeReviewFinding(message="bad", severity="major")],
                files_modified=["src/lied_about.py"],
            )
        )
        verdict = await _dispatcher(client).review(
            brief=_brief(), run_id="r1", node_id="qa.counter", cwd="/tmp/wt"
        )
        assert verdict.files_modified == []
        assert verdict.passed is False

    @pytest.mark.asyncio
    async def test_findings_tagged_with_this_seat(self):
        client = FakeMantleClient(
            verdict=CodeReviewVerdict(
                passed=True,
                findings=[CodeReviewFinding(message="nit", severity="nit")],
            )
        )
        verdict = await _dispatcher(client).review(
            brief=_brief(), run_id="r1", node_id="qa.counter", cwd="/tmp/wt"
        )
        assert verdict.findings[0].source == "mantle-adversarial"


class TestModelAndProfile:
    def test_default_model_gpt_5_6_sol(self):
        assert MANTLE_DEFAULT_REVIEW_MODEL == "gpt-5.6-sol"
        assert MantleAdversarialReviewDispatcher(
            client=FakeMantleClient()
        )._model == "gpt-5.6-sol"

    def test_conf_key_literal_is_pinned_equal(self):
        """conf.py duplicates the literal (it must not import parrot.flows)."""
        assert conf.DEV_LOOP_MANTLE_REVIEW_MODEL == MANTLE_DEFAULT_REVIEW_MODEL

    def test_codex_adversarial_model_key_not_repointed(self):
        """The codex seat keeps its own model key (spec: do NOT repoint)."""
        assert conf.DEV_LOOP_ADVERSARIAL_MODEL != MANTLE_DEFAULT_REVIEW_MODEL

    def test_explicit_model_wins(self):
        d = MantleAdversarialReviewDispatcher(
            model="openai.gpt-oss-120b", client=FakeMantleClient()
        )
        assert d.build_review_profile().model == "openai.gpt-oss-120b"

    def test_profile_carries_scope(self):
        d = MantleAdversarialReviewDispatcher(
            review_scope="base", review_base="dev", client=FakeMantleClient()
        )
        profile = d.build_review_profile()
        assert profile.review_scope == "base"
        assert profile.review_base == "dev"

    @pytest.mark.asyncio
    async def test_unknown_model_max_tokens_passes_through(self):
        """``effective_max_tokens`` must not clamp an unmapped id."""
        client = FakeMantleClient(verdict=CodeReviewVerdict(passed=True, findings=[]))
        await _dispatcher(client, max_tokens=16384).review(
            brief=_brief(), run_id="r1", node_id="qa.counter", cwd="/tmp/wt"
        )
        assert client.calls[0]["max_tokens"] == 16384


class TestDegradation:
    """Missing bearer key / outage must degrade, never crash the QA node."""

    @pytest.mark.asyncio
    async def test_client_error_degrades_to_passing_nit(self):
        client = FakeMantleClient(raises=RuntimeError("401 Unauthorized"))
        verdict = await _dispatcher(client).review(
            brief=_brief(), run_id="r1", node_id="qa.counter", cwd="/tmp/wt"
        )
        assert verdict.passed is True
        assert verdict.findings[0].severity == "nit"
        assert "401 Unauthorized" in verdict.findings[0].message

    @pytest.mark.asyncio
    async def test_bad_structured_output_degrades(self):
        client = FakeMantleClient(verdict={"not": "a verdict"})
        verdict = await _dispatcher(client).review(
            brief=_brief(), run_id="r1", node_id="qa.counter", cwd="/tmp/wt"
        )
        assert verdict.passed is True
        assert verdict.findings[0].severity == "nit"


class TestTelemetryBinding:
    """FEAT-479: a newly built client must reach the run's registry."""

    @pytest.mark.asyncio
    async def test_registry_bound_when_resolver_supplied(self):
        sentinel = object()
        client = FakeMantleClient(verdict=CodeReviewVerdict(passed=True, findings=[]))
        await _dispatcher(
            client, event_registry_resolver=lambda _rid: sentinel
        ).review(brief=_brief(), run_id="r1", node_id="qa.counter", cwd="/tmp/wt")
        assert client._events_registry is sentinel

    @pytest.mark.asyncio
    async def test_no_resolver_leaves_client_untouched(self):
        client = FakeMantleClient(verdict=CodeReviewVerdict(passed=True, findings=[]))
        await _dispatcher(client).review(
            brief=_brief(), run_id="r1", node_id="qa.counter", cwd="/tmp/wt"
        )
        assert client._events_registry is None


class TestFactoryAndTriad:
    def test_factory_registration(self):
        dispatcher = CodeReviewDispatcherFactory.create(
            "mantle-adversarial", client=FakeMantleClient()
        )
        assert isinstance(dispatcher, MantleAdversarialReviewDispatcher)

    def test_triad_resolves_mantle(self):
        resolved = llm_catalog.resolve_adversarial_backend(
            lambda key, fallback="": "mantle"
        )
        assert resolved == "mantle"

    def test_triad_default_is_still_codex(self):
        """[R3]: an operator who configures nothing sees no change."""
        assert llm_catalog.ADVERSARIAL_BACKEND == "codex"
        assert (
            llm_catalog.resolve_adversarial_backend(lambda key, fallback="": fallback)
            == "codex"
        )

    def test_triad_still_rejects_unknown(self):
        with pytest.raises(ValueError, match="codex, nova, mantle"):
            llm_catalog.resolve_adversarial_backend(lambda key, fallback="": "bogus")

    def test_existing_choices_preserved(self):
        assert llm_catalog._ADVERSARIAL_BACKEND_CHOICES[:2] == ("codex", "nova")
        assert "mantle" in llm_catalog._ADVERSARIAL_BACKEND_CHOICES


class TestCatalogAdditivity:
    """Every catalog change must be provably additive (spec AC)."""

    def test_backend_ids_unchanged(self):
        assert [b.id for b in llm_catalog.BACKENDS] == [
            "claude-code",
            "codex",
            "gemini",
            "google_coding",
            "nvidia",
            "grok",
            "zai",
            "moonshot",
            "nova",
        ]

    def test_nova_models_are_append_only(self):
        nova = llm_catalog.get_backend("nova")
        assert nova.models[:8] == (
            "minimax.minimax-m2.5",
            "moonshotai.kimi-k2.5",
            "zai.glm-5",
            "us.amazon.nova-2-lite-v1:0",
            "us.amazon.nova-pro-v1:0",
            "us.anthropic.claude-opus-5",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            "global.anthropic.claude-fable-5",
        )
        assert nova.models[8:] == (
            "qwen.qwen3-coder-480b-a35b-v1:0",
            "gpt-5.6-sol",
        )

    def test_nova_identity_fields_unchanged(self):
        nova = llm_catalog.get_backend("nova")
        assert nova.default_model == "minimax.minimax-m2.5"
        assert nova.model_env == "DEV_LOOP_NOVA_CODE_MODEL"
        assert nova.roles == ("development", "adversarial")

    def test_codex_models_not_extended_with_gpt_5_6_sol(self):
        """Spec-resolved: the Codex CLI cannot run gpt-5.6-sol."""
        assert "gpt-5.6-sol" not in llm_catalog.get_backend("codex").models

    def test_judge_and_primary_review_backends_unchanged(self):
        """JudgeSpec / judge panel are explicitly untouched by FEAT-486."""
        assert llm_catalog.JUDGE_BACKENDS == (
            "claude-code",
            "codex",
            "gemini",
            "google_coding",
        )
        assert llm_catalog.PRIMARY_REVIEW_BACKENDS == (
            "claude-code",
            "codex",
            "gemini",
            "google_coding",
        )
