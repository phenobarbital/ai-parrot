"""FEAT-902 benchmark schema, isolation and evidence contracts."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

BENCHMARK_REPORT_SCHEMA = 1


def _load_driver() -> Any:
    """Load the adjacent driver explicitly; do not assume a benchmarks package."""
    path = Path(__file__).parent / "benchmarks" / "sqlite_ledger_hardening.py"
    specification = importlib.util.spec_from_file_location("sqlite_ledger_hardening", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def _revision() -> str:
    """Return the current checkout revision for worker isolation checks."""
    root = Path(__file__).parents[5]
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _config(driver: Any, tmp_path: Path, **changes: Any) -> Any:
    """Create a tiny valid cell rooted at this checkout."""
    values = {
        "arm": "candidate",
        "revision": _revision(),
        "source_root": Path(__file__).parents[5],
        "processes": 1,
        "workload": "idle-ledger",
        "lifecycle": "resident",
        "trials": 1,
        "warmup": 0,
        "operations": 2,
        "seed": 902,
        "output_dir": tmp_path / "output",
        "run_timeout_s": 60,
    }
    values.update(changes)
    return driver.BenchmarkConfig(**values)


def test_benchmark_config_and_report_schema(tmp_path: Path) -> None:
    """Invalid inputs, incomplete cells and missing outcome fields are rejected."""
    driver = _load_driver()
    with pytest.raises(Exception):
        _config(driver, tmp_path, processes=2)
    with pytest.raises(Exception):
        _config(driver, tmp_path, output_dir=Path(__file__).parents[5] / ".parrot" / "ledger")
    with pytest.raises(Exception):
        driver.OperationSample(
            worker_id=0,
            sequence=0,
            operation="ledger.get",
            duration_ms=1.0,
            success=True,
        )

    config = _config(driver, tmp_path)
    with pytest.raises(Exception):
        driver.BenchmarkReport(
            schema_version=BENCHMARK_REPORT_SCHEMA,
            config=config,
            environment={},
            trials=[],
            invariants={},
            complete=True,
        )
    incomplete = driver.BenchmarkReport(
        schema_version=BENCHMARK_REPORT_SCHEMA,
        config=config,
        environment={},
        trials=[],
        invariants={"all_trials_complete": False},
        complete=False,
    )
    serialized = json.loads(incomplete.model_dump_json())
    assert serialized["schema_version"] == BENCHMARK_REPORT_SCHEMA
    assert serialized["complete"] is False


def test_worker_rejects_wrong_source_revision(tmp_path: Path) -> None:
    """The imported checkout must match the requested arm revision."""
    driver = _load_driver()
    wrong_revision = "0" * 40
    config = _config(driver, tmp_path, revision=wrong_revision)
    with pytest.raises(driver.SourceIsolationError):
        driver.run_benchmark(config)
    assert not list((tmp_path / "output").glob("trial-*/*/*.db"))


@pytest.mark.parametrize(
    ("workload", "lifecycle"),
    [
        ("idle-ledger", "resident"),
        ("idle-ledger", "ephemeral"),
        ("mixed-ledger", "resident"),
        ("mixed-ledger", "ephemeral"),
        ("claim-race", "resident"),
        ("claim-race", "ephemeral"),
        ("wiki", "resident"),
        ("wiki", "ephemeral"),
    ],
)
def test_smoke_workloads_and_counts(tmp_path: Path, workload: str, lifecycle: str) -> None:
    """Small cells cover all workloads/lifecycles without running the full matrix."""
    driver = _load_driver()
    config = _config(
        driver,
        tmp_path,
        workload=workload,
        lifecycle=lifecycle,
        output_dir=tmp_path / f"{workload}-{lifecycle}",
    )
    report = driver.run_benchmark(config)
    assert report.complete
    assert report.schema_version == BENCHMARK_REPORT_SCHEMA
    assert report.environment["fixture_scale"] == 4
    assert report.environment["connection_lifecycle"] == "connection-per-operation"
    trial = report.trials[0]
    assert len(trial.samples) == config.operations
    assert trial.counts.connection_opens > 0
    assert trial.counts.successful_operations + trial.counts.unsuccessful_operations == config.operations
    # The imported checkout includes the TASK-5716 timing hooks, so observed phases are
    # reported as measured samples; a phase that was not emitted stays None (unavailable),
    # never a numeric zero. Baseline sources without hooks keep reporting None.
    connection_open = trial.phase_timings_ms["connection_open"]
    assert connection_open, "candidate source must report connection_open timings"
    assert all(isinstance(value, (int, float)) and value >= 0 for value in connection_open)
    assert all(value is None or value for value in trial.phase_timings_ms.values())
    assert all(trial.invariants.values())
    assert trial.wal_after_bytes.keys() == {"ledger", "wiki"}


def test_minimal_spawned_claim_race(tmp_path: Path) -> None:
    """A fresh issue has exactly one successful owner across four spawned workers."""
    driver = _load_driver()
    config = _config(
        driver,
        tmp_path,
        processes=4,
        workload="claim-race",
        lifecycle="resident",
        operations=1,
        output_dir=tmp_path / "claim-race",
    )
    report = driver.run_benchmark(config)
    trial = report.trials[0]
    claims = [sample for sample in trial.samples if sample.operation == "ledger.claim"]
    assert len(claims) == 4
    assert sum(sample.success for sample in claims) == 1
    assert trial.invariants["claim_owner_unique"]


# Later measurement task appends test_committed_measurement_evidence here.
# Preserve the unique benchmark report schema attachment anchor.
