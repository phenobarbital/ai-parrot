"""Unit tests for parrot.bots.flows.core.fsm (TASK-914)."""
import pytest
from statemachine.exceptions import TransitionNotAllowed
from parrot.bots.flows.core.fsm import AgentTaskMachine, TransitionCondition


class TestTransitionCondition:
    def test_all_values(self):
        assert TransitionCondition.ON_SUCCESS == "on_success"
        assert TransitionCondition.ON_ERROR == "on_error"
        assert TransitionCondition.ON_TIMEOUT == "on_timeout"
        assert TransitionCondition.ON_CONDITION == "on_condition"
        assert TransitionCondition.ALWAYS == "always"

    def test_has_five_members(self):
        assert len(TransitionCondition) == 5

    def test_is_str_subclass(self):
        assert isinstance(TransitionCondition.ON_SUCCESS, str)


class TestAgentTaskMachine:
    @pytest.fixture
    def fsm(self):
        return AgentTaskMachine(agent_name="test-agent")

    def test_initial_state_is_idle(self, fsm):
        assert fsm.current_state == fsm.idle

    def test_happy_path(self, fsm):
        fsm.schedule()
        assert fsm.current_state == fsm.ready
        fsm.start()
        assert fsm.current_state == fsm.running
        fsm.succeed()
        assert fsm.current_state == fsm.completed

    def test_retry_path(self, fsm):
        fsm.schedule()
        fsm.start()
        fsm.fail()
        assert fsm.current_state == fsm.failed
        fsm.retry()
        assert fsm.current_state == fsm.ready

    def test_blocked_path(self, fsm):
        fsm.block()
        assert fsm.current_state == fsm.blocked
        fsm.unblock()
        assert fsm.current_state == fsm.ready

    def test_completed_is_final(self, fsm):
        """No transitions allowed from completed state."""
        fsm.schedule()
        fsm.start()
        fsm.succeed()
        with pytest.raises(TransitionNotAllowed):
            fsm.schedule()

    def test_failed_is_not_final(self, fsm):
        """Failed state allows retry transition."""
        fsm.schedule()
        fsm.start()
        fsm.fail()
        fsm.retry()  # should NOT raise
        assert fsm.current_state == fsm.ready

    def test_invalid_idle_to_running(self, fsm):
        with pytest.raises(TransitionNotAllowed):
            fsm.start()

    def test_invalid_idle_to_completed(self, fsm):
        with pytest.raises(TransitionNotAllowed):
            fsm.succeed()

    def test_fail_from_idle(self, fsm):
        """fail transition works from idle state."""
        fsm.fail()
        assert fsm.current_state == fsm.failed

    def test_fail_from_ready(self, fsm):
        """fail transition works from ready state."""
        fsm.schedule()
        fsm.fail()
        assert fsm.current_state == fsm.failed

    def test_block_from_idle(self, fsm):
        """block transition works from idle."""
        fsm.block()
        assert fsm.current_state == fsm.blocked

    def test_block_from_ready(self, fsm):
        """block transition works from ready."""
        fsm.schedule()
        fsm.block()
        assert fsm.current_state == fsm.blocked

    def test_agent_name_stored(self, fsm):
        assert fsm.agent_name == "test-agent"
