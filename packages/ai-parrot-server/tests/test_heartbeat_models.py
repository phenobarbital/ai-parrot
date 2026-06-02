"""Unit tests for HeartbeatConfig, HeartbeatState, and DefaultHeartbeatStrategy.

Tests for TASK-1391 (FEAT-209 — Autonomous Agent Heartbeat).
"""

import pytest

from parrot.autonomous.heartbeat import (
    DefaultHeartbeatStrategy,
    HeartbeatConfig,
    HeartbeatState,
)


class TestHeartbeatConfig:
    """Tests for the HeartbeatConfig Pydantic model."""

    def test_defaults(self):
        """Default values match the spec."""
        cfg = HeartbeatConfig(agent_name="test-agent")
        assert cfg.interval == 60.0
        assert cfg.jitter == 0.0
        assert cfg.enabled is True
        assert cfg.max_consecutive_errors == 5
        assert cfg.mission is None

    def test_interval_must_be_positive(self):
        """interval=0 must be rejected."""
        with pytest.raises(Exception):
            HeartbeatConfig(agent_name="a", interval=0)

    def test_interval_negative_rejected(self):
        """Negative interval must be rejected."""
        with pytest.raises(Exception):
            HeartbeatConfig(agent_name="a", interval=-1)

    def test_jitter_must_be_non_negative(self):
        """Negative jitter must be rejected."""
        with pytest.raises(Exception):
            HeartbeatConfig(agent_name="a", jitter=-1)

    def test_jitter_zero_allowed(self):
        """jitter=0 is allowed (default)."""
        cfg = HeartbeatConfig(agent_name="a", jitter=0.0)
        assert cfg.jitter == 0.0

    def test_max_consecutive_errors_minimum_one(self):
        """max_consecutive_errors must be >= 1."""
        with pytest.raises(Exception):
            HeartbeatConfig(agent_name="a", max_consecutive_errors=0)

    def test_custom_values(self):
        """Custom values are stored correctly."""
        cfg = HeartbeatConfig(
            agent_name="my-agent",
            interval=30.0,
            jitter=5.0,
            enabled=False,
            max_consecutive_errors=3,
            mission="Do some work",
        )
        assert cfg.agent_name == "my-agent"
        assert cfg.interval == 30.0
        assert cfg.jitter == 5.0
        assert cfg.enabled is False
        assert cfg.max_consecutive_errors == 3
        assert cfg.mission == "Do some work"


class TestHeartbeatState:
    """Tests for the HeartbeatState Pydantic model."""

    def test_defaults(self):
        """All fields initialise to their zero/None defaults."""
        state = HeartbeatState(agent_name="test-agent")
        assert state.running is False
        assert state.tick_count == 0
        assert state.action_count == 0
        assert state.last_tick_at is None
        assert state.last_action_at is None
        assert state.consecutive_errors == 0
        assert state.last_error is None

    def test_agent_name_stored(self):
        """agent_name is stored as provided."""
        state = HeartbeatState(agent_name="my-bot")
        assert state.agent_name == "my-bot"

    def test_fields_mutable(self):
        """State fields can be mutated (manager updates them in-place)."""
        state = HeartbeatState(agent_name="a")
        state.running = True
        state.tick_count = 5
        state.action_count = 2
        assert state.running is True
        assert state.tick_count == 5
        assert state.action_count == 2


class TestDefaultHeartbeatStrategy:
    """Tests for DefaultHeartbeatStrategy."""

    async def test_build_context_returns_dict_with_tick_count_and_config(self):
        """build_context returns a dict with 'tick_count' and 'config' keys."""
        strategy = DefaultHeartbeatStrategy()
        cfg = HeartbeatConfig(agent_name="a")
        ctx = await strategy.build_context(cfg)
        assert "tick_count" in ctx
        assert "config" in ctx
        assert ctx["config"] is cfg

    async def test_should_act_with_pending_work(self):
        """should_act returns True when has_pending_work() returns True."""

        async def has_work():
            return True

        strategy = DefaultHeartbeatStrategy(has_pending_work=has_work)
        cfg = HeartbeatConfig(agent_name="a")
        ctx = await strategy.build_context(cfg)
        assert await strategy.should_act(ctx) is True

    async def test_should_not_act_without_pending_work_and_not_on_n_tick(self):
        """should_act returns False when no pending work and tick_count not on N boundary."""

        async def no_work():
            return False

        strategy = DefaultHeartbeatStrategy(has_pending_work=no_work)
        cfg = HeartbeatConfig(agent_name="a")
        ctx = await strategy.build_context(cfg)
        ctx["tick_count"] = 3  # not on N boundary (default N=10)
        assert await strategy.should_act(ctx) is False

    async def test_fallback_every_n_ticks(self):
        """Fallback cadence fires when tick_count is a positive multiple of N."""
        strategy = DefaultHeartbeatStrategy(act_every_n_ticks=5)
        cfg = HeartbeatConfig(agent_name="a")
        ctx = await strategy.build_context(cfg)
        ctx["tick_count"] = 10  # multiple of 5
        assert await strategy.should_act(ctx) is True

    async def test_fallback_tick_zero_does_not_act(self):
        """tick_count=0 should not trigger the fallback (guard: tick_count > 0)."""
        strategy = DefaultHeartbeatStrategy(act_every_n_ticks=1)
        cfg = HeartbeatConfig(agent_name="a")
        ctx = await strategy.build_context(cfg)
        ctx["tick_count"] = 0
        # With no has_pending_work and tick=0, should not act
        assert await strategy.should_act(ctx) is False

    async def test_fallback_fires_on_exact_n(self):
        """Fallback fires exactly on multiples of N."""
        strategy = DefaultHeartbeatStrategy(act_every_n_ticks=3)
        cfg = HeartbeatConfig(agent_name="a")
        ctx = await strategy.build_context(cfg)

        ctx["tick_count"] = 3
        assert await strategy.should_act(ctx) is True

        ctx["tick_count"] = 6
        assert await strategy.should_act(ctx) is True

        ctx["tick_count"] = 4  # not a multiple
        assert await strategy.should_act(ctx) is False

    async def test_pending_work_takes_priority_over_fallback(self):
        """has_pending_work=True triggers even when not on N boundary."""

        async def always():
            return True

        strategy = DefaultHeartbeatStrategy(
            has_pending_work=always, act_every_n_ticks=100
        )
        cfg = HeartbeatConfig(agent_name="a")
        ctx = await strategy.build_context(cfg)
        ctx["tick_count"] = 1  # not on N boundary
        assert await strategy.should_act(ctx) is True

    async def test_build_prompt_returns_mission_from_config(self):
        """build_prompt returns cfg.mission when set."""
        strategy = DefaultHeartbeatStrategy()
        cfg = HeartbeatConfig(agent_name="a", mission="check the queue")
        ctx = {"config": cfg}
        prompt = await strategy.build_prompt(ctx)
        assert prompt == "check the queue"

    async def test_build_prompt_returns_default_when_no_mission(self):
        """build_prompt returns a sensible fallback when mission is None."""
        strategy = DefaultHeartbeatStrategy()
        cfg = HeartbeatConfig(agent_name="a")
        ctx = {"config": cfg}
        prompt = await strategy.build_prompt(ctx)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    async def test_has_pending_work_exception_falls_through_to_n_ticks(self):
        """If has_pending_work raises, the fallback N-ticks check still applies."""

        async def broken():
            raise RuntimeError("connection lost")

        strategy = DefaultHeartbeatStrategy(
            has_pending_work=broken, act_every_n_ticks=5
        )
        cfg = HeartbeatConfig(agent_name="a")
        ctx = await strategy.build_context(cfg)
        ctx["tick_count"] = 5  # on N boundary — fallback should trigger
        # The exception in has_pending_work is swallowed; fallback fires.
        assert await strategy.should_act(ctx) is True

    async def test_default_strategy_idle_tick_no_action(self):
        """should_act returns False when has_pending_work=None, tick_count not on N boundary."""
        strategy = DefaultHeartbeatStrategy(act_every_n_ticks=10)
        cfg = HeartbeatConfig(agent_name="a")
        ctx = await strategy.build_context(cfg)
        ctx["tick_count"] = 3  # not a multiple of 10, and no has_pending_work
        assert await strategy.should_act(ctx) is False
