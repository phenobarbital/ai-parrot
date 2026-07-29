# TASK-1946: Empirical calibration of the RLIMIT_AS default

**Feature**: FEAT-380 — Sandbox Hardening — PythonREPLTool a worker persistente
**Spec**: `sdd/specs/sandbox-hardening.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1943
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 / AC15. The `RLIMIT_AS` default shipped in `WorkerConfig`
(~4 GiB) is a provisional, generous guess. The brainstorm decided the final
default must be backed by **measured** memory highwater of realistic pandas
workloads — not set by eye. `RLIMIT_AS` limits *virtual address space*, which
pandas/numpy/matplotlib over-reserve relative to RSS; an uncalibrated limit
produces spurious `MemoryError`s that surface to users as namespace-loss
kills.

---

## Scope

- Write a calibration script `scripts/sdd/calibrate_rlimit_as.py` (or
  `packages/ai-parrot/benchmarks/` if benchmarks conventions fit better —
  check first) that, for each workload below, spawns a real REPL worker with
  a candidate `rlimit_as_bytes` and reports peak VmPeak/VmRSS (from
  `/proc/self/status` inside the worker) and whether the workload survived:
  - bootstrap only (pandas+numpy+matplotlib+seaborn imports);
  - CSV/parquet load of a ~100 MB and a ~500 MB synthetic dataset;
  - a multi-key `merge` + `groupby.agg` over the loaded frames;
  - a seaborn/matplotlib plot saved via `save_current_plot`.
- Binary-search (or step through candidate limits) to find the smallest
  RLIMIT_AS at which every workload passes, then add safety margin (≥2×
  observed VmPeak) and round to a human-sane value.
- Save the evidence — raw measurements table + chosen default + rationale —
  to `artifacts/logs/feat-380-rlimit-as-calibration.md` (project rule:
  evidence goes to `artifacts/logs/`).
- Update `WorkerConfig.rlimit_as_bytes` default in
  `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` to the
  calibrated value, with a comment pointing at the evidence file.
- Add/adjust a test asserting the default matches the documented calibrated
  value (guards against drive-by edits).

**NOT in scope**: calibrating CPU/NOFILE limits (defaults stand); Windows
(no rlimits there — AC16, TASK-1960); changing deadline defaults.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/calibrate_rlimit_as.py` | CREATE | Calibration harness (POSIX-only, runs real workers) |
| `artifacts/logs/feat-380-rlimit-as-calibration.md` | CREATE | Evidence: measurements + chosen default + rationale |
| `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` | MODIFY | Calibrated `rlimit_as_bytes` default + evidence pointer |
| `packages/ai-parrot/tests/repl_worker/test_worker.py` | MODIFY | Assert default == calibrated value |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` HEAD on 2026-07-27.

### Verified Imports

```python
from parrot.tools.repl_worker.protocol import WorkerConfig   # TASK-1940
from parrot.tools.repl_worker.handle import WorkerHandle     # TASK-1941
import resource   # stdlib, POSIX-only — guard with sys.platform checks
```

### Existing Signatures to Use

```python
# spec §2 — the field being calibrated:
class WorkerConfig(BaseModel):
    rlimit_as_bytes: int = 4 * 1024**3   # provisional; THIS task fixes the default
```

```python
# Reading peak memory inside the worker (Linux):
# exec via the worker: open('/proc/self/status') → VmPeak / VmHWM lines.
# Portable-ish alternative: resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
# (KiB on Linux, bytes on macOS — normalize).
```

### Does NOT Exist

- ~~A benchmarks harness for the REPL worker~~ — check
  `packages/ai-parrot/benchmarks/`-style conventions before inventing one;
  if nothing fits, the standalone script under `scripts/sdd/` is the
  deliverable.
- ~~`RLIMIT_RSS` enforcement on Linux~~ — Linux does not enforce RLIMIT_RSS;
  that is why the spec uses RLIMIT_AS and why VmPeak (virtual) is the number
  that matters for calibration.
- ~~A CI job running this calibration~~ — it is a one-shot empirical task;
  the committed artifact is the evidence, the script makes it repeatable.

---

## Implementation Notes

### Key Constraints

- Run workloads **through the real worker path** (spawn + preexec rlimits),
  not in-process — the whole point is measuring the deployed configuration.
- Synthetic datasets: generate deterministically (seeded numpy) into
  `tmp`/scratch, sized by bytes not rows; do not commit datasets.
- Record environment in the evidence file: Python version, pandas/numpy/
  pyarrow versions, glibc/malloc notes if relevant, machine RAM.
- Conclusion format in the evidence file: observed VmPeak per workload →
  chosen default → margin rationale. AC15 audits exactly this.
- The script must be re-runnable (`--limits`, `--sizes` flags) so future
  dependency bumps can re-calibrate.

### References in Codebase

- `parrot/tools/repl_worker/` (TASK-1940–1943) — the machinery under test.
- `sdd/specs/sandbox-hardening.spec.md` §7 Known Risks, row 1.

---

## Acceptance Criteria

- [ ] Calibration script runs all four workload classes through real workers
      and prints a measurements table.
- [ ] Evidence file committed at
      `artifacts/logs/feat-380-rlimit-as-calibration.md` with measurements,
      chosen default, and rationale (AC15).
- [ ] `WorkerConfig.rlimit_as_bytes` default updated to the calibrated value
      with a comment referencing the evidence file.
- [ ] Test asserts the shipped default equals the documented value.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/repl_worker/ -v`
- [ ] No linting errors: `ruff check scripts/sdd/calibrate_rlimit_as.py packages/ai-parrot/src/parrot/tools/repl_worker/`

---

## Test Specification

```python
# packages/ai-parrot/tests/repl_worker/test_worker.py (addition)
def test_rlimit_as_default_is_calibrated():
    """Guard: the shipped default matches the calibrated, documented value.
    See artifacts/logs/feat-380-rlimit-as-calibration.md before changing."""
    from parrot.tools.repl_worker.protocol import WorkerConfig
    assert WorkerConfig().rlimit_as_bytes == CALIBRATED_VALUE  # set by this task
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1943 must be in `sdd/tasks/completed/`
   (Modules 2–5 operational)
3. **Verify the Codebase Contract** — confirm the worker/handle APIs as built
4. **Update status** in `sdd/tasks/index/sandbox-hardening.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1946-rlimit-as-calibration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-28
**Notes**:
- `scripts/sdd/calibrate_rlimit_as.py` (new): spawns a REAL worker
  (`WorkerHandle`, the deployed spawn+preexec-rlimits path) and measures
  `VmPeak`/`VmHWM` by polling `/proc/<worker-pid>/status` from the HOST
  process (never from inside the sandboxed worker, since `open()` is
  categorically denied there — reading the worker's own `/proc` entry from
  its parent sidesteps that cleanly and is arguably more honest, since it
  can't be perturbed by anything the workload itself does). Ran the
  bootstrap → 100 MB load → 500 MB load → merge+groupby → plot sequence on
  ONE worker (cumulative session growth, not per-workload cold starts), as
  real usage would.
- **Real measured result**: peak VmPeak = 5522.8 MB (~5.39 GiB) across the
  full session; bootstrap ALONE already reserves ~3.45 GiB of virtual
  address space (pandas/numpy/matplotlib/seaborn import — mostly
  OpenBLAS/thread-pool over-reservation; actual RSS for that step is only
  ~354 MB). Calibrated default = 2× margin over observed peak, rounded:
  **12 GiB** (`12 * 1024**3`), replacing the provisional 4 GiB. Full
  measurements, method, and rationale in
  `artifacts/logs/feat-380-rlimit-as-calibration.md` (force-added past the
  blanket `artifacts/` gitignore rule, matching the existing
  `feat-310-bench-*`/`feat-317-bench-*` precedent already tracked there).
- `protocol.py`: `WorkerConfig.rlimit_as_bytes` default updated to
  `12 * 1024**3` with a comment pointing at the evidence file.
- Added `test_rlimit_as_default_is_calibrated()` to `test_worker.py` (per
  the task's own Test Specification) AND fixed
  `test_protocol.py::TestValueCodec::test_worker_config_defaults_match_spec`
  (TASK-1940), which asserted the OLD 4 GiB value and would otherwise have
  failed after this change — both now assert `12 * 1024**3` with a comment
  pointing at the evidence file.
- Full regression: `pytest packages/ai-parrot/tests/repl_worker/
  packages/ai-parrot/tests/test_pythonrepl_security.py
  packages/ai-parrot/tests/test_pythonrepl_executor.py -q` → **113 passed**
  with the new 12 GiB default in effect (every `real_worker_config`-style
  fixture across the whole suite uses `WorkerConfig()`'s default or an
  explicit override, so this exercised the new default broadly, not just in
  the one new guard test). Verified zero orphaned worker processes and zero
  `/dev/shm` leaks after the run. `ruff check` on every touched file: clean.

**Deviations from spec**:
1. **Workload substitution — "CSV/parquet load" implemented as in-memory
   DataFrame construction, not literal file I/O.** `pd.read_csv`/
   `pd.read_parquet` are on the sandbox's categorical data-IO denylist
   (`python_sanitizer.py` `_PANDAS_IO_NAMES`) — deliberately unmodified
   (out of scope; that denylist is a security boundary, not a calibration
   inconvenience). Used seeded `numpy` random generation to construct
   DataFrames of the target byte size directly instead. This reproduces the
   dominant peak-memory driver (holding the materialized DataFrame) but not
   `read_csv`'s transient parsing/type-inference staging-buffer overhead —
   documented in the evidence file as a follow-up if the denylist is ever
   revisited for trusted tooling contexts.
2. **A bug in the calibration workload itself was found and fixed
   mid-task**: the first `merge_groupby` run used a merge key with only
   1,000 distinct values shared across both multi-million-row frames — a
   low-cardinality many-to-many join that combinatorially explodes to ~13.4
   BILLION merged rows (correctly triggered a `MemoryError`, but from a
   defective test workload, not a real usage pattern). Fixed by sizing the
   join key's cardinality to the larger frame's row count before
   re-running; documented in the evidence file's "Method" section so the
   mistake and fix are part of the audit trail (AC15 asks for measurements
   + rationale, and this is relevant rationale).
3. **Script location**: used `scripts/sdd/calibrate_rlimit_as.py` per the
   task's own fallback instruction — confirmed
   `packages/ai-parrot/benchmarks/` does not exist in this repo, so no
   existing benchmarks convention to fit into.
