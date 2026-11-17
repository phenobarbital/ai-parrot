"""FEAT-902 benchmark schema, isolation and evidence contracts."""

from __future__ import annotations

import hashlib
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


# --- FEAT-902 committed measurement evidence ---------------------------------

EVIDENCE_ROOT = Path(__file__).resolve().parents[5] / "sdd" / "state" / "FEAT-902" / "benchmarks"
BASELINE_REVISION = "e5f3f7534876f9b4f56ad1cedc7b4e56176ee568"
MATRIX_PROCESSES = [1, 4, 8]
MATRIX_LIFECYCLES = ["resident", "ephemeral"]
MATRIX_WORKLOADS = ["idle-ledger", "mixed-ledger", "claim-race", "wiki"]
MATRIX_ARMS = ["baseline", "candidate"]
EVIDENCE_TRIALS = 3


def _load_manifest() -> dict[str, Any]:
    """Load the committed FEAT-902 measurement manifest."""
    return json.loads((EVIDENCE_ROOT / "manifest.json").read_text(encoding="utf-8"))


def test_committed_measurement_evidence() -> None:
    """Committed FEAT-902 evidence covers the complete approved matrix."""
    manifest = _load_manifest()
    assert manifest["schema_version"] == 1
    assert manifest["feature_id"] == "FEAT-902"
    assert manifest["baseline_revision"] == BASELINE_REVISION
    candidate = manifest["candidate_revision"]
    assert isinstance(candidate, str) and len(candidate) == 40
    matrix = manifest["matrix"]
    assert matrix["processes"] == MATRIX_PROCESSES
    assert matrix["lifecycles"] == MATRIX_LIFECYCLES
    assert matrix["workloads"] == MATRIX_WORKLOADS
    assert matrix["arms"] == MATRIX_ARMS
    cells = manifest["cells"]
    expected = {
        (arm, procs, lifecycle, workload)
        for arm in MATRIX_ARMS
        for procs in MATRIX_PROCESSES
        for lifecycle in MATRIX_LIFECYCLES
        for workload in MATRIX_WORKLOADS
    }
    observed = {(c["arm"], c["processes"], c["lifecycle"], c["workload"]) for c in cells}
    assert observed == expected
    assert len(cells) == len(expected) == 48
    for cell in cells:
        assert cell["exit_code"] == 0
        assert cell["complete"] is True
        assert all(cell["invariants"].values())
        assert cell["settings"] == {"trials": 3, "warmup": 100, "operations": 1000, "seed": 902}
        assert len(cell["trials"]) == EVIDENCE_TRIALS
        for trial in cell["trials"]:
            assert trial["complete"] is True
            assert all(trial["invariants"].values())
            assert trial["errors"] == 0
            assert trial["busy_outcomes"] == 0
    assert {c["revision"] for c in cells if c["arm"] == "candidate"} == {candidate}
    assert {c["revision"] for c in cells if c["arm"] == "baseline"} == {BASELINE_REVISION}


def test_committed_raw_file_hashes() -> None:
    """Raw files listed in the manifest match their hashes when present locally."""
    manifest = _load_manifest()
    repo_root = EVIDENCE_ROOT.parents[3]
    artifacts_present = (repo_root / "artifacts" / "logs" / "FEAT-902" / "sqlite-hardening").is_dir()
    for entry in manifest["raw_files"]:
        path = repo_root / entry["path"]
        if not path.is_file():
            # Fresh checkouts lack gitignored artifacts; the committed hashes stand in for them.
            assert not artifacts_present, f"raw file missing during execution: {entry['path']}"
            continue
        assert path.stat().st_size == entry["size_bytes"], entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], entry["path"]


def test_measurement_report_is_filled_and_defers_reuse() -> None:
    """Report and follow-up contain measured content and the recorded defer disposition."""
    report = (EVIDENCE_ROOT / "report.md").read_text(encoding="utf-8")
    followup = (EVIDENCE_ROOT / "persistent-connections-followup.md").read_text(encoding="utf-8")
    assert "FILL IN" not in report
    assert "FILL IN" not in followup
    assert "## Matrix and results" in report
    assert "## Correctness and failures" in report
    assert "## Disposition\n**Defer.**" in followup


@pytest.mark.xfail(
    strict=True,
    reason="DEBUG-off overhead pass not run: the driver always captures DEBUG and has no switch to disable it",
)
def test_debug_off_overhead_pass_recorded() -> None:
    """The DEBUG-off overhead pass required by the spec is recorded as complete."""
    manifest = _load_manifest()
    assert manifest["missing"] == []
    assert manifest["complete"] is True
