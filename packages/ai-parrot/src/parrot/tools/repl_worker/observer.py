"""Host-side process observer for REPL workers (FEAT-521 Module 2).

``ProcessObserver`` is the continuous, cheap observation primitive the rest
of FEAT-521 builds on: one instance per live :class:`~parrot.tools.
repl_worker.handle.WorkerHandle`, sampling its child process (CPU time,
RSS, status, thread count, and on Linux the kernel wait channel) on a fixed
interval from spawn until kill, and turning that sample stream into a
first-class busy/hung verdict (spec G1/G2) plus soft/hard RSS guardrails
(spec G4).

Observation is strictly host-side: this module never reads or writes the
control pipe (spec Non-Goals — no heartbeat frames), so no protocol
reordering is possible. A :class:`ProcessObserver` never raises out of
:meth:`ProcessObserver.run` — a dead or inaccessible process, or an
unsupported (non-POSIX) host, degrades the verdict to ``"unavailable"``
instead of propagating an exception (spec G1).

The ``/proc``-parsing helpers in this module are also used by
:func:`parrot.tools.repl_worker.handle.probe_process_state`, which now
delegates to them and keeps its own signature/return-value contract as a
thin compatibility wrapper (spec §3 Module 2).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Awaitable, Callable, Optional

import psutil

from .protocol import MemoryVerdict, ProcessSample, Verdict, WorkerConfig

logger = logging.getLogger(__name__)

#: CPU-seconds delta below which a window is treated as "flat" (psutil's
#: cpu_times() resolution is clock-tick granularity, typically 10ms).
_CPU_FLAT_EPSILON_S = 1e-3

#: Re-arm threshold for the soft-limit hysteresis (spec §2: "cleared when
#: RSS drops below 90% of the soft limit").
_SOFT_LIMIT_REARM_RATIO = 0.9

#: Minimum ring size regardless of poll/stall-window ratio, so a very short
#: stall_window_ms still keeps a little history for cpu_progress().
_RING_MIN_LEN = 64
#: How many stall windows' worth of samples the ring keeps.
_RING_WINDOW_MULTIPLIER = 3


# ---------------------------------------------------------------------------
# /proc parsing helpers (Linux-only; reused by both ProcessObserver sampling
# and handle.probe_process_state()'s compatibility wrapper).
# ---------------------------------------------------------------------------


def read_proc_status(pid: int) -> dict[str, str]:
    """Parse ``/proc/<pid>/status`` into a ``{field: value}`` mapping.

    Args:
        pid: The process to inspect.

    Returns:
        A mapping of status field names (e.g. ``"State"``, ``"Threads"``,
        ``"VmPeak"``) to their raw string values.

    Raises:
        OSError: the status file could not be read (process gone, not
            Linux, permission denied, ...).
    """
    text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8", errors="replace")
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = " ".join(value.split())
    return fields


def read_proc_wchan(pid: int) -> str:
    """Read ``/proc/<pid>/wchan`` (Linux only).

    Args:
        pid: The process to inspect.

    Returns:
        The kernel wait channel name, ``"0"`` when the process is not
        blocked on one, or ``""`` when unavailable (non-Linux host or a
        read failure).
    """
    if sys.platform != "linux":
        return ""
    try:
        return Path(f"/proc/{pid}/wchan").read_text(encoding="utf-8", errors="replace").strip() or "0"
    except OSError:
        return ""


def read_proc_cpu_seconds(pid: int) -> float:
    """Read cumulative user+system CPU seconds from ``/proc/<pid>/stat``.

    Args:
        pid: The process to inspect.

    Returns:
        User + system CPU time, in seconds.

    Raises:
        OSError: the stat file could not be read.
        ValueError: the stat file's contents could not be parsed as
            integers.
        IndexError: the stat file did not contain the expected fields.
    """
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    after_comm = stat.rsplit(")", 1)[1].split()
    ticks = os.sysconf("SC_CLK_TCK") or 100
    return (int(after_comm[11]) + int(after_comm[12])) / ticks


class ProcessObserver:
    """Continuously samples one worker process and derives a busy/hung verdict.

    Owned by a single :class:`~parrot.tools.repl_worker.handle.WorkerHandle`,
    started as a background task alongside its stdio drain task and torn
    down with it. See spec §2 "Architectural Design" for the full verdict
    table and the soft/hard RSS guardrail semantics.

    Attributes:
        pid: The observed process id.

    Note:
        The ``"booting"`` verdict (spec: "no ``ReadyResponse`` yet") is
        derived from whether :meth:`mark_busy`/:meth:`mark_idle` has ever
        been called rather than from a dedicated readiness signal — this
        class has no visibility into the control-protocol handshake by
        design (observation is host-side only). The owning
        ``WorkerHandle`` is expected to call :meth:`mark_idle` once after
        its readiness future resolves, which is also the natural idle
        starting state for a freshly-booted worker.
    """

    def __init__(
        self,
        pid: int,
        config: WorkerConfig,
        *,
        on_hard_breach: Callable[[MemoryVerdict], Awaitable[None]],
    ) -> None:
        """Initialize the observer.

        Args:
            pid: The worker process id to sample.
            config: The owning worker's :class:`WorkerConfig` (poll cadence,
                stall window, and RSS thresholds are read from here).
            on_hard_breach: Awaited exactly once, with the measured
                :class:`MemoryVerdict`, the first time a sample crosses
                ``config.memory_hard_limit_bytes``. After it is awaited,
                :meth:`run` returns.
        """
        self.pid = pid
        self._config = config
        self._on_hard_breach = on_hard_breach

        ring_len = max(
            _RING_MIN_LEN,
            _RING_WINDOW_MULTIPLIER * max(1, config.stall_window_ms // max(1, config.observer_poll_ms)),
        )
        self._ring: "deque[ProcessSample]" = deque(maxlen=ring_len)

        self._in_flight = False
        self._activated = False
        self._unavailable = False
        self._busy_since: Optional[float] = None

        self._soft_pressure_active = False
        self._memory_pressure_state: Optional[tuple[int, int]] = None
        self._hard_breach_fired = False
        self._memory_verdict: Optional[MemoryVerdict] = None

    async def run(self) -> None:
        """Sample the process on ``observer_poll_ms`` until it dies or is unusable.

        Never raises: a non-POSIX host, a `psutil` failure resolving the
        process, or `psutil.NoSuchProcess`/`AccessDenied` mid-loop all end
        the loop (setting the verdict to ``"unavailable"`` where
        appropriate) instead of propagating. Returns immediately after the
        one-shot hard-breach callback has been awaited (spec: "loop
        stops").
        """
        if os.name != "posix":
            self._unavailable = True
            return

        try:
            proc = psutil.Process(self.pid)
        except psutil.Error:
            self._unavailable = True
            return

        poll_s = max(self._config.observer_poll_ms, 1) / 1000.0
        wchan_supported = sys.platform == "linux"

        while True:
            try:
                sample = self._take_sample(proc, wchan_supported)
            except psutil.NoSuchProcess:
                return
            except psutil.AccessDenied:
                self._unavailable = True
                return
            except Exception:  # noqa: BLE001 - defensive, spec: "never raises"
                logger.debug("ProcessObserver(pid=%s): sampling error", self.pid, exc_info=True)
                await asyncio.sleep(poll_s)
                continue

            self._ring.append(sample)
            self._update_memory_pressure(sample.rss)

            if self._check_hard_breach(sample.rss):
                try:
                    await self._on_hard_breach(self._memory_verdict)
                except Exception:  # noqa: BLE001 - defensive, spec: "never raises"
                    logger.exception("ProcessObserver(pid=%s): on_hard_breach callback raised", self.pid)
                return

            await asyncio.sleep(poll_s)

    def _take_sample(self, proc: psutil.Process, wchan_supported: bool) -> ProcessSample:
        """Read one :class:`ProcessSample` from ``proc``.

        Args:
            proc: The live `psutil.Process` handle for :attr:`pid`.
            wchan_supported: Whether to also read ``/proc/<pid>/wchan``.

        Returns:
            The sampled vitals.

        Raises:
            psutil.NoSuchProcess: the process has already exited.
            psutil.AccessDenied: the host cannot read this process' stats.
        """
        cpu_times = proc.cpu_times()
        rss = proc.memory_info().rss
        state = proc.status()
        threads = proc.num_threads()
        wchan = read_proc_wchan(self.pid) if wchan_supported else ""
        return ProcessSample(
            t=time.monotonic(),
            cpu_s=cpu_times.user + cpu_times.system,
            rss=rss,
            state=state,
            wchan=wchan,
            threads=threads,
        )

    def mark_busy(self) -> None:
        """Record that a request round-trip started (called around ``_roundtrip()``)."""
        if not self._in_flight:
            self._busy_since = time.monotonic()
        self._in_flight = True
        self._activated = True

    def mark_idle(self) -> None:
        """Record that the in-flight request round-trip finished (or none is pending)."""
        self._in_flight = False
        self._busy_since = None
        self._activated = True

    def verdict(self) -> Verdict:
        """Derive the current busy/hung verdict from the sample ring.

        Returns:
            One of ``"booting"``, ``"settled"``, ``"computing"``,
            ``"stalled"``, or ``"unavailable"`` (see spec §2 table).
        """
        if self._unavailable:
            return "unavailable"
        if not self._activated or not self._ring:
            return "booting"
        if not self._in_flight:
            return "settled"

        window_s = self._config.stall_window_ms / 1000.0
        progress = self.cpu_progress(window_s)
        if progress > _CPU_FLAT_EPSILON_S:
            return "computing"
        # CPU is flat over the trailing window; only call it "stalled" once
        # the CURRENT busy period itself has lasted at least stall_window_ms
        # — otherwise a request that just started, sampled against a ring
        # still full of older (possibly also-flat) idle history, would be
        # misclassified as stalled immediately.
        if self._busy_since is not None and (time.monotonic() - self._busy_since) >= window_s:
            return "stalled"
        return "computing"

    def last(self) -> Optional[ProcessSample]:
        """The most recent sample, or ``None`` if none has been taken yet."""
        return self._ring[-1] if self._ring else None

    def cpu_progress(self, window_s: float) -> float:
        """CPU seconds advanced over the trailing ``window_s`` window.

        Args:
            window_s: Length of the trailing window, in seconds.

        Returns:
            ``last.cpu_s - baseline.cpu_s`` where ``baseline`` is the
            oldest sample within the window (or the oldest sample in the
            ring, if the ring doesn't span the full window yet). ``0.0``
            when fewer than two samples are available.
        """
        if len(self._ring) < 2:
            return 0.0
        last = self._ring[-1]
        threshold = last.t - window_s
        baseline = self._ring[0]
        for sample in self._ring:
            if sample.t >= threshold:
                baseline = sample
                break
        return max(0.0, last.cpu_s - baseline.cpu_s)

    @property
    def memory_pressure(self) -> Optional[tuple[int, int]]:
        """``(rss, soft_limit)`` while over `memory_soft_limit_bytes`, else `None`."""
        return self._memory_pressure_state

    @property
    def memory_verdict(self) -> Optional[MemoryVerdict]:
        """The recorded hard-breach verdict, or `None` if none has occurred."""
        return self._memory_verdict

    def _update_memory_pressure(self, rss: int) -> None:
        """Update soft-limit pressure state with 90% re-arm hysteresis."""
        soft_limit = self._config.memory_soft_limit_bytes
        if soft_limit <= 0:
            return
        if rss >= soft_limit:
            if not self._soft_pressure_active:
                logger.warning(
                    "ProcessObserver(pid=%s): RSS %d exceeds memory_soft_limit_bytes=%d",
                    self.pid,
                    rss,
                    soft_limit,
                )
            self._soft_pressure_active = True
            self._memory_pressure_state = (rss, soft_limit)
        elif self._soft_pressure_active and rss < soft_limit * _SOFT_LIMIT_REARM_RATIO:
            self._soft_pressure_active = False
            self._memory_pressure_state = None

    def _check_hard_breach(self, rss: int) -> bool:
        """Record a hard-limit breach at most once.

        Args:
            rss: The just-sampled RSS, in bytes.

        Returns:
            ``True`` the first (and only) time ``rss`` crosses
            `memory_hard_limit_bytes`.
        """
        hard_limit = self._config.memory_hard_limit_bytes
        if hard_limit <= 0 or self._hard_breach_fired or rss < hard_limit:
            return False
        self._hard_breach_fired = True
        self._memory_verdict = MemoryVerdict(rss=rss, limit=hard_limit)
        return True

    def describe(self) -> str:
        """One-line description of the current verdict and last sample.

        Used to enrich every timeout/bootstrap/namespace-loss error message
        (spec G2/G3 "no blank errors").

        Returns:
            E.g. ``"verdict=stalled cpu=58.10s rss=1996488704 state=S
            wchan=pipe_read threads=4"``, or ``"verdict=booting (no samples
            yet)"`` before the first sample.
        """
        verdict = self.verdict()
        sample = self.last()
        if sample is None:
            return f"verdict={verdict} (no samples yet)"
        return (
            f"verdict={verdict} cpu={sample.cpu_s:.2f}s rss={sample.rss} "
            f"state={sample.state} wchan={sample.wchan or '-'} threads={sample.threads}"
        )
