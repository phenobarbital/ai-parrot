"""Unit tests for SecretsGuardrail (FEAT-396 / TASK-2029)."""
import pytest
from parrot.bots.guardrails.base import (
    GuardrailAction,
    GuardrailContext,
    GuardrailStage,
)
from parrot.bots.guardrails.builtin.secrets import SecretsGuardrail
from parrot.bots.guardrails.registry import build_guardrails
from parrot.security.redaction import OutputScrubber


@pytest.fixture
def guardrail():
    return SecretsGuardrail()


@pytest.fixture
def ctx():
    return GuardrailContext(stage=GuardrailStage.TOOL_OUTPUT, agent_name="test", tool_name="my_tool")


class TestSecretsGuardrail:
    @pytest.mark.asyncio
    async def test_scrubs_secrets(self, guardrail, ctx):
        result = await guardrail.check("API_KEY=sk-1234abcdefghij", ctx)
        assert result.action == GuardrailAction.TRANSFORM
        assert "sk-1234abcdefghij" not in result.content
        assert "REDACTED" in result.content

    @pytest.mark.asyncio
    async def test_clean_text_passes(self, guardrail, ctx):
        result = await guardrail.check("hello world", ctx)
        assert result.action == GuardrailAction.PASS
        assert result.content is None

    @pytest.mark.asyncio
    async def test_idempotent(self, guardrail, ctx):
        """Re-scrubbing an already-scrubbed value is a no-op (PASS, i.e.
        content unchanged) — NOT a second TRANSFORM with identical content."""
        result1 = await guardrail.check("API_KEY=sk-1234abcdefghij", ctx)
        assert result1.action == GuardrailAction.TRANSFORM
        result2 = await guardrail.check(result1.content, ctx)
        assert result2.action == GuardrailAction.PASS
        assert result2.content is None

    def test_fail_open(self, guardrail):
        assert guardrail.on_error == "fail_open"

    def test_priority_sanitizer_band(self, guardrail):
        assert guardrail.priority < 100

    def test_stages(self, guardrail):
        assert guardrail.stages == {GuardrailStage.TOOL_OUTPUT, GuardrailStage.OUTPUT}

    def test_name(self, guardrail):
        assert guardrail.name == "secrets"

    def test_scrub_handles_dict(self, guardrail):
        out = guardrail.scrub({"token": "abc", "ok": "plain"}, tool_name="t")
        assert out["ok"] == "plain"
        assert out["token"] != "abc"

    def test_scrub_handles_list(self, guardrail):
        out = guardrail.scrub(["clean", "PASSWORD=hunter2secret"], tool_name="t")
        assert out[0] == "clean"
        assert "hunter2secret" not in out[1]

    @pytest.mark.asyncio
    async def test_check_uses_ctx_tool_name(self, guardrail, ctx):
        result = await guardrail.check("API_KEY=sk-abcdefghijkl", ctx)
        # Same-tool re-scrub must be idempotent regardless of which tool_name
        # produced the marker.
        result2 = await guardrail.check(result.content, ctx)
        assert result2.action == GuardrailAction.PASS


class TestRegistration:
    def test_registered_name_resolves_to_class(self):
        built = build_guardrails(["secrets"])
        assert len(built) == 1
        assert isinstance(built[0], SecretsGuardrail)
        assert built[0].name == "secrets"

    def test_registered_with_policy_kwargs(self):
        built = build_guardrails([{"name": "secrets", "tool_name": "custom_tool"}])
        assert isinstance(built[0]._scrubber, OutputScrubber)


class TestScrubFailureNonFatal:
    @pytest.mark.asyncio
    async def test_scrub_error_propagates_for_pipeline_fail_open_handling(self, ctx, monkeypatch):
        """check() itself does not swallow errors — the pipeline's
        fail_open contract (on_error='fail_open') is what makes a scrub
        failure non-fatal; verified at the pipeline level in
        test_guardrails_pipeline.py::TestPipelineErrorContract."""
        guardrail = SecretsGuardrail()

        def _boom(value, tool_name=None):
            raise RuntimeError("scrub backend down")

        monkeypatch.setattr(guardrail._scrubber, "scrub", _boom)
        with pytest.raises(RuntimeError):
            await guardrail.check("some text", ctx)
