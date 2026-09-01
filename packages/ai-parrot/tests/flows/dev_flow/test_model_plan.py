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
    ENV_PARTNER_GPT_MODEL,
    ENV_PARTNER_NOVA_MODEL,
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

#: FEAT-482's authoritative key. Not re-exported by model_plan (which no
#: longer owns any partner enable/backend key), so named here.
ENV_RESEARCH_PARTNER = "DEV_FLOW_RESEARCH_PARTNER"


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
            DevFlowModelPlan.model_validate({"dev_pool": [{"agent": "not-a-backend", "model": "x"}]})

    def test_unknown_backend_message_names_the_offender(self):
        with pytest.raises(ValueError, match="not-a-backend"):
            DevFlowModelPlan.model_validate({"dev_pool": [{"agent": "not-a-backend"}]})

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
        plan = DevFlowModelPlan.model_validate({"dev_pool": [{"agent": "nova", "model": "totally-made-up-model"}]})
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
        """Setting one partner field must not freeze the others.

        FEAT-487: the sibling now resolves from FEAT-482's per-backend
        model key rather than a partner-specific ``_MODEL`` key.
        """
        resolved = resolve_model_plan(
            DevFlowModelPlan(research_partner=ResearchPartnerPlan(enabled=True)),
            config_getter=_getter(
                {ENV_RESEARCH_PARTNER: "", ENV_PARTNER_GPT_MODEL: "openai.gpt-oss-120b"}
            ),
        )
        # `enabled` was explicit, so the (disabled) config must not win...
        assert resolved.research_partner.enabled is True
        # ...while `model` still resolves from config.
        assert resolved.research_partner.model == "openai.gpt-oss-120b"

    def test_partner_backend_from_env(self):
        """FEAT-487: one key carries enable AND backend."""
        resolved = resolve_model_plan(
            None, config_getter=_getter({ENV_RESEARCH_PARTNER: "nova"})
        )
        assert resolved.research_partner.backend == "nova"
        assert resolved.research_partner.enabled is True

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
            resolve_model_plan(None, config_getter=_getter({ENV_DEV_POOL: '[{"agent": "bogus"}]'}))

    def test_env_pool_invalid_json_raises(self):
        with pytest.raises(ValueError, match="JSON array"):
            resolve_model_plan(None, config_getter=_getter({ENV_DEV_POOL: "not json"}))

    def test_env_pool_non_array_json_raises(self):
        with pytest.raises(ValueError, match="JSON \\*array\\*"):
            resolve_model_plan(None, config_getter=_getter({ENV_DEV_POOL: '{"agent": "nova"}'}))

    def test_blank_env_value_falls_back_to_builtin(self):
        resolved = resolve_model_plan(None, config_getter=_getter({ENV_RESEARCH_PRIMARY: "   "}))
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


class TestPartnerKeyDedup:
    """FEAT-487 — one key set for the research-partner seat.

    FEAT-486 shipped `DEV_FLOW_RESEARCH_PARTNER_ENABLED`/`_BACKEND`/`_MODEL`
    alongside FEAT-482's `DEV_FLOW_RESEARCH_PARTNER` + per-backend model
    keys. These pin the retired keys dead and the survivors live.
    """

    def test_partner_enabled_from_feat482_key(self):
        resolved = resolve_model_plan(
            None, config_getter=_getter({ENV_RESEARCH_PARTNER: "gpt"})
        )
        assert resolved.research_partner.enabled is True
        assert resolved.research_partner.backend == "gpt"

    def test_partner_disabled_when_key_unset(self):
        """The pure-addition guarantee: unset ⇒ the seat does not run."""
        resolved = resolve_model_plan(None, config_getter=_getter({}))
        assert resolved.research_partner.enabled is False

    def test_partner_disabled_when_key_blank(self):
        resolved = resolve_model_plan(
            None, config_getter=_getter({ENV_RESEARCH_PARTNER: ""})
        )
        assert resolved.research_partner.enabled is False

    def test_partner_model_follows_backend_nova(self):
        """THE bug FEAT-487 fixes: a nova partner must not default to gpt-*."""
        resolved = resolve_model_plan(
            None, config_getter=_getter({ENV_RESEARCH_PARTNER: "nova"})
        )
        assert resolved.research_partner.model == "us.amazon.nova-2-lite-v1:0"
        assert not resolved.research_partner.model.startswith("gpt-")

    def test_partner_model_follows_backend_gpt(self):
        resolved = resolve_model_plan(
            None, config_getter=_getter({ENV_RESEARCH_PARTNER: "gpt"})
        )
        assert resolved.research_partner.model == "gpt-5.6-sol"

    def test_per_backend_model_keys_are_honoured(self):
        for backend, key, value in (
            ("gpt", ENV_PARTNER_GPT_MODEL, "openai.gpt-oss-120b"),
            ("nova", ENV_PARTNER_NOVA_MODEL, "us.amazon.nova-pro-v1:0"),
        ):
            resolved = resolve_model_plan(
                None,
                config_getter=_getter({ENV_RESEARCH_PARTNER: backend, key: value}),
            )
            assert resolved.research_partner.model == value

    def test_explicit_plan_still_beats_config(self):
        resolved = resolve_model_plan(
            DevFlowModelPlan(
                research_partner=ResearchPartnerPlan(
                    enabled=True, backend="nova", model="pinned-model"
                )
            ),
            config_getter=_getter({ENV_RESEARCH_PARTNER: "gpt"}),
        )
        assert resolved.research_partner.backend == "nova"
        assert resolved.research_partner.model == "pinned-model"

    def test_retired_keys_are_ignored(self):
        """The FEAT-486 keys must be inert — they no longer enable the seat."""
        resolved = resolve_model_plan(
            None,
            config_getter=_getter(
                {
                    "DEV_FLOW_RESEARCH_PARTNER_ENABLED": "1",
                    "DEV_FLOW_RESEARCH_PARTNER_BACKEND": "nova",
                    "DEV_FLOW_RESEARCH_PARTNER_MODEL": "ignored-model",
                }
            ),
        )
        assert resolved.research_partner.enabled is False
        assert resolved.research_partner.backend == "gpt"
        assert resolved.research_partner.model == "gpt-5.6-sol"

    def test_retired_constants_are_gone(self):
        """Guard against a well-meaning re-introduction."""
        from parrot.flows.dev_flow import model_plan

        for name in ("ENV_PARTNER_ENABLED", "ENV_PARTNER_BACKEND", "ENV_PARTNER_MODEL"):
            assert not hasattr(model_plan, name), f"{name} was re-added"

    def test_invalid_backend_surfaces_feat482_error(self):
        """Delegation means FEAT-482's own error text, not a second dialect."""
        with pytest.raises(ValueError, match="gpt, nova"):
            resolve_model_plan(
                None, config_getter=_getter({ENV_RESEARCH_PARTNER: "bogus"})
            )

    def test_anthropic_partner_model_rejected(self):
        """The family guard now reaches the plan resolver via delegation."""
        with pytest.raises(ValueError, match="research-partner seat"):
            resolve_model_plan(
                None,
                config_getter=_getter(
                    {
                        ENV_RESEARCH_PARTNER: "nova",
                        ENV_PARTNER_NOVA_MODEL: "us.anthropic.claude-opus-5",
                    }
                ),
            )
