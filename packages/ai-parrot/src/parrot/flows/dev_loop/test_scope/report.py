"""Structured pytest result recording for the SDD cycle (FEAT-695).

Stdlib-only, like the rest of the kernel. Records are temporary artifacts under
``report_root()``; they are never written into a worktree or committed.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .datatypes import PytestInvocation

try:  # POSIX only
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

REPORT_ROOT_ENV = "SDD_TEST_REPORT_DIR"
RERUN_TASK_THRESHOLD = 10
RERUN_RECORD = "_rerun"
STATUSES = ("ok", "failed", "timed_out", "no_junit", "report_parse_error", "selection_error")


@dataclass(frozen=True)
class SuiteResult:
    """Outcome recorded for one pytest invocation."""

    suite: str
    tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_s: float
    exit_code: int
    argv: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class TaskTestRecord:
    """All latest suite outcomes recorded for one task execution history."""

    feature_id: str
    task_id: str
    head_sha: str
    base_ref: str
    tier: str
    source: str
    recorded_at: str
    attempts: int
    suites: tuple[SuiteResult, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)


def report_root() -> Path:
    """Return the configured report root or the sandbox-shared default root."""
    override = os.environ.get(REPORT_ROOT_ENV)
    if override:
        return Path(override)
    return Path("/tmp") / f"claude-{os.getuid()}" / "sdd-tests"


def junit_path_for(feature_id: str, task_id: str, suite: str, ordinal: int) -> Path:
    """Return a unique junit path for an invocation and ensure its directory exists."""
    junit_dir = report_root() / feature_id / "junit"
    junit_dir.mkdir(parents=True, exist_ok=True)
    return junit_dir / f"{task_id}--{suite}--{ordinal}.xml"


def with_junit(invocation: PytestInvocation, junit_path: Path) -> tuple[str, ...]:
    """Return a new invocation argv augmented with its isolated junit path."""
    return (*invocation.argv, f"--junitxml={junit_path}")


def _empty_result(
    suite: str, argv: tuple[str, ...], exit_code: int, duration_s: float, status: str
) -> SuiteResult:
    """Build a zero-count result for a missing or unparsable junit report."""
    return SuiteResult(suite, 0, 0, 0, 0, 0, duration_s, exit_code, argv, status)


def parse_junit(
    junit_path: Path,
    *,
    suite: str,
    argv: tuple[str, ...],
    exit_code: int,
    duration_s: float,
    timed_out: bool = False,
) -> SuiteResult:
    """Parse junit counters without allowing absent or invalid reports to raise."""
    if not junit_path.exists():
        return _empty_result(suite, argv, exit_code, duration_s, "timed_out" if timed_out else "no_junit")

    try:
        root = ET.parse(junit_path).getroot()
        counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        for node in root.iter("testsuite"):
            for name in counts:
                counts[name] += int(node.attrib.get(name, "0"))
    except (ET.ParseError, OSError, ValueError):
        return _empty_result(suite, argv, exit_code, duration_s, "timed_out" if timed_out else "report_parse_error")

    failed = counts["failures"]
    errors = counts["errors"]
    skipped = counts["skipped"]
    tests = counts["tests"]
    passed = max(0, tests - failed - errors - skipped)
    status = "timed_out" if timed_out else "failed" if exit_code != 0 or failed or errors else "ok"
    return SuiteResult(suite, tests, passed, failed, errors, skipped, duration_s, exit_code, argv, status)


def _record_from_payload(payload: dict[str, object]) -> TaskTestRecord:
    """Deserialize a report JSON payload into immutable public data classes."""
    suites = tuple(
        SuiteResult(
            suite=item["suite"],
            tests=item["tests"],
            passed=item["passed"],
            failed=item["failed"],
            errors=item["errors"],
            skipped=item["skipped"],
            duration_s=item["duration_s"],
            exit_code=item["exit_code"],
            argv=tuple(item["argv"]),
            status=item["status"],
        )
        for item in payload["suites"]
    )
    return TaskTestRecord(
        feature_id=payload["feature_id"],
        task_id=payload["task_id"],
        head_sha=payload["head_sha"],
        base_ref=payload["base_ref"],
        tier=payload["tier"],
        source=payload["source"],
        recorded_at=payload["recorded_at"],
        attempts=payload["attempts"],
        suites=suites,
        notes=tuple(payload.get("notes", ())),
    )


def _write_record(path: Path, record: TaskTestRecord) -> None:
    """Atomically publish a record by replacing it with a same-directory temp file."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(asdict(record), stream, sort_keys=True)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def append_suite(
    feature_id: str,
    task_id: str,
    result: SuiteResult,
    *,
    head_sha: str,
    base_ref: str,
    tier: str,
    source: str,
    note: str | None = None,
) -> Path | None:
    """Merge one suite into a task record, returning ``None`` for I/O failures."""
    path = report_root() / feature_id / f"{task_id}.json"
    lock_path = path.with_suffix(".json.lock")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                old = _record_from_payload(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None
                suites = {item.suite: item for item in old.suites} if old else {}
                suites[result.suite] = result
                notes = (*old.notes, note) if old and note else (note,) if note else old.notes if old else ()
                record = TaskTestRecord(
                    feature_id=feature_id,
                    task_id=task_id,
                    head_sha=head_sha,
                    base_ref=base_ref,
                    tier=tier,
                    source=source,
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                    attempts=(old.attempts if old else 0) + 1,
                    suites=tuple(suites[name] for name in sorted(suites)),
                    notes=notes,
                )
                _write_record(path, record)
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Unable to record pytest result for %s: %s", task_id, exc)
        return None
    return path


def load_records(feature_id: str) -> tuple[dict[str, TaskTestRecord], list[str]]:
    """Load valid feature records and notes for corrupt records that were skipped."""
    directory = report_root() / feature_id
    records: dict[str, TaskTestRecord] = {}
    notes: list[str] = []
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError as exc:
        logger.warning("Unable to load pytest reports for %s: %s", feature_id, exc)
        return records, notes
    for path in paths:
        try:
            record = _record_from_payload(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logger.warning("Skipping corrupt pytest report %s: %s", path, exc)
            notes.append(f"skipped corrupt report: {path.name}")
            continue
        records[record.task_id] = record
    return records, notes


def should_rerun(task_count: int) -> bool:
    """Return whether the deterministic closeout rule permits a re-run."""
    return task_count <= RERUN_TASK_THRESHOLD


def _aggregate(records: dict[str, TaskTestRecord]) -> dict[str, list[float]]:
    """Aggregate count and duration fields by suite name."""
    totals: dict[str, list[float]] = {}
    for record in records.values():
        for result in record.suites:
            values = totals.setdefault(result.suite, [0, 0, 0, 0, 0, 0.0])
            values[0] += result.tests
            values[1] += result.passed
            values[2] += result.failed
            values[3] += result.skipped
            values[4] += result.errors
            values[5] += result.duration_s
    return totals


def _rerun_value(rerun: TaskTestRecord | None, suite: str) -> str:
    """Render the final-head count cell for one suite."""
    if rerun is None:
        return "—"
    result = next((item for item in rerun.suites if item.suite == suite), None)
    if result is None:
        return "—"
    marker = " ❌" if result.failed or result.errors else ""
    return f"{result.passed}/{result.tests}{marker}"


def render_markdown(
    records: dict[str, TaskTestRecord],
    task_ids: list[str],
    *,
    final_head: str,
    rerun: TaskTestRecord | None,
    rerun_skip_reason: str | None,
) -> str:
    """Render a deterministic Tests section including aggregate and per-task evidence."""
    totals = _aggregate(records)
    has_rerun = rerun is not None
    header = "| Suite | Tests | Passed | Failed | Skipped | Errors | Duration"
    separator = "| --- | ---: | ---: | ---: | ---: | ---: | ---:"
    if has_rerun:
        header += " | Final HEAD re-run"
        separator += " | ---"
    rows = ["## Tests", "", header + " |", separator + " |"]
    grand_total = [0, 0, 0, 0, 0, 0.0]
    rerun_suites = {result.suite: result for result in rerun.suites} if rerun else {}
    for suite in sorted(set(totals) | set(rerun_suites)):
        values = totals.get(suite, [0, 0, 0, 0, 0, 0.0])
        for index, value in enumerate(values):
            grand_total[index] += value
        label = f"{suite}{' ❌' if values[2] or values[4] else ''}"
        row = (
            f"| {label} | {int(values[0])} | {int(values[1])} | {int(values[2])} | "
            f"{int(values[3])} | {int(values[4])} | {values[5]:.2f}s"
        )
        if has_rerun:
            row += f" | {_rerun_value(rerun, suite)}"
        rows.append(row + " |")
    total_label = "Total (per-task invocation totals)"
    row = (
        f"| {total_label}{' ❌' if grand_total[2] or grand_total[4] else ''} | {int(grand_total[0])} | "
        f"{int(grand_total[1])} | {int(grand_total[2])} | {int(grand_total[3])} | {int(grand_total[4])} | "
        f"{grand_total[5]:.2f}s"
    )
    if has_rerun:
        rerun_tests = sum(result.tests for result in rerun.suites)
        rerun_passed = sum(result.passed for result in rerun.suites)
        rerun_failed = sum(result.failed for result in rerun.suites)
        rerun_errors = sum(result.errors for result in rerun.suites)
        marker = " ❌" if rerun_failed or rerun_errors else ""
        row += f" | {rerun_passed}/{rerun_tests}{marker}"
    rows.append(row + " |")
    if rerun_skip_reason:
        rows.extend(["", f"re-run skipped ({rerun_skip_reason})"])
    rows.extend(["", "<details>", "<summary>Per-task test results</summary>", ""])
    for task_id in task_ids:
        record = records.get(task_id)
        if record is None:
            rows.append(f"- {task_id}: no data")
        else:
            state = " (stale)" if record.head_sha != final_head else ""
            rows.append(f"- {task_id}{state}: {len(record.suites)} suite(s), {record.attempts} attempt(s)")
    rows.extend(["", "</details>", ""])
    return "\n".join(rows)
