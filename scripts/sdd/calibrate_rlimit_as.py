#!/usr/bin/env python
"""Empirical calibration of ``WorkerConfig.rlimit_as_bytes`` (FEAT-380 TASK-1946)
and ``memory_soft/hard_limit_bytes`` (FEAT-521 TASK-2783).

Spawns REAL REPL workers — the exact deployed code path (spawn + preexec
rlimits, `parrot.tools.repl_worker.handle.WorkerHandle`) — and measures each
workload's peak *virtual* memory (`VmPeak`) alongside peak *resident* memory
(`VmRSS` — the metric FEAT-521's `memory_soft/hard_limit_bytes` actually
guards, via `psutil`'s `memory_info().rss` inside `ProcessObserver`) and
`VmHWM` (the kernel's own "high water mark" resident-memory record, a
useful independent cross-check on the sampled `VmRSS` peak). All three are
read from `/proc/<worker-pid>/status`, polled from THIS host process, never
from inside the sandboxed worker, while running under a generous ceiling so
the workload isn't clipped mid-measurement.

Linux/POSIX only (`/proc/<pid>/status` + `resource.setrlimit`), matching the
feature's own POSIX-only rlimit enforcement (spec AC16 — Windows has no
rlimits at all).

Workloads (spec §3 Module 8):
    - bootstrap: pandas/numpy/matplotlib/seaborn import cost only.
    - load_<N>mb: an in-memory DataFrame sized to ~N MB.
    - merge_groupby: a multi-key merge + groupby().agg() over two loaded frames.
    - plot: a seaborn/matplotlib plot saved via save_current_plot().

Note on workload realism: the spec calls for "CSV/parquet load", but
`pd.read_csv`/`pd.read_parquet` are on the sandbox's categorical data-IO
denylist (`python_sanitizer.py` `_PANDAS_IO_NAMES`) — deliberately
unmodified here (out of this task's scope). Workloads instead construct an
in-memory DataFrame of the target size directly (seeded `numpy` random
generation, already-preloaded `pd`/`np`) — the dominant peak-memory driver
either way is holding the *materialized* DataFrame, which this reproduces
faithfully; only the transient CSV-parsing staging-buffer overhead is not
exercised. See the evidence file for the full write-up.

Usage:
    python scripts/sdd/calibrate_rlimit_as.py [--sizes 100,500] [--limit-gib 8]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

_SRC = Path(__file__).resolve().parents[2] / "packages" / "ai-parrot" / "src"
sys.path.insert(0, str(_SRC))

from parrot.tools.repl_worker.handle import WorkerHandle  # noqa: E402
from parrot.tools.repl_worker.protocol import WorkerConfig  # noqa: E402

if sys.platform != "linux":
    raise SystemExit("calibrate_rlimit_as.py is Linux-only (reads /proc/<pid>/status)")


#: /proc/<pid>/status fields tracked as running peaks across the workload's
#: whole lifetime (spec Q1: RSS is the metric `memory_soft/hard_limit_bytes`
#: actually enforces; VmPeak/VmHWM stay for the RLIMIT_AS calibration this
#: script already did, and as an independent cross-check on the RSS peak).
_TRACKED_FIELDS = ("VmPeak", "VmHWM", "VmRSS")


@dataclass
class Measurement:
    workload: str
    vm_peak_kb: int
    vm_hwm_kb: int
    vm_rss_peak_kb: int
    survived: bool
    detail: str = ""

    @property
    def vm_peak_mb(self) -> float:
        return self.vm_peak_kb / 1024

    @property
    def vm_hwm_mb(self) -> float:
        return self.vm_hwm_kb / 1024

    @property
    def vm_rss_peak_mb(self) -> float:
        return self.vm_rss_peak_kb / 1024


def _read_proc_status(pid: int) -> dict[str, int]:
    """Read VmPeak/VmHWM/VmRSS (KiB) for `pid` from /proc — host-side, unsandboxed."""
    out: dict[str, int] = {}
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                for key in _TRACKED_FIELDS:
                    if line.startswith(f"{key}:"):
                        out[key] = int(line.split()[1])
    except FileNotFoundError:
        pass
    return out


async def _run_with_peak_tracking(handle: WorkerHandle, code: Optional[str], poll_interval: float = 0.05):
    """Run `code` in the worker (or just wait if `code` is None, for the
    bootstrap-only workload) while polling its VmPeak/VmHWM/VmRSS from the host.
    """
    pid = handle._proc.pid
    peaks = {key: 0 for key in _TRACKED_FIELDS}
    stop = asyncio.Event()

    async def poll() -> None:
        while not stop.is_set():
            for key, value in _read_proc_status(pid).items():
                peaks[key] = max(peaks[key], value)
            await asyncio.sleep(poll_interval)

    poll_task = asyncio.create_task(poll())
    try:
        result = await handle.execute(code) if code else await handle.ping()
    finally:
        # One last sample after the workload returns, before stopping.
        for key, value in _read_proc_status(pid).items():
            peaks[key] = max(peaks[key], value)
        stop.set()
        await poll_task
    return result, peaks


def _size_to_shape(target_mb: int, n_cols: int = 8) -> tuple[int, int]:
    """Row/col shape of a float64 DataFrame whose payload is ~target_mb MB."""
    total_cells = (target_mb * 1024 * 1024) // 8
    rows = max(1, total_cells // n_cols)
    return rows, n_cols


async def _spawn(config: WorkerConfig, output_dir: str) -> WorkerHandle:
    handle = WorkerHandle(config, output_dir=output_dir)
    await handle.start()
    return handle


async def calibrate(sizes_mb: list[int], limit_gib: float, output_dir: str) -> list[Measurement]:
    config = WorkerConfig(
        rlimit_as_bytes=int(limit_gib * 1024**3),
        deadline_ms=120_000,
        max_workers=2,
        idle_ttl_seconds=30,
        prewarm_pool_size=0,
    )
    measurements: list[Measurement] = []

    # 1. bootstrap only
    handle = await _spawn(config, output_dir)
    try:
        _, peaks = await _run_with_peak_tracking(handle, None)
        measurements.append(
            Measurement(
                "bootstrap",
                peaks["VmPeak"],
                peaks["VmHWM"],
                peaks["VmRSS"],
                True,
                "pandas/numpy/matplotlib/seaborn import",
            )
        )

        # 2. load_<N>mb for each requested size (same worker, cumulative state
        #    like a real session — subsequent workloads build on prior ones).
        # `key` cardinality is sized to the LARGEST requested workload so the
        # merge step below stays a realistic ~1-to-few join, not a low-
        # cardinality many-to-many cross-product blowup (e.g. `% 1000` on
        # multi-million-row frames multiplies out to tens of billions of
        # merged rows — an artifact of the test data, not a real workload).
        key_space = max(_size_to_shape(size_mb)[0] for size_mb in sizes_mb) or 1
        loaded_names = []
        for size_mb in sizes_mb:
            rows, cols = _size_to_shape(size_mb)
            var = f"df_{size_mb}mb"
            code = (
                f"{var} = pd.DataFrame(np.random.default_rng(42).random(({rows}, {cols})))\n"
                f"{var}['key'] = np.arange({rows}) % {key_space}\n"
                f"{var}['cat'] = (np.arange({rows}) % 5).astype(str)\n"
                f"result = {var}.shape"
            )
            output, peaks = await _run_with_peak_tracking(handle, code)
            survived = isinstance(output, str)
            measurements.append(
                Measurement(
                    f"load_{size_mb}mb",
                    peaks["VmPeak"],
                    peaks["VmHWM"],
                    peaks["VmRSS"],
                    survived,
                    f"shape=({rows},{cols}) + key/cat cols" if survived else str(output),
                )
            )
            if survived:
                loaded_names.append(var)

        # 3. merge + groupby.agg over the loaded frames (needs >= 2)
        if len(loaded_names) >= 2:
            a, b = loaded_names[0], loaded_names[1]
            code = (
                f"merged = {a}.merge({b}, on='key', suffixes=('_a', '_b'))\n"
                "result = merged.groupby('cat_a').agg({'0_a': 'sum'})"
            )
            output, peaks = await _run_with_peak_tracking(handle, code)
            survived = isinstance(output, str)
            measurements.append(
                Measurement(
                    "merge_groupby",
                    peaks["VmPeak"],
                    peaks["VmHWM"],
                    peaks["VmRSS"],
                    survived,
                    f"{a} x {b}" if survived else str(output),
                )
            )

        # 4. plot
        first = loaded_names[0] if loaded_names else None
        if first:
            code = f"plt.plot({first}.iloc[:2000, 0])\nresult = save_current_plot()"
            output, peaks = await _run_with_peak_tracking(handle, code)
            survived = isinstance(output, str)
            measurements.append(Measurement("plot", peaks["VmPeak"], peaks["VmHWM"], peaks["VmRSS"], survived))
    finally:
        await handle.kill()

    return measurements


def _print_table(measurements: list[Measurement]) -> None:
    print(
        f"{'workload':<16} {'VmPeak (MB)':>12} {'VmHWM (MB)':>12} {'VmRSS peak (MB)':>16} " f"{'survived':>9}  detail"
    )
    for m in measurements:
        print(
            f"{m.workload:<16} {m.vm_peak_mb:>12.1f} {m.vm_hwm_mb:>12.1f} {m.vm_rss_peak_mb:>16.1f} "
            f"{str(m.survived):>9}  {m.detail}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="100,500", help="Comma-separated target DataFrame sizes in MB")
    parser.add_argument("--limit-gib", type=float, default=8.0, help="Ceiling RLIMIT_AS (GiB) used while measuring")
    parser.add_argument("--output-json", default=None, help="Optional path to dump raw measurements as JSON")
    args = parser.parse_args()

    sizes_mb = [int(s) for s in args.sizes.split(",")]

    import os
    import tempfile

    with tempfile.TemporaryDirectory(prefix="rlimit-calibration-") as tmp:
        # `AbstractTool.__init__`'s output_dir guard requires `output_dir`
        # to fall under `STATIC_DIR`/`OUTPUT_DIR` (parrot.conf). The WORKER
        # subprocess re-imports `parrot.conf` fresh and inherits this
        # process' environment (`subprocess.Popen` default), so setting the
        # env var here — before any worker is spawned — is what lets the
        # freshly-created temp dir pass the guard inside the child.
        os.environ["STATIC_DIR"] = tmp
        measurements = asyncio.run(calibrate(sizes_mb, args.limit_gib, tmp))

    _print_table(measurements)

    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps(
                {
                    "python_version": platform.python_version(),
                    "platform": platform.platform(),
                    "measurements": [asdict(m) for m in measurements],
                },
                indent=2,
            )
        )
        print(f"\nWrote raw measurements to {args.output_json}")


if __name__ == "__main__":
    main()
