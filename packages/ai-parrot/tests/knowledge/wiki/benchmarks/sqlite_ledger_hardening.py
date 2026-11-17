"""FEAT-902 explicit, isolated SQLite/ledger measurement driver."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import multiprocessing
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DRIVER_MODULE = "sqlite_ledger_hardening"
_TIMING_PHASES = (
    "connection_open",
    "connection_setup",
    "begin_wait",
    "transaction_body",
    "commit",
    "rollback",
    "log_append",
    "log_fsync",
    "replay",
    "sync_probe",
)


class SourceIsolationError(ValueError):
    """The requested source checkout or revision was not loaded by a worker."""


class BenchmarkConfig(BaseModel):
    """Validated arm and isolated source/workload parameters."""

    model_config = {"extra": "forbid", "frozen": True}

    arm: Literal["baseline", "candidate"]
    revision: str = Field(min_length=7)
    source_root: Path
    processes: Literal[1, 4, 8]
    workload: Literal["idle-ledger", "mixed-ledger", "claim-race", "wiki"]
    lifecycle: Literal["resident", "ephemeral"]
    trials: int = Field(default=3, ge=1)
    warmup: int = Field(default=100, ge=0)
    operations: int = Field(default=1000, ge=1)
    seed: int = 902
    output_dir: Path
    run_timeout_s: int = Field(default=1800, ge=1)

    def model_post_init(self, __context: Any) -> None:
        """Reject source/output combinations that could touch a live project plane."""
        source_root = self.source_root.expanduser().resolve()
        output_dir = self.output_dir.expanduser().resolve()
        live_plane = source_root / ".parrot"
        if output_dir == live_plane or live_plane in output_dir.parents:
            raise ValueError("benchmark output_dir must not be inside source_root/.parrot")


class PercentileSummary(BaseModel):
    """Sample count and latency percentiles, with no fabricated empty values."""

    model_config = {"extra": "forbid", "frozen": True}

    count: int = Field(ge=0)
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None

    def model_post_init(self, __context: Any) -> None:
        """Require empty summaries to use unavailable percentile values."""
        values = (self.p50_ms, self.p95_ms, self.p99_ms)
        if self.count == 0 and any(value is not None for value in values):
            raise ValueError("empty percentile summaries must use null values")
        if self.count > 0 and any(value is None for value in values):
            raise ValueError("non-empty percentile summaries require all percentiles")


class OperationSample(BaseModel):
    """One raw timed operation, including unsuccessful attempts."""

    model_config = {"extra": "forbid", "frozen": True}

    worker_id: int = Field(ge=0)
    sequence: int = Field(ge=0)
    operation: str = Field(min_length=1)
    duration_ms: float = Field(ge=0.0)
    success: bool
    outcome: str = Field(min_length=1)
    subject: str | None
    error_type: str | None


class BenchmarkCounts(BaseModel):
    """Connection, transaction, replay and operation counters."""

    model_config = {"extra": "forbid", "frozen": True}

    connection_opens: int = Field(ge=0)
    begin_attempts: int = Field(ge=0)
    commits: int = Field(ge=0)
    rollbacks: int = Field(ge=0)
    fast_paths: int | None = Field(default=None, ge=0)
    replay_events: int | None = Field(default=None, ge=0)
    stale_read_fallbacks: int | None = Field(default=None, ge=0)
    busy_outcomes: int = Field(ge=0)
    errors: int = Field(ge=0)
    successful_operations: int = Field(ge=0)
    unsuccessful_operations: int = Field(ge=0)


class WorkerReport(BaseModel):
    """Raw evidence captured by one spawned process."""

    model_config = {"extra": "forbid", "frozen": True}

    worker_id: int = Field(ge=0)
    pid: int = Field(gt=0)
    revision: str = Field(min_length=40, max_length=40)
    dirty: bool
    imported_modules: dict[str, str]
    module_sha256: dict[str, str]
    environment: dict[str, Any]
    pragmas: dict[str, dict[str, Any]]
    samples: list[OperationSample]
    loop_lag_ms: list[float]
    phase_timings_ms: dict[str, list[float] | None]
    timing_records: list[dict[str, Any]]
    counts: BenchmarkCounts
    wal_before_bytes: dict[str, int]
    wal_after_bytes: dict[str, int]
    elapsed_s: float = Field(ge=0.0)
    complete: bool
    error: str | None


class TrialReport(BaseModel):
    """Aggregated evidence and invariants for one trial."""

    model_config = {"extra": "forbid", "frozen": True}

    trial: int = Field(ge=0)
    workers: list[WorkerReport]
    samples: list[OperationSample]
    latency_ms: dict[str, PercentileSummary]
    successful_latency_ms: PercentileSummary
    unsuccessful_latency_ms: PercentileSummary
    loop_lag_ms: PercentileSummary
    throughput_ops_s: float = Field(ge=0.0)
    counts: BenchmarkCounts
    outcomes: dict[str, int]
    phase_timings_ms: dict[str, list[float] | None]
    wal_before_bytes: dict[str, int]
    wal_after_bytes: dict[str, int]
    invariants: dict[str, bool]
    complete: bool


class BenchmarkReport(BaseModel):
    """Raw samples, metadata, outcomes and invariants for one matrix cell."""

    model_config = {"extra": "forbid", "frozen": True}

    schema_version: Literal[1] = 1
    config: BenchmarkConfig
    environment: dict[str, Any]
    trials: list[TrialReport]
    invariants: dict[str, bool]
    complete: bool

    def model_post_init(self, __context: Any) -> None:
        """Prevent complete reports from omitting cells or failed invariants."""
        if not self.complete:
            return
        if len(self.trials) != self.config.trials:
            raise ValueError("complete report must contain every configured trial")
        if not self.trials or not all(trial.complete for trial in self.trials):
            raise ValueError("complete report contains an incomplete trial")
        if not self.invariants or not all(self.invariants.values()):
            raise ValueError("complete report contains a failed or missing invariant")


class _MemoryLogHandler(logging.Handler):
    """Capture structured benchmark timing records without file I/O."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Retain only the approved structured timing and stale-read fields."""
        try:
            event = getattr(record, "event", None)
            if event not in ("wiki.sqlite.timing", "wiki.ledger.stale_read"):
                return
            captured = {
                "event": event,
                "operation": getattr(record, "operation", None),
                "phase": getattr(record, "phase", None),
                "duration_ms": getattr(record, "duration_ms", None),
                "outcome": getattr(record, "outcome", None),
                "pid": getattr(record, "pid", record.process),
                "db_name": getattr(record, "db_name", None),
                "applied_events": getattr(record, "applied_events", None),
                "fast_path": getattr(record, "fast_path", None),
            }
            self.records.append(captured)
        except Exception:  # noqa: BLE001 -- instrumentation must not alter the measured operation
            return


class _ConnectionCapture:
    """Wrap public aiosqlite connection and trace APIs for one timed worker."""

    def __init__(self, aiosqlite_module: Any) -> None:
        self._aiosqlite = aiosqlite_module
        self._original_connect = aiosqlite_module.connect
        self.connection_opens = 0
        self.begin_attempts = 0
        self.commits = 0
        self.rollbacks = 0

    def install(self) -> None:
        """Install a process-local wrapper around ``aiosqlite.connect``."""
        capture = self

        def wrapped_connect(*args: Any, **kwargs: Any) -> _CapturedConnection:
            capture.connection_opens += 1
            return _CapturedConnection(capture._original_connect(*args, **kwargs), capture)

        self._aiosqlite.connect = wrapped_connect

    def restore(self) -> None:
        """Restore the original public connector."""
        self._aiosqlite.connect = self._original_connect

    def reset(self) -> None:
        """Exclude fixture and warmup connection activity from timed counts."""
        self.connection_opens = 0
        self.begin_attempts = 0
        self.commits = 0
        self.rollbacks = 0

    def trace(self, statement: str) -> None:
        """Count transaction boundaries without retaining SQL text."""
        normalized = statement.lstrip().upper()
        if normalized.startswith("BEGIN"):
            self.begin_attempts += 1
        elif normalized.startswith("COMMIT"):
            self.commits += 1
        elif normalized.startswith("ROLLBACK"):
            self.rollbacks += 1


class _CapturedConnection:
    """Awaitable/context-manager proxy that installs a public trace callback."""

    def __init__(self, connection: Any, capture: _ConnectionCapture) -> None:
        self._connection = connection
        self._capture = capture

    async def _open(self) -> Any:
        connection = await self._connection
        await connection.set_trace_callback(self._capture.trace)
        return connection

    def __await__(self) -> Any:
        return self._open().__await__()

    async def __aenter__(self) -> Any:
        connection = await self._connection.__aenter__()
        await connection.set_trace_callback(self._capture.trace)
        return connection

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> Any:
        return await self._connection.__aexit__(exc_type, exc, traceback)


def _git_metadata(source_root: Path, revision: str) -> tuple[str, bool]:
    """Resolve and verify the immutable checkout revision without importing Parrot."""

    def git(*arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(source_root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
            raise SourceIsolationError(detail)
        return result.stdout.strip()

    actual = git("rev-parse", "HEAD")
    expected = git("rev-parse", f"{revision}^{{commit}}")
    if actual != expected:
        raise SourceIsolationError(f"requested revision {expected} but source checkout HEAD is {actual}")
    return actual, bool(git("status", "--porcelain", "--untracked-files=no"))


def _sha256(path: Path) -> str:
    """Hash an imported module file for reproducible source evidence."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_source(config: BenchmarkConfig) -> dict[str, Any]:
    """Root imports at the requested checkout and verify their paths and revision."""
    source_root = config.source_root.expanduser().resolve()
    package_root = (source_root / "packages" / "ai-parrot" / "src").resolve()
    if not (package_root / "parrot" / "knowledge" / "wiki" / "store.py").is_file():
        raise SourceIsolationError(f"source root has no ai-parrot package: {source_root}")
    preloaded = sorted(name for name in sys.modules if name == "parrot" or name.startswith("parrot."))
    if preloaded:
        raise SourceIsolationError(f"Parrot modules were imported before source resolution: {preloaded[:3]}")
    sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != package_root]
    sys.path.insert(0, str(package_root))
    revision, dirty = _git_metadata(source_root, config.revision)

    from parrot.knowledge.wiki import store as store_module
    from parrot.knowledge.wiki.ledger import service as service_module
    from parrot.knowledge.wiki.ledger.service import LedgerService
    from parrot.knowledge.wiki.store import SQLitePragmaPolicy, SQLiteWikiStore, WikiPageRecord

    imported_modules = {
        "store": str(Path(store_module.__file__).resolve()),
        "ledger_service": str(Path(service_module.__file__).resolve()),
    }
    for module_name, module_path_text in imported_modules.items():
        module_path = Path(module_path_text)
        if package_root not in module_path.parents:
            raise SourceIsolationError(f"{module_name} imported outside requested source: {module_path}")
    return {
        "revision": revision,
        "dirty": dirty,
        "imported_modules": imported_modules,
        "module_sha256": {name: _sha256(Path(path)) for name, path in imported_modules.items()},
        "LedgerService": LedgerService,
        "SQLitePragmaPolicy": SQLitePragmaPolicy,
        "SQLiteWikiStore": SQLiteWikiStore,
        "WikiPageRecord": WikiPageRecord,
    }


async def _new_service(symbols: dict[str, Any], ledger_dir: Path) -> Any:
    """Construct a ledger service off-loop because it creates directories."""
    policy = symbols["SQLitePragmaPolicy"]()
    return await asyncio.to_thread(lambda: symbols["LedgerService"].from_dir(ledger_dir, sqlite_policy=policy))


async def _new_wiki_store(symbols: dict[str, Any], wiki_db: Path) -> Any:
    """Construct a wiki store off-loop because it creates directories."""
    policy = symbols["SQLitePragmaPolicy"]()
    return await asyncio.to_thread(
        lambda: symbols["SQLiteWikiStore"](wiki_db, wiki_name="benchmark", sqlite_policy=policy)
    )


async def _seed_fixtures(
    config: BenchmarkConfig,
    symbols: dict[str, Any],
    trial_dir: Path,
    fixture_scale: int,
) -> None:
    """Build disposable ledger and wiki fixtures through existing public APIs."""
    ledger_dir = trial_dir / "ledger"
    wiki_db = trial_dir / "wiki" / "wiki.db"
    service = await _new_service(symbols, ledger_dir)
    issue_ids = []
    for index in range(fixture_scale):
        issue_ids.append(
            await service.open_issue(
                f"benchmark issue {index}",
                "reproducible benchmark fixture",
                discovered_from=f"benchmark:{config.seed}:{index}",
                actor="agent:benchmark-fixture",
            )
        )
    claim_issue_ids = []
    if config.workload == "claim-race":
        for index in range(config.warmup + config.operations):
            claim_issue_ids.append(
                await service.open_issue(
                    f"claim race {index}",
                    "fresh synchronized claim target",
                    discovered_from=f"claim:{config.seed}:{index}",
                    actor="agent:benchmark-fixture",
                )
            )

    store = await _new_wiki_store(symbols, wiki_db)
    pages = [
        symbols["WikiPageRecord"](
            concept_id=f"benchmark-page-{index}",
            title=f"Benchmark page {index}",
            category="benchmark",
            summary="sqlite ledger benchmark",
            body=f"benchmark fixture body {index}",
            origin="authored",
            asserted_by="agent:benchmark-fixture",
        )
        for index in range(fixture_scale)
    ]
    await store.upsert_pages(pages)
    manifest = {"issue_ids": issue_ids, "claim_issue_ids": claim_issue_ids}
    await asyncio.to_thread(
        (trial_dir / "fixture.json").write_text,
        json.dumps(manifest, sort_keys=True),
        "utf-8",
    )


async def _read_fixture(trial_dir: Path) -> dict[str, list[str]]:
    """Read the worker-shared fixture manifest outside timed operations."""
    raw = await asyncio.to_thread((trial_dir / "fixture.json").read_text, "utf-8")
    value = json.loads(raw)
    return {"issue_ids": list(value["issue_ids"]), "claim_issue_ids": list(value["claim_issue_ids"])}


async def _barrier_wait(barrier: Any) -> None:
    """Wait on a multiprocessing barrier without blocking the event loop."""
    await asyncio.to_thread(barrier.wait)


async def _heartbeat(stop: asyncio.Event, samples: list[float]) -> None:
    """Record 10 ms event-loop scheduling lag until ``stop`` is set."""
    interval = 0.010
    target = time.perf_counter() + interval
    while not stop.is_set():
        await asyncio.sleep(max(0.0, target - time.perf_counter()))
        now = time.perf_counter()
        samples.append(max(0.0, now - target) * 1000.0)
        target += interval


async def _wal_sizes(trial_dir: Path) -> dict[str, int]:
    """Measure current wiki and ledger WAL sizes without creating them."""

    def size(path: Path) -> int:
        try:
            return path.stat().st_size
        except FileNotFoundError:
            return 0

    return await asyncio.to_thread(
        lambda: {
            "ledger": size(trial_dir / "ledger" / "ledger.db-wal"),
            "wiki": size(trial_dir / "wiki" / "wiki.db-wal"),
        }
    )


async def _execute_operation(
    config: BenchmarkConfig,
    symbols: dict[str, Any],
    trial_dir: Path,
    fixture: dict[str, list[str]],
    resident_service: Any,
    resident_store: Any,
    worker_id: int,
    sequence: int,
    stage: str,
) -> tuple[str, str | None, bool]:
    """Execute one configured operation and return its operation, subject and outcome."""
    if config.lifecycle == "ephemeral":
        service = await _new_service(symbols, trial_dir / "ledger")
        store = await _new_wiki_store(symbols, trial_dir / "wiki" / "wiki.db")
    else:
        service = resident_service
        store = resident_store

    issue_ids = fixture["issue_ids"]
    ordinal = sequence + (config.seed * (worker_id + 1))
    if config.workload == "idle-ledger":
        mode = ordinal % 3
        if mode == 0:
            subject = issue_ids[ordinal % len(issue_ids)]
            return "ledger.get", subject, (await service.get_issue(subject)) is not None
        if mode == 1:
            await service.list_issues()
            return "ledger.list", None, True
        await service.ready_work()
        return "ledger.ready", None, True

    if config.workload == "mixed-ledger":
        if ordinal % 5 == 0:
            subject = await service.open_issue(
                f"mixed {stage} {worker_id} {sequence}",
                "mixed benchmark write",
                discovered_from=f"mixed:{stage}:{worker_id}:{sequence}:{config.seed}",
                actor=f"agent:benchmark-{worker_id}",
            )
            return "ledger.open", subject, True
        mode = ordinal % 3
        if mode == 0:
            subject = issue_ids[ordinal % len(issue_ids)]
            return "ledger.get", subject, (await service.get_issue(subject)) is not None
        if mode == 1:
            await service.list_issues()
            return "ledger.list", None, True
        await service.ready_work()
        return "ledger.ready", None, True

    if config.workload == "claim-race":
        subject = fixture["claim_issue_ids"][sequence]
        accepted = await service.claim(subject, f"agent:benchmark-{worker_id}")
        return "ledger.claim", subject, bool(accepted)

    if ordinal % 5 == 0:
        subject = f"benchmark-{stage}-{worker_id}-{sequence}"
        count = await store.upsert_pages(
            [
                symbols["WikiPageRecord"](
                    concept_id=subject,
                    title=f"Benchmark {stage} {worker_id} {sequence}",
                    category="benchmark",
                    summary="sqlite ledger benchmark",
                    body="benchmark unique upsert body",
                    origin="authored",
                    asserted_by=f"agent:benchmark-{worker_id}",
                )
            ]
        )
        return "wiki.upsert", subject, count == 1
    if ordinal % 2 == 0:
        subject = f"benchmark-page-{ordinal % len(issue_ids)}"
        return "wiki.get", subject, (await store.get_page(subject)) is not None
    await store.search_fts("benchmark", limit=10)
    return "wiki.search", None, True


async def _worker_async(payload: dict[str, Any], barrier: Any) -> dict[str, Any]:
    """Run one workload participant after source-root verification."""
    config = BenchmarkConfig.model_validate(payload["config"])
    worker_id = int(payload["worker_id"])
    trial_dir = Path(payload["trial_dir"])
    fixture_scale = int(payload["fixture_scale"])
    symbols = _prepare_source(config)

    import aiosqlite

    if worker_id == 0:
        await _seed_fixtures(config, symbols, trial_dir, fixture_scale)
    await _barrier_wait(barrier)
    fixture = await _read_fixture(trial_dir)
    resident_service = await _new_service(symbols, trial_dir / "ledger")
    resident_store = await _new_wiki_store(symbols, trial_dir / "wiki" / "wiki.db")

    pragmas = {
        "ledger": await resident_service.store.sqlite_settings(),
        "wiki": await resident_store.sqlite_settings(),
    }
    sqlite_version = None
    async with aiosqlite.connect(trial_dir / "wiki" / "wiki.db") as connection:
        async with connection.execute("SELECT sqlite_version()") as cursor:
            row = await cursor.fetchone()
            sqlite_version = row[0] if row else None

    handler = _MemoryLogHandler()
    capture_logger = logging.getLogger("parrot.knowledge.wiki")
    previous_level = capture_logger.level
    previous_propagate = capture_logger.propagate
    capture_logger.addHandler(handler)
    capture_logger.setLevel(logging.DEBUG)
    capture_logger.propagate = False
    capture = _ConnectionCapture(aiosqlite)
    capture.install()
    try:
        for sequence in range(config.warmup):
            if config.workload == "claim-race":
                await _barrier_wait(barrier)
            await _execute_operation(
                config,
                symbols,
                trial_dir,
                fixture,
                resident_service,
                resident_store,
                worker_id,
                sequence,
                "warmup",
            )
        capture.reset()
        handler.records.clear()

        samples = []
        loop_lag_ms: list[float] = []
        stop_heartbeat = asyncio.Event()
        heartbeat = asyncio.create_task(_heartbeat(stop_heartbeat, loop_lag_ms))
        wal_before = await _wal_sizes(trial_dir)
        started = time.perf_counter()
        for sequence in range(config.operations):
            if config.workload == "claim-race":
                await _barrier_wait(barrier)
                operation_sequence = config.warmup + sequence
            else:
                operation_sequence = sequence
            operation_started = time.perf_counter()
            operation = config.workload
            subject = None
            success = False
            outcome = "error"
            error_type = None
            try:
                operation, subject, success = await _execute_operation(
                    config,
                    symbols,
                    trial_dir,
                    fixture,
                    resident_service,
                    resident_store,
                    worker_id,
                    operation_sequence,
                    "timed",
                )
                outcome = "ok" if success else "rejected"
            except Exception as exc:  # noqa: BLE001 -- failures are benchmark outcomes
                error_type = type(exc).__name__
                outcome = "busy" if error_type == "WikiStoreBusy" or "locked" in str(exc).lower() else "error"
            samples.append(
                OperationSample(
                    worker_id=worker_id,
                    sequence=sequence,
                    operation=operation,
                    duration_ms=(time.perf_counter() - operation_started) * 1000.0,
                    success=success,
                    outcome=outcome,
                    subject=subject,
                    error_type=error_type,
                )
            )
        elapsed_s = time.perf_counter() - started
        wal_after = await _wal_sizes(trial_dir)
        stop_heartbeat.set()
        await heartbeat
        await _barrier_wait(barrier)

        phase_timings: dict[str, list[float] | None] = dict.fromkeys(_TIMING_PHASES)
        for record in handler.records:
            phase = record.get("phase")
            duration = record.get("duration_ms")
            if phase in phase_timings and isinstance(duration, (int, float)):
                current = phase_timings[phase]
                if current is None:
                    current = []
                    phase_timings[phase] = current
                current.append(float(duration))
        fast_path_values = [
            record.get("fast_path") for record in handler.records if record.get("fast_path") is not None
        ]
        replay_values = [
            int(record["applied_events"]) for record in handler.records if isinstance(record.get("applied_events"), int)
        ]
        stale_reads = sum(record.get("event") == "wiki.ledger.stale_read" for record in handler.records)
        busy = sum(sample.outcome == "busy" for sample in samples)
        errors = sum(sample.outcome == "error" for sample in samples)
        counts = BenchmarkCounts(
            connection_opens=capture.connection_opens,
            begin_attempts=capture.begin_attempts,
            commits=capture.commits,
            rollbacks=capture.rollbacks,
            fast_paths=sum(bool(value) for value in fast_path_values) if fast_path_values else None,
            replay_events=sum(replay_values) if replay_values else None,
            stale_read_fallbacks=(
                stale_reads
                if any(record.get("event") == "wiki.ledger.stale_read" for record in handler.records)
                else None
            ),
            busy_outcomes=busy,
            errors=errors,
            successful_operations=sum(sample.success for sample in samples),
            unsuccessful_operations=sum(not sample.success for sample in samples),
        )
        uname = os.uname() if hasattr(os, "uname") else None
        environment = {
            "python": sys.version,
            "sqlite": sqlite_version,
            "aiosqlite": getattr(aiosqlite, "__version__", None),
            "platform": sys.platform,
            "os": uname.sysname if uname else os.name,
            "os_release": uname.release if uname else None,
            "cpu_count": os.cpu_count(),
            "fixture_scale": fixture_scale,
        }
        return WorkerReport(
            worker_id=worker_id,
            pid=os.getpid(),
            revision=symbols["revision"],
            dirty=symbols["dirty"],
            imported_modules=symbols["imported_modules"],
            module_sha256=symbols["module_sha256"],
            environment=environment,
            pragmas=pragmas,
            samples=samples,
            loop_lag_ms=loop_lag_ms,
            phase_timings_ms=phase_timings,
            timing_records=handler.records,
            counts=counts,
            wal_before_bytes=wal_before,
            wal_after_bytes=wal_after,
            elapsed_s=elapsed_s,
            complete=len(samples) == config.operations,
            error=None,
        ).model_dump(mode="json")
    finally:
        capture.restore()
        capture_logger.removeHandler(handler)
        capture_logger.setLevel(previous_level)
        capture_logger.propagate = previous_propagate


def _worker_entry(payload: dict[str, Any], barrier: Any, result_connection: Any) -> None:
    """Spawn-safe synchronous worker entry point."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result_connection.send({"result": loop.run_until_complete(_worker_async(payload, barrier))})
    except SourceIsolationError as exc:
        result_connection.send(
            {
                "worker_id": payload["worker_id"],
                "source_isolation": True,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    except BaseException as exc:  # noqa: BLE001 -- infrastructure failures must reach the report
        result_connection.send(
            {
                "worker_id": payload["worker_id"],
                "source_isolation": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    finally:
        result_connection.close()
        # The existing ledger APIs use asyncio.to_thread. Some protected runners
        # cannot join the idle default executor during interpreter shutdown, so
        # this already-isolated worker exits after all connections and evidence
        # have been closed and synchronously sent to its parent.
        os._exit(0)


async def _verify_trial_async(payload: dict[str, Any]) -> dict[str, Any]:
    """Check log preservation, projection recovery and database integrity."""
    config = BenchmarkConfig.model_validate(payload["config"])
    trial_dir = Path(payload["trial_dir"])
    accepted = list(payload["accepted"])
    successful_claims = list(payload["successful_claims"])
    symbols = _prepare_source(config)

    import aiosqlite

    service = await _new_service(symbols, trial_dir / "ledger")
    await service.index.sync()
    statuses = ("open", "claimed", "closed", "superseded")
    before = await service.list_issues(statuses=statuses)
    before.sort(key=lambda row: row["issue_id"])
    await service.index.rebuild()
    after = await service.list_issues(statuses=statuses)
    after.sort(key=lambda row: row["issue_id"])

    log_path = trial_dir / "ledger" / "events.jsonl"
    log_text = await asyncio.to_thread(log_path.read_text, "utf-8")
    lines = [line for line in log_text.splitlines() if line.strip()]
    decoded = [json.loads(line) for line in lines]
    subjects = [entry.get("subject") for entry in decoded]
    preserved = all(subject in subjects for subject in accepted)

    claim_counts: dict[str, int] = {}
    for subject in successful_claims:
        claim_counts[subject] = claim_counts.get(subject, 0) + 1
    claimed_rows = {row["issue_id"]: row for row in after if row.get("status") == "claimed"}
    claims_unique = all(
        count == 1 and claimed_rows.get(subject, {}).get("claimed_by") for subject, count in claim_counts.items()
    )

    integrity: dict[str, bool] = {}
    for name, database in (
        ("ledger", trial_dir / "ledger" / "ledger.db"),
        ("wiki", trial_dir / "wiki" / "wiki.db"),
    ):
        async with aiosqlite.connect(database) as connection:
            async with connection.execute("PRAGMA integrity_check") as cursor:
                rows = await cursor.fetchall()
        integrity[name] = bool(rows) and all(str(row[0]).lower() == "ok" for row in rows)
    return {
        "projection_matches_rebuild": before == after,
        "accepted_events_preserved": preserved,
        "claim_owner_unique": claims_unique,
        "integrity_ok": all(integrity.values()),
        "log_sha256": hashlib.sha256(log_text.encode("utf-8")).hexdigest(),
        "event_count": len(decoded),
    }


def _verification_entry(payload: dict[str, Any], result_connection: Any) -> None:
    """Spawn-safe verification entry point."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result_connection.send({"result": loop.run_until_complete(_verify_trial_async(payload))})
    except SourceIsolationError as exc:
        result_connection.send({"source_isolation": True, "error": f"{type(exc).__name__}: {exc}"})
    except BaseException as exc:  # noqa: BLE001 -- verification failures make evidence incomplete
        result_connection.send({"source_isolation": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        result_connection.close()
        os._exit(0)


def _quantile(values: list[float], fraction: float) -> float:
    """Return a linearly interpolated quantile for any non-empty sample size."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * weight)


def _summarize(values: list[float]) -> PercentileSummary:
    """Build p50/p95/p99 without substituting zero for unavailable data."""
    if not values:
        return PercentileSummary(count=0, p50_ms=None, p95_ms=None, p99_ms=None)
    return PercentileSummary(
        count=len(values),
        p50_ms=float(statistics.median(values)),
        p95_ms=_quantile(values, 0.95),
        p99_ms=_quantile(values, 0.99),
    )


def _sum_optional(values: list[int | None]) -> int | None:
    """Sum available counters while preserving wholly unavailable metrics."""
    available = [value for value in values if value is not None]
    return sum(available) if available else None


def _aggregate_counts(workers: list[WorkerReport]) -> BenchmarkCounts:
    """Aggregate worker counters without converting unavailable values to zero."""
    return BenchmarkCounts(
        connection_opens=sum(worker.counts.connection_opens for worker in workers),
        begin_attempts=sum(worker.counts.begin_attempts for worker in workers),
        commits=sum(worker.counts.commits for worker in workers),
        rollbacks=sum(worker.counts.rollbacks for worker in workers),
        fast_paths=_sum_optional([worker.counts.fast_paths for worker in workers]),
        replay_events=_sum_optional([worker.counts.replay_events for worker in workers]),
        stale_read_fallbacks=_sum_optional([worker.counts.stale_read_fallbacks for worker in workers]),
        busy_outcomes=sum(worker.counts.busy_outcomes for worker in workers),
        errors=sum(worker.counts.errors for worker in workers),
        successful_operations=sum(worker.counts.successful_operations for worker in workers),
        unsuccessful_operations=sum(worker.counts.unsuccessful_operations for worker in workers),
    )


def _placeholder_worker(worker_id: int, error: str) -> WorkerReport:
    """Represent a missing/crashed worker without fabricating samples or metadata."""
    return WorkerReport(
        worker_id=worker_id,
        pid=1,
        revision="0" * 40,
        dirty=False,
        imported_modules={},
        module_sha256={},
        environment={},
        pragmas={},
        samples=[],
        loop_lag_ms=[],
        phase_timings_ms=dict.fromkeys(_TIMING_PHASES),
        timing_records=[],
        counts=BenchmarkCounts(
            connection_opens=0,
            begin_attempts=0,
            commits=0,
            rollbacks=0,
            fast_paths=None,
            replay_events=None,
            stale_read_fallbacks=None,
            busy_outcomes=0,
            errors=1,
            successful_operations=0,
            unsuccessful_operations=0,
        ),
        wal_before_bytes={"ledger": 0, "wiki": 0},
        wal_after_bytes={"ledger": 0, "wiki": 0},
        elapsed_s=0.0,
        complete=False,
        error=error,
    )


def _wait_for_connections(connections: dict[int, Any], deadline: float) -> dict[int, dict[str, Any]]:
    """Read child pipes before joins so result payloads cannot block process exit."""
    pending = dict(connections)
    results: dict[int, dict[str, Any]] = {}
    while pending and time.monotonic() < deadline:
        progressed = False
        for worker_id, connection in list(pending.items()):
            if not connection.poll(0.01):
                continue
            try:
                results[worker_id] = connection.recv()
            except EOFError:
                results[worker_id] = {"worker_id": worker_id, "error": "worker pipe closed without evidence"}
            connection.close()
            del pending[worker_id]
            progressed = True
        if not progressed and pending:
            first = next(iter(pending.values()))
            first.poll(min(0.05, max(0.0, deadline - time.monotonic())))
    for connection in pending.values():
        connection.close()
    return results


def _run_trial(config: BenchmarkConfig, trial: int, fixture_scale: int) -> TrialReport:
    """Spawn one trial's workers, aggregate evidence and run recovery checks."""
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(config.processes, timeout=config.run_timeout_s)
    trial_dir = config.output_dir.expanduser().resolve() / f"trial-{trial:02d}"
    trial_dir.mkdir(parents=True, exist_ok=False)
    processes = []
    result_connections: dict[int, Any] = {}
    for worker_id in range(config.processes):
        payload = {
            "config": config.model_dump(mode="json"),
            "worker_id": worker_id,
            "trial_dir": str(trial_dir),
            "fixture_scale": fixture_scale,
        }
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_worker_entry, args=(payload, barrier, sender))
        process.start()
        sender.close()
        processes.append(process)
        result_connections[worker_id] = receiver

    deadline = time.monotonic() + config.run_timeout_s
    queued_by_worker = _wait_for_connections(result_connections, deadline)
    for process in processes:
        process.join(max(0.0, deadline - time.monotonic()))
    timed_out = []
    for worker_id, process in enumerate(processes):
        if process.is_alive():
            timed_out.append(worker_id)
            process.terminate()
            process.join(10)

    queued = list(queued_by_worker.values())
    isolation_errors = [item["error"] for item in queued if item.get("source_isolation")]
    if isolation_errors:
        raise SourceIsolationError("; ".join(isolation_errors))
    by_worker: dict[int, WorkerReport] = {}
    for item in queued:
        if "result" in item:
            report = WorkerReport.model_validate(item["result"])
            by_worker[report.worker_id] = report
        elif "worker_id" in item:
            worker_id = int(item["worker_id"])
            by_worker[worker_id] = _placeholder_worker(worker_id, str(item.get("error", "worker failed")))
    for worker_id, process in enumerate(processes):
        if worker_id not in by_worker:
            reason = "worker timed out" if worker_id in timed_out else f"worker exited with code {process.exitcode}"
            by_worker[worker_id] = _placeholder_worker(worker_id, reason)
    workers = [by_worker[index] for index in sorted(by_worker)]
    samples = [sample for worker in workers for sample in worker.samples]

    accepted = [
        sample.subject
        for sample in samples
        if sample.success and sample.subject and sample.operation in ("ledger.open", "ledger.claim")
    ]
    successful_claims = [
        sample.subject for sample in samples if sample.success and sample.subject and sample.operation == "ledger.claim"
    ]
    verification_payload = {
        "config": config.model_dump(mode="json"),
        "trial_dir": str(trial_dir),
        "accepted": accepted,
        "successful_claims": successful_claims,
    }
    verification_receiver, verification_sender = context.Pipe(duplex=False)
    verifier = context.Process(target=_verification_entry, args=(verification_payload, verification_sender))
    verifier.start()
    verification_sender.close()
    verification_deadline = time.monotonic() + config.run_timeout_s
    verification_by_id = _wait_for_connections({0: verification_receiver}, verification_deadline)
    verifier.join(max(0.0, verification_deadline - time.monotonic()))
    if verifier.is_alive():
        verifier.terminate()
        verifier.join(10)
        verification_item: dict[str, Any] = {"error": "verification timed out"}
    else:
        verification_item = verification_by_id.get(0, {"error": "verification produced no result"})
    if verification_item.get("source_isolation"):
        raise SourceIsolationError(str(verification_item["error"]))
    verification = verification_item.get("result", {})

    latency: dict[str, PercentileSummary] = {}
    for operation in sorted({sample.operation for sample in samples}):
        latency[operation] = _summarize([sample.duration_ms for sample in samples if sample.operation == operation])
    outcomes: dict[str, int] = {}
    for sample in samples:
        outcomes[sample.outcome] = outcomes.get(sample.outcome, 0) + 1
    phase_timings: dict[str, list[float] | None] = {}
    for phase in _TIMING_PHASES:
        values = [duration for worker in workers for duration in (worker.phase_timings_ms.get(phase) or [])]
        phase_timings[phase] = values or None
    wal_before = {
        plane: min((worker.wal_before_bytes.get(plane, 0) for worker in workers), default=0)
        for plane in ("ledger", "wiki")
    }
    wal_after = {
        plane: max((worker.wal_after_bytes.get(plane, 0) for worker in workers), default=0)
        for plane in ("ledger", "wiki")
    }
    invariants = {
        "worker_cleanup": all(not process.is_alive() for process in [*processes, verifier]),
        "worker_count": len(workers) == config.processes,
        "operation_count": len(samples) == config.operations * config.processes,
        "projection_matches_rebuild": bool(verification.get("projection_matches_rebuild", False)),
        "accepted_events_preserved": bool(verification.get("accepted_events_preserved", False)),
        "claim_owner_unique": bool(verification.get("claim_owner_unique", False)),
        "integrity_ok": bool(verification.get("integrity_ok", False)),
    }
    elapsed = max((worker.elapsed_s for worker in workers), default=0.0)
    complete = all(worker.complete for worker in workers) and all(invariants.values())
    return TrialReport(
        trial=trial,
        workers=workers,
        samples=samples,
        latency_ms=latency,
        successful_latency_ms=_summarize([sample.duration_ms for sample in samples if sample.success]),
        unsuccessful_latency_ms=_summarize([sample.duration_ms for sample in samples if not sample.success]),
        loop_lag_ms=_summarize([lag for worker in workers for lag in worker.loop_lag_ms]),
        throughput_ops_s=(len(samples) / elapsed) if elapsed > 0 else 0.0,
        counts=_aggregate_counts(workers),
        outcomes=outcomes,
        phase_timings_ms=phase_timings,
        wal_before_bytes=wal_before,
        wal_after_bytes=wal_after,
        invariants=invariants,
        complete=complete,
    )


def run_benchmark(config: BenchmarkConfig) -> BenchmarkReport:
    """Spawn isolated workers and report measured samples plus correctness evidence."""
    source_root = config.source_root.expanduser().resolve()
    output_dir = config.output_dir.expanduser().resolve()
    canonical = config.model_copy(update={"source_root": source_root, "output_dir": output_dir})
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"benchmark output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    driver_dir = str(Path(__file__).resolve().parent)
    if driver_dir not in sys.path:
        sys.path.insert(0, driver_dir)
    fixture_scale = min(1000, max(canonical.operations, canonical.warmup, 4))
    trials = [_run_trial(canonical, trial, fixture_scale) for trial in range(canonical.trials)]
    invariants = {
        "all_trials_complete": all(trial.complete for trial in trials),
        "source_revision_consistent": all(
            worker.revision == trials[0].workers[0].revision
            for trial in trials
            for worker in trial.workers
            if worker.complete
        ),
        "separate_databases": all(
            worker.pragmas.get("wiki") is not None and worker.pragmas.get("ledger") is not None
            for trial in trials
            for worker in trial.workers
        ),
    }
    first_worker = trials[0].workers[0]
    environment = {
        **first_worker.environment,
        "revision": first_worker.revision,
        "dirty": first_worker.dirty,
        "imported_modules": first_worker.imported_modules,
        "module_sha256": first_worker.module_sha256,
        "fixture_scale": fixture_scale,
        "connection_lifecycle": "connection-per-operation",
        "ephemeral_scope": "store/service per operation; interpreter startup excluded",
    }
    complete = all(invariants.values())
    return BenchmarkReport(
        config=canonical,
        environment=environment,
        trials=trials,
        invariants=invariants,
        complete=complete,
    )


def _parser() -> argparse.ArgumentParser:
    """Build the explicit benchmark command-line contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("baseline", "candidate"), required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--processes", type=int, choices=(1, 4, 8), required=True)
    parser.add_argument("--workload", choices=("idle-ledger", "mixed-ledger", "claim-race", "wiki"), required=True)
    parser.add_argument("--lifecycle", choices=("resident", "ephemeral"), required=True)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--operations", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=902)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-timeout-s", type=int, default=1800)
    return parser


def main() -> int:
    """Run the explicit benchmark CLI; reject invalid/incomplete evidence."""
    arguments = _parser().parse_args()
    try:
        config = BenchmarkConfig.model_validate(vars(arguments))
        report = run_benchmark(config)
        report_path = config.output_dir.expanduser().resolve() / (
            f"{config.arm}-{config.workload}-{config.processes}p-{config.lifecycle}.json"
        )
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 -- CLI must reject invalid/incomplete evidence with a nonzero status
        logger.exception("SQLite/ledger benchmark failed")
        return 2
    return 0 if report.complete else 1


# Explicit file loading gives the module arbitrary names in tests. A stable alias plus
# the driver directory on sys.path keeps multiprocessing's spawn pickling importable.
sys.modules.setdefault(_DRIVER_MODULE, sys.modules[__name__])
_worker_entry.__module__ = _DRIVER_MODULE
_verification_entry.__module__ = _DRIVER_MODULE


if __name__ == "__main__":
    raise SystemExit(main())
