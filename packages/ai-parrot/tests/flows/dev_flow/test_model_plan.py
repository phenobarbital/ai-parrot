"""Unit tests for ``DevFlowModelPlan`` and its resolver (FEAT-486 TASK-2651).

Covers spec §4 rows ``test_model_plan_defaults``,
``test_model_plan_unknown_backend_fails_fast`` and
``test_model_plan_env_defaults``, plus the ``DevAgentPoolConfig``
production TASK-2652 consumes.
"""

from __future__ import annotations

from typing import Any

import pytest
from parrot.flows.dev_flow.model_plan import (
    DEFAULT_RESEARCH_PRIMARY,
    ENV_DEV_POOL,
    ENV_PARTNER_BACKEND,
    ENV_PARTNER_ENABLED,
    ENV_PARTNER_MODEL,
    ENV_RESEARCH_PRIMARY,
    ENV_REVIEW_COUNTER_MODEL,
    ENV_REVIEW_PRIMARY_MODEL,
    DevFlowModelPlan,
    ResearchPartnerPlan,
    ReviewPairPlan,
    resolve_model_plan,
    supported_dev_pool_backends,
)
from parrot.flows.dev_loop.models.base import DevAgentPoolConfig, DevAgentSpec


def _getter(values: dict[str, Any]):
    """Build a ``(key, fallback=...) -> Any`` config getter over a dict."""

    def getter(key: str, fallback: Any = "") -> Any:
        return values.get(key, fallback)

    return getter


class TestDevFlowModelPlanDefaults:
    """Built-in defaults, straight from spec §2."""

    def test_defaults(self):
        plan = DevFlowModelPlan()
        assert plan.research_primary == "claude-opus-5"
        assert plan.research_partner.enabled is False
        assert plan.research_partner.backend == "gpt"
        assert plan.research_partner.model == "gpt-5.6-sol"
        assert plan.dev_pool == []
        assert plan.review.primary.agent == "claude-code"
        assert plan.review.primary.model == "claude-opus-5"
        assert plan.review.counter_model == "gpt-5.6-sol"

    def test_nested_defaults_are_not_shared(self):
        """``default_factory`` — mutating one plan must not touch another."""
        first = DevFlowModelPlan()
        second = DevFlowModelPlan()
        first.dev_pool.append(DevAgentSpec(agent="nova", model="zai.glm-5"))
        assert second.dev_pool == []
        assert first.research_partner is not second.research_partner

    def test_default_review_primary_is_a_dev_agent_spec(self):
        assert isinstance(DevFlowModelPlan().review.primary, DevAgentSpec)


class TestDevPoolValidation:
    """Fail-fast backend validation (spec: before any dispatch)."""

    def test_unknown_backend_fails_fast(self):
        with pytest.raises(ValueError, match="claude-code"):
            DevFlowModelPlan.model_validate(
                {"dev_pool": [{"agent": "not-a-backend", "model": "x"}]}
            )

    def test_unknown_backend_message_names_the_offender(self):
        with pytest.raises(ValueError, match="not-a-backend"):
            DevFlowModelPlan.model_validate(
                {"dev_pool": [{"agent": "not-a-backend"}]}
            )

    def test_supported_backends_match_the_literal(self):
        supported = supported_dev_pool_backends()
        assert "claude-code" in supported
        assert "nova" in supported
        assert "not-a-backend" not in supported

    @pytest.mark.parametrize("backend", ["nova", "claude-code", "moonshot", "zai"])
    def test_known_backends_accepted(self, backend: str):
        plan = DevFlowModelPlan.model_validate({"dev_pool": [{"agent": backend}]})
        assert plan.dev_pool[0].agent == backend

    def test_models_are_never_validated(self):
        """Model ids are free text by catalog policy (catalog.py:22-24)."""
        plan = DevFlowModelPlan.model_validate(
            {"dev_pool": [{"agent": "nova", "model": "totally-made-up-model"}]}
        )
        assert plan.dev_pool[0].model == "totally-made-up-model"


class TestToPoolConfig:
    """``DevAgentPoolConfig`` production for TASK-2652."""

    def test_empty_pool_returns_none(self):
        assert DevFlowModelPlan().to_pool_config() is None

    def test_pool_config_carries_every_spec(self):
        plan = DevFlowModelPlan(
            dev_pool=[
                DevAgentSpec(agent="nova", model="zai.glm-5"),
                DevAgentSpec(agent="nova", model="qwen.qwen3-coder-480b-a35b-v1:0"),
            ]
        )
        cfg = plan.to_pool_config()
        assert isinstance(cfg, DevAgentPoolConfig)
        assert [s.model for s in cfg.agents] == [
            "zai.glm-5",
            "qwen.qwen3-coder-480b-a35b-v1:0",
        ]

    def test_pool_config_uses_shared_isolation(self):
        """Spec non-goal: no per-agent worktrees — shared, always."""
        plan = DevFlowModelPlan(dev_pool=[DevAgentSpec(agent="nova")])
        assert plan.to_pool_config().isolation_mode == "shared"

    def test_pool_config_is_a_copy(self):
        plan = DevFlowModelPlan(dev_pool=[DevAgentSpec(agent="nova")])
        cfg = plan.to_pool_config()
        cfg.agents.append(DevAgentSpec(agent="codex"))
        assert len(plan.dev_pool) == 1


class TestResolveModelPlan:
    """Precedence: explicit argument > env > built-in default."""

    def test_no_plan_no_env_gives_builtin_defaults(self):
        resolved = resolve_model_plan(None, config_getter=_getter({}))
        assert resolved.research_primary == DEFAULT_RESEARCH_PRIMARY
        assert resolved.research_partner.enabled is False
        assert resolved.dev_pool == []
        assert resolved.review.counter_model == "gpt-5.6-sol"

    def test_env_beats_builtin(self):
        resolved = resolve_model_plan(
            None,
            config_getter=_getter(
                {
                    ENV_RESEARCH_PRIMARY: "claude-sonnet-4-6",
                    ENV_REVIEW_COUNTER_MODEL: "nova-2-lite",
                    ENV_REVIEW_PRIMARY_MODEL: "claude-haiku-4-5",
                }
            ),
        )
        assert resolved.research_primary == "claude-sonnet-4-6"
        assert resolved.review.counter_model == "nova-2-lite"
        assert resolved.review.primary.model == "claude-haiku-4-5"

    def test_explicit_beats_env(self):
        resolved = resolve_model_plan(
            DevFlowModelPlan(research_primary="claude-opus-5"),
            config_getter=_getter({ENV_RESEARCH_PRIMARY: "claude-sonnet-4-6"}),
        )
        assert resolved.research_primary == "claude-opus-5"

    def test_explicit_nested_field_beats_env_sibling_still_resolves(self):
        """Setting one partner field must not freeze the others."""
        resolved = resolve_model_plan(
            DevFlowModelPlan(research_partner=ResearchPartnerPlan(enabled=True)),
            config_getter=_getter(
                {ENV_PARTNER_ENABLED: "false", ENV_PARTNER_MODEL: "nova-2-lite"}
            ),
        )
        assert resolved.research_partner.enabled is True
        assert resolved.research_partner.model == "nova-2-lite"

    @pytest.mark.parametrize(
        "raw,expected",
        [("1", True), ("true", True), ("yes", True), ("0", False), ("false", False), ("", False)],
    )
    def test_partner_enabled_env_coercion(self, raw: str, expected: bool):
        resolved = resolve_model_plan(
            None, config_getter=_getter({ENV_PARTNER_ENABLED: raw})
        )
        assert resolved.research_partner.enabled is expected

    def test_partner_backend_from_env(self):
        resolved = resolve_model_plan(
            None, config_getter=_getter({ENV_PARTNER_BACKEND: "nova"})
        )
        assert resolved.research_partner.backend == "nova"

    def test_dev_pool_from_env_json(self):
        resolved = resolve_model_plan(
            None,
            config_getter=_getter(
                {
                    ENV_DEV_POOL: (
                        '[{"agent": "nova", "model": "zai.glm-5"}, '
                        '{"agent": "nova", "model": "qwen.qwen3-coder-480b-a35b-v1:0"}]'
                    )
                }
            ),
        )
        assert [s.model for s in resolved.dev_pool] == [
            "zai.glm-5",
            "qwen.qwen3-coder-480b-a35b-v1:0",
        ]

    def test_explicit_empty_pool_beats_env(self):
        """An operator who explicitly passes ``dev_pool=[]`` means it."""
        resolved = resolve_model_plan(
            DevFlowModelPlan(dev_pool=[]),
            config_getter=_getter({ENV_DEV_POOL: '[{"agent": "nova"}]'}),
        )
        assert resolved.dev_pool == []

    def test_env_pool_unknown_backend_fails_fast(self):
        with pytest.raises(ValueError, match="unknown dev agent backend"):
            resolve_model_plan(
                None, config_getter=_getter({ENV_DEV_POOL: '[{"agent": "bogus"}]'})
            )

    def test_env_pool_invalid_json_raises(self):
        with pytest.raises(ValueError, match="JSON array"):
            resolve_model_plan(None, config_getter=_getter({ENV_DEV_POOL: "not json"}))

    def test_env_pool_non_array_json_raises(self):
        with pytest.raises(ValueError, match="JSON \\*array\\*"):
            resolve_model_plan(
                None, config_getter=_getter({ENV_DEV_POOL: '{"agent": "nova"}'})
            )

    def test_blank_env_value_falls_back_to_builtin(self):
        resolved = resolve_model_plan(
            None, config_getter=_getter({ENV_RESEARCH_PRIMARY: "   "})
        )
        assert resolved.research_primary == DEFAULT_RESEARCH_PRIMARY

    def test_explicit_review_pair_survives(self):
        resolved = resolve_model_plan(
            DevFlowModelPlan(
                review=ReviewPairPlan(
                    primary=DevAgentSpec(agent="codex", model="gpt-5.5"),
                    counter_model="nova-2-lite",
                )
            ),
            config_getter=_getter({ENV_REVIEW_COUNTER_MODEL: "ignored"}),
        )
        assert resolved.review.primary.agent == "codex"
        assert resolved.review.counter_model == "nova-2-lite"

    def test_resolver_returns_a_new_object(self):
        plan = DevFlowModelPlan()
        assert resolve_model_plan(plan, config_getter=_getter({})) is not plan


class TestExports:
    """The plan must be reachable from the package's public surface."""

    def test_reexported_from_models(self):
        from parrot.flows.dev_flow.models import DevFlowModelPlan as FromModels

        assert FromModels is DevFlowModelPlan

    def test_reexported_from_package(self):
        import parrot.flows.dev_flow as pkg

        assert pkg.DevFlowModelPlan is DevFlowModelPlan
        assert "DevFlowModelPlan" in pkg.__all__
