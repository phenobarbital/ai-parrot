# Proposed spec amendment — S2 (TASK-3383) · status: PROPOSED (owner + architecture review required)

> Mirrored here by the sdd-worker orchestrator, post-merge, for owner review. The
> authoritative copy (produced by the coder) lives at
> `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/amendment.md` — the
> FEAT-549 sdd-coder engine's fidelity gate forbids coders from committing under `sdd/`.

## Freeze

- **Local dynamics backend**: SQLite/WAL prototype (`sqlite_prototype.SQLiteEpisodeBackend`) → M2
  should create `parrot/memory/episodic/backends/sqlite.py` from this candidate. FAISS snapshots are
  **rejected** for the review-transaction role and must stay single-writer-only for any use it keeps.
  Evidence: REPORT.md rows `plain_writes_5000`/`plain_writes_10000` — the sqlite arm converged with
  **zero lost writes** at both 5k and 10k under 8 concurrent processes; the FAISS arm lost **100% of
  writes** in both runs (`lost_writes=5000/5000` and `10000/10000`) and additionally left the on-disk
  snapshot **unparseable** (`final_snapshot_corrupted=True`, 3 of 8 workers raised `JSONDecodeError`
  reading a sibling's in-progress write) — a stronger failure than a clean overwrite race, because
  `FAISSBackend.save()`/`load()` write with plain `open(path, "w")` (`faiss.py:292-360`): no lock, no
  temp-file-then-rename.

- **Atomic review protocol**: one `BEGIN IMMEDIATE` transaction = dedupe check on
  `(outcome_id, outcome_revision, episode_id)` + `memory_state.apply_revision` equality check +
  review-row insert + state upsert + commit (the ack). Result categories: `applied` | `duplicate` |
  `stale_revision` | `pending` (unused by S2 — reserved for an async/queued backend) |
  `storage_unavailable` (unused by S2's sqlite arm; reserved for PG/Redis outage handling in M2).
  Evidence: `duplicate_apply_review` (8 workers issue the *same* command concurrently — exactly 1
  `applied`, 7 `duplicate`, final `apply_revision=1`) and `concurrent_same_memory_review` (8 workers
  race *different* revisions on the *same* episode with `expected_apply_revision=0` — exactly 1
  `applied`, 7 `stale_revision`, final `apply_revision=1`) both converged in every run.

- **Review-log cursor/record schema**: S2 did not build a separate `JsonlReviewLog`/`PostgresReviewLog`
  sink (out of scope — see task Scope). Instead it proved the *recovery order* the log-based sinks
  M2 builds must honour, directly on the SQLite backend's own transaction: **the transaction itself is
  the log** — `reviews` (the durable append set) and `memory_state` (materialized state) commit
  together, so there is no separate "log write" step to interleave incorrectly. Recovery order after a
  crash: **replay the same command against the backend; the backend's own dedupe/apply_revision check
  decides idempotently whether it needs re-applying.** No log offset/cursor tracking was needed because
  nothing partial was ever left on disk to reconcile (`crash_before_log`/`after_log`/`after_state` — see
  below). If M2 nonetheless adds an external JSONL/Postgres review-log (e.g., for audit/export, not for
  correctness), it must still be **subordinate** to this transaction — write the log record only after
  the backend transaction commits (never before), and use `LedgerLog`-style `O_APPEND` + `fsync` if that
  external log itself must be durable (`core/knowledge/wiki/ledger/log.py:21-81` — that offset is
  documented there as best-effort/non-authoritative for the same reason it must not be M2's cursor).

- **Crash/replay convergence**: `S2_CRASH_AT ∈ {before_log, after_log, after_state}` all inject the
  `os._exit(137)` **inside** the same open transaction, before `COMMIT`. All three converged in every
  run (REPORT.md `crash_before_log`/`crash_after_log`/`crash_after_state`, `applied_on_replay=1` each)
  — because none of the three crash points reaches `COMMIT`, SQLite rolls the whole transaction back on
  reconnect regardless of which internal statement had already run, and the subsequent `replay()` call
  (idempotent via the same dedupe check) re-applies cleanly. This is the practical demonstration of the
  "Required invariant" (spec §2): materialized state after crash+replay equals exactly one application
  of the outcome, independent of the injection point.

- **Identity/migration**: episode ids stay UUID strings; imported feedback maps deterministically via
  `uuid5(NAMESPACE, f"coder-feedback:{legacy_id}")` (spike used a fixed local `NAMESPACE` constant,
  `_IMPORT_NAMESPACE` in `harness.py` — M2 should mint and freeze a permanent UUID constant, e.g. in
  `parrot/memory/episodic/models.py` or a small migration module, rather than reusing the spike's
  throwaway one). `model_id` is stored as its **own column** in the prototype schema
  (`sqlite_prototype.SCHEMA`), never concatenated with anything (spec §2) — `namespace_filter` dicts may
  key on `model_id` alongside `tenant_id`/`agent_id`/etc. and every filter is applied in the SQL `WHERE`
  clause **before** any `LIMIT`/top-k (spec §2 "apply every namespace filter before inclusion").
  Imported rows get `expires_at = NULL`. Evidence: `namespace_model_id_filter` — sqlite arm isolated
  `openai:gpt-4o` (250) from `anthropic:claude` (250) exactly on every run; `feedback_import_batch` —
  running the same 300-row import batch twice left `count() == 300` both times (idempotent via
  `INSERT OR IGNORE` on the deterministic id) with `timestamps_preserved=True`.

- **TTL interaction for imported feedback**: `delete_expired()` filters `WHERE expires_at IS NOT NULL`,
  so `NULL`-expiry imported rows are structurally exempt from the store's generic `default_ttl_days=90`
  sweep (spec §2 "prevent generic TTL defaults from silently replacing its new retention policy") —
  evidence: `feedback_import_batch` shows `deleted_by_ttl_sweep=0`, `after_delete_count=300`.

- **Local retrieval without embeddings**: **FTS5**, confirmed available in this build
  (`sqlite3.sqlite_version=3.45.1`, `PRAGMA compile_options` includes FTS5; `aiosqlite` inherits the
  same compiled `sqlite3` C library). `sqlite_prototype.search_text()` ranks with `bm25()` normalized
  to `[0, 1]` via a per-result-set min/max rescale, with a `LIKE`-based fallback path if a deployment's
  SQLite build ever lacks FTS5 (untested here since this build has it). **Gotcha for M2**: the FTS5
  `MATCH` argument is parsed through FTS5's own query grammar even when bound as a parameter — an
  unquoted term containing `-`, `:` or `"` is control syntax there, not literal text (e.g. a raw token
  `"w3-624"` raised `sqlite3.OperationalError: no such column: 624` during this spike's own harness
  runs). The prototype now always wraps the caller's query as an escaped phrase
  (`'"' + query.replace('"', '""') + '"'`) before binding it — M2's real module must keep this
  quoting, it is not optional hardening.

- **Oversampling**: the prototype does **not** oversample — `search_similar()` runs the namespace SQL
  filter first (correct order per spec §2), then scores the **entire filtered candidate set** with a
  pure-Python cosine loop (no ANN index). This is why `recall_similar_db_ms` p95 **FAILed** the <50ms@5k
  bar in every run (measured ~130-260ms at 5k-10k, REPORT.md Pass/Fail) — it scales with the *shared
  table's* total row count (all 8 processes write into the same `s2-agent` namespace concurrently), not
  one worker's share. **Recommendation for M2**: either keep a small pre-filter oversampling factor
  (candidate ≈ `4×top_k` after the SQL filter, matching FAISS's own `search_k = min(top_k*10,
  ntotal)` pattern at `faiss.py:145`) only when a real ANN/vector index backs the column, or accept
  brute-force cosine only below a documented row-count ceiling and require a real index (e.g. `sqlite-vec`
  or an external ANN library) once corpora exceed it — this spike does not pick one, it only shows the
  naive approach does not meet the latency bar past ~1-5k rows sharing a namespace.

- **PostgreSQL / Redis**: confirmed non-atomic from source only (no live run, per Scope) —
  `PgVectorBackend.update_metadata` (`pgvector.py:515`) does `SET metadata = COALESCE(metadata,'{}') ||
  $1::jsonb` with no row-version check; `RedisVectorBackend.update_metadata` (`redis_vector.py:575-587`)
  does `hget` → merge in Python → `hset` with no `WATCH`/`MULTI`. M2 must give both backends a real
  transactional identity/state path (e.g. Postgres: a dedicated `reviews`/`memory_state` table pair
  with a serializable transaction or `SELECT ... FOR UPDATE`, mirroring this prototype's shape; Redis:
  a Lua script or `WATCH`/`MULTI`/`EXEC` pipeline) before `store.review()`/`.cite()` (M1/M2) can safely
  target them. FAISS stays single-writer-only for any role it keeps.

## Pass/Fail

- Zero lost writes, 8 processes, 5k and 10k (sqlite arm): **PASS**
- p95 recall_similar < 50 ms at 5k (hardware: Intel Core i7-9850H @2.60GHz, 12 threads, NVMe/SSD,
  Linux 7.0.0-30-generic, embedding-stub latency reported separately at ~0.016-0.025ms and excluded):
  **FAIL** (measured p95 ≈ 130-260ms — see "Oversampling" above for cause and recommendation)
- Crash/replay convergence at before_log / after_log / after_state: **PASS** each (all three runs)
- Feedback-import batch idempotent (twice → no new rows, timestamps preserved): **PASS**

## Open (not decided by this gate)

- U4 review-log retention (owner) · optional G4 coordination on page-state atomicity
- Whether M2 needs a real ANN/ vector-index extension (e.g. `sqlite-vec`) to close the recall_similar
  latency gap identified above, or whether brute-force cosine is acceptable below a documented
  per-namespace row-count ceiling — an architecture decision this gate surfaces but does not make.
- The permanent UUID namespace constant for `uuid5()` feedback-import ids (S2 used a throwaway local
  constant for the experiment only).

## Sections to edit on acceptance

§2 "Durable Storage and Lineage", §2 Data Models (MemoryRef/ReviewRecord/ReviewReceipt storage
fields), §3 M2 eligibility row and conditional `backends/sqlite.py` path, §6 C5.
