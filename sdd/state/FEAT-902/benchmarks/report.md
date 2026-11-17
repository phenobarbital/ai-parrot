# FEAT-902 SQLite and ledger measurements

**Status: matrix complete (48/48 cells, all invariants true). Evidence is INCOMPLETE: the DEBUG-off overhead pass was not run because the driver cannot disable DEBUG capture (see Limitations).**

## Revisions and environment
- Baseline: `e5f3f7534876f9b4f56ad1cedc7b4e56176ee568`, isolated detached worktree `.parrot/worktrees/baseline-e5f3f7534876`, clean.
- Candidate: `01bbdd2ff060b529fb6450dcdcede7c261974295` (feature branch head at measurement time), `.parrot/worktrees/feat-FEAT-902-wiki-ledger-sqlite-hardening`, clean.
- Python 3.12.3, SQLite 3.45.1, aiosqlite 0.22.1, Linux 7.0.0-31-generic, 12 CPUs. Fixture scale 1000.
- Host was not exclusive: a concurrent feat-904 `sdd-worker` session was running (low CPU during the window). The 8-process cells also load the host by design. Treat absolute numbers as indicative; the arm comparison is the signal.

## Reproduction
- Driver: `packages/ai-parrot/tests/knowledge/wiki/benchmarks/sqlite_ledger_hardening.py`, one invocation per cell with `--trials 3 --warmup 100 --operations 1000 --seed 902 --run-timeout-s 1800`.
- Arm order alternates per cell. Matrix runner exit codes: `artifacts/logs/FEAT-902/sqlite-hardening/matrix-exit-codes.tsv` (48 rows, all exit 0).
- Per-cell reports: `artifacts/logs/FEAT-902/sqlite-hardening/<arm>-<p>p-<workload>-<lifecycle>/*.json`; logs `<cell>.log`. Hashes and sizes are in `manifest.json`.
- Raw working DBs (294 `.db`/`-wal` files, ~1.8 GB) are regenerated per trial and are not committed.
- The 8-process candidate timing probe is kept under `timing-probe-candidate-8-mixed-ephemeral/` but is not evidence (it was a pre-run timing check).

## Matrix and results
Latency is the median over three trials of successful-operation latency. Throughput shows the median and the trial range. Numbers are per the table columns below; "rejected" are claim operations that lost to another owner (see Correctness).

| procs | lifecycle | workload | arm | p50 ms | p95 ms | p99 ms | throughput ops/s (median, range) | loop lag p99 ms | conn opens/trial | BEGINs/trial | fast-path/trial | rejected/trial |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ephemeral | claim-race | baseline | 62.93 | 95.19 | 125.67 | 15.9 (15.6–15.9) | 1.97 | 2000 | 1000 | n/a | 0 |
| 1 | ephemeral | claim-race | candidate | 56.61 | 89.39 | 118.84 | 17.0 (16.7–17.4) | 1.99 | 1000 | 1000 | n/a | 0 |
| 1 | ephemeral | idle-ledger | baseline | 11.77 | 16.20 | 21.31 | 91.3 (46.8–95.1) | 10.21 | 3000 | 1000 | n/a | 0 |
| 1 | ephemeral | idle-ledger | candidate | 19.61 | 51.17 | 78.38 | 43.8 (26.3–69.8) | 18.65 | 3000 | 0 | 1000 | 0 |
| 1 | ephemeral | mixed-ledger | baseline | 25.39 | 60.81 | 81.89 | 34.8 (25.1–51.4) | 21.97 | 2800 | 1000 | n/a | 0 |
| 1 | ephemeral | mixed-ledger | candidate | 18.63 | 70.87 | 89.13 | 36.0 (28.2–50.2) | 23.63 | 2800 | 200 | 800 | 0 |
| 1 | ephemeral | wiki | baseline | 24.79 | 39.46 | 69.02 | 42.1 (38.4–43.9) | 1.60 | 1000 | 200 | n/a | 0 |
| 1 | ephemeral | wiki | candidate | 17.86 | 34.67 | 37.71 | 55.0 (40.0–85.3) | 1.20 | 1000 | 200 | n/a | 0 |
| 1 | resident | claim-race | baseline | 51.03 | 67.14 | 79.23 | 19.4 (14.4–22.1) | 1.81 | 2000 | 1000 | n/a | 0 |
| 1 | resident | claim-race | candidate | 29.25 | 34.17 | 41.48 | 37.1 (23.0–39.0) | 1.25 | 1000 | 1000 | n/a | 0 |
| 1 | resident | idle-ledger | baseline | 12.25 | 20.61 | 50.54 | 81.0 (75.1–105.2) | 14.84 | 3000 | 1000 | n/a | 0 |
| 1 | resident | idle-ledger | candidate | 11.55 | 19.68 | 30.90 | 90.6 (72.7–100.8) | 11.85 | 3000 | 0 | 1000 | 0 |
| 1 | resident | mixed-ledger | baseline | 12.92 | 29.03 | 63.28 | 68.8 (68.4–72.8) | 21.39 | 2800 | 1000 | n/a | 0 |
| 1 | resident | mixed-ledger | candidate | 15.68 | 40.35 | 69.91 | 54.1 (49.9–88.0) | 23.16 | 2800 | 200 | 800 | 0 |
| 1 | resident | wiki | baseline | 16.70 | 28.56 | 30.65 | 58.7 (49.4–71.1) | 1.82 | 1000 | 200 | n/a | 0 |
| 1 | resident | wiki | candidate | 15.47 | 28.14 | 31.27 | 57.7 (57.7–70.4) | 1.62 | 1000 | 200 | n/a | 0 |
| 4 | ephemeral | claim-race | baseline | 49.55 | 53.76 | 60.27 | 33.4 (32.6–36.9) | 2.19 | 8000 | 4000 | n/a | 3000 |
| 4 | ephemeral | claim-race | candidate | 17.00 | 44.98 | 48.51 | 60.3 (54.4–61.9) | 2.06 | 4000 | 4000 | n/a | 3000 |
| 4 | ephemeral | idle-ledger | baseline | 13.19 | 23.03 | 37.64 | 295.0 (284.9–296.9) | 11.01 | 12000 | 4000 | n/a | 0 |
| 4 | ephemeral | idle-ledger | candidate | 13.56 | 19.25 | 28.05 | 311.1 (306.1–312.6) | 13.00 | 12000 | 0 | 4000 | 0 |
| 4 | ephemeral | mixed-ledger | baseline | 15.63 | 33.61 | 52.33 | 238.4 (230.4–241.9) | 18.28 | 11200 | 4000 | n/a | 0 |
| 4 | ephemeral | mixed-ledger | candidate | 16.79 | 33.53 | 43.88 | 222.2 (206.8–236.8) | 21.84 | 11200 | 1464 | 2535 | 0 |
| 4 | ephemeral | wiki | baseline | 3.75 | 7.61 | 10.38 | 847.9 (840.0–855.2) | 1.04 | 4000 | 800 | n/a | 0 |
| 4 | ephemeral | wiki | candidate | 4.02 | 14.61 | 38.29 | 610.5 (603.5–829.0) | 1.33 | 4000 | 800 | n/a | 0 |
| 4 | resident | claim-race | baseline | 38.18 | 48.85 | 70.75 | 35.3 (35.1–36.3) | 2.20 | 8000 | 4000 | n/a | 3000 |
| 4 | resident | claim-race | candidate | 31.72 | 41.78 | 64.02 | 38.5 (37.6–38.6) | 2.22 | 4000 | 4000 | n/a | 3000 |
| 4 | resident | idle-ledger | baseline | 11.19 | 22.42 | 48.60 | 328.2 (296.7–329.6) | 11.29 | 12000 | 4000 | n/a | 0 |
| 4 | resident | idle-ledger | candidate | 11.69 | 17.88 | 26.59 | 352.5 (323.9–363.2) | 13.32 | 12000 | 0 | 4000 | 0 |
| 4 | resident | mixed-ledger | baseline | 13.93 | 31.96 | 54.70 | 257.8 (224.7–259.9) | 17.83 | 11200 | 4000 | n/a | 0 |
| 4 | resident | mixed-ledger | candidate | 20.07 | 63.12 | 109.03 | 154.0 (149.9–216.9) | 20.29 | 11206 | 1607 | 2392 | 0 |
| 4 | resident | wiki | baseline | 3.18 | 10.70 | 22.00 | 796.3 (488.0–1528.5) | 1.21 | 4000 | 800 | n/a | 0 |
| 4 | resident | wiki | candidate | 1.85 | 5.16 | 8.14 | 1384.2 (1374.4–1405.3) | 1.06 | 4000 | 800 | n/a | 0 |
| 8 | ephemeral | claim-race | baseline | 12.65 | 37.69 | 41.23 | 45.6 (45.5–50.6) | 2.17 | 16000 | 8000 | n/a | 7000 |
| 8 | ephemeral | claim-race | candidate | 17.94 | 40.96 | 42.38 | 47.5 (38.3–51.4) | 2.20 | 8000 | 8000 | n/a | 7000 |
| 8 | ephemeral | idle-ledger | baseline | 15.82 | 60.44 | 146.35 | 338.8 (337.3–346.3) | 10.37 | 24000 | 8000 | n/a | 0 |
| 8 | ephemeral | idle-ledger | candidate | 19.68 | 23.93 | 36.47 | 456.1 (455.8–461.4) | 17.70 | 24000 | 0 | 8000 | 0 |
| 8 | ephemeral | mixed-ledger | baseline | 22.19 | 61.24 | 136.05 | 281.0 (278.6–283.4) | 31.27 | 22400 | 8000 | n/a | 0 |
| 8 | ephemeral | mixed-ledger | candidate | 26.09 | 54.87 | 68.87 | 294.1 (289.4–294.2) | 39.60 | 22403 | 3223 | 4776 | 0 |
| 8 | ephemeral | wiki | baseline | 6.19 | 13.23 | 15.36 | 1019.9 (998.9–1020.3) | 1.49 | 8000 | 1600 | n/a | 0 |
| 8 | ephemeral | wiki | candidate | 6.97 | 14.67 | 16.73 | 903.9 (889.7–972.1) | 1.49 | 8000 | 1600 | n/a | 0 |
| 8 | resident | claim-race | baseline | 33.11 | 35.56 | 46.13 | 30.2 (29.9–33.3) | 2.21 | 16000 | 8000 | n/a | 7000 |
| 8 | resident | claim-race | candidate | 25.83 | 27.42 | 33.84 | 41.3 (40.5–47.7) | 2.21 | 8000 | 8000 | n/a | 7000 |
| 8 | resident | idle-ledger | baseline | 15.02 | 66.35 | 191.38 | 331.8 (319.2–342.6) | 12.50 | 24000 | 8000 | n/a | 0 |
| 8 | resident | idle-ledger | candidate | 19.38 | 25.40 | 38.50 | 471.8 (456.2–490.0) | 20.45 | 24000 | 0 | 8000 | 0 |
| 8 | resident | mixed-ledger | baseline | 22.78 | 67.52 | 160.23 | 260.3 (256.6–269.2) | 33.82 | 22400 | 8000 | n/a | 0 |
| 8 | resident | mixed-ledger | candidate | 21.63 | 49.27 | 63.85 | 348.6 (334.8–351.5) | 39.00 | 22401 | 3395 | 4605 | 0 |
| 8 | resident | wiki | baseline | 3.15 | 9.21 | 11.02 | 1760.8 (1677.9–1837.9) | 1.10 | 8000 | 1600 | n/a | 0 |
| 8 | resident | wiki | candidate | 3.39 | 9.39 | 11.35 | 1627.3 (1579.8–1807.3) | 1.27 | 8000 | 1600 | n/a | 0 |

Baseline phase timings are unavailable (`null`) for every phase, never zero. Candidate phase distributions (p50 / p95 ms, all trials, resident lifecycle):

| cell | begin_wait | connection_open | connection_setup | sync_probe | log_fsync | commit |
|---|---|---|---|---|---|---|
| 1p mixed-ledger | 0.05 / 0.13 | 0.35 / 0.85 | 1.83 / 5.29 | 5.24 / 13.27 | 1.28 / 2.51 | 1.42 / 2.88 |
| 4p mixed-ledger | 3.19 / 18.93 | 0.26 / 0.55 | 0.78 / 9.49 | 3.31 / 21.98 | 4.07 / 14.66 | 0.08 / 6.46 |
| 8p mixed-ledger | 1.16 / 18.39 | 0.31 / 0.45 | 0.96 / 1.98 | 3.81 / 7.19 | 1.12 / 1.72 | 0.09 / 1.61 |
| 4p claim-race | 34.29 / 79.59 | 1.52 / 1.76 | 5.70 / 8.43 | n/a | 4.29 / 4.91 | 0.46 / 5.87 |
| 8p claim-race | 54.29 / 179.84 | 1.53 / 1.99 | 5.85 / 7.52 | n/a | 1.49 / 1.64 | 0.43 / 2.76 |

Phases are inclusive and overlap (for example `connection_setup` contains `connection_open`), so they must not be summed.

## Correctness and failures
- All 48 cells: `complete=true`, three trials each, every invariant true for both arms (`worker_cleanup`, `worker_count`, `operation_count`, `projection_matches_rebuild`, `accepted_events_preserved`, `claim_owner_unique`, `integrity_ok`), plus `all_trials_complete`, `source_revision_consistent`, `separate_databases`.
- Errors and BUSY outcomes: zero in every trial of every cell, both arms.
- Claim-race cells report `rejected` operations (4p: 3000 per trial; 8p: 7000 per trial) on both arms. These are claims that lost to the single owner, which is the expected outcome of the workload; `claim_owner_unique` holds in every trial. They are preserved, not filtered.
- No failed trials and no timeouts. No cell was dropped or re-run.

## Interpretation and limitations
- No uniform speedup. The candidate is faster in some cells and slower in others, and trial-to-trial variance is large in several cells (for example baseline 4p resident wiki ranges 488–1528 ops/s), so many differences fall inside the noise.
- Where the candidate wins clearly:
  - Idle-ledger 8p: throughput 472 vs 332 ops/s (resident) and 456 vs 339 (ephemeral); the candidate eliminates BEGIN attempts (0 vs 8000 per trial) through the sync fast path.
  - Claim-race ephemeral 4p: p50 17.0 vs 49.6 ms and connection opens halved (4000 vs 8000 per trial).
  - Mixed-ledger ephemeral 8p: p99 68.9 vs 136.0 ms.
- Where the candidate is worse or unclear:
  - Idle-ledger 1p ephemeral: throughput 43.8 vs 91.3 ops/s and p50 19.6 vs 11.8 ms.
  - Mixed-ledger resident 4p: p99 109.0 vs 54.7 ms, and loop lag rises (20.3 vs 17.8 ms at 4p; 39.0 vs 33.8 ms at 8p resident).
- Connection-count reductions appear only in claim-race cells. Per the spec, connection counts alone do not show reuse benefit.
- Writer wait dominates contention: under claim-race, `begin_wait` p50 is 34–54 ms while `connection_setup` is 6 ms, so connection setup is a small share of the cost.
- **DEBUG-off overhead: not measured.** The driver always attaches its own DEBUG handler and sets `parrot.knowledge.wiki` to DEBUG. There is no switch to disable it, so the instrumentation overhead cannot be estimated from this matrix. The manifest records this as a `missing` item and sets `complete: false`.
- The concurrent feat-904 worker and the 8-process cells load the host; results are indicative only.
