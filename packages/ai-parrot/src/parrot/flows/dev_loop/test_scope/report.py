"""Structured pytest result recording for the SDD cycle (FEAT-695).

Stdlib-only, like the rest of the kernel. Records are temporary artifacts under
``report_root()``; they are never written into a worktree or committed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .datatypes import Invocation, RunReport
from .planner import OVERRIDE_MARKER_EXPRESSION

try:  # POSIX only
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

REPORT_ROOT_ENV = "SDD_TEST_REPORT_DIR"
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
    nodes: tuple[tuple[str, str], ...] = ()
    unmapped: int = 0
    baseline: tuple[tuple[str, str], ...] = ()


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
    cached: tuple[str, ...] = field(default_factory=tuple)


def report_root() -> Path:
    """Return the configured report root or the sandbox-shared default root."""
    override = os.environ.get(REPORT_ROOT_ENV)
    if override:
        return Path(override)
    return Path("/tmp") / f"claude-{os.getuid()}" / "sdd-tests"


# Feature/task ids safe as a PATH COMPONENT. Deliberately stricter than the
# sdd_coder task-id gates (`models._TASK_ID_RE` and friends, FEAT-736): their
# key class `[A-Za-z0-9._-]` mirrors `brief_meta._SAFE_REF_RE` and admits `.`,
# which here would make `HOTFIX-a..b-1` a usable path component. The key class
# below excludes `.`, so a dotted brief key falls back to `_invalid` -- safe,
# and no worse than refusing every brief id as this did before. `_safe_id`
# uses `.match()`, so the trailing `$` is what makes this a full match: keep it.
_SAFE_ID_RE = re.compile(
    r"^(?:FEAT-\d+|TASK-\d+|BRIEF-[A-Za-z0-9][A-Za-z0-9_-]*|HOTFIX-[A-Za-z0-9][A-Za-z0-9_-]*-\d+|_rerun)$"
)


def _safe_id(value: str) -> bool:
    """Return True when ``value`` is a feature/task id that is safe to use as a path component."""
    return bool(_SAFE_ID_RE.match(value))


def junit_path_for(feature_id: str, task_id: str, suite: str, ordinal: int) -> Path:
    """Return a fresh junit path for an invocation and ensure its directory exists.

    Any file left at the path by an earlier attempt is removed, so a run killed before pytest writes its XML can
    never be reported with a previous attempt's counts. Unsafe ids are mapped to a neutral directory name.
    """
    feature_dir = feature_id if _safe_id(feature_id) else "_invalid"
    task_part = task_id if _safe_id(task_id) else "_invalid"
    junit_dir = report_root() / feature_dir / "junit"
    junit_dir.mkdir(parents=True, exist_ok=True)
    path = junit_dir / f"{task_part}--{suite}--{ordinal}.xml"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("could not remove stale junit file %s", path)
    return path


def with_report(invocation: Invocation, report_path: Path) -> tuple[str, ...]:
    """Return report arguments for pytest; other runners already carry them."""
    if invocation.runner == "pytest":
        return (*invocation.argv, "-o", "junit_family=xunit1", f"--junitxml={report_path}")
    return tuple(invocation.argv)


def nodeid_from_testcase(file_attr: str | None, classname: str, name: str, *, runner: str = "pytest") -> str | None:
    """Return a canonical pytest node id or ``<file>::<name>`` for another runner."""
    if runner != "pytest":
        return f"{file_attr}::{name}" if file_attr else None
    if not file_attr or not file_attr.endswith(".py"):
        return None

    module_path = file_attr[:-3].replace("/", ".")
    if classname == module_path:
        class_segments: tuple[str, ...] = ()
    elif classname.startswith(f"{module_path}."):
        class_segments = tuple(classname[len(module_path) + 1 :].split("."))
    else:
        return None

    return "::".join((file_attr, *class_segments, name))


def suite_name(invocation: Invocation) -> str:
    """Record key for one invocation: ``<dist>``, ``<dist>[contract]`` or ``<dist>[markers]``."""
    if invocation.runner != "pytest":
        return f"{invocation.runner}:{invocation.distribution}"

    try:
        marker_expression = invocation.argv[invocation.argv.index("-m") + 1]
    except (ValueError, IndexError):
        return invocation.distribution

    if marker_expression == OVERRIDE_MARKER_EXPRESSION:
        return f"{invocation.distribution}[contract]"
    if marker_expression.startswith("(") and marker_expression.endswith(f" and {OVERRIDE_MARKER_EXPRESSION}"):
        return f"{invocation.distribution}[markers]"
    return invocation.distribution


def _empty_result(suite: str, argv: tuple[str, ...], exit_code: int, duration_s: float, status: str) -> SuiteResult:
    """Build a zero-count result for a missing or unparsable junit report."""
    return SuiteResult(suite, 0, 0, 0, 0, 0, duration_s, exit_code, argv, status)


def parse_junit_report(
    junit_path: Path,
    *,
    runner: str,
    suite: str,
    exit_code: int,
    duration_s: float,
    timed_out: bool = False,
) -> RunReport:
    """Parse any junit file into a report while retaining failure text per node."""
    unavailable_status = "timed_out" if timed_out else "no_report"
    if not junit_path.exists():
        return RunReport(runner, suite, 0, 0, 0, 0, 0, duration_s, exit_code, unavailable_status)

    try:
        root = ET.parse(junit_path).getroot()
        counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        for node in root.iter("testsuite"):
            for name in counts:
                counts[name] += int(node.attrib.get(name, "0"))

        nodes: list[tuple[str, str]] = []
        failure_text: dict[str, str] = {}
        unmapped = 0
        for testcase in root.iter("testcase"):
            failure = testcase.find("failure")
            error = testcase.find("error")
            testcase_status = (
                "failed"
                if failure is not None
                else "error" if error is not None else "skipped" if testcase.find("skipped") is not None else "passed"
            )
            nodeid = nodeid_from_testcase(
                testcase.attrib.get("file"),
                testcase.attrib.get("classname", ""),
                testcase.attrib.get("name", ""),
                runner=runner,
            )
            if nodeid is None:
                unmapped += 1
                continue
            nodes.append((nodeid, testcase_status))
            failure_node = failure if failure is not None else error
            if failure_node is not None:
                failure_text[nodeid] = f"{failure_node.attrib.get('message', '')}\n{failure_node.text or ''}"
    except (ET.ParseError, OSError, ValueError):
        return RunReport(runner, suite, 0, 0, 0, 0, 0, duration_s, exit_code, unavailable_status)

    failed = counts["failures"]
    errors = counts["errors"]
    skipped = counts["skipped"]
    tests = counts["tests"]
    passed = max(0, tests - failed - errors - skipped)
    status = "timed_out" if timed_out else "failed" if exit_code != 0 or failed or errors else "ok"
    return RunReport(
        runner=runner,
        suite=suite,
        tests=tests,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        duration_s=duration_s,
        exit_code=exit_code,
        status=status,
        nodes=tuple(sorted(nodes)),
        failure_text=failure_text,
        unmapped=unmapped,
    )


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
    report = parse_junit_report(
        junit_path,
        runner="pytest",
        suite=suite,
        exit_code=exit_code,
        duration_s=duration_s,
        timed_out=timed_out,
    )
    status = report.status
    if status == "no_report":
        status = "report_parse_error" if junit_path.exists() else "no_junit"
    return SuiteResult(
        report.suite,
        report.tests,
        report.passed,
        report.failed,
        report.errors,
        report.skipped,
        report.duration_s,
        report.exit_code,
        argv,
        status,
        nodes=report.nodes,
        unmapped=report.unmapped,
    )


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
            nodes=tuple(tuple(node) for node in item.get("nodes", ())),
            unmapped=item.get("unmapped", 0),
            baseline=tuple(tuple(verdict) for verdict in item.get("baseline", ())),
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
        cached=tuple(payload.get("cached", ())),
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
    if not (_safe_id(feature_id) and _safe_id(task_id)):
        logger.warning("refusing to record test results for unsafe ids %r/%r", feature_id, task_id)
        return None
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
                    cached=old.cached if old else (),
                )
                _write_record(path, record)
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Unable to record pytest result for %s: %s", task_id, exc)
        return None
    return path


def append_cached(
    feature_id: str,
    task_id: str,
    targets: Sequence[str],
    *,
    head_sha: str,
    base_ref: str,
    tier: str,
    source: str,
) -> Path | None:
    """Merge cached target paths into a task record, returning ``None`` for I/O failures."""
    if not (_safe_id(feature_id) and _safe_id(task_id)):
        logger.warning("refusing to record cached targets for unsafe ids %r/%r", feature_id, task_id)
        return None
    path = report_root() / feature_id / f"{task_id}.json"
    lock_path = path.with_suffix(".json.lock")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                old = _record_from_payload(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None
                cached = tuple(sorted(set(old.cached if old else ()) | set(targets)))
                record = TaskTestRecord(
                    feature_id=feature_id,
                    task_id=task_id,
                    head_sha=head_sha,
                    base_ref=base_ref,
                    tier=tier,
                    source=source,
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                    attempts=old.attempts if old else 0,
                    suites=old.suites if old else (),
                    notes=old.notes if old else (),
                    cached=cached,
                )
                _write_record(path, record)
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Unable to record cached targets for %s: %s", task_id, exc)
        return None
    return path


def load_records(feature_id: str) -> tuple[dict[str, TaskTestRecord], list[str]]:
    """Load valid feature records and notes for corrupt records that were skipped."""
    records: dict[str, TaskTestRecord] = {}
    notes: list[str] = []
    if not _safe_id(feature_id):
        return records, [f"unsafe feature id {feature_id!r}: no records loaded"]
    directory = report_root() / feature_id
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
    """FEAT-699: re-run whenever the feature has at least one task."""
    return task_count >= 1


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


def _is_failure(result: SuiteResult) -> bool:
    """Return whether a suite result must be flagged, including zero-count non-ok statuses."""
    return result.status != "ok" or bool(result.failed or result.errors)


def _failed_suites(records: dict[str, TaskTestRecord]) -> set[str]:
    """Suite names with at least one flagged result across all records."""
    return {result.suite for record in records.values() for result in record.suites if _is_failure(result)}


def _rerun_value(rerun: TaskTestRecord | None, suite: str) -> str:
    """Render the final-head count cell for one suite."""
    if rerun is None:
        return "—"
    result = next((item for item in rerun.suites if item.suite == suite), None)
    if result is None:
        return "—"
    marker = " ❌" if _is_failure(result) else ""
    return f"{result.passed}/{result.tests}{marker}"


def _baseline_counts(results: Sequence[SuiteResult]) -> tuple[int | None, int | None, int | None]:
    """Return new-red, baseline-red, and unknown counts for aggregated suite results."""
    if any(_is_failure(result) and not result.baseline for result in results):
        return None, None, None
    counts = {"new_red": 0, "baseline_red": 0, "unknown": 0}
    for result in results:
        for _nodeid, status in result.baseline:
            if status in counts:
                counts[status] += 1
    return counts["new_red"], counts["baseline_red"], counts["unknown"]


def render_markdown(
    records: dict[str, TaskTestRecord],
    task_ids: list[str],
    *,
    final_head: str,
    rerun: TaskTestRecord | None,
    rerun_skip_reason: str | None,
    notes: tuple[str, ...] = (),
) -> str:
    """Render a deterministic Tests section including aggregate and per-task evidence."""
    totals = _aggregate(records)
    failed_suites = _failed_suites(records)
    has_rerun = rerun is not None
    suites: dict[str, list[SuiteResult]] = {}
    for record in records.values():
        for result in record.suites:
            suites.setdefault(result.suite, []).append(result)
    header = "| Suite | Tests | Passed | Failed | Skipped | Errors | New red | Baseline red | Unknown | Duration"
    separator = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---:"
    if has_rerun:
        header += " | Final HEAD re-run (stale)" if rerun.head_sha != final_head else " | Final HEAD re-run"
        separator += " | ---"
    rows = ["## Tests", "", header + " |", separator + " |"]
    grand_total = [0, 0, 0, 0, 0, 0.0]
    baseline_totals = [0, 0, 0]
    unclassified_failures = False
    rerun_suites = {result.suite: result for result in rerun.suites} if rerun else {}
    for suite in sorted(set(totals) | set(rerun_suites)):
        values = totals.get(suite, [0, 0, 0, 0, 0, 0.0])
        for index, value in enumerate(values):
            grand_total[index] += value
        label = f"{suite}{' ❌' if suite in failed_suites else ''}"
        if ":" in suite:
            baseline_cells = ("n/a", "n/a", "n/a")
        else:
            new_red, baseline_red, unknown = _baseline_counts(suites.get(suite, ()))
        if ":" not in suite and new_red is None:
            unclassified_failures = True
            baseline_cells = ("—", "—", "—")
        elif ":" not in suite:
            baseline_totals[0] += new_red
            baseline_totals[1] += baseline_red
            baseline_totals[2] += unknown
            baseline_cells = (str(new_red), str(baseline_red), str(unknown))
        row = (
            f"| {label} | {int(values[0])} | {int(values[1])} | {int(values[2])} | "
            f"{int(values[3])} | {int(values[4])} | {' | '.join(baseline_cells)} | {values[5]:.2f}s"
        )
        if has_rerun:
            row += f" | {_rerun_value(rerun, suite)}"
        rows.append(row + " |")
    total_label = "Total (per-task invocation totals)"
    row = (
        f"| {total_label}{' ❌' if failed_suites else ''} | {int(grand_total[0])} | "
        f"{int(grand_total[1])} | {int(grand_total[2])} | {int(grand_total[3])} | {int(grand_total[4])} | "
        f"{baseline_totals[0] if not unclassified_failures else '—'} | "
        f"{baseline_totals[1] if not unclassified_failures else '—'} | "
        f"{baseline_totals[2] if not unclassified_failures else '—'} | {grand_total[5]:.2f}s"
    )
    if has_rerun:
        rerun_tests = sum(result.tests for result in rerun.suites)
        rerun_passed = sum(result.passed for result in rerun.suites)
        marker = " ❌" if any(_is_failure(result) for result in rerun.suites) else ""
        row += f" | {rerun_passed}/{rerun_tests}{marker}"
    rows.append(row + " |")
    cached = sum(len(record.cached) for record in records.values())
    rows.extend(["", f"cached (skipped, unchanged since green): {cached} target(s)"])
    if unclassified_failures:
        rows.append("Gate: ⚠️ failures not classified")
    elif baseline_totals[0] or baseline_totals[2]:
        rows.append(f"Gate: ❌ {baseline_totals[0]} new red, {baseline_totals[2]} unknown")
    else:
        rows.append("Gate: ✅ no new reds")
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
    if notes:
        rows.extend(["### Notes", ""])
        rows.extend(f"- {note}" for note in notes)
        rows.append("")
    return "\n".join(rows)
