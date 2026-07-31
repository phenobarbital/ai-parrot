"""Unit tests for DreamScheduler (TASK-1987)."""
from datetime import UTC, datetime, timedelta

import pytest
from parrot.memory.dream import DreamConfig, DreamScheduler, DreamState, save_state
from parrot.memory.episodic.models import MemoryNamespace


class StubRunner:
    """Fake DreamCycleRunner: counts calls, returns a success report."""

    def __init__(self, agent_id: str = "a1"):
        self._namespace = MemoryNamespace(agent_id=agent_id)
        self.cycles_run = 0

    async def run_cycle(self, state: DreamState):
        from parrot.memory.dream import DreamCycleReport

        self.cycles_run += 1
        now = datetime.now(UTC)
        return DreamCycleReport(started_at=now, finished_at=now, aborted=False)


class AbortingRunner:
    """Fake DreamCycleRunner that always reports an aborted cycle."""

    def __init__(self, agent_id: str = "a1"):
        self._namespace = MemoryNamespace(agent_id=agent_id)
        self.cycles_run = 0

    async def run_cycle(self, state: DreamState):
        from parrot.memory.dream import DreamCycleReport

        self.cycles_run += 1
        now = datetime.now(UTC)
        return DreamCycleReport(
            started_at=now, finished_at=now, aborted=True, abort_reason="store down"
        )


@pytest.fixture
def stub_runner() -> StubRunner:
    return StubRunner()


@pytest.fixture
def aborting_runner() -> AbortingRunner:
    return AbortingRunner()


@pytest.fixture
def no_jitter_config() -> DreamConfig:
    return DreamConfig(startup_jitter_seconds=0)


class TestSchedulerStart:
    async def test_catchup_on_overdue_next_due(self, tmp_path, stub_runner, no_jitter_config):
        state_path = tmp_path / "dream_state.json"
        state = DreamState(
            agent_id="a1", next_due=datetime.now(UTC) - timedelta(hours=1)
        )
        save_state(state, state_path)

        sched = DreamScheduler(
            stub_runner, state_path, interval_hours=24, config=no_jitter_config
        )
        await sched.start()
        assert stub_runner.cycles_run == 1
        await sched.stop()

    async def test_first_run_schedules_only(self, tmp_path, stub_runner, no_jitter_config):
        state_path = tmp_path / "dream_state.json"
        sched = DreamScheduler(
            stub_runner, state_path, interval_hours=24, config=no_jitter_config
        )
        await sched.start()
        assert stub_runner.cycles_run == 0
        assert sched._state.next_due is not None
        assert sched._state.next_due > datetime.now(UTC)
        await sched.stop()

    async def test_stale_lock_ignored(self, tmp_path, stub_runner, no_jitter_config):
        state_path = tmp_path / "dream_state.json"
        state = DreamState(
            agent_id="a1",
            running=True,
            running_since=datetime.now(UTC) - timedelta(hours=100),
            next_due=datetime.now(UTC) - timedelta(hours=1),
        )
        save_state(state, state_path)

        sched = DreamScheduler(
            stub_runner, state_path, interval_hours=24, config=no_jitter_config
        )
        await sched.start()
        # Stale lock was ignored, so the overdue catch-up still ran.
        assert stub_runner.cycles_run == 1
        await sched.stop()

    async def test_fresh_lock_prevents_second_loop(self, tmp_path, stub_runner, no_jitter_config):
        state_path = tmp_path / "dream_state.json"
        state = DreamState(
            agent_id="a1",
            running=True,
            running_since=datetime.now(UTC) - timedelta(minutes=1),
            next_due=datetime.now(UTC) - timedelta(hours=1),
        )
        save_state(state, state_path)

        sched = DreamScheduler(
            stub_runner, state_path, interval_hours=24, config=no_jitter_config
        )
        await sched.start()
        assert stub_runner.cycles_run == 0
        assert sched._task is None


class TestRunNow:
    async def test_explicit_trigger(self, tmp_path, stub_runner, no_jitter_config):
        state_path = tmp_path / "dream_state.json"
        sched = DreamScheduler(
            stub_runner, state_path, interval_hours=24, config=no_jitter_config
        )
        report = await sched.run_now()
        assert stub_runner.cycles_run == 1
        assert report.aborted is False
        assert sched._state.next_due is not None

    async def test_lock_prevents_concurrent(self, tmp_path, stub_runner, no_jitter_config):
        state_path = tmp_path / "dream_state.json"
        state = DreamState(
            agent_id="a1",
            running=True,
            running_since=datetime.now(UTC) - timedelta(minutes=1),
        )
        save_state(state, state_path)

        sched = DreamScheduler(
            stub_runner, state_path, interval_hours=24, config=no_jitter_config
        )
        report = await sched.run_now()
        assert stub_runner.cycles_run == 0
        assert report.aborted is True


class TestBackoff:
    async def test_aborted_cycle_backs_off(self, tmp_path, aborting_runner, no_jitter_config):
        state_path = tmp_path / "dream_state.json"
        config = DreamConfig(startup_jitter_seconds=0, failure_backoff_divisor=4)
        sched = DreamScheduler(
            aborting_runner, state_path, interval_hours=24, config=config
        )
        before = datetime.now(UTC)
        report = await sched.run_now()

        assert report.aborted is True
        expected = before + timedelta(hours=24 / 4)
        assert abs((sched._state.next_due - expected).total_seconds()) < 5


class TestStop:
    async def test_stop_persists_state_and_clears_lock(self, tmp_path, stub_runner, no_jitter_config):
        state_path = tmp_path / "dream_state.json"
        sched = DreamScheduler(
            stub_runner, state_path, interval_hours=24, config=no_jitter_config
        )
        await sched.start()
        await sched.stop()

        assert sched._task is None
        from parrot.memory.dream import load_state

        reloaded = load_state(state_path, agent_id="a1")
        assert reloaded.running is False
        assert reloaded.running_since is None
