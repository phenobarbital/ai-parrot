"""Integration tests for the heartbeat system.

Tests for TASK-1393 (FEAT-209 — Autonomous Agent Heartbeat).

Verifies that HeartbeatManager + DefaultHeartbeatStrategy drive the
orchestrator and record state correctly. Also verifies that the public
export from parrot.autonomous works.
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.autonomous.heartbeat import (
    HeartbeatConfig,
    HeartbeatManager,
    DefaultHeartbeatStrategy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_orchestrator():
    """Minimal orchestrator fake for integration testing."""
    orch = MagicMock()
    orch.execute_agent = AsyncMock(
        return_value=MagicMock(success=True, result="done")
    )
    return orch


# ---------------------------------------------------------------------------
# Integration: HeartbeatManager + DefaultHeartbeatStrategy + fake orchestrator
# ---------------------------------------------------------------------------


class TestHeartbeatIntegration:
    async def test_heartbeat_drives_orchestrator(self, fake_orchestrator):
        """Real HeartbeatManager + real DefaultHeartbeatStrategy
        drives the orchestrator and records state correctly."""

        async def always_pending():
            return True

        strategy = DefaultHeartbeatStrategy(has_pending_work=always_pending)
        mgr = HeartbeatManager(fake_orchestrator, strategy=strategy)
        mgr.register(HeartbeatConfig(
            agent_name="integration-agent",
            interval=0.05,
            mission="check everything",
        ))

        await mgr.start()
        await asyncio.sleep(0.3)
        await mgr.stop()

        state = mgr.get_state("integration-agent")
        assert state.tick_count > 0
        assert state.action_count > 0
        assert state.last_action_at is not None
        assert state.running is False
        assert fake_orchestrator.execute_agent.called

    async def test_mission_forwarded_to_execute_agent(self, fake_orchestrator):
        """The mission string is forwarded as the 'task' argument to execute_agent."""

        async def always_pending():
            return True

        mission = "inspect the daily ledger"
        strategy = DefaultHeartbeatStrategy(has_pending_work=always_pending)
        mgr = HeartbeatManager(fake_orchestrator, strategy=strategy)
        mgr.register(HeartbeatConfig(
            agent_name="mission-agent",
            interval=0.05,
            mission=mission,
        ))

        await mgr.start()
        await asyncio.sleep(0.2)
        await mgr.stop()

        # execute_agent should have been called with the agent name and mission
        assert fake_orchestrator.execute_agent.called
        first_call_args = fake_orchestrator.execute_agent.call_args_list[0]
        # First positional arg is agent_name, second is task (mission)
        assert first_call_args.args[0] == "mission-agent"
        assert first_call_args.args[1] == mission

    async def test_no_work_no_action(self, fake_orchestrator):
        """When has_pending_work returns False, execute_agent is not called."""

        async def no_work():
            return False

        strategy = DefaultHeartbeatStrategy(
            has_pending_work=no_work,
            act_every_n_ticks=1000,  # effectively never via fallback
        )
        mgr = HeartbeatManager(fake_orchestrator, strategy=strategy)
        mgr.register(HeartbeatConfig(
            agent_name="idle-agent",
            interval=0.05,
        ))

        await mgr.start()
        await asyncio.sleep(0.2)
        await mgr.stop()

        state = mgr.get_state("idle-agent")
        # Ticks ran but no actions were taken
        assert state.tick_count >= 1
        assert state.action_count == 0
        fake_orchestrator.execute_agent.assert_not_called()

    async def test_multiple_agents_independent(self, fake_orchestrator):
        """Multiple agents run independently with separate state."""

        async def always():
            return True

        strategy = DefaultHeartbeatStrategy(has_pending_work=always)
        mgr = HeartbeatManager(fake_orchestrator, strategy=strategy)
        mgr.register(HeartbeatConfig(agent_name="alpha", interval=0.05))
        mgr.register(HeartbeatConfig(agent_name="beta", interval=0.05))

        await mgr.start()
        await asyncio.sleep(0.3)
        await mgr.stop()

        alpha = mgr.get_state("alpha")
        beta = mgr.get_state("beta")

        assert alpha.tick_count > 0
        assert beta.tick_count > 0
        assert alpha.action_count > 0
        assert beta.action_count > 0
        # States are independent
        assert alpha.agent_name == "alpha"
        assert beta.agent_name == "beta"

    async def test_fallback_n_ticks_triggers_action(self, fake_orchestrator):
        """Without has_pending_work, the fallback N-ticks cadence triggers actions."""
        # Use act_every_n_ticks=2 so fallback fires often with fast interval
        strategy = DefaultHeartbeatStrategy(act_every_n_ticks=2)
        mgr = HeartbeatManager(fake_orchestrator, strategy=strategy)
        mgr.register(HeartbeatConfig(
            agent_name="fallback-agent",
            interval=0.05,
            mission="fallback check",
        ))

        await mgr.start()
        await asyncio.sleep(0.5)
        await mgr.stop()

        state = mgr.get_state("fallback-agent")
        # With 0.05s interval and act_every_n_ticks=2, should see several actions
        assert state.action_count >= 1


# ---------------------------------------------------------------------------
# Export contract: from parrot.autonomous import HeartbeatManager etc.
# ---------------------------------------------------------------------------


class TestHeartbeatPublicExport:
    def test_import_heartbeat_manager_from_parrot_autonomous(self):
        """HeartbeatManager is importable from parrot.autonomous."""
        from parrot.autonomous import HeartbeatManager as HM  # noqa: PLC0415
        assert HM is not None

    def test_import_heartbeat_config_from_parrot_autonomous(self):
        """HeartbeatConfig is importable from parrot.autonomous."""
        from parrot.autonomous import HeartbeatConfig as HC  # noqa: PLC0415
        assert HC is not None

    def test_import_heartbeat_state_from_parrot_autonomous(self):
        """HeartbeatState is importable from parrot.autonomous."""
        from parrot.autonomous import HeartbeatState as HS  # noqa: PLC0415
        assert HS is not None

    def test_import_heartbeat_strategy_from_parrot_autonomous(self):
        """HeartbeatStrategy is importable from parrot.autonomous."""
        from parrot.autonomous import HeartbeatStrategy as HStr  # noqa: PLC0415
        assert HStr is not None

    def test_import_default_heartbeat_strategy_from_parrot_autonomous(self):
        """DefaultHeartbeatStrategy is importable from parrot.autonomous."""
        from parrot.autonomous import DefaultHeartbeatStrategy as DHS  # noqa: PLC0415
        assert DHS is not None

    def test_existing_exports_still_work(self):
        """Existing autonomous exports are not broken by heartbeat additions."""
        from parrot.autonomous import (  # noqa: PLC0415
            AutonomousOrchestrator,
            ExecutionTarget,
            ExecutionRequest,
            ExecutionResult,
        )
        assert AutonomousOrchestrator is not None
        assert ExecutionTarget is not None
        assert ExecutionRequest is not None
        assert ExecutionResult is not None
