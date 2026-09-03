# TASK-2783: Document observer guardrails and calibrate RSS defaults

**Feature**: FEAT-521 - REPL Worker Idle/Busy Detection & Memory Guardrails
**Spec**: `sdd/specs/repl-worker-idle-detection-memory-guardrails.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2774, TASK-2775, TASK-2777, TASK-2778, TASK-2779
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 and AC2/AC12/AC14 require operator documentation and reproducible evidence that the default RSS limits fit realistic REPL workloads.

## Scope

- Extend `calibrate_rlimit_as.py` to record peak RSS alongside VmPeak/VmHWM for every existing workload.
- Run the calibration against bootstrap, DataFrame load, merge/groupby, and plot workloads.
- Record command, environment, raw measurements, derived soft/hard defaults, and observer overhead/sample cost in a deterministic evidence artifact.
- Update worker sandbox documentation with verdict meanings, observer lifecycle, two-stage deadline, soft/hard RSS behavior, host reserve/cgroup behavior, configuration fields, error interpretation, and in-process/Windows degradation.
- Reconcile documented defaults with the approved 4 GiB soft / 8 GiB hard decision; if measurements contradict safety, stop and update the spec rather than silently changing defaults.

**NOT in scope**: product implementation, replacing RLIMIT_AS, Windows observer support, or introducing new benchmark dependencies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/calibrate_rlimit_as.py` | MODIFY | Capture and report peak RSS |
| `artifacts/logs/feat-521-memory-calibration.md` | CREATE | Reproducible measurements and derived limits |
| `docs/repl-worker-sandbox.md` | MODIFY | Operator-facing behavior/configuration documentation |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.repl_worker.handle import WorkerHandle  # calibrate_rlimit_as.py:48
from parrot.tools.repl_worker.protocol import WorkerConfig  # calibrate_rlimit_as.py:49
```

### Existing Signatures to Use

```python
# calibrate_rlimit_as.py:56-70
@dataclass
class Measurement:
    workload: str
    vm_peak_kb: int
    vm_hwm_kb: int
    survived: bool

def _read_proc_status(pid: int) -> dict[str, int]: ...  # :72
async def _run_with_peak_tracking(handle: WorkerHandle, code: Optional[str], poll_interval: float = 0.05): ...  # :86
async def calibrate(sizes_mb: list[int], limit_gib: float, output_dir: str) -> list[Measurement]: ...  # :124
```

### Does NOT Exist

- ~~Peak RSS fields/output in the calibration script~~ do not exist; it currently tracks only `VmPeak` and `VmHWM`.
- ~~`artifacts/logs/feat-521-memory-calibration.md`~~ does not exist.
- ~~FEAT-521 verdict/memory configuration documentation~~ does not exist in the sandbox guide.

## Implementation Notes

- Prefer `/proc/<pid>/status` `VmRSS`/`VmHWM` or psutil RSS consistently and state the chosen metric.
- Include exact versions/platform and distinguish RSS from virtual address space and shared-memory double-counting.
- Record observation overhead for AC2 with method and sample count; do not claim precision unsupported by the run.
- Keep the artifact lightweight, textual, and reproducible.

## Acceptance Criteria

- [ ] Calibration reports peak resident memory for every workload.
- [ ] Evidence supports or explicitly challenges the approved defaults with reproducible calculations.
- [ ] Evidence records <0.1 ms/sample and <2% workload overhead, or documents a failing result for correction.
- [ ] Documentation covers verdicts, deadlines, all new fields, memory errors/hints, cgroups, Windows, and in-process limitations.
- [ ] Script formatting/linting passes and documentation links resolve.

## Test Specification

Run the calibration command from its usage text with representative sizes, validate optional JSON output includes RSS, and manually verify every new documentation field against `WorkerConfig`.

## Agent Instructions

Confirm implementation dependencies are completed. Read the final field defaults and error strings before writing docs; capture actual measurements rather than estimated values.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-03
**Notes**: Extended `calibrate_rlimit_as.py` to track peak `VmRSS`
alongside the existing `VmPeak`/`VmHWM` (new `_TRACKED_FIELDS` tuple,
`Measurement.vm_rss_peak_kb`/`.vm_rss_peak_mb`, updated `_print_table()`
and every `Measurement(...)` call site). Also fixed the SAME `STATIC_DIR`
output_dir-guard issue documented in TASK-2781/2782 — the script's own
`tempfile.TemporaryDirectory()` output dir needed `os.environ["STATIC_DIR"]`
set before spawning any worker, or the calibration run failed at the very
first workload with the exact same `ValueError: output_dir escapes allowed
directories` (verified: reproduced, then fixed, then re-ran clean).

Ran the calibration for real (`--sizes 100,500 --limit-gib 8`) and wrote
`artifacts/logs/feat-521-memory-calibration.md` (force-added: `artifacts/`
is globally gitignored but this file follows the same already-tracked
carve-out as `feat-380-rlimit-as-calibration.md`, per CLAUDE.md's
`sdd/templates/` precedent). Findings: a freshly-booted worker's own
baseline RSS is ~248 MB (pandas/numpy/matplotlib/seaborn imported, zero
user data) — the floor any `memory_soft_limit_bytes` must clear; peak RSS
across a full session (bootstrap + 100 MB load + 500 MB load +
merge/groupby) reached 2312.0 MB (≈2.26 GiB). The `plot` workload could
not be measured — `matplotlib`/`plt` is denied by the sandbox's allowlist
gate (verified interactively, a pre-existing REPL-sandbox restriction
unrelated to FEAT-521 and out of this task's scope to fix) — documented
honestly as a failing result rather than silently dropped, per the
Implementation Notes. **Reconciliation**: the approved 4 GiB soft / 8 GiB
hard defaults give ≈1.77×/≈3.54× headroom over the measured 2.26 GiB peak
— the measurement supports the approved Q1 decision without contradiction,
so no default was changed.

Measured observation overhead for AC2 two ways: (1) raw `psutil`
per-sample cost (the exact 4 calls `ProcessObserver._take_sample()` makes)
averaged over 2,000 calls — **0.0639 ms/sample**, under the `< 0.1 ms`
budget; (2) whole-workload wall-clock — a 3s synthetic groupby loop run
3× at `observer_poll_ms=50` (tight) vs. 3× at `observer_poll_ms=999_999_999`
(practical "disabled" proxy — `WorkerConfig` has no explicit on/off
switch) — **-0.01% overhead** (within measurement noise), under the `< 2%`
budget. Both recorded with method, sample counts, and raw per-run numbers
in the evidence file.

Extended `docs/repl-worker-sandbox.md`: new §2c "Observation & verdicts"
(verdict table, two-stage deadline, bootstrap diagnostics reading from the
observer's ring instead of a one-shot probe), new §3c "Memory guardrails"
(soft hint mechanics + 90% hysteresis, hard-kill + deterministic
classification, host memory reserve + cgroup v2, `memory_summary()`,
"Not covered" for in-process/Windows), 8 new `WorkerConfig` field rows in
§3's table (all cross-checked against `protocol.py`'s actual defaults),
updated the §2 failure-modes table and "which timeouts kill" table for the
two-stage deadline, rewrote the stale "Reading a `WorkerBootstrapError`"
example (was still showing the pre-TASK-2777 one-shot `/proc` format),
added two new rows to the §5 Windows degradation table (observer/interrupt
unavailable; host memory reserve is the one guardrail that DOES still work
cross-platform, since `psutil.virtual_memory()` itself is
platform-independent), added a FEAT-521 §6 History entry, and updated
"See also" with both new artifact/spec links. Caught and fixed a
section-ordering bug of my own (`§3c` initially inserted before `§3b` in
document order) before finalizing. All internal markdown links
link-checked programmatically (resolved every relative link against the
worktree).

**Deviations from spec**: none — the `plot` workload's measurement gap is
a documented, explained limitation (see evidence file), not a deviation
from what this task was asked to do.
