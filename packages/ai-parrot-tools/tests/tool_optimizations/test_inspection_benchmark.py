"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers.

Measures the concurrency ``InspectionRunner`` (TASK-3556) actually delivers
with a controlled, synthetic per-item delay standing in for I/O — never real
disk timing, which would make the ratio a hardware-dependent flake. The
point is to demonstrate genuine overlap under the four-slot admission limit,
not to claim a specific wall-clock speedup on real files.
"""

import asyncio
import json
import time
from pathlib import Path

import pytest

import parrot_tools.tool_optimizations.inspection as inspection_module
from parrot_tools.tool_optimizations.reader import BoundedSourceToolkit

#: tool_optimizations -> tests -> ai-parrot-tools -> packages -> repo root
ARTIFACT_LOGS = Path(__file__).resolve().parents[4] / "artifacts" / "logs"

#: Controlled per-item I/O delay; large enough that scheduling jitter cannot
#: erase the parallel/serial gap, small enough the whole suite stays fast.
_ITEM_DELAY_SECONDS = 0.1
_ITEM_COUNT = 8
_REPETITIONS = 3
_MAX_RATIO = 0.65


async def _run_batch(toolkit: BoundedSourceToolkit, concurrency: int, delay_seconds: float):
    """Run one 8-item batch with a controlled per-item delay, off real disk I/O.

    Args:
        toolkit: A fresh toolkit instance, so its admission semaphore starts clean.
        concurrency: The batch's own concurrency ceiling.
        delay_seconds: The synthetic per-item delay standing in for I/O.

    Returns:
        A ``(result, wall_ms, peak_active)`` tuple, timed with a monotonic clock.
    """
    original_do_read = inspection_module.InspectionRunner._do_read
    active = {"value": 0}
    peak = {"value": 0}
    lock = asyncio.Lock()

    async def _delayed_do_read(self, request, started):
        async with lock:
            active["value"] += 1
            peak["value"] = max(peak["value"], active["value"])
        try:
            if delay_seconds:
                await asyncio.sleep(delay_seconds)
            return await original_do_read(self, request, started)
        finally:
            async with lock:
                active["value"] -= 1

    requests = [{"id": f"item-{i}", "kind": "read", "path": f"f{i}.py"} for i in range(_ITEM_COUNT)]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(inspection_module.InspectionRunner, "_do_read", _delayed_do_read)
        wall_start = time.perf_counter()
        result = await toolkit.source_inspect_batch(requests, concurrency=concurrency)
        wall_ms = (time.perf_counter() - wall_start) * 1000
    return result, wall_ms, peak["value"]


def _record_evidence(payload: dict) -> None:
    """Persist the runner and measured results under artifacts/logs.

    Written unconditionally (before the threshold assertion), so a failure
    still leaves durable evidence of what was actually measured.
    """
    ARTIFACT_LOGS.mkdir(parents=True, exist_ok=True)
    target = ARTIFACT_LOGS / "TASK-3557-inspection-benchmark.json"
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_four_slots_overlap_equivalent_operations(git_repo: Path) -> None:
    """Eight controlled 100ms I/O operations have p50 parallel/serial ratio at most 0.65."""
    for i in range(_ITEM_COUNT):
        (git_repo / f"f{i}.py").write_text(f"line{i}\n")

    # Warmup: exercise the whole path once (imports, event loop, semaphores)
    # without the synthetic delay, so first-call overhead never pollutes the
    # timed repetitions below.
    asyncio.run(_run_batch(BoundedSourceToolkit(repo_root=git_repo), concurrency=4, delay_seconds=0.0))

    ratios: list[float] = []
    evidence: list[dict] = []
    for rep in range(_REPETITIONS):
        parallel_result, parallel_ms, parallel_peak = asyncio.run(
            _run_batch(BoundedSourceToolkit(repo_root=git_repo), concurrency=4, delay_seconds=_ITEM_DELAY_SECONDS)
        )
        serial_result, serial_ms, serial_peak = asyncio.run(
            _run_batch(BoundedSourceToolkit(repo_root=git_repo), concurrency=1, delay_seconds=_ITEM_DELAY_SECONDS)
        )

        assert parallel_result.status == "ok"
        assert serial_result.status == "ok"
        # The admission limit is a hard ceiling (never more than 4 active),
        # and this controlled batch must actually exercise real overlap
        # (never just 1, which would prove nothing about concurrency).
        assert 2 <= parallel_peak <= 4, f"rep {rep}: expected overlap within the 4-slot cap, saw {parallel_peak}"
        assert serial_peak == 1, f"rep {rep}: serial run must never overlap, saw {serial_peak}"

        # Same operations, same output regardless of concurrency.
        parallel_data = {item["id"]: item["data"] for item in parallel_result.data["items"]}
        serial_data = {item["id"]: item["data"] for item in serial_result.data["items"]}
        assert parallel_data == serial_data

        # sum_item_ms accounts for every (overlapped) item individually and
        # must never be conflated with the batch's own wall-clock elapsed_ms.
        assert parallel_result.data["sum_item_ms"] > parallel_result.data["elapsed_ms"]

        ratio = parallel_ms / serial_ms
        ratios.append(ratio)
        evidence.append(
            {
                "rep": rep,
                "parallel_wall_ms": parallel_ms,
                "serial_wall_ms": serial_ms,
                "ratio": ratio,
                "parallel_peak_active": parallel_peak,
                "parallel_sum_item_ms": parallel_result.data["sum_item_ms"],
                "parallel_elapsed_ms": parallel_result.data["elapsed_ms"],
            }
        )

    ratios.sort()
    p50_ratio = ratios[len(ratios) // 2]
    _record_evidence(
        {
            "runner": "InspectionRunner",
            "item_count": _ITEM_COUNT,
            "item_delay_seconds": _ITEM_DELAY_SECONDS,
            "repetitions": _REPETITIONS,
            "ratios": ratios,
            "p50_ratio": p50_ratio,
            "max_ratio_allowed": _MAX_RATIO,
            "runs": evidence,
            "note": (
                "synthetic per-item delay stands in for I/O; no 4x-on-real-disk "
                "speedup is claimed, only demonstrated overlap under the 4-slot cap"
            ),
        }
    )
    assert p50_ratio <= _MAX_RATIO, f"p50 parallel/serial ratio {p50_ratio} exceeds {_MAX_RATIO}; ratios={ratios}"
