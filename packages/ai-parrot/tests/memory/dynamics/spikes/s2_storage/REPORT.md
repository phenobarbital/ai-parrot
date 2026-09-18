# S2 (TASK-3383) — Concurrent Local Episodic Backend and Durable Review — Gate Report

## Commands

```
PARROT_SPIKE_FULL=1 python3 -m pytest packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/test_s2_harness.py::test_full_matrix_writes_report -q > artifacts/logs/feat-571-s2-<ts>.log 2>&1
```

## Environment

- **python**: 3.12.3
- **platform**: Linux-7.0.0-30-generic-x86_64-with-glibc2.39
- **cpu**: Intel(R) Core(TM) i7-9850H CPU @ 2.60GHz
- **cpu_count**: 12
- **kernel**: 7.0.0-30-generic
- **disk**: SSD/NVMe (non-rotational)
- **sqlite**: 3.45.1
- **aiosqlite**: 0.22.1
- **faiss**: 1.15.1

## Workload Results

| Workload | Arm | Lost writes | Converged | Notes |
|---|---|---|---|---|
| plain_writes_5000 | sqlite | 0 | True | store_ms: p50=0.320ms p95=4.529ms p99=18.660ms (n=5000); recall_similar_embed_ms: p50=0.017ms p95=0.023ms p99=0.027ms (n=160); recall_similar_db_ms: p50=85.433ms p95=126.385ms p99=143.927ms (n=160); search_text_embed_ms: p50=0.001ms p95=0.003ms p99=0.004ms (n=160); search_text_db_ms: p50=0.347ms p95=0.582ms p99=2.251ms (n=160); worker_errors=0 final_snapshot_corrupted=False |
| plain_writes_5000 | faiss | 1875 | False | store_ms: p50=0.009ms p95=0.017ms p99=0.024ms (n=3750); recall_similar_embed_ms: p50=0.004ms p95=0.008ms p99=0.008ms (n=120); recall_similar_db_ms: p50=0.108ms p95=0.211ms p99=0.314ms (n=120); worker_errors=2 final_snapshot_corrupted=False |
| plain_writes_10000 | sqlite | 0 | True | store_ms: p50=0.359ms p95=4.710ms p99=18.728ms (n=10000); recall_similar_embed_ms: p50=0.018ms p95=0.026ms p99=0.035ms (n=160); recall_similar_db_ms: p50=152.994ms p95=256.811ms p99=271.636ms (n=160); search_text_embed_ms: p50=0.001ms p95=0.003ms p99=0.004ms (n=160); search_text_db_ms: p50=0.358ms p95=0.603ms p99=3.201ms (n=160); worker_errors=0 final_snapshot_corrupted=False |
| plain_writes_10000 | faiss | 10000 | False | store_ms: p50=0.012ms p95=0.020ms p99=0.029ms (n=3750); recall_similar_embed_ms: p50=0.006ms p95=0.007ms p99=0.008ms (n=60); recall_similar_db_ms: p50=0.165ms p95=0.399ms p99=3.244ms (n=60); worker_errors=5 final_snapshot_corrupted=True |
| duplicate_apply_review | sqlite | 0 | True | apply_review_ms: p50=0.383ms p95=0.694ms p99=0.760ms (n=8); applied=1 rejected=7 |
| concurrent_same_memory_review | sqlite | 0 | True | apply_review_ms: p50=0.344ms p95=0.636ms p99=0.718ms (n=8); applied=1 rejected=7 |
| crash_before_log | sqlite | 0 | True | crash_at=before_log worker_crashed=True exitcode=137 applied_on_replay=1 |
| crash_after_log | sqlite | 0 | True | crash_at=after_log worker_crashed=True exitcode=137 applied_on_replay=1 |
| crash_after_state | sqlite | 0 | True | crash_at=after_state worker_crashed=True exitcode=137 applied_on_replay=1 |
| namespace_model_id_filter | sqlite | 0 | True | counts={'openai': 250, 'claude': 250} expected_each=250; worker_errors=0 final_snapshot_corrupted=False |
| namespace_model_id_filter | faiss | 0 | True | counts={'openai': 0, 'claude': 0} expected_each=250; worker_errors=1 final_snapshot_corrupted=False |
| feedback_import_batch | sqlite | 0 | True | first=300 second=300 ttl_deleted=0 ts_preserved=True |

## Non-Atomicity Evidence (documented, not re-run live) — spec §6 C5

- **PostgreSQL** `PgVectorBackend.update_metadata` (`core/memory/episodic/backends/pgvector.py:515`): `SET metadata = COALESCE(metadata,'{}') || $1::jsonb` — a shallow JSONB merge with no row version check; two concurrent `fsrs` replacements silently clobber each other (last `UPDATE` wins).
- **Redis** `RedisVectorBackend.update_metadata` (`core/memory/episodic/backends/redis_vector.py:575-587`): `hget(key, "metadata")` → merge in Python → `hset(key, "metadata", ...)` with no `WATCH`/`MULTI` — a classic read-modify-write race.
- **FAISS** `FAISSBackend.save`/`load` (`core/memory/episodic/backends/faiss.py:292-360`) rewrites the entire snapshot from this process's in-memory `_episodes` dict with plain `open(path, "w")` — no lock, no temp-file-then-rename. Measured this run under 8 concurrent processes: plain_writes_5000: 1875/5000 lost (38%), worker_errors=2, final_snapshot_corrupted=False; plain_writes_10000: 10000/10000 lost (100%), worker_errors=5, final_snapshot_corrupted=True. `worker_errors` counts workers that additionally raised `JSONDecodeError` reading a sibling's in-progress write; `final_snapshot_corrupted` (when true) means even the final on-disk snapshot failed to load at all — a stronger failure than a clean last-writer-wins overwrite race. Both outcomes were observed across repeated runs of this same harness; see `metrics.json` for this run's exact figures.

## Pass/Fail

- Zero lost writes across all sqlite-arm workloads: PASS (total lost=0)
- p95 recall_similar (DB-only) < 50ms @5k: FAIL (measured 126.385ms)
- Crash/replay convergence at before_log: PASS
- Crash/replay convergence at after_log: PASS
- Crash/replay convergence at after_state: PASS
- Feedback-import batch idempotent: PASS

## Limitations

- Crash-injection workloads use a single dedicated process (not the full 8-process pool) so the exact injection point is deterministic; contention scenarios (duplicate/concurrent review, plain writes, namespace filter) use the full pool per spec §3 row G2.
- No live PostgreSQL/Redis run — their non-atomicity is documented from source only (spec explicitly excludes a live run from S2).
- U4 review-log retention policy is an open owner decision (see amendment.md).
- `sqlite_prototype.search_similar` does the namespace-filtered SQL query first (correct per spec §2) but then scores candidates with a pure-Python cosine loop with no ANN index — recall_similar's DB-only p95 scales with the SHARED table's total row count (all 8 processes write into the same `s2-agent` namespace concurrently), not just one worker's share, which is why the p95 recall_similar check above FAILs at 5k/10k. This is a known prototype-scaling gap for the amendment to flag, not a correctness bug.

See `amendment.md` in this directory for the proposed spec freeze.
