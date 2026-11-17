"""Unit tests for the G1 harness (FEAT-824 TASK-5248). No server, no SDK."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2] / "scripts" / "spikes" / "surrealdb_g1" / "harness.py"


def _load():
    spec = importlib.util.spec_from_file_location("g1_harness", HARNESS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verdict_requires_all_blocking() -> None:
    """NO-GO when one blocking check fails; informational failures do not block."""
    module = _load()
    CheckResult = module.CheckResult

    # All blocking checks pass
    results = [
        CheckResult(check_id="G1-01", title="Check 1", blocking=True, status="pass", evidence="OK"),
        CheckResult(check_id="G1-02", title="Check 2", blocking=True, status="pass", evidence="OK"),
        CheckResult(check_id="G1-06", title="Check 6", blocking=False, status="fail", evidence="OK"),
    ]
    assert module.verdict(results) == "GO"

    # One blocking check fails
    results = [
        CheckResult(check_id="G1-01", title="Check 1", blocking=True, status="pass", evidence="OK"),
        CheckResult(check_id="G1-02", title="Check 2", blocking=True, status="fail", evidence="OK"),
    ]
    assert module.verdict(results) == "NO-GO"

    # Empty list
    assert module.verdict([]) == "NO-GO"


def test_report_lists_every_check() -> None:
    """Report has one row per check, the pinned versions and the verdict."""
    module = _load()
    CheckResult = module.CheckResult
    SpikeContext = module.SpikeContext

    ctx = SpikeContext(
        url="http://localhost:8000",
        username="root",
        password="root",
        server_image="surrealdb/surrealdb@sha256:abc123",
        sdk_version="2.0.0",
    )
    results = [
        CheckResult(
            check_id="G1-01",
            title="Check 1",
            blocking=True,
            status="pass",
            evidence="OK",
            measurements={"latency": 0.1},
        ),
        CheckResult(
            check_id="G1-02",
            title="Check 2",
            blocking=True,
            status="fail",
            evidence="Failed",
        ),
    ]
    report = module.render_report(ctx, results)
    assert "surrealdb/surrealdb@sha256:abc123" in report
    assert "2.0.0" in report
    assert "| G1-01 | Check 1 | Yes | pass |  | OK |" in report
    assert "| G1-02 | Check 2 | Yes | fail |  | Failed |" in report
    assert "**Verdict: NO-GO**" in report


def test_run_records_crashing_check_as_fail() -> None:
    """A check that raises becomes status 'fail' and the run continues."""
    module = _load()
    CheckResult = module.CheckResult
    SpikeContext = module.SpikeContext

    async def crashing_check(ctx: SpikeContext) -> CheckResult:
        raise ValueError("Crash")

    async def passing_check(ctx: SpikeContext) -> CheckResult:
        return CheckResult(
            check_id="G1-01",
            title="Passing Check",
            blocking=True,
            status="pass",
            evidence="OK",
        )

    ctx = SpikeContext(
        url="http://localhost:8000",
        username="root",
        password="root",
        server_image="surrealdb/surrealdb@sha256:abc123",
        sdk_version="2.0.0",
    )
    results = asyncio.run(module.run(ctx, [crashing_check, passing_check]))
    assert len(results) == 2
    assert results[0].status == "fail"
    assert "ValueError: Crash" in results[0].evidence
    assert results[1].status == "pass"
