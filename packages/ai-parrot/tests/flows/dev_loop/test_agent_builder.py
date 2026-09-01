"""Unit tests for the dev-agent dispatcher builder & pool env parsing (FEAT-323 TASK-1859)."""

from __future__ import annotations

import pytest

from parrot.flows.dev_loop.agent_builder import (
    DEFAULT_LLM_MAX_TURNS,
    ENV_LLM_MAX_TURNS,
    build_dispatcher,
    parse_pool_env,
    resolve_pool_max,
)
from parrot.flows.dev_loop.models import DevAgentSpec, LLMCodeDispatchProfile


def fake_getter(env: dict):
    def _get(key, fallback=None):
        return env.get(key, fallback)

    return _get


class TestBuildDispatcher:
    @pytest.mark.parametrize(
        "backend",
        ["claude-code", "codex", "gemini", "nvidia", "grok", "zai", "moonshot"],
    )
    def test_all_backends_build(self, backend):
        dispatcher, profile = build_dispatcher(
            DevAgentSpec(agent=backend),
            redis_url="redis://localhost:6379/0",
            max_concurrent=2,
            stream_ttl_seconds=3600,
            config_getter=fake_getter({}),
        )
        assert hasattr(dispatcher, "dispatch")
        assert profile is not None

    def test_codex_default_model(self):
        _, profile = build_dispatcher(
            DevAgentSpec(agent="codex"),
            redis_url="redis://localhost:6379/0",
            max_concurrent=1,
            stream_ttl_seconds=3600,
            config_getter=fake_getter({}),
        )
        assert profile.model == "gpt-5.5"

    def test_explicit_model_wins(self):
        _, profile = build_dispatcher(
            DevAgentSpec(agent="codex", model="gpt-9"),
            redis_url="redis://localhost:6379/0",
            max_concurrent=1,
            stream_ttl_seconds=3600,
            config_getter=fake_getter({"DEV_LOOP_CODEX_MODEL": "gpt-should-not-win"}),
        )
        assert profile.model == "gpt-9"

    def test_env_model_used_when_spec_model_empty(self):
        _, profile = build_dispatcher(
            DevAgentSpec(agent="gemini"),
            redis_url="redis://localhost:6379/0",
            max_concurrent=1,
            stream_ttl_seconds=3600,
            config_getter=fake_getter({"DEV_LOOP_GEMINI_MODEL": "gemini-pro"}),
        )
        assert profile.model == "gemini-pro"

    def test_nvidia_llm_field_prefixed(self):
        _, profile = build_dispatcher(
            DevAgentSpec(agent="nvidia"),
            redis_url="redis://localhost:6379/0",
            max_concurrent=1,
            stream_ttl_seconds=3600,
            config_getter=fake_getter({}),
        )
        assert profile.llm == "nvidia:minimaxai/minimax-m3"

    def test_zai_defaults(self):
        _, profile = build_dispatcher(
            DevAgentSpec(agent="zai"),
            redis_url="redis://localhost:6379/0",
            max_concurrent=1,
            stream_ttl_seconds=3600,
            config_getter=fake_getter({}),
        )
        assert profile.model == "glm-5.2"
        assert profile.enable_thinking is True
        assert profile.reasoning_effort == "max"

    def test_claude_code_default_model(self):
        _, profile = build_dispatcher(
            DevAgentSpec(agent="claude-code"),
            redis_url="redis://localhost:6379/0",
            max_concurrent=1,
            stream_ttl_seconds=3600,
            config_getter=fake_getter({}),
        )
        assert profile.model == "claude-sonnet-4-6"


class TestLLMTurnBudget:
    """The in-process coding loop's turn budget (``DEV_LOOP_LLM_MAX_TURNS``).

    Regression: `LLMCodeDispatchProfile`'s library default of 24 turns was
    unreachable from config, and every seat of an 8-task run hit it — one
    chat completion per turn is simply not the budget an agentic CLI spends.
    The dev-loop wiring defaults to 60 and stays overridable.
    """

    LOOP_BACKENDS = ("nvidia", "grok", "zai", "moonshot", "nova")

    @pytest.mark.parametrize("backend", LOOP_BACKENDS)
    def test_default_is_sixty_not_the_library_default(self, backend):
        _dispatcher, profile = build_dispatcher(
            DevAgentSpec(agent=backend, model="m"),
            redis_url="redis://x",
            max_concurrent=1,
            stream_ttl_seconds=60,
            config_getter=fake_getter({}),
        )
        assert profile.max_turns == DEFAULT_LLM_MAX_TURNS == 60
        assert LLMCodeDispatchProfile.model_fields["max_turns"].default == 24

    @pytest.mark.parametrize("backend", LOOP_BACKENDS)
    def test_env_key_overrides(self, backend):
        _dispatcher, profile = build_dispatcher(
            DevAgentSpec(agent=backend, model="m"),
            redis_url="redis://x",
            max_concurrent=1,
            stream_ttl_seconds=60,
            config_getter=fake_getter({ENV_LLM_MAX_TURNS: "80"}),
        )
        assert profile.max_turns == 80

    def test_unparsable_value_falls_back(self):
        _dispatcher, profile = build_dispatcher(
            DevAgentSpec(agent="nova", model="m"),
            redis_url="redis://x",
            max_concurrent=1,
            stream_ttl_seconds=60,
            config_getter=fake_getter({ENV_LLM_MAX_TURNS: "sesenta"}),
        )
        assert profile.max_turns == DEFAULT_LLM_MAX_TURNS

    @pytest.mark.parametrize("backend", ["claude-code", "codex", "gemini"])
    def test_agentic_cli_backends_have_no_turn_budget(self, backend):
        """Those run their own loop — there is nothing here to set."""
        _dispatcher, profile = build_dispatcher(
            DevAgentSpec(agent=backend, model="m"),
            redis_url="redis://x",
            max_concurrent=1,
            stream_ttl_seconds=60,
            config_getter=fake_getter({ENV_LLM_MAX_TURNS: "80"}),
        )
        assert not hasattr(profile, "max_turns")


class TestEnvParsing:
    def test_valid_json(self):
        cfg = parse_pool_env(
            fake_getter(
                {"DEV_LOOP_DEV_AGENTS": '[{"agent": "claude-code", "count": 2}]'}
            )
        )
        assert cfg is not None
        assert cfg.agents[0].count == 2

    def test_valid_json_with_isolation(self):
        cfg = parse_pool_env(
            fake_getter(
                {
                    "DEV_LOOP_DEV_AGENTS": '[{"agent": "codex"}]',
                    "DEV_LOOP_DEV_ISOLATION": "isolated",
                }
            )
        )
        assert cfg.isolation_mode == "isolated"

    def test_invalid_json_returns_none(self):
        assert parse_pool_env(fake_getter({"DEV_LOOP_DEV_AGENTS": "{oops"})) is None

    def test_unknown_backend_returns_none(self):
        cfg = parse_pool_env(
            fake_getter({"DEV_LOOP_DEV_AGENTS": '[{"agent": "not-a-backend"}]'})
        )
        assert cfg is None

    def test_absent_returns_none(self):
        assert parse_pool_env(fake_getter({})) is None


class TestResolvePoolMax:
    def test_default_when_unset(self):
        assert resolve_pool_max(fake_getter({})) == 4

    def test_parses_int(self):
        assert resolve_pool_max(fake_getter({"DEV_LOOP_DEV_POOL_MAX": "8"})) == 8

    def test_invalid_falls_back_to_default(self):
        assert resolve_pool_max(fake_getter({"DEV_LOOP_DEV_POOL_MAX": "oops"})) == 4

    def test_clamped_to_at_least_one(self):
        assert resolve_pool_max(fake_getter({"DEV_LOOP_DEV_POOL_MAX": "0"})) == 1
