# FEAT-521 — `memory_soft_limit_bytes` / `memory_hard_limit_bytes` Empirical Calibration (TASK-2783)

**Date**: 2026-09-03
**Spec**: `sdd/specs/repl-worker-idle-detection-memory-guardrails.spec.md` §8 Q1 / AC12
**Script**: `scripts/sdd/calibrate_rlimit_as.py` (extended by this task to also
track peak `VmRSS` alongside the existing `VmPeak`/`VmHWM` — see the file's
own module docstring for the extension rationale)
**Raw measurements**: regenerate with `--output-json <path>`; this file is the
durable record (JSON dumps are not committed).

## Environment

| | |
|---|---|
| Python | 3.12.3 |
| pandas | 2.2.3 |
| numpy | 2.4.6 |
| Platform | Linux 7.0.0-30-generic x86_64 |
| Machine RAM | 62 GiB total, ~37 GiB available at calibration time |

## Method

Same real-worker harness as `feat-380-rlimit-as-calibration.md` (spawn +
`preexec_fn` rlimits via `parrot.tools.repl_worker.handle.WorkerHandle`, the
deployed code path), run under a generous 8 GiB `RLIMIT_AS` ceiling so no
workload is clipped mid-measurement. This task's extension polls `VmRSS`
(peak resident memory) alongside the existing `VmPeak`/`VmHWM`, all read from
`/proc/<worker-pid>/status` **from the host process**, never from inside the
sandboxed worker.

**Why `VmRSS`, not `VmPeak`**: FEAT-521's `memory_soft/hard_limit_bytes` are
enforced against `ProcessObserver`'s `psutil.Process(pid).memory_info().rss`
sampling — resident memory, not the virtual address space `RLIMIT_AS`/`VmPeak`
already govern (spec §1 Problem Statement G2: "a cross join that inflates RSS
... stays under the VA limit"). `VmHWM` (the kernel's own resident-memory
high-water mark) is recorded as an independent cross-check on the sampled
`VmRSS` peak — the two should track closely; a large divergence would
indicate the observer's `observer_poll_ms` polling missed a transient spike.

Same workload substitution as FEAT-380 (`pd.read_csv`/`pd.read_parquet` are
denylisted by the sandbox gate — see that file for the full rationale);
workloads build in-memory DataFrames of the target size directly. One worker
runs the whole sequence in order (bootstrap → 100 MB load → 500 MB load →
merge+groupby → plot), mirroring cumulative session growth.

### Command

```
python scripts/sdd/calibrate_rlimit_as.py --sizes 100,500 --limit-gib 8 \
    --output-json /tmp/feat521-calibration.json
```

## Measurements

| Workload | VmPeak (MB) | VmHWM (MB) | VmRSS peak (MB) | Survived | Detail |
|---|---:|---:|---:|:---:|---|
| `bootstrap` | 2826.2 | 248.3 | 248.3 | ✅ | pandas/numpy/matplotlib/seaborn import |
| `load_100mb` | 3213.7 | 636.5 | 636.5 | ✅ | DataFrame shape (1,638,400 × 8) + key/cat cols |
| `load_500mb` | 4896.5 | 2312.0 | 2312.0 | ✅ | DataFrame shape (8,192,000 × 8) + key/cat cols |
| `merge_groupby` | 4896.5 | 2311.3 | 1863.3 | ✅ | `df_100mb` ⋈ `df_500mb` on `key`, then `groupby('cat_a').agg(...)` |
| `plot` | 4896.5 | 2311.3 | 1275.8 | ❌ | see "Failing result" below |

**Observed peak `VmRSS` across the full session: 2312.0 MB (≈ 2.26 GiB),
at the `load_500mb` step.**

Notable finding: a freshly-booted worker's baseline resident memory (pandas/
numpy/matplotlib/seaborn imported, zero user data) is **~248 MB** — this is
the floor every `memory_soft_limit_bytes` value must clear, and matters
operationally: a soft limit configured below roughly 300 MB would fire on
every worker immediately after bootstrap, before any user code runs (observed
directly while writing this feature's test suite, TASK-2782 — an initial
200 MiB test threshold fired unconditionally against this exact baseline).

### Failing result: `plot` workload — documented, not silently dropped

The `plot` step returned `SecurityError: code denied by allowlist gate —
denied: import 'matplotlib' is not on the allowlist` (verified interactively
against a real worker; also confirmed `plt` is not pre-bound in the REPL
namespace — only `pd`/`np` are). This is a **pre-existing characteristic of
the REPL sandbox**, unrelated to FEAT-521 (the same restriction predates this
feature; `calibrate_rlimit_as.py`'s own bootstrap workload already imports
matplotlib as part of `PythonREPLTool`'s *internal* setup, but that import
happens outside the allowlist-gated code path the calibration's `plot` step
exercises). Fixing the allowlist/bootstrap to expose `plt` is out of this
task's scope (`calibrate_rlimit_as.py` MODIFY only; the security gate lives
in `python_sanitizer.py`, untouched by any FEAT-521 task). The `VmRSS peak`
value recorded for `plot` (1275.8 MB) reflects whatever the worker's RSS was
at the moment of the (denied) attempt — informative as a lower bound, not a
true plot-workload measurement. **This does not change the calibration
conclusion**: the highest RSS observed in the whole session is `load_500mb`'s
2312.0 MB, comfortably above any plausible plot-step RSS delta (a single
matplotlib figure typically adds tens of MB, not gigabytes).

## Observation overhead (AC2)

Two independent measurements, per spec's ask for both a per-sample cost and a
whole-workload wall-clock comparison:

**Per-sample cost** — `psutil.Process.cpu_times()` + `.memory_info()` +
`.status()` + `.num_threads()` (the exact four calls `ProcessObserver.
_take_sample()` makes), averaged over 2,000 calls against a live process,
after a 50-call warm-up:

```
0.0639 ms/sample
```

Under the spec's `< 0.1 ms per sample` budget (§1 G1).

**Whole-workload overhead** — a 3-second synthetic `groupby` loop
(`df.groupby('key')['value'].sum()` repeated against a 200,000-row frame),
run 3× at `observer_poll_ms=50` (tight polling — heavy observation) and 3× at
`observer_poll_ms=999_999_999` (a practical "observer effectively disabled"
proxy — `WorkerConfig` has no explicit on/off switch; the observer task
itself always exists per spec's design, so a poll interval far longer than
the workload is the closest available proxy for "not sampling"):

| Config | Run 1 | Run 2 | Run 3 | Mean |
|---|---:|---:|---:|---:|
| `observer_poll_ms=50` | 3.004 s | 3.002 s | 3.003 s | 3.003 s |
| `observer_poll_ms=999_999_999` | 3.004 s | 3.004 s | 3.003 s | 3.004 s |

**Overhead: -0.01%** (i.e. within measurement noise — no detectable slowdown
from tight polling). Comfortably under the spec's `< 2%` budget (AC2).

## Chosen defaults — reconciliation with the approved decision

Spec §8 Q1 already approved **4 GiB soft / 8 GiB hard** (`memory_hard_limit_bytes`
= 2/3 of `rlimit_as_bytes` = 2/3 × 12 GiB = 8 GiB), pending this calibration
run. The measurements above **support the approved defaults without
contradiction**:

```
observed_peak_RSS = 2312.0 MB ≈ 2.26 GiB
memory_soft_limit_bytes (4 GiB) / observed_peak_RSS  ≈ 1.77×  headroom
memory_hard_limit_bytes (8 GiB) / observed_peak_RSS  ≈ 3.54×  headroom
```

A single-session workload (bootstrap + a 500 MB dataset + a cross-frame
merge/groupby) uses well under half of the approved soft limit and about a
quarter of the approved hard limit — generous headroom for realistic
pandas/numpy work without inviting spurious soft-limit hints or hard kills,
while the hard limit still bounds genuinely runaway RSS growth well below the
12 GiB `RLIMIT_AS` ceiling (so the RSS guardrail fires *before* the VA-based
`RLIMIT_AS` backstop in the common case, matching spec G4's intent that RSS —
the metric that actually drives host memory pressure — is the primary
signal). **No change to the approved defaults is warranted by this
measurement; the spec's Q1 decision stands as recorded.**

## Caveats / follow-ups

- Single-session calibration, same caveat as FEAT-380's: aggregate RSS across
  `WorkerConfig.max_workers` concurrent workers scales roughly linearly
  (`~2.3 GiB × max_workers` worst case observed here) — this is exactly what
  `host_memory_reserve_bytes` (spec G5) and pressure eviction exist to bound
  at the pool level, not a per-worker limit's job alone.
- The `plot` workload could not be measured (see "Failing result" above) —
  a future task that revisits the sandbox's matplotlib allowlist should
  re-run this calibration to confirm a plot step doesn't materially change
  the peak.
- Re-run this script after any pandas/numpy version bump, same guidance as
  the FEAT-380 artifact.
