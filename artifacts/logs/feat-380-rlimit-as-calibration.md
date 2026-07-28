# FEAT-380 — `RLIMIT_AS` Empirical Calibration (TASK-1946)

**Date**: 2026-07-28
**Spec**: `sdd/specs/sandbox-hardening.spec.md` §3 Module 8 / AC15
**Script**: `scripts/sdd/calibrate_rlimit_as.py`
**Raw measurements**: see the two JSON dumps referenced below (not committed —
regenerate with `--output-json` if needed; this file is the durable record).

## Environment

| | |
|---|---|
| Python | 3.11.15 |
| pandas | 2.2.3 |
| numpy | 2.4.6 |
| matplotlib | 3.10.0 |
| pyarrow | 24.0.0 |
| Platform | Linux-7.0.0-28-generic-x86_64-with-glibc2.39 |
| CPUs | 12 |
| Machine RAM | 62 GiB total, 54 GiB available at calibration time |

## Method

`scripts/sdd/calibrate_rlimit_as.py` spawns a **real** REPL worker (the
deployed code path: `spawn` + `preexec_fn` rlimits via
`parrot.tools.repl_worker.handle.WorkerHandle`) under a generous 8 GiB
ceiling (so no workload is clipped mid-measurement) and polls
`VmPeak`/`VmHWM` from `/proc/<worker-pid>/status` **from the host process**
(never from inside the sandboxed worker — `/proc/self/status` reads
themselves would require `open()`, which the allowlist gate categorically
denies, and rightly so; measuring from the host sidesteps that entirely and
is more honest since it can't be perturbed by anything the workload does).

One worker runs the whole sequence below in order (bootstrap → 100 MB load →
500 MB load → merge+groupby → plot), mirroring a real session's cumulative
memory growth rather than measuring each workload cold in isolation.

### Workload substitution note

The spec calls for "CSV/parquet load of a ~100 MB and a ~500 MB synthetic
dataset". `pd.read_csv`/`pd.read_parquet` are on the sandbox's categorical
data-IO denylist (`python_sanitizer.py` `_PANDAS_IO_NAMES`) — deliberately
**not** modified for this task (out of scope; the denylist is a security
boundary, not a calibration inconvenience). Workloads instead construct an
in-memory DataFrame of the target size directly via seeded `numpy` random
generation (`np.random.default_rng(42)`, already-preloaded `pd`/`np`). The
dominant peak-memory driver either way is holding the *materialized*
DataFrame in memory, which this reproduces faithfully; only the transient
CSV-parsing staging-buffer overhead (`pd.read_csv` internally over-allocates
during type inference before settling into final dtypes) is not exercised.
This makes the calibration slightly less conservative than a literal CSV
load would be — a reason the chosen margin below is generous.

### Calibration bug found and fixed mid-run

The first run's `merge_groupby` workload used a merge key with only 1,000
distinct values across both frames — a **low-cardinality many-to-many
join**, which multiplies out combinatorially (1.64M rows × 8.19M rows /
1,000 keys ≈ 13.4 **billion** merged rows) and legitimately blew through
100 GiB. This was an artifact of the test workload's data design, not a
real usage pattern (no realistic multi-key merge joins a few-hundred-row
dimension against multi-million-row fact tables without an aggregation
step in between). Fixed by sizing the join key's cardinality to the larger
frame's own row count (~8.19M distinct keys), producing a realistic ~1-to-few
join. Re-run below reflects the corrected workload.

## Measurements (corrected run)

| Workload | VmPeak (MB) | VmHWM (MB) | Survived | Detail |
|---|---:|---:|:---:|---|
| `bootstrap` | 3452.5 | 354.4 | ✅ | pandas/numpy/matplotlib/seaborn import |
| `load_100mb` | 3840.0 | 742.5 | ✅ | DataFrame shape (1,638,400 × 8) + key/cat cols |
| `load_500mb` | 5522.8 | 2417.8 | ✅ | DataFrame shape (8,192,000 × 8) + key/cat cols |
| `merge_groupby` | 5522.8 | 2416.8 | ✅ | `df_100mb` ⋈ `df_500mb` on `key`, then `groupby('cat_a').agg(...)` |
| `plot` | 5522.8 | 2416.8 | ✅ | seaborn/matplotlib line plot, `save_current_plot()` |

**Observed peak VmPeak across the full session: 5522.8 MB (≈ 5.39 GiB).**

Notable finding: bootstrap alone (pandas/numpy/matplotlib/seaborn imports,
zero user data) already reserves **~3.45 GiB of *virtual* address space** —
typical of numpy/OpenBLAS thread-pool and matplotlib font-cache
over-reservation; actual resident memory (`VmHWM`) for the same step is only
~354 MB. This is precisely why the spec limits `RLIMIT_AS` (virtual) rather
than relying on RSS enforcement (Linux doesn't enforce `RLIMIT_RSS` at all)
— but it also means the calibrated floor must clear this ~3.45 GiB
bootstrap tax before any user workload even starts. The **previous
provisional default (4 GiB)** left only ~550 MB of headroom above the
bootstrap cost alone — confirmed separately during TASK-1940/1941/1942
development, where a worker under a 512 MiB–1 GiB `RLIMIT_AS` reliably
**crashed during `numpy.random`'s compiled-extension import**, before ever
reaching user code. 4 GiB was survivable only because it happened to clear
the bootstrap floor with little margin for real data.

## Chosen default

```
margin = 2 × observed_peak_VmPeak = 2 × 5522.8 MB ≈ 10.79 GiB
```

Rounded to a human-sane value: **12 GiB** (`12 * 1024**3` = 12,884,901,888
bytes).

This gives ≈2.17× headroom over the full measured session (bootstrap + a
500 MB dataset + a cross-frame merge/groupby + a plot) — enough for
realistic single-session pandas/numpy/matplotlib work without inviting
spurious `MemoryError`s that would surface to users as namespace-loss kills
(the exact failure mode this task exists to eliminate), while still bounding
a genuinely runaway allocation instead of leaving it unlimited.

## Caveats / follow-ups

- This is a **single-session** calibration. `WorkerConfig.max_workers`
  (default `max(4, cpu_count)`, capped 16) means worst-case *aggregate*
  virtual memory across concurrently active workers could reach
  `12 GiB × max_workers` — operators tuning `max_workers` up on
  memory-constrained hosts should account for this multiplicatively, not
  just per-worker. Not a new risk this task introduces (any per-worker
  limit multiplies by worker count), but worth calling out since 12 GiB is
  larger than the previous 4 GiB provisional value.
- The CSV/parquet-load substitution (see above) means the actual
  `pd.read_csv` staging-buffer overhead was not measured. If/when a future
  task revisits the data-IO denylist for trusted deployment tooling, this
  calibration should be re-run against literal file loads to confirm the
  12 GiB margin still holds.
- Re-run this script (`python scripts/sdd/calibrate_rlimit_as.py`) after any
  pandas/numpy/matplotlib/pyarrow version bump — the ~3.45 GiB bootstrap
  floor in particular is sensitive to BLAS/thread-pool defaults that have
  shifted across major numpy releases before.
