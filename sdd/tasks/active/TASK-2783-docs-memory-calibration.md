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

**Completed by**: unassigned
**Date**: pending
**Notes**: pending

**Deviations from spec**: none
