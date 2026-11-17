# TASK-5717: Reproducible SQLite and ledger benchmark driver

**Feature**: FEAT-902 - Wiki and ledger SQLite hardening
**Spec**: `sdd/specs/wiki-ledger-sqlite-hardening.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: No predecessor: creates only the benchmark driver and its contract tests, using existing LedgerService/SQLiteWikiStore APIs. New phase records are optional inputs and missing baseline phases remain unavailable, so driver preparation can run beside the cursor implementation.

## Context

Implement the driver half of spec M5. The approved matrix must be reproducible across source revisions without accidentally importing the candidate for both arms. Runtime implementation and actual full measurement are separate deliverables.

## Scope

- Create BenchmarkConfig/BenchmarkReport and the explicit CLI driver with all spec defaults and workloads.
- Implement isolated spawn workers, source/revision verification, raw-sample capture, counts, percentiles and invariant checks.
- Capture existing public SQLite connect/trace behavior on both arms and optional candidate timing logs without editing production code.
- Add fast driver tests on disposable databases; do not run or claim completion of the full measurement matrix here.

**NOT in scope**: No production metrics changes, persistent writer prototype, environment installation, live .parrot DB access or full evidence report.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/benchmarks/sqlite_ledger_hardening.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py` | CREATE | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified against base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` on 2026-11-16. Existing signatures and exact edit anchors were re-read; dependency-produced symbols are explicitly distinguished from existing ones. Recheck them after predecessor commits. If a required import or interface differs, stop and report drift instead of guessing.

### Verified Imports

```python
import argparse
import asyncio
import hashlib
import importlib.util
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
import aiosqlite
import pytest
from pydantic import BaseModel, Field
from parrot.knowledge.wiki.store import SQLiteWikiStore, SQLitePragmaPolicy, WikiPageRecord
from parrot.knowledge.wiki.ledger.service import LedgerService
```

Stdlib imports and installed pytest/aiosqlite/Pydantic were verified in the activated repository environment; no new dependency is authorized. Imports of new symbols belong to their named producer below and must be verified after it lands.

### Existing Signatures and Dependency Interfaces

- packages/ai-parrot/src/parrot/knowledge/wiki/store.py:606: WikiPageRecord has concept_id (required), title/category/summary/body and default origin/attrs.
- packages/ai-parrot/src/parrot/knowledge/wiki/store.py:2325: upsert_pages(pages: list[WikiPageRecord]) -> int; :2869 get_page(concept_id: str, include_body: bool=True) -> Optional[dict[str,Any]].
- packages/ai-parrot/src/parrot/knowledge/wiki/store.py:2938: search_fts(query: str, category: Optional[str]=None, limit: int=10) -> list[dict[str,Any]].
- packages/ai-parrot/src/parrot/knowledge/wiki/store.py:3074,3185: dump_pages() -> list[dict[str,Any]], sqlite_settings() -> dict[str,Any].
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:195,243,276,300,336,380: from_dir, open_issue(title,body,kind='bug',severity='minor',discovered_from='',about=None,actor='agent:sdd'), ready_work, list_issues, get_issue, claim(issue_id,actor).
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:306,396: sync(conn=None) -> int and rebuild() -> int; access through service.index.
- Source roots are packages/ai-parrot/src and its parrot namespace. Worker resolution MUST precede importing these modules; actual imported paths and SHA are evidence.
- aiosqlite dependency: packages/ai-parrot/pyproject.toml:209. Public connect/set_trace_callback are existing APIs; verify installed signature in driver work, without private queue/thread access.
- BenchmarkConfig, BenchmarkReport, run_benchmark and main are new, not importable on the authoring base.

### Does NOT Exist

- No benchmark module or persisted measurement report exists yet.
- No installed package named benchmarks is assumed: tests load the driver by its explicit file path.
- No functioning persistent_writer mode exists to benchmark. Both arms use connection-per-operation.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/benchmarks/sqlite_ledger_hardening.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLitePragmaPolicy",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.upsert_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.get_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.search_fts",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.dump_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.sqlite_settings",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.from_dir",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.open_issue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.ready_work",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.list_issues",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.get_issue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.claim",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.sync",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.rebuild"
  ]
}
```

## Implementation Notes

Keep the existing SQLite + aiosqlite stack, separate wiki/ledger databases and connection-per-operation lifecycle. Preserve asynchronous I/O and existing transaction ownership; offload blocking file work. No new dependency, schema migration or persistent connection is authorized. Tests use disposable state only.

Blueprint gaps below are bounded authoring instructions, not deliverable code. Complete all marked branches and assertions; never ship stubs. A CREATE block is a whole-file starting point and a MODIFY block attaches only to the quoted owner; preserve surrounding and predecessor changes.

## Implementation Blueprint

### Steps (in order)

1. Define validated config/report models and CLI — a frozen versioned schema makes baseline/candidate comparisons auditable.
2. Resolve source checkout inside fresh workers before any parrot import — shared editable installs must not substitute the wrong arm.
3. Implement all four workloads and both lifecycles — reuse of service objects is not connection reuse.
4. Wrap public connection/trace hooks and capture logs in memory — file logging must not contaminate timed intervals.
5. Validate counts and projection recovery — speed alone cannot establish correctness. Use small smoke fixtures for task tests.

### `packages/ai-parrot/tests/knowledge/wiki/benchmarks/sqlite_ledger_hardening.py` (CREATE)

```python
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

class BenchmarkConfig(BaseModel):
    """Validated arm and isolated source/workload parameters."""
    arm: Literal["baseline", "candidate"]
    revision: str
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

class BenchmarkReport(BaseModel):
    """Raw samples, metadata, outcomes and invariants for one matrix cell."""
    schema_version: Literal[1] = 1
    config: BenchmarkConfig
    environment: dict[str, Any]
    trials: list[dict[str, Any]]
    invariants: dict[str, bool]
    complete: bool

# FILL IN: typed nested report models/validation, spawn-safe workers and aggregation.
# In workers, establish source_root/packages/ai-parrot/src BEFORE parrot imports.
# Import verified aiosqlite, LedgerService, SQLiteWikiStore and WikiPageRecord there.
# Reject actual module paths or git revision mismatches; no silent fallback imports.
def run_benchmark(config: BenchmarkConfig) -> BenchmarkReport:
    """Spawn isolated workers and report measured samples plus correctness evidence."""
    # FILL IN: workloads/hooks, 10ms heartbeat, outcomes and recovery checks (AC2-AC5).
    raise NotImplementedError

def main() -> int:
    """Run the explicit benchmark CLI; reject invalid/incomplete evidence."""
    # FILL IN: spec CLI plus harness-only --source-root (defaults to current checkout).
    # Write reports after timing; no print, no installation or live database reuse.
    raise NotImplementedError

if __name__ == "__main__":
    raise SystemExit(main())
```

Keep parrot imports inside correctly rooted spawned workers. The harness-only source-root selector supplies revision isolation without changing application configuration.

### `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py` (CREATE)

```python
"""FEAT-902 benchmark schema, isolation and evidence contracts."""
from __future__ import annotations
import importlib.util
import json
import sys
from pathlib import Path
import pytest
from typing import Any

BENCHMARK_REPORT_SCHEMA = 1

def _load_driver() -> Any:
    """Load the adjacent driver explicitly; do not assume a benchmarks package."""
    # FILL IN: spec_from_file_location, register module in sys.modules, execute it.
    raise NotImplementedError

def test_benchmark_config_and_report_schema(tmp_path: Path) -> None:
    """Invalid inputs, incomplete cells and missing outcome fields are rejected."""
    # FILL IN: models and serializable report contract; no production DB fixture.
    raise NotImplementedError

def test_worker_rejects_wrong_source_revision(tmp_path: Path) -> None:
    """The imported checkout must match the requested arm revision."""
    # FILL IN: wrong-source/sha refusal and no fallback to the shared editable install.
    raise NotImplementedError

def test_smoke_workloads_and_counts(tmp_path: Path) -> None:
    """Small cells cover all workloads/lifecycles without running the full matrix."""
    # FILL IN: small operation counts, lifecycle invariants and unavailable baseline phases.
    raise NotImplementedError
# Later measurement task appends test_committed_measurement_evidence here.
# Preserve the unique BENCHMARK_REPORT_SCHEMA = 1 attachment anchor.
```

Tests validate driver behavior cheaply and reserve an explicit attachment point for evidence verification after real measurements exist.

### FILL IN Checklist

- [ ] `packages/ai-parrot/tests/knowledge/wiki/benchmarks/sqlite_ledger_hardening.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] Verify imports, types, exact attachment anchors and dependency outputs in the implementation checkout.
- [ ] Remove every unfinished scaffold from delivered files; inspect the scoped diff and run all mandatory gates.

## Acceptance Criteria

- [ ] AC1: Required config/report signatures and CLI flags exist with spec defaults; JSON uses schema_version=1.
- [ ] AC2: Spawned workers verify source paths and git SHA before workloads; no environment or live DB modifications.
- [ ] AC3: Four workloads, both lifecycles, fixed seed/warmup and separate DBs are supported; ephemeral excludes interpreter startup.
- [ ] AC4: Count connect calls and traced BEGIN/COMMIT; report p50/p95/p99, outcomes, loop lag, optional timings and WAL growth without treating unavailable metrics as zero.
- [ ] AC5: Final sync/rebuild comparison, accepted-event preservation, claim owner uniqueness, integrity and worker cleanup are evaluated.
- [ ] AC6: Small smoke tests pass; no full-matrix result or persistent-reuse benefit is fabricated.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py -q`

## Test Specification

Keep tests small and deterministic; validate malformed config/report, wrong source root/revision, small 1-process workloads and a minimal spawned claim race. Driver raw-sample schema must preserve unsuccessful attempts and test unavailable phase metrics distinctly from numeric zero.

Run the task-specific commands above. The feature-wide regression contract is cached in the per-spec index and runs at its configured SDD gates; do not replace these focused checks with bare pytest or a directory scan.

## Agent Instructions

1. Start with `$sdd-start TASK-5717`; the implementation workflow provisions the feature worktree. Do not implement on dev.
2. Verify predecessors are done in `sdd/tasks/index/wiki-ledger-sqlite-hardening.json` and recheck this task's contracts.
3. Implement only the declared files, preserve other agents' changes, and complete every acceptance gate. Store execution logs under `artifacts/logs/`.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; do not hand-edit them.
