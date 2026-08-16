"""Unit tests for ModerationGuardrail (FEAT-396 / TASK-2030)."""
import pytest
from parrot.bots.guardrails.base import (
    GuardrailAction,
    GuardrailContext,
    GuardrailStage,
)
from parrot.bots.guardrails.builtin.moderation import (
    ModerationGuardrail,
    ModerationPolicy,
    StubModerationBackend,
)
from pydantic import ValidationError


@pytest.fixture
def ctx():
    return GuardrailContext(stage=GuardrailStage.INPUT, agent_name="test")


class TestStubBackend:
    @pytest.mark.asyncio
    async def test_allow_all(self):
        backend = StubModerationBackend()
        result = await backend.classify("any text")
        assert result == {}


class TestModerationPolicy:
    def test_defaults(self):
        policy = ModerationPolicy()
        assert policy.threshold == 0.8
        assert policy.action == "flag"
        assert policy.categories == []

    def test_rejects_invalid_action(self):
        with pytest.raises(ValidationError):
            ModerationPolicy(action="delete")


class TestModerationGuardrail:
    def test_name_priority_stages(self):
        g = ModerationGuardrail()
        assert g.name == "moderation"
        assert g.priority == 50
        assert g.priority > 10  # after prompt_injection/secrets (priority 10)
        assert g.stages == {GuardrailStage.INPUT, GuardrailStage.OUTPUT}

    def test_default_backend_is_stub(self):
        g = ModerationGuardrail()
        assert isinstance(g.backend, StubModerationBackend)

    @pytest.mark.asyncio
    async def test_stub_passes_everything(self, ctx):
        guardrail = ModerationGuardrail()
        result = await guardrail.check("hello", ctx)
        assert result.action == GuardrailAction.PASS

    @pytest.mark.asyncio
    async def test_flag_on_threshold(self, ctx):
        class MockBackend:
            async def classify(self, text):
                return {"hate": 0.9}
        guardrail = ModerationGuardrail(
            policy=ModerationPolicy(categories=["hate"], action="flag"),
            backend=MockBackend(),
        )
        result = await guardrail.check("hateful content", ctx)
        assert result.action == GuardrailAction.FLAG
        assert "hate" in result.report
        assert result.report["hate"] == 0.9

    @pytest.mark.asyncio
    async def test_block_on_threshold(self, ctx):
        class MockBackend:
            async def classify(self, text):
                return {"violence": 0.95}
        guardrail = ModerationGuardrail(
            policy=ModerationPolicy(categories=["violence"], action="block", threshold=0.9),
            backend=MockBackend(),
        )
        result = await guardrail.check("violent content", ctx)
        assert result.action == GuardrailAction.BLOCK
        assert result.reason is not None
        assert result.content is None
        assert "violence" in result.reason

    @pytest.mark.asyncio
    async def test_below_threshold_passes(self, ctx):
        class MockBackend:
            async def classify(self, text):
                return {"hate": 0.3}
        guardrail = ModerationGuardrail(
            policy=ModerationPolicy(categories=["hate"], threshold=0.8),
            backend=MockBackend(),
        )
        result = await guardrail.check("mild text", ctx)
        assert result.action == GuardrailAction.PASS

    @pytest.mark.asyncio
    async def test_category_not_in_policy_is_ignored(self, ctx):
        """A backend may return scores for categories the policy doesn't
        track — those must never trigger flag/block."""
        class MockBackend:
            async def classify(self, text):
                return {"spam": 0.99}
        guardrail = ModerationGuardrail(
            policy=ModerationPolicy(categories=["hate"], threshold=0.5),
            backend=MockBackend(),
        )
        result = await guardrail.check("text", ctx)
        assert result.action == GuardrailAction.PASS

    @pytest.mark.asyncio
    async def test_multiple_triggered_categories_in_report(self, ctx):
        class MockBackend:
            async def classify(self, text):
                return {"hate": 0.9, "violence": 0.85, "spam": 0.1}
        guardrail = ModerationGuardrail(
            policy=ModerationPolicy(categories=["hate", "violence"], threshold=0.8),
            backend=MockBackend(),
        )
        result = await guardrail.check("text", ctx)
        assert result.action == GuardrailAction.FLAG
        assert result.report == {"hate": 0.9, "violence": 0.85}

    def test_on_error_depends_on_action(self):
        g_flag = ModerationGuardrail(policy=ModerationPolicy(action="flag"))
        assert g_flag.on_error == "fail_open"
        g_block = ModerationGuardrail(policy=ModerationPolicy(action="block"))
        assert g_block.on_error == "fail_closed"


class TestRegistration:
    def test_registered(self):
        from parrot.bots.guardrails.registry import build_guardrails
        guardrails = build_guardrails(["moderation"])
        assert len(guardrails) == 1
        assert guardrails[0].name == "moderation"

    def test_registered_with_policy_dict(self):
        from parrot.bots.guardrails.registry import build_guardrails
        built = build_guardrails([
            {"name": "moderation", "policy": ModerationPolicy(action="block")}
        ])
        assert built[0].on_error == "fail_closed"
