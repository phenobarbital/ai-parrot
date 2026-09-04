"""Unit tests for `ProcessObserver` sampling, verdict derivation, and RSS
guardrails (FEAT-521 Module 2, TASK-2780).

These tests never spawn a real REPL worker: verdict-transition tests inject
synthetic `ProcessSample`s directly into the observer's ring (deterministic,
no sleeps), and the sampling-loop tests (`run()`, `NoSuchProcess`/
`AccessDenied`/non-POSIX degradation, soft hysteresis, hard-breach callback)
monkeypatch `psutil.Process` with a small scripted fake so `run()` itself is
exercised end to end without touching a real process.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from types import SimpleNamespace

import psutil
import pytest

from parrot.tools.repl_worker import observer as observer_module
from parrot.tools.repl_worker.observer import ProcessObserver
from parrot.tools.repl_worker.protocol import ProcessSample, WorkerConfig

# pytest-asyncio runs in "auto" mode for this package (pyproject.toml) — no
# explicit `@pytest.mark.asyncio` needed on `async def test_*` functions.


@pytest.fixture
def tight_config():
    """Spec §4 Test Data — a small, fast-cycling config for deterministic tests."""
    return WorkerConfig(
        deadline_ms=1_000,
        interrupt_grace_ms=500,
        observer_poll_ms=100,
        stall_window_ms=500,
        memory_soft_limit_bytes=0,
        memory_hard_limit_bytes=0,
    )


async def _noop_hard_breach(_verdict) -> None:
    """Default no-op `on_hard_breach` callback for observers under test."""


def _make_observer(config: WorkerConfig | None = None, *, on_hard_breach=None) -> ProcessObserver:
    return ProcessObserver(
        pid=1,
        config=config or WorkerConfig(),
        on_hard_breach=on_hard_breach or _noop_hard_breach,
    )


def _sample(
    t: float, cpu_s: float, *, rss: int = 100_000_000, state: str = "running", wchan: str = "", threads: int = 4
) -> ProcessSample:
    return ProcessSample(t=t, cpu_s=cpu_s, rss=rss, state=state, wchan=wchan, threads=threads)


class _ScriptedProcess:
    """`psutil.Process`-shaped fake that replays a fixed sequence of samples.

    `cpu_times()` is always the FIRST of the four calls `ProcessObserver.
    _take_sample()` makes per sample, so it advances the internal cursor;
    the other three read the same (already-advanced) entry.
    """

    def __init__(self, samples: list[tuple[float, int, str, int]]) -> None:
        self._samples = samples
        self._i = -1

    @property
    def index(self) -> int:
        return self._i

    def cpu_times(self):
        if self._i < len(self._samples) - 1:
            self._i += 1
        cpu_s = self._samples[self._i][0]
        return SimpleNamespace(user=cpu_s, system=0.0)

    def memory_info(self):
        return SimpleNamespace(rss=self._samples[self._i][1])

    def status(self):
        return self._samples[self._i][2]

    def num_threads(self):
        return self._samples[self._i][3]


class _RaisingProcess:
    """`psutil.Process`-shaped fake whose sample methods always raise."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def cpu_times(self):
        raise self._exc

    def memory_info(self):
        raise self._exc

    def status(self):
        raise self._exc

    def num_threads(self):
        raise self._exc


# ---------------------------------------------------------------------------
# Verdict derivation (synthetic ring injection — deterministic, no sleeps)
# ---------------------------------------------------------------------------


class TestVerdictDerivation:
    def test_booting_before_any_activation(self):
        """spec: 'booting' = no ReadyResponse yet (observer never activated)."""
        obs = _make_observer()
        assert obs.verdict() == "booting"

    def test_booting_persists_even_with_samples_before_activation(self):
        obs = _make_observer()
        obs._ring.append(_sample(t=0.0, cpu_s=1.0))
        assert obs.verdict() == "booting"

    def test_settled_when_idle_and_cpu_flat(self):
        obs = _make_observer()
        obs.mark_idle()
        obs._ring.append(_sample(t=0.0, cpu_s=1.0))
        obs._ring.append(_sample(t=0.5, cpu_s=1.0))
        assert obs.verdict() == "settled"

    def test_computing_when_busy_and_cpu_rising(self):
        obs = _make_observer()
        obs.mark_busy()
        obs._ring.append(_sample(t=0.0, cpu_s=1.0))
        obs._ring.append(_sample(t=0.1, cpu_s=1.2))
        assert obs.verdict() == "computing"

    def test_computing_when_busy_but_window_not_yet_elapsed(self):
        """Flat CPU while busy, but the busy period hasn't lasted stall_window_ms yet."""
        config = WorkerConfig(stall_window_ms=500)
        obs = _make_observer(config)
        obs.mark_busy()
        obs._busy_since = time.monotonic()  # just started
        obs._ring.append(_sample(t=0.0, cpu_s=2.0))
        obs._ring.append(_sample(t=0.1, cpu_s=2.0))
        assert obs.verdict() == "computing"

    def test_stalled_after_sustained_flat_window(self):
        """spec: busy + flat CPU for >= stall_window_ms -> stalled."""
        config = WorkerConfig(stall_window_ms=500)
        obs = _make_observer(config)
        obs.mark_busy()
        obs._busy_since = time.monotonic() - 1.0  # busy for 1s (real) > 0.5s window
        obs._ring.append(_sample(t=0.0, cpu_s=2.0))
        obs._ring.append(_sample(t=0.6, cpu_s=2.0))
        assert obs.verdict() == "stalled"

    def test_cpu_tick_resets_stalled_to_computing(self):
        """spec test_verdict_stalled_after_window: 'CPU tick resets it'."""
        config = WorkerConfig(stall_window_ms=500)
        obs = _make_observer(config)
        obs.mark_busy()
        obs._busy_since = time.monotonic() - 1.0
        # Both samples must fall within the trailing `stall_window_ms`
        # window (last.t - window_s <= sample.t) for the tick to register
        # as progress rather than being excluded as "outside the window".
        obs._ring.append(_sample(t=0.0, cpu_s=2.0))
        obs._ring.append(_sample(t=0.1, cpu_s=2.5))  # ticked within the window
        assert obs.verdict() == "computing"

    def test_unavailable_when_flagged(self):
        obs = _make_observer()
        obs._unavailable = True
        assert obs.verdict() == "unavailable"

    def test_unavailable_takes_priority_over_samples(self):
        obs = _make_observer()
        obs.mark_busy()
        obs._ring.append(_sample(t=0.0, cpu_s=1.0))
        obs._unavailable = True
        assert obs.verdict() == "unavailable"


class TestCpuProgress:
    def test_zero_with_fewer_than_two_samples(self):
        obs = _make_observer()
        assert obs.cpu_progress(window_s=1.0) == 0.0
        obs._ring.append(_sample(t=0.0, cpu_s=1.0))
        assert obs.cpu_progress(window_s=1.0) == 0.0

    def test_progress_over_window_uses_earliest_in_window_sample(self):
        obs = _make_observer()
        obs._ring.append(_sample(t=0.0, cpu_s=1.0))
        obs._ring.append(_sample(t=1.0, cpu_s=1.0))
        obs._ring.append(_sample(t=2.0, cpu_s=3.0))
        # threshold = 2.0 - 1.5 = 0.5 -> baseline is the t=1.0 sample
        assert obs.cpu_progress(window_s=1.5) == pytest.approx(2.0)

    def test_progress_zero_when_window_shorter_than_sample_interval(self):
        obs = _make_observer()
        obs._ring.append(_sample(t=0.0, cpu_s=1.0))
        obs._ring.append(_sample(t=1.0, cpu_s=1.0))
        obs._ring.append(_sample(t=2.0, cpu_s=3.0))
        # threshold = 2.0 - 0.5 = 1.5 -> only the last sample itself qualifies
        assert obs.cpu_progress(window_s=0.5) == pytest.approx(0.0)


class TestLastAndDescribe:
    def test_last_is_none_before_any_sample(self):
        obs = _make_observer()
        assert obs.last() is None

    def test_last_returns_most_recent_sample(self):
        obs = _make_observer()
        obs._ring.append(_sample(t=0.0, cpu_s=1.0))
        obs._ring.append(_sample(t=1.0, cpu_s=2.0))
        assert obs.last().cpu_s == 2.0

    def test_describe_without_a_sample(self):
        obs = _make_observer()
        desc = obs.describe()
        assert "verdict=booting" in desc
        assert "no samples yet" in desc

    def test_describe_with_a_sample(self):
        obs = _make_observer()
        obs.mark_idle()
        obs._ring.append(_sample(t=0.0, cpu_s=3.5, rss=123, state="sleeping", wchan="pipe_read", threads=7))
        desc = obs.describe()
        assert "verdict=settled" in desc
        assert "cpu=3.50s" in desc
        assert "rss=123" in desc
        assert "state=sleeping" in desc
        assert "wchan=pipe_read" in desc
        assert "threads=7" in desc


class TestMarkBusyIdle:
    def test_mark_busy_then_idle_clears_in_flight(self):
        obs = _make_observer()
        obs.mark_busy()
        assert obs._in_flight is True
        obs.mark_idle()
        assert obs._in_flight is False

    def test_mark_busy_sets_busy_since_only_on_transition(self):
        obs = _make_observer()
        obs.mark_busy()
        first = obs._busy_since
        assert first is not None
        obs.mark_busy()  # already busy — must not reset the clock
        assert obs._busy_since == first

    def test_mark_idle_clears_busy_since(self):
        obs = _make_observer()
        obs.mark_busy()
        obs.mark_idle()
        assert obs._busy_since is None


# ---------------------------------------------------------------------------
# Soft/hard RSS guardrails (synthetic state — deterministic, no sleeps)
# ---------------------------------------------------------------------------


class TestMemoryPressure:
    def test_no_pressure_when_soft_limit_disabled(self):
        obs = _make_observer(WorkerConfig(memory_soft_limit_bytes=0))
        obs._update_memory_pressure(10_000_000_000)
        assert obs.memory_pressure is None

    def test_pressure_recorded_at_or_above_soft_limit(self):
        obs = _make_observer(WorkerConfig(memory_soft_limit_bytes=1000, memory_hard_limit_bytes=0))
        obs._update_memory_pressure(1000)
        assert obs.memory_pressure == (1000, 1000)

    def test_pressure_holds_in_the_90_to_100_percent_band(self):
        obs = _make_observer(WorkerConfig(memory_soft_limit_bytes=1000, memory_hard_limit_bytes=0))
        obs._update_memory_pressure(1000)
        obs._update_memory_pressure(950)  # still >= 900 (90%) -> stays active
        assert obs.memory_pressure == (1000, 1000)

    def test_pressure_clears_below_90_percent_rearm_threshold(self):
        obs = _make_observer(WorkerConfig(memory_soft_limit_bytes=1000, memory_hard_limit_bytes=0))
        obs._update_memory_pressure(1000)
        obs._update_memory_pressure(899)  # < 900 -> re-arms
        assert obs.memory_pressure is None

    def test_hard_breach_recorded_exactly_once(self):
        obs = _make_observer(WorkerConfig(memory_soft_limit_bytes=0, memory_hard_limit_bytes=2000))
        assert obs._check_hard_breach(2000) is True
        assert obs.memory_verdict.rss == 2000
        assert obs.memory_verdict.limit == 2000
        # a second, even larger breach must not re-fire
        assert obs._check_hard_breach(5000) is False
        assert obs.memory_verdict.rss == 2000  # unchanged

    def test_hard_breach_disabled_when_limit_is_zero(self):
        obs = _make_observer(WorkerConfig(memory_soft_limit_bytes=0, memory_hard_limit_bytes=0))
        assert obs._check_hard_breach(10_000_000_000) is False
        assert obs.memory_verdict is None


# ---------------------------------------------------------------------------
# The sampling loop itself (`run()`, monkeypatched `psutil.Process`)
# ---------------------------------------------------------------------------


class TestRunNeverRaises:
    async def test_ends_quietly_on_no_such_process(self, monkeypatch, tight_config):
        monkeypatch.setattr(observer_module.psutil, "Process", lambda pid: _RaisingProcess(psutil.NoSuchProcess(pid)))
        obs = _make_observer(tight_config)
        await obs.run()  # must return, never raise
        assert obs.verdict() == "booting"  # never sampled, never flagged unavailable

    async def test_marks_unavailable_on_access_denied(self, monkeypatch, tight_config):
        monkeypatch.setattr(observer_module.psutil, "Process", lambda pid: _RaisingProcess(psutil.AccessDenied(pid)))
        obs = _make_observer(tight_config)
        await obs.run()
        assert obs.verdict() == "unavailable"

    async def test_marks_unavailable_when_process_resolution_fails(self, monkeypatch, tight_config):
        def _raise(pid):
            raise psutil.NoSuchProcess(pid)

        monkeypatch.setattr(observer_module.psutil, "Process", _raise)
        obs = _make_observer(tight_config)
        await obs.run()
        assert obs.verdict() == "unavailable"

    async def test_marks_unavailable_on_non_posix_host(self, monkeypatch, tight_config):
        monkeypatch.setattr(observer_module.os, "name", "nt")
        obs = _make_observer(tight_config)
        await obs.run()
        assert obs.verdict() == "unavailable"

    async def test_unexpected_sampling_error_does_not_escape(self, monkeypatch, tight_config):
        """A non-psutil exception mid-loop is swallowed, not propagated (spec: 'never raises')."""

        class _FlakyProcess(_ScriptedProcess):
            def __init__(self, samples):
                super().__init__(samples)
                self._calls = 0

            def cpu_times(self):
                self._calls += 1
                if self._calls == 1:
                    raise RuntimeError("transient sampling glitch")
                return super().cpu_times()

        proc = _FlakyProcess([(1.0, 100, "running", 4), (1.0, 100, "running", 4)])
        monkeypatch.setattr(observer_module.psutil, "Process", lambda pid: proc)
        obs = _make_observer(tight_config)
        task = asyncio.create_task(obs.run())
        for _ in range(200):
            if obs.last() is not None:
                break
            await asyncio.sleep(0.005)
        assert obs.last() is not None  # recovered after the transient error
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class TestSoftLimitHysteresisViaRun:
    async def test_one_warning_per_episode(self, monkeypatch, caplog):
        soft = 1000
        samples = [
            (1.0, 500, "running", 4),  # below soft
            (1.0, 1000, "running", 4),  # breach #1
            (1.0, 1000, "running", 4),  # still breached, no new warning
            (1.0, 850, "running", 4),  # in the 90-100% hysteresis band
            (1.0, 800, "running", 4),  # < 90% -> re-arms
            (1.0, 1000, "running", 4),  # breach #2
        ]
        proc = _ScriptedProcess(samples)
        monkeypatch.setattr(observer_module.psutil, "Process", lambda pid: proc)
        config = WorkerConfig(observer_poll_ms=5, memory_soft_limit_bytes=soft, memory_hard_limit_bytes=0)
        obs = _make_observer(config)
        with caplog.at_level(logging.WARNING, logger="parrot.tools.repl_worker.observer"):
            task = asyncio.create_task(obs.run())
            for _ in range(500):
                if proc.index >= len(samples) - 1:
                    break
                await asyncio.sleep(0.005)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 2, [r.message for r in warnings]


class TestHardLimitViaRun:
    async def test_callback_invoked_once_with_measured_rss_and_limit(self, monkeypatch):
        samples = [
            (1.0, 100, "running", 4),
            (1.0, 5000, "running", 4),  # crosses the hard limit
        ]
        proc = _ScriptedProcess(samples)
        monkeypatch.setattr(observer_module.psutil, "Process", lambda pid: proc)
        config = WorkerConfig(observer_poll_ms=5, memory_soft_limit_bytes=0, memory_hard_limit_bytes=4000)
        calls = []

        async def on_hard(verdict):
            calls.append(verdict)

        obs = ProcessObserver(pid=1, config=config, on_hard_breach=on_hard)
        await obs.run()  # returns on its own once the callback has been awaited

        assert len(calls) == 1
        assert calls[0].rss == 5000
        assert calls[0].limit == 4000
        assert obs.memory_verdict is calls[0]
