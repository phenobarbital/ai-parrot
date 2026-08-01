"""Unit tests for the guardrails registry + config coercion (FEAT-396 / TASK-2026).

Note on scope: the concrete `"prompt_injection"` / `"secrets"` plugin
classes land in TASK-2027 / TASK-2029 (this task only pre-registers their
names via lazy factories — see `registry.py`). The spec's own Test
Specification (§4) assigns end-to-end legacy-flag-mapping compat testing
to Module 2 (`test_legacy_flag_mapping`), not Module 1. Consistent with
that, the legacy-mapping tests here register temporary stub factories
under the real `"prompt_injection"`/`"secrets"` names (monkeypatched, so
they don't leak between tests) to verify this task's own logic — which
flags map to which stage, and the no-duplicate-registration rule — without
depending on TASK-2027/2029 already existing. TASK-2027/2028/2029 add
their own compat suites against the real plugins.
"""
from typing import Any, ClassVar

import pytest
from parrot.bots.guardrails.base import (
    Guardrail,
    GuardrailAction,
    GuardrailResult,
    GuardrailStage,
)
from parrot.bots.guardrails.config import build_pipelines_from_config
from parrot.bots.guardrails.registry import (
    _GUARDRAIL_FACTORIES,
    build_guardrails,
    register_guardrail,
)


class StubGuardrail(Guardrail):
    """Minimal concrete guardrail for registry/config tests."""
    name = "stub"
    stages: ClassVar[set] = {GuardrailStage.INPUT}
    priority = 50
    on_error = "fail_open"

    async def check(self, content: str, ctx: Any) -> GuardrailResult:
        return GuardrailResult(action=GuardrailAction.PASS)


class _StubBuiltinStandIn(Guardrail):
    """Concrete stand-in used to simulate a not-yet-built plugin by name."""

    async def check(self, content: str, ctx: Any) -> GuardrailResult:
        return GuardrailResult(action=GuardrailAction.PASS)


def _make_stub_factory(name: str, stages: set) -> Any:
    def _factory(**kwargs):
        g = _StubBuiltinStandIn()
        g.name = name
        g.stages = stages
        g.priority = 50
        g.on_error = "fail_open"
        g._kwargs = kwargs
        return g
    return _factory


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    """Ensure test-registered names never leak into other tests."""
    original = dict(_GUARDRAIL_FACTORIES)
    yield
    _GUARDRAIL_FACTORIES.clear()
    _GUARDRAIL_FACTORIES.update(original)


class TestRegistry:
    def test_register_and_build_by_name(self):
        register_guardrail("test_stub_registry", lambda **kw: StubGuardrail())
        built = build_guardrails(["test_stub_registry"])
        assert len(built) == 1
        assert built[0].name == "stub"

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="Unknown guardrail"):
            build_guardrails(["nonexistent"])

    def test_reserved_name_raises(self):
        with pytest.raises(NotImplementedError):
            build_guardrails(["pii"])

    def test_reserved_pseudonymize_raises(self):
        with pytest.raises(NotImplementedError):
            build_guardrails(["pseudonymize"])

    def test_reserved_groundedness_raises(self):
        with pytest.raises(NotImplementedError):
            build_guardrails(["groundedness"])

    def test_build_from_dict(self):
        received = {}

        def factory(**kwargs):
            received.update(kwargs)
            return StubGuardrail()

        register_guardrail("test_stub_dict", factory)
        built = build_guardrails([{"name": "test_stub_dict", "threshold": 0.5}])
        assert len(built) == 1
        assert received == {"threshold": 0.5}

    def test_build_from_instance(self):
        instance = StubGuardrail()
        built = build_guardrails([instance])
        assert built == [instance]

    def test_dict_missing_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            build_guardrails([{"threshold": 0.5}])

    def test_invalid_entry_type_raises(self):
        with pytest.raises(TypeError):
            build_guardrails([123])

    def test_prompt_injection_and_secrets_preregistered(self):
        # Names are pre-registered (lazy factories) even before the real
        # plugin modules exist — only *calling* them requires the module.
        assert "prompt_injection" in _GUARDRAIL_FACTORIES
        assert "secrets" in _GUARDRAIL_FACTORIES
        assert "moderation" in _GUARDRAIL_FACTORIES


class TestConfigCoercion:
    def test_legacy_injection_flags_map(self, monkeypatch):
        monkeypatch.setitem(
            _GUARDRAIL_FACTORIES,
            "prompt_injection",
            _make_stub_factory("prompt_injection", {GuardrailStage.INPUT}),
        )
        pipelines = build_pipelines_from_config(
            guardrails=None,
            legacy_flags={"injection_detection": True, "strict_mode": True},
        )
        assert pipelines[GuardrailStage.INPUT].has_guardrails
        assert not pipelines[GuardrailStage.OUTPUT].has_guardrails

    def test_legacy_redaction_flag_maps(self, monkeypatch):
        monkeypatch.setitem(
            _GUARDRAIL_FACTORIES,
            "secrets",
            _make_stub_factory("secrets", {GuardrailStage.TOOL_OUTPUT, GuardrailStage.OUTPUT}),
        )
        pipelines = build_pipelines_from_config(
            guardrails=None,
            legacy_flags={"enable_redaction": True},
        )
        assert pipelines[GuardrailStage.TOOL_OUTPUT].has_guardrails
        assert pipelines[GuardrailStage.OUTPUT].has_guardrails

    def test_empty_config_empty_pipelines(self):
        pipelines = build_pipelines_from_config(
            guardrails=None,
            legacy_flags={"injection_detection": False, "enable_redaction": False},
        )
        for pipeline in pipelines.values():
            assert not pipeline.has_guardrails

    def test_all_four_stages_present(self):
        pipelines = build_pipelines_from_config(guardrails=None, legacy_flags={})
        assert set(pipelines.keys()) == set(GuardrailStage)

    def test_explicit_guardrail_routed_by_stage(self):
        pipelines = build_pipelines_from_config(guardrails=[StubGuardrail()], legacy_flags={})
        assert pipelines[GuardrailStage.INPUT].has_guardrails
        assert not pipelines[GuardrailStage.TOOL_OUTPUT].has_guardrails

    def test_no_duplicate_registration_explicit_and_legacy(self, monkeypatch):
        calls = []

        def factory(**kwargs):
            calls.append(kwargs)
            stub = _make_stub_factory("prompt_injection", {GuardrailStage.INPUT})(**kwargs)
            return stub

        monkeypatch.setitem(_GUARDRAIL_FACTORIES, "prompt_injection", factory)
        pipelines = build_pipelines_from_config(
            guardrails=["prompt_injection"],
            legacy_flags={"injection_detection": True},
        )
        # Only the explicit entry should have triggered construction.
        assert len(calls) == 1
        assert len(pipelines[GuardrailStage.INPUT]._guardrails) == 1

    def test_no_guardrails_kwarg_defaults_to_empty_when_flags_off(self):
        pipelines = build_pipelines_from_config()
        for pipeline in pipelines.values():
            assert not pipeline.has_guardrails
