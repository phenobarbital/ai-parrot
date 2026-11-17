# TASK-5718: Measure baseline versus candidate and decide persistent-connection follow-up

**Feature**: FEAT-902 - Wiki and ledger SQLite hardening
**Spec**: `sdd/specs/wiki-ledger-sqlite-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5716, TASK-5717
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Depends on TASK-5716 for candidate phase instrumentation and TASK-5717 for the executable benchmark/report schema and test file. Exclusive: owns the measurement host I/O/CPU window and isolated baseline snapshot during comparable trials.

## Context

Deliver the explicitly requested standalone measurement task (spec M5, AC9/AC10). Running real comparable matrices and deciding the next scope are required; passing driver unit tests alone does not complete this task.

## Scope

- Run the approved baseline/candidate matrix on an isolated host window; preserve all failed trials and raw samples.
- Write report.md, manifest.json and persistent-connections-followup.md from actual results.
- Add an evidence-validation test to the dependency-created benchmark test module.
- Keep the current production access mode; recommend defer, an isolated reuse spike, or a production-reuse proposal.

**NOT in scope**: No connection-reuse implementation, tuning pragmas, deleting live DBs, installing dependencies, fabricated performance thresholds or discarded failed trials.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-902/benchmarks/report.md` | CREATE | Measured evidence artifact |
| `sdd/state/FEAT-902/benchmarks/manifest.json` | CREATE | Measured evidence artifact |
| `sdd/state/FEAT-902/benchmarks/persistent-connections-followup.md` | CREATE | Measured evidence artifact |
| `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py` | MODIFY | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified against base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` on 2026-11-16. Existing signatures and exact edit anchors were re-read; dependency-produced symbols are explicitly distinguished from existing ones. Recheck them after predecessor commits. If a required import or interface differs, stop and report drift instead of guessing.

### Verified Imports

```python
import hashlib
import json
from pathlib import Path
import pytest
```

Stdlib imports and installed pytest/aiosqlite/Pydantic were verified in the activated repository environment; no new dependency is authorized. Imports of new symbols belong to their named producer below and must be verified after it lands.

### Existing Signatures and Dependency Interfaces

- TASK-5717 creates packages/ai-parrot/tests/knowledge/wiki/benchmarks/sqlite_ledger_hardening.py with BenchmarkConfig, BenchmarkReport, run_benchmark(config) and main(); consume its versioned schema and source-root selector.
- TASK-5717 creates packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py; its declared unique attachment anchor is BENCHMARK_REPORT_SCHEMA = 1. This is a dependency-output contract, NOT an existing-base verification. Re-read and grep -c -F after TASK-5717 lands; expected count is 1 before appending the evidence test.
- TASK-5716 supplies candidate logs: event wiki.sqlite.timing, phases in spec §2, and wiki.ledger.stale_read. Baseline phase hooks are unavailable.
- Baseline source SHA: e5f3f7534876f9b4f56ad1cedc7b4e56176ee568. Actual implementation/candidate SHA must be recorded after dependencies land.
- packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1361,1366,1853: persistent_writer/_writer_conn are unused by _write at the baseline; do not claim toggling the flag measures reuse.
- Standard library imports were verified installed during authoring; report artifacts are new plain JSON/Markdown.

### Does NOT Exist

- No report, manifest or follow-up result exists before this task runs.
- The dependency test anchor does not exist on the original base; never pretend its occurrence count was measured there.
- No reuse speedup may be inferred from service-object reuse or connection count alone.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "sdd/state/FEAT-902/benchmarks/report.md",
      "action": "CREATE"
    },
    {
      "path": "sdd/state/FEAT-902/benchmarks/manifest.json",
      "action": "CREATE"
    },
    {
      "path": "sdd/state/FEAT-902/benchmarks/persistent-connections-followup.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._write"
  ]
}
```

## Implementation Notes

Keep the existing SQLite + aiosqlite stack, separate wiki/ledger databases and connection-per-operation lifecycle. Preserve asynchronous I/O and existing transaction ownership; offload blocking file work. No new dependency, schema migration or persistent connection is authorized. Tests use disposable state only.

Blueprint gaps below are bounded authoring instructions, not deliverable code. Complete all marked branches and assertions; never ship stubs. A CREATE block is a whole-file starting point and a MODIFY block attaches only to the quoted owner; preserve surrounding and predecessor changes.

## Implementation Blueprint

### Steps (in order)

1. Provision a clean isolated baseline snapshot and record candidate SHA/import paths — arm contamination invalidates every result.
2. Run 1/4/8 processes × resident/ephemeral × four workloads × baseline/candidate with 3 trials, 100 warmups, 1000 measured operations per worker and seed 902 — matching parameters are required for comparison.
3. Alternate arm order and repeat a DEBUG-off pass — distinguish runtime gains from instrumentation overhead.
4. Validate all candidate invariants, compare normalized final/rebuilt projections and preserve failed baseline outcomes — correctness is a gate, not a filter.
5. Write compact committed reports/manifests with raw-file hashes and add the evidence-validation test — close only with complete auditable data.

### `sdd/state/FEAT-902/benchmarks/report.md` (CREATE)

````markdown
# FEAT-902 SQLite and ledger measurements

## Revisions and environment
FILL IN from observed baseline/candidate SHAs, module paths, versions, host, storage,
filesystem, effective pragmas, fixture scale and dirty-state checks.

## Reproduction
FILL IN exact commands and baseline snapshot setup; raw logs/samples live under
artifacts/logs/FEAT-902/sqlite-hardening/ and are referenced by manifest hashes.

## Matrix and results
FILL IN every arm/process/workload/lifecycle cell and three trials. Record operation
sample counts, p50/p95/p99, throughput, BUSY/errors, connection/BEGIN counts,
loop lag, WAL before/after and optional candidate-only phase distributions.

## Correctness and failures
FILL IN all invariant outcomes and failures, including unsuccessful baseline trials.
Never omit a failed trial or treat an unavailable baseline phase as zero.

## Interpretation and limitations
FILL IN ratios, variation and DEBUG-on/off comparison. Inclusive phases overlap;
no summing them as independent costs or unsupported production SLA claims.
````

The report is completed from measured evidence, not prefilled optimistic conclusions.

### `sdd/state/FEAT-902/benchmarks/manifest.json` (CREATE)

```json
{
  "schema_version": 1,
  "feature_id": "FEAT-902",
  "baseline_revision": "e5f3f7534876f9b4f56ad1cedc7b4e56176ee568",
  "candidate_revision": null,
  "complete": false,
  "commands": [],
  "cells": [],
  "raw_files": [],
  "candidate_invariants": {},
  "instrumentation_overhead": {}
}
```

FILL IN: replace null/empty evidence with actual complete data. Each raw_files entry has path, sha256 and size_bytes; cells carry arm/processes/workload/lifecycle/trial/settings/outcomes and hashes, with DEBUG-on/off runs distinguished. Candidate completion must not be true on invariant failure.

### `sdd/state/FEAT-902/benchmarks/persistent-connections-followup.md` (CREATE)

````markdown
# Persistent-connection follow-up for FEAT-902

## Disposition
FILL IN exactly one: defer / run isolated reuse spike / propose production reuse.

## Evidence
FILL IN measured connection/setup attribution versus writer wait, fsync and replay,
variation, regressions and limitations. Connection counts alone are insufficient.

## Next scope
FILL IN per-file/per-process ownership, bounded whole-transaction admission,
commit acknowledgments, cancellation/failed transaction cleanup, read connections,
shutdown/drain and cross-process limitations when proposing reuse.
If deferring, identify missing evidence and the conditions for reconsideration.

## Acceptance evidence for the next step
FILL IN concrete comparisons and correctness checks; do not implement reuse here.
````

Noise or dominant fsync/lock wait can justify defer. The deliverable is a decision backed by evidence, not a mandated optimization.

### `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py` (MODIFY)

Dependency-output anchor, supplied by **TASK-5717**; absent on the authoring base. After the dependency lands, verify exact count **1** with `grep -c -F`; stop and refresh this contract if absent/ambiguous:

```text
BENCHMARK_REPORT_SCHEMA = 1
```

```python
# Append after existing tests, preserving TASK-5717's unique schema anchor.
# Add stdlib hashlib/json imports only if absent; pytest and Path already exist.
def test_committed_measurement_evidence() -> None:
    """Committed FEAT-902 evidence covers the complete approved matrix."""
    root = Path(__file__).resolve().parents[5]
    evidence = root / "sdd/state/FEAT-902/benchmarks"
    # FILL IN: parse manifest, verify schema/SHAs, matrix axes and default parameters.
    # Require complete=true, passing candidate invariants, all trial outcomes,
    # report.md and a follow-up disposition backed by named result cells.
    # Validate raw file hashes when files are locally present; fresh checkouts
    # validate the committed hash manifest without inventing raw-byte verification.
    # During this task's execution ALL raw files must exist and hashes must match.
    raise NotImplementedError
```

The test prevents closing with partial/placeholder evidence. It is added only after measurement so the driver's earlier tests do not require nonexistent reports.

### FILL IN Checklist

- [ ] `sdd/state/FEAT-902/benchmarks/report.md` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `sdd/state/FEAT-902/benchmarks/manifest.json` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `sdd/state/FEAT-902/benchmarks/persistent-connections-followup.md` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] Verify imports, types, exact attachment anchors and dependency outputs in the implementation checkout.
- [ ] Remove every unfinished scaffold from delivered files; inspect the scoped diff and run all mandatory gates.

## Acceptance Criteria

- [ ] AC1: All 24 cells per arm (1/4/8 × 2 lifecycles × 4 workloads) run with three trials and approved defaults; missing cells/timeouts cannot count as complete.
- [ ] AC2: Both source revisions/import paths, environment, pragmas, raw samples/logs and exact commands are recorded, with DEBUG-off overhead evidence.
- [ ] AC3: No candidate invariant failures, lost accepted events, duplicate claim owners, integrity errors or stranded workers; baseline failures remain visible.
- [ ] AC4: Compact report/manifest/follow-up are committed; all raw files exist and their hashes are verified at task completion.
- [ ] AC5: Follow-up makes exactly one evidence-backed disposition, separates costs and limitations, and introduces no production reuse.
- [ ] AC6: The evidence-validation pytest node passes; a small smoke run alone cannot satisfy AC1-AC5.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py::test_committed_measurement_evidence -q`

## Test Specification

The evidence test verifies committed structural completeness. Actual matrix execution and raw hash verification are additional mandatory acceptance gates, outside the machine-selected pytest command. Preserve reports so the test can run in a fresh checkout without locally retained raw files.

Run the task-specific commands above. The feature-wide regression contract is cached in the per-spec index and runs at its configured SDD gates; do not replace these focused checks with bare pytest or a directory scan.

## Measurement Execution Gate

Activate the repository environment first; use it read-only. For each arm and source-root,
run the driver for each process count, workload and lifecycle using the exact spec defaults.
Example cell (replace only the observed candidate SHA and isolated source root):

`python packages/ai-parrot/tests/knowledge/wiki/benchmarks/sqlite_ledger_hardening.py --arm baseline --revision e5f3f7534876f9b4f56ad1cedc7b4e56176ee568 --source-root /tmp/feat902-baseline --processes 1 --workload idle-ledger --lifecycle resident --trials 3 --warmup 100 --operations 1000 --seed 902 --output-dir artifacts/logs/FEAT-902/sqlite-hardening/baseline-1-idle-ledger-resident --run-timeout-s 1800`

The example is one cell, not the full gate. Alternate baseline/candidate trial order;
run DEBUG-on and separate DEBUG-off passes as specified. Manage the isolated baseline
snapshot without resetting the main checkout, modifying the shared venv, or deleting
unowned files. Use a clean existing snapshot or create an isolated baseline worktree at
the recorded SHA. Stop/label incomplete evidence on timeout; never silently lower the
approved sample sizes. No strict speedup is required, but all candidate invariants are.

## Agent Instructions

1. Start with `$sdd-start TASK-5718`; the implementation workflow provisions the feature worktree. Do not implement on dev.
2. Verify predecessors are done in `sdd/tasks/index/wiki-ledger-sqlite-hardening.json` and recheck this task's contracts.
3. Implement only the declared files, preserve other agents' changes, and complete every acceptance gate. Store execution logs under `artifacts/logs/`.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; do not hand-edit them.

## Completion Note (BLOCKED — not closed)

- Contract conflict resolved: `test_smoke_workloads_and_counts` asserted `phase_timings_ms["connection_open"] is None`, which predates TASK-5716. It now asserts candidate sources report non-negative `connection_open` samples while unavailable phases stay `None` (never zero). All 11 tests in `test_sqlite_benchmark_contract.py` pass; no test was dropped.
- Anchor `BENCHMARK_REPORT_SCHEMA = 1` is unique (commit 8bf548039a).
- Measurement NOT performed: the baseline arm needs an isolated snapshot at e5f3f7534876f9b4f56ad1cedc7b4e56176ee568, but `parrot sdd worktree baseline create` fails inside the worker sandbox (`.git/worktrees` is read-only), and improvising one (git archive) is prohibited. The full 48-cell matrix (+ DEBUG-off pass) also requires an isolated host window.
- Required next step (host operator): create the baseline worktree and run the matrix per "Measurement Execution Gate", then write report.md / manifest.json / persistent-connections-followup.md and add `test_committed_measurement_evidence`. TASK-5719 stays blocked on this.
