"""Unit tests for Nova backend registration & wiring (FEAT-405, TASK-2088)."""

import pytest
from parrot.flows.dev_loop.agent_builder import build_dispatcher
from parrot.flows.dev_loop.catalog import (
    JUDGE_BACKENDS,
    PRIMARY_REVIEW_BACKENDS,
    catalog_payload,
    resolve_adversarial_backend,
)
from parrot.flows.dev_loop.dispatchers import NovaCodeDispatcher
from parrot.flows.dev_loop.models import DevAgentSpec, NovaCodeDispatchProfile

COMMON = {"redis_url": "redis://localhost:6379/0", "max_concurrent": 1, "stream_ttl_seconds": 60}


class TestBuildDispatcher:
    def test_nova_branch_returns_pair(self):
        d, p = build_dispatcher(DevAgentSpec(agent="nova"), **COMMON)
        assert isinstance(d, NovaCodeDispatcher)
        assert isinstance(p, NovaCodeDispatchProfile)

    def test_spec_model_overrides_config(self):
        _, p = build_dispatcher(DevAgentSpec(agent="nova", model="zai.glm-5"), **COMMON)
        assert p.model == "zai.glm-5"

    def test_default_model_is_minimax(self):
        _, p = build_dispatcher(DevAgentSpec(agent="nova"), **COMMON)
        assert p.model == "minimax.minimax-m2.5"

    def test_config_getter_overrides_hardcoded_default(self):
        getter = lambda key, fallback=None: (
            "moonshotai.kimi-k2.5" if key == "DEV_LOOP_NOVA_CODE_MODEL" else fallback
        )
        _, p = build_dispatcher(DevAgentSpec(agent="nova"), config_getter=getter, **COMMON)
        assert p.model == "moonshotai.kimi-k2.5"

    def test_unknown_backend_still_raises(self):
        """Existing raise-on-unknown fallthrough is untouched (insert-only guard).

        ``DevAgentSpec.agent``'s ``Literal`` type rejects unknown ids before
        ``build_dispatcher`` ever runs, so bypass validation via
        ``model_construct`` to exercise the ``raise ValueError`` branch
        directly.
        """
        bogus_spec = DevAgentSpec.model_construct(agent="totally-unknown", model="", count=1)
        with pytest.raises(ValueError, match="Unknown DevAgentBackend"):
            build_dispatcher(bogus_spec, **COMMON)


class TestCatalog:
    def test_nova_listed(self):
        payload = catalog_payload()
        assert any(b["id"] == "nova" for b in payload["backends"])

    def test_nova_roles_include_development_and_adversarial(self):
        payload = catalog_payload()
        nova_entry = next(b for b in payload["backends"] if b["id"] == "nova")
        assert "development" in nova_entry["roles"]
        assert "adversarial" in nova_entry["roles"]

    def test_nova_not_in_judge_backends(self):
        assert "nova" not in JUDGE_BACKENDS
        assert "nova" not in PRIMARY_REVIEW_BACKENDS

    def test_catalog_payload_unconfigured_matches_pre_feature(self):
        """[R3] regression guard: unset config -> byte-identical adversarial payload."""
        payload = catalog_payload()
        assert payload["adversarial_backend"] == "codex"
        assert payload["roles"]["adversarial"] == ["codex"]


class TestAdversarialSelector:
    def test_defaults_to_codex(self):
        """[R3] regression guard — unset config must not change behaviour."""
        assert resolve_adversarial_backend(lambda k, fallback=None: fallback) == "codex"

    def test_selects_nova_when_configured(self):
        getter = lambda k, fallback=None: (
            "nova" if "ADVERSARIAL_BACKEND" in k else fallback
        )
        assert resolve_adversarial_backend(getter) == "nova"

    def test_invalid_value_raises_naming_options(self):
        getter = lambda k, fallback=None: (
            "gemini" if "ADVERSARIAL_BACKEND" in k else fallback
        )
        with pytest.raises(ValueError, match="codex"):
            resolve_adversarial_backend(getter)

    def test_invalid_value_error_names_nova_too(self):
        getter = lambda k, fallback=None: (
            "gemini" if "ADVERSARIAL_BACKEND" in k else fallback
        )
        with pytest.raises(ValueError, match="nova"):
            resolve_adversarial_backend(getter)

    def test_catalog_payload_reflects_nova_selection(self):
        getter = lambda k, fallback=None: (
            "nova" if "ADVERSARIAL_BACKEND" in k else fallback
        )
        payload = catalog_payload(getter)
        assert payload["adversarial_backend"] == "nova"
        assert payload["roles"]["adversarial"] == ["nova"]
