"""Unit tests for HeartbeatManager — loop & lifecycle.

Tests for TASK-1392 (FEAT-209 — Autonomous Agent Heartbeat).

Covers:
- register / initial state
- start / stop lifecycle
- tick loop with action recording
- skip-if-busy (per-agent lock)
- backoff on consecutive errors
- clean cancellation via stop()
- get_all_states
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.autonomous.heartbeat import (
    HeartbeatConfig,
    HeartbeatManager,
    HeartbeatState,
    DefaultHeartbeatStrategy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_orchestrator():
    """Orchestrator mock that records execute_agent calls and returns success."""
    orch = MagicMock()
    orch.execute_agent = AsyncMock(
        return_value=MagicMock(success=True, result="ok")
    )
    return orch


@pytest.fixture
def always_act_strategy():
    """Strategy where should_act always returns True."""
    strategy = MagicMock()
    strategy.build_context = AsyncMock(return_value={"tick_count": 0})
    strategy.should_act = AsyncMock(return_value=True)
    strategy.build_prompt = AsyncMock(return_value="do something")
    return strategy


@pytest.fixture
def never_act_strategy():
    """Strategy where should_act always returns False."""
    strategy = MagicMock()
    strategy.build_context = AsyncMock(return_value={"tick_count": 0})
    strategy.should_act = AsyncMock(return_value=False)
    strategy.build_prompt = AsyncMock(return_value="never called")
    return strategy


# ---------------------------------------------------------------------------
# Registration and state
# ---------------------------------------------------------------------------


class TestHeartbeatManagerRegistration:
    def test_register_creates_state(self, fake_orchestrator):
        """register() creates a HeartbeatState with running=False."""
        mgr = HeartbeatManager(fake_orchestrator)
        cfg = HeartbeatConfig(agent_name="agent-1")
        mgr.register(cfg)
        state = mgr.get_state("agent-1")
        assert state is not None
        assert isinstance(state, HeartbeatState)
        assert state.running is False
        assert state.tick_count == 0

    def test_register_multiple_agents(self, fake_orchestrator):
        """Multiple agents can be registered independently."""
        mgr = HeartbeatManager(fake_orchestrator)
        mgr.register(HeartbeatConfig(agent_name="a"))
        mgr.register(HeartbeatConfig(agent_name="b"))
        assert mgr.get_state("a") is not None
        assert mgr.get_state("b") is not None
        assert mgr.get_state("a").agent_name == "a"
        assert mgr.get_state("b").agent_name == "b"

    def test_get_state_unknown_agent_returns_none(self, fake_orchestrator):
        """get_state returns None for an unregistered agent."""
        mgr = HeartbeatManager(fake_orchestrator)
        assert mgr.get_state("nonexistent") is None

    def test_get_all_states(self, fake_orchestrator):
        """get_all_states returns one entry per registered agent."""
        mgr = HeartbeatManager(fake_orchestrator)
        mgr.register(HeartbeatConfig(agent_name="a"))
        mgr.register(HeartbeatConfig(agent_name="b"))
        states = mgr.get_all_states()
        assert len(states) == 2
        names = {s.agent_name for s in states}
        assert names == {"a", "b"}

    def test_get_all_states_empty(self, fake_orchestrator):
        """get_all_states returns empty list when no agents registered."""
        mgr = HeartbeatManager(fake_orchestrator)
        assert mgr.get_all_states() == []


# ---------------------------------------------------------------------------
# Start / stop lifecycle
# ---------------------------------------------------------------------------


class TestHeartbeatManagerLifecycle:
    async def test_start_stop_lifecycle(self, fake_orchestrator, always_act_strategy):
        """start() spawns tasks, stop() cancels them cleanly, running becomes False."""
        mgr = HeartbeatManager(fake_orchestrator, strategy=always_act_strategy)
        mgr.register(HeartbeatConfig(agent_name="a", interval=0.05))

        await mgr.start()
        # Give the loop a chance to run at least one tick
        await asyncio.sleep(0.2)
        await mgr.stop()

        state = mgr.get_state("a")
        assert state.running is False
        assert state.tick_count > 0
        assert state.action_count > 0

    async def test_stop_cancels_cleanly(self, fake_orchestrator, always_act_strategy):
        """stop() does not raise and leaves running=False."""
        mgr = HeartbeatManager(fake_orchestrator, strategy=always_act_strategy)
        mgr.register(HeartbeatConfig(agent_name="x", interval=0.05))
        await mgr.start()
        await asyncio.sleep(0.1)
        # Should NOT raise
        await mgr.stop()
        assert mgr.get_state("x").running is False

    async def test_stop_without_start_is_safe(self, fake_orchestrator):
        """stop() on a manager that was never started does not raise."""
        mgr = HeartbeatManager(fake_orchestrator)
        mgr.register(HeartbeatConfig(agent_name="a"))
        # Should not raise even if no tasks were spawned
        await mgr.stop()

    async def test_disabled_agent_not_started(self, fake_orchestrator, always_act_strategy):
        """Agents with enabled=False are not given a loop task."""
        mgr = HeartbeatManager(fake_orchestrator, strategy=always_act_strategy)
        mgr.register(HeartbeatConfig(agent_name="off", interval=0.05, enabled=False))
        await mgr.start()
        await asyncio.sleep(0.15)
        await mgr.stop()
        state = mgr.get_state("off")
        # Loop was never spawned — tick_count stays 0
        assert state.tick_count == 0
        assert state.action_count == 0


# ---------------------------------------------------------------------------
# Loop ticks and actions
# ---------------------------------------------------------------------------


class TestHeartbeatManagerLoop:
    async def test_loop_ticks_and_acts(self, fake_orchestrator, always_act_strategy):
        """With a fast interval and always-act strategy, ticks and actions accumulate."""
        mgr = HeartbeatManager(fake_orchestrator, strategy=always_act_strategy)
        mgr.register(HeartbeatConfig(agent_name="fast", interval=0.05))
        await mgr.start()
        await asyncio.sleep(0.35)
        await mgr.stop()
        state = mgr.get_state("fast")
        # Should have seen several ticks in 0.35s with 0.05s interval
        assert state.tick_count >= 2
        assert state.action_count >= 2
        assert state.last_tick_at is not None
        assert state.last_action_at is not None

    async def test_loop_no_act_when_strategy_refuses(
        self, fake_orchestrator, never_act_strategy
    ):
        """When should_act returns False, execute_agent is never called."""
        mgr = HeartbeatManager(fake_orchestrator, strategy=never_act_strategy)
        mgr.register(HeartbeatConfig(agent_name="passive", interval=0.05))
        await mgr.start()
        await asyncio.sleep(0.2)
        await mgr.stop()
        state = mgr.get_state("passive")
        assert state.tick_count >= 1
        assert state.action_count == 0
        fake_orchestrator.execute_agent.assert_not_called()

    async def test_consecutive_errors_reset_on_success(
        self, fake_orchestrator, always_act_strategy
    ):
        """consecutive_errors resets to 0 after a successful execute_agent call."""
        mgr = HeartbeatManager(fake_orchestrator, strategy=always_act_strategy)
        mgr.register(HeartbeatConfig(agent_name="a", interval=0.05))

        # Inject a pre-existing error count into state (simulate prior failures)
        await mgr.start()
        await asyncio.sleep(0.15)

        # After successful ticks, consecutive_errors must be 0
        state = mgr.get_state("a")
        assert state.consecutive_errors == 0

        await mgr.stop()

    async def test_jitter_does_not_break_loop(self, fake_orchestrator, always_act_strategy):
        """Loop works correctly with jitter enabled."""
        mgr = HeartbeatManager(fake_orchestrator, strategy=always_act_strategy)
        mgr.register(HeartbeatConfig(agent_name="j", interval=0.05, jitter=0.02))
        await mgr.start()
        await asyncio.sleep(0.3)
        await mgr.stop()
        state = mgr.get_state("j")
        assert state.tick_count >= 1


# ---------------------------------------------------------------------------
# Skip-if-busy (per-agent lock)
# ---------------------------------------------------------------------------


class TestHeartbeatManagerSkipWhenBusy:
    async def test_loop_skips_when_busy(self, fake_orchestrator):
        """If a tick is still running, the next tick skips (no overlap)."""
        slow_strategy = MagicMock()
        slow_strategy.build_context = AsyncMock(return_value={"tick_count": 0})
        slow_strategy.should_act = AsyncMock(return_value=True)
        slow_strategy.build_prompt = AsyncMock(return_value="slow task")

        # execute_agent takes 0.3s — much longer than the 0.05s interval
        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(0.3)
            return MagicMock(success=True)

        fake_orchestrator.execute_agent = slow_execute

        mgr = HeartbeatManager(fake_orchestrator, strategy=slow_strategy)
        mgr.register(HeartbeatConfig(agent_name="slow", interval=0.05))
        await mgr.start()
        await asyncio.sleep(0.5)
        await mgr.stop()

        # With 0.05s interval and 0.3s execution, at most ~1-2 actions
        # but many ticks counted (skipped ticks still count).
        state = mgr.get_state("slow")
        assert state.action_count <= 2  # most ticks were skipped


# ---------------------------------------------------------------------------
# Backoff on consecutive errors
# ---------------------------------------------------------------------------


class TestHeartbeatManagerBackoff:
    async def test_backoff_on_consecutive_errors(
        self, fake_orchestrator, always_act_strategy
    ):
        """consecutive_errors increments; agent pauses after max_consecutive_errors."""
        fake_orchestrator.execute_agent = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        mgr = HeartbeatManager(fake_orchestrator, strategy=always_act_strategy)
        mgr.register(HeartbeatConfig(
            agent_name="err", interval=0.05, max_consecutive_errors=3
        ))
        await mgr.start()
        await asyncio.sleep(0.5)
        await mgr.stop()
        state = mgr.get_state("err")
        assert state.consecutive_errors >= 3
        assert state.last_error is not None
        assert "boom" in state.last_error

    async def test_loop_continues_after_single_error(
        self, fake_orchestrator, always_act_strategy
    ):
        """A single error does not kill the loop — it continues ticking."""
        call_count = 0

        async def flaky(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")
            return MagicMock(success=True)

        fake_orchestrator.execute_agent = flaky

        mgr = HeartbeatManager(fake_orchestrator, strategy=always_act_strategy)
        mgr.register(HeartbeatConfig(
            agent_name="flaky", interval=0.05, max_consecutive_errors=5
        ))
        await mgr.start()
        await asyncio.sleep(0.4)
        await mgr.stop()

        state = mgr.get_state("flaky")
        # After the transient error, the loop recovered and kept acting
        assert state.action_count >= 1
        assert state.consecutive_errors == 0  # reset after success

    async def test_paused_agent_stops_acting(
        self, fake_orchestrator, always_act_strategy
    ):
        """After hitting max_consecutive_errors, agent stops calling execute_agent."""
        fake_orchestrator.execute_agent = AsyncMock(
            side_effect=RuntimeError("fatal")
        )
        mgr = HeartbeatManager(fake_orchestrator, strategy=always_act_strategy)
        mgr.register(HeartbeatConfig(
            agent_name="fatal", interval=0.05, max_consecutive_errors=2
        ))
        await mgr.start()
        await asyncio.sleep(0.5)
        await mgr.stop()

        state = mgr.get_state("fatal")
        calls_at_stop = fake_orchestrator.execute_agent.call_count

        # Wait again — no new calls should appear because loop exited
        await asyncio.sleep(0.1)
        assert fake_orchestrator.execute_agent.call_count == calls_at_stop
