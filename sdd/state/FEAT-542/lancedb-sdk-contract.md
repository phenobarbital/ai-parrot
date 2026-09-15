# FEAT-542 — LanceDB SDK contract evidence

**Gate task**: TASK-3057 · **Date**: 2026-09-10 · **Verdict**: pass

## Environment

| Item | Value |
|---|---|
| lancedb | 0.38.0 (exact pin, resolved and installed clean) |
| pyarrow | 25.0.1 |
| Python | 3.12.3 (workspace `>=3.11`; note: system default `python3` here is 3.14, which `uv sync` **cannot** use — `asyncdb==2.15.10` has no cp314 wheel. Use 3.12 or 3.11 explicitly, e.g. `uv venv --python /usr/bin/python3.12 .venv`.) |

All probes executed in an isolated worktree venv against the real, installed
`lancedb==0.38.0` package — no mocks. Commands and full pytest output logged at
`artifacts/logs/TASK-3057-lancedb.log`. Test module:
`packages/ai-parrot-embeddings/tests/test_lancedb_sdk_contract.py` (6/6 passed).

```bash
uv venv --python /usr/bin/python3.12 .venv --clear
source .venv/bin/activate
uv sync
uv pip install "lancedb==0.38.0"
uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_sdk_contract.py -v
```

## Verified API surface

| Operation | Exact call | Result columns | Notes |
|---|---|---|---|
| Connect | `await lancedb.connect_async(uri: str \| Path, *, read_consistency_interval: Optional[timedelta] = None, ...)` | — | Returns `lancedb.db.AsyncConnection`. `uri` is a plain local path; no scheme required or rejected by the SDK itself (backend must reject URI schemes itself per spec). |
| Create table | `await conn.create_table(name, schema=pa.Schema, mode=None\|"create"\|"overwrite", exist_ok=None)` | — | Returns `AsyncTable`. Schema-level Arrow `metadata` (bytes keys/values) round-trips exactly through close/reopen — use this for the versioned manifest (schema_version, dimension, metric, embedding identity). No first-row inference occurred; schema is authoritative. |
| Open existing table | `await conn.open_table(name)` | — | Idempotent; safe to call from a fresh connection or repeatedly from the same connection to refresh to the latest committed version (see concurrency contract below — this refresh is load-bearing, not cosmetic). |
| List tables | `await conn.table_names(*, start_after=None, limit=None)` | — | For `get_vector()`/default-table resolution. |
| Get schema | `await tbl.schema()` | — | Returns `pa.Schema`; `.metadata` is the persisted manifest dict (bytes→bytes). |
| Vector search | `await tbl.query().nearest_to(vector).distance_type("cosine").where(sql_str).limit(n).to_list()` | `_distance` | **Critical finding**: default `distance_type` (when `.distance_type(...)` is omitted) is **squared L2**, not cosine. The backend MUST call `.distance_type("cosine")` explicitly on every vector query or the raw `distance` alias silently becomes squared-L2. Verified direction: identical vectors → `0.0`; orthogonal → `1.0`; opposite → `2.0` (i.e. `1 - cos_sim`, range `[0, 2]`, lower is better — matches spec). |
| FTS index creation | `await tbl.create_index(column, config=lancedb.index.FTS())` (from `lancedb.index import FTS`) | — | This is the async, current API. The synchronous `create_fts_index` and legacy Tantivy config were NOT used or needed — confirms spec §7's risk note. |
| FTS search | `await tbl.query().nearest_to_text(query_str).limit(n).to_list()` | `_score` | BM25-derived, **higher is better**. A row added to the table *after* `create_index(...)` was called is visible in FTS results immediately, with no separate rebuild/maintenance step (spec §7 "FTS index freshness"). |
| Hybrid search | `await tbl.query().nearest_to(vector).distance_type("cosine").nearest_to_text(query_str).limit(n).to_list()` | `_relevance_score` only | **Confirms spec §8 Q6**: the default hybrid query (RRF fusion, no explicit reranker introspection call) exposes **only the fused `_relevance_score`** column. No `_distance` or `_score` (pre-fusion component) columns are present alongside it. → **v1 ships the single fused score**, per the spec's documented fallback. `lancedb.rerankers.RRFReranker` exists as an importable class but was not required to reproduce this behavior (it is the implicit default). |
| Prefilter | `.where("<sql-ish predicate>")` chained before `.limit(n)` on the same query builder | — | Applies identically whether the query is vector-only, FTS-only (via `.nearest_to_text`), or hybrid (both legs) — same builder, same `.where(...)` call site. Confirms "one shared compiler, one conjunctive predicate" is achievable with a single `.where()` call regardless of mode. |
| Upsert | `tbl.merge_insert(on="record_id").when_matched_update_all().when_not_matched_insert_all()` then `await <builder>.execute(rows)` | `MergeResult(version, num_updated_rows, num_inserted_rows, num_deleted_rows, num_attempts, num_rows)` | Both builder calls (`when_matched_update_all`, `when_not_matched_insert_all`) are required before `.execute()`; there is no implicit merge policy. |
| Delete | `await tbl.delete(where="<sql-ish predicate>")` | `DeleteResult(num_deleted_rows, version)` | Explicit count returned, including `0` for no matches (not separately probed here but the result shape supports it — count comes directly from the SDK, not computed by the backend). |

## Concurrency contract (consumed by TASK-3061)

**An in-process `asyncio.Lock` cannot prove or provide this — verified empirically
with two real `multiprocessing` (spawn) OS processes racing the same directory.**

### What was tried and failed

Two processes, each holding one long-lived `AsyncTable` handle obtained once at
startup, raced 10× `merge_insert(...).when_not_matched_insert_all()` calls each
with the **same new** `record_id` ("shared"), synchronized to start via a
`multiprocessing.Barrier`:

- **No file lock at all**: zero exceptions were raised by either process (no
  distinguishable conflict error surfaced), yet the final table contained **2**
  rows with `record_id = "shared"` — a duplicate logical ID. Each process's
  "not matched → insert" branch evaluated against its own stale in-process
  snapshot and both inserts committed independently.
- **File lock (`fcntl.flock`, `LOCK_EX`) around `execute()` only, reusing the
  cached `AsyncTable` handle obtained before the lock**: still produced **2**
  rows for the colliding ID. The lock serialized *execution* but each process's
  handle still held its pre-lock-acquisition view of "not matched", so the
  serialization did not, by itself, fix the staleness.

### What proved correct

- **File lock (`fcntl.flock`, `LOCK_EX`) around a critical section that (a)
  calls `conn.open_table(name)` to obtain a *fresh* handle bound to the latest
  committed version, THEN (b) builds and executes the `merge_insert`, released
  only after `execute()` returns** — produced exactly **1** row for the
  colliding ID, repeatably.

### Required coordinator interface (binds TASK-3061)

1. A single process-shared lock file inside the collection directory (e.g.
   `<uri>/.lancedb_mutation.lock`), acquired with `fcntl.flock(fd, LOCK_EX)`
   (POSIX; this repo targets Linux — no cross-platform fallback required per
   `.agent/CONTEXT.md`/`CLAUDE.md` environment).
2. The lock's critical section MUST reopen/refresh the table handle
   (`await conn.open_table(name)`) *inside* the lock, immediately before
   building the mutation — a cached handle from before lock acquisition is
   insufficient even though the lock alone prevents interleaved execution.
3. This file lock is **layered on top of, not a replacement for**, the
   existing in-process `asyncio.Lock` — the asyncio lock still serializes
   concurrent calls within one process/event loop (cheap, no syscall), while
   the file lock is the cross-process correctness mechanism.
4. No distinguishable "commit conflict" exception type was observed from the
   SDK for this race (`lancedb` exposes no `lancedb.errors` module in 0.38.0
   and no conflict-specific exception surfaced in any of these probes).
   Therefore: **do not architect TASK-3061 around catching a conflict
   exception and retrying — architect it around the file lock + reopen
   pattern above**, which is the verified sufficient mechanism. A bounded
   retry-with-jitter loop around the whole locked critical section is still
   worth keeping as defense-in-depth for genuine I/O-level errors (e.g. lock
   file contention timeouts, transient filesystem errors), but it is not the
   primary correctness mechanism the way the spec's draft language implied.
5. Reference implementation used to verify all of the above is inlined as
   `_mutate_worker` / `flock` in
   `packages/ai-parrot-embeddings/tests/test_lancedb_sdk_contract.py::test_two_process_concurrent_commit_behavior`
   — TASK-3061 should treat that function's locking pattern as the proven
   contract, not reinvent it from scratch.
6. Not separately re-probed here but follows from the same mechanism:
   concurrent `delete` and concurrent `create_index` (FTS rebuild) races
   should be guarded by the *same* lock file/critical-section discipline
   (reopen-then-mutate-under-lock) since both are mutations to the same
   table's committed version chain. TASK-3061 owns implementing and testing
   this generalization; this gate proves the mechanism on the merge-insert
   case, which is the highest-risk case (silent duplication, no exception).

## Offline profile (consumed by TASK-3068)

**Storage half — proven directly by this gate** (`test_offline_storage_path_denies_sockets`):
with `socket.socket.connect`/`connect_ex` monkeypatched to always raise `OSError`,
the full LanceDB local-directory path — `connect_async` → `create_table` →
`add` → `create_index(FTS())` → vector search → FTS search → hybrid search —
completed with zero network calls. LanceDB's local-directory mode makes no
outbound connection at all for any of these operations. This confirms storage
locality does not, by itself, need any offline *proof* beyond "don't pass a
remote URI" — the SDK simply never dials out for a local path.

**Agent half — NOT proven by this gate, scoped to TASK-3068**: a fully
offline *agent* additionally requires a locally provisioned embedding model
(for real ingest/vector/hybrid — FTS never needs one) and, if the agent path
also exercises an LLM, a local LLM server. This environment has **no cached
embedding model weights** (`~/.cache/huggingface/hub` contains only unrelated
guard/classifier models, no `sentence-transformers/all-mpnet-base-v2` or
similar); downloading ~420MB of weights is out of this 4-hour gate's budget
and is explicitly a **Non-Goal** for this spec to vendor/bundle. Recommended
profile for TASK-3068 (not executed here):

- **Embedding provider**: the existing HuggingFace local embedding extra
  (`parrot.embeddings.huggingface`, per `.agent/CONTEXT.md`) configured with
  a small locally-provisioned sentence-transformers checkpoint (the spec's
  own example uses `sentence-transformers/all-mpnet-base-v2`; a smaller
  model such as `all-MiniLM-L6-v2` would reduce provisioning cost and still
  demonstrates the same offline contract — TASK-3068's call, since it owns
  the provisioning step documentation).
- **LLM (if the offline agent profile exercises tool-calling, not just
  ingest/retrieval)**: `parrot.clients.local.LocalLLMClient` per the
  Codebase Contract (`packages/ai-parrot-client-local/src/parrot/clients/local/client.py:79`),
  pointed at an explicit local `base_url` (e.g. a locally-run
  Ollama/llama.cpp server) — never the default remote provider on
  `BasicAgent`.
- **Egress-denial mechanism**: the same `socket.socket` monkeypatch pattern
  used in this gate's `test_offline_storage_path_denies_sockets` generalizes
  directly — wrap the *whole* ingest/vector/FTS/hybrid exercise (including
  embedding-provider calls) in the patched-socket context, not just the
  LanceDB calls, per spec §9 S11 / I8.
- **No PostgreSQL container or remote endpoint** is required anywhere in
  this profile — confirmed by construction (LanceDB is a local directory;
  the recommended embedding/LLM providers above are both local-process).

## Spec §8 Q6 input

**Answered**: No. `AsyncTable.query().nearest_to(vec).distance_type("cosine").nearest_to_text(text).limit(n).to_list()`
exposes only `_relevance_score` (the fused RRF value) on each hybrid result
row — no `_distance` or `_score` component columns are present alongside it
in lancedb 0.38.0's default hybrid path. Per the spec's own fallback
language ("If undecided when TASK-3057 runs, ... v1 ships the single fused
score"), **§8 Q6 resolves to: single fused score is sufficient for v1**;
`LanceDBHybridHit` should NOT be widened to carry per-leg component scores,
since the SDK does not hand them to us without a materially different query
path (e.g. running two separate queries and re-fusing manually, which the
spec's "no cross-origin comparison of raw scores" language and "native RRF"
requirement both argue against).

## Blockers

None. The candidate pin (`lancedb==0.38.0`) resolves cleanly against the
existing `pyarrow>=25.0` core constraint and Python 3.11-3.13 (verified on
3.12.3; note the *system* default `python3` in this dev environment is 3.14
and cannot be used for `uv sync` — this is an environment note, not an SDK
blocker, since the workspace already declares `requires-python >=3.11` and
the resolver correctly rejects 3.14 for `asyncdb`). All required behaviors
in spec §2/§4/§7/§8 were proven directly against the real SDK: async local
connection, persisted schema metadata, native FTS index creation and
freshness, explicit vector+text hybrid with RRF fusion, one conjunctive
prefilter usable across vector/FTS/hybrid, merge-insert upsert semantics,
explicit delete counts, cross-process mutation correctness (via the file
lock + reopen coordinator), and a fully network-free local storage path.
