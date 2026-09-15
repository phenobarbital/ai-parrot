# Task Memory — Phase 0 Integration Map (FEAT-538 / TASK-2970)

**Status**: Phase 0 investigation deliverable. Nothing here is production
code, and nothing here authorizes an API that does not yet exist.

**Pinned base**: `dev` at `0b4920b2f` (worktree
`feat-538-workingmemory-toolkit`). The spec's own anchor commit is
`4f066afcb`; the core source tree exercised below is unchanged between the
two.

**Runnable companion**:
`packages/ai-parrot/tests/tools/working_memory/task_memory/bench_snapshot_costs.py`
re-derives everything in §1 and §3 from the live source and re-measures §2.
Raw output: `artifacts/logs/task-2970-tm-integration-spike.log`.

> **Delivery A is not durable.** Everything Delivery A ships is in-process
> continuity only. Nothing in this document may be read as a durability
> promise before Delivery B lands PostgreSQL, blob write-through and crash
> reconciliation.

---

## 1. Integration inventory

### 1.1 There is no universal hook

The single most important Phase 0 finding, and the one the rest of the
feature has to be designed around: **there is no chokepoint** for catalog
writes, for bot rendering, or for turn construction. Every one of these is
a multi-site integration.

| Surface | Distinct call sites | Consequence for FEAT-538 |
|---|---|---|
| Catalog writes | 9 in `working_memory/tool.py` (7 × `put`, 2 × `put_generic`) | The awaited path must be introduced *inside the toolkit*, not by wrapping one function. |
| Catalog reads outside the toolkit | 3 in `bots/flows/plan/node.py` (`_read_key`, `_has_key`, `_keys_for` via `getattr(..., "_catalog")`) | The plan node bypasses the toolkit entirely and reads the private attribute. Any versioning must keep `catalog.get(key)` working. |
| `render_context_history` | 5 (`bots/base.py` ×3, `bots/data.py`, `bots/voice.py`) | Stage 2 injection cannot be bolted onto one entry point; it belongs inside `render_context_history` itself. |
| `ConversationTurn.from_ai_message` | 4 (`bots/base.py` ×3, `bots/data.py`) | The canonical-invocation handoff must live in the classmethod (or in an argument to it), not per call site. |

### 1.2 Catalog write/read sites

`packages/ai-parrot/src/parrot/tools/working_memory/tool.py`

| Line | Call | Path |
|---|---|---|
| 202 | `self._catalog.put(...)` | `store()` — DataFrame registration |
| 231 | `self._catalog.put_generic(...)` | `store_result()` — generic registration; **the tee lands here** |
| 423, 435 | `self._catalog.put(...)` | import-from-tool paths |
| 477, 532, 590, 638 | `self._catalog.put(...)` | operate / compute / derived-result paths |
| 757 | `self._catalog.put_generic(...)` | temporary/summary result path |

All nine are **synchronous** against a plain `dict` (`internals.py:469`).
`put` (`:473`), `put_generic` (`:499`), `get` (`:542`) and `drop` (`:548`)
take no lock and perform no I/O. The spec's rule — a synchronous write
against an *enabled persistent* catalog must fail explicitly rather than
fire-and-forget — therefore has to be enforced at these nine sites plus the
external readers below, since nothing else sits between them and the dict.

External readers (must keep working unchanged):

- `bots/flows/plan/node.py:363` `_read_artifact` → `:392` `_read_key` →
  `catalog.get(key)`; `_has_key` (`:407`) uses `key in catalog`.
- `working_memory/tests.py:70-71` seeds the catalog directly (legacy
  fixture; enabled-mode fixtures must use the awaited path instead).

### 1.3 `ToolManager.execute_tool` — dispatch anatomy

`packages/ai-parrot/src/parrot/tools/manager.py:1514`

```
execute_tool(tool_name, parameters, permission_context=None, *, return_tool_result=False)
│
├─ 1563  tool_name not in self._tools ──────────────► ToolResult(status="not_found")   [executed=False]
├─ 1568  full_result_lock = None
└─ try:
   ├─ 1584  TOOL_CALL guardrail pipeline ───────────► ToolResult(status="forbidden")   [executed=False]
   ├─ 1624  if isinstance(tool, ToolDefinition):
   │        ├─ 1630  ConfirmationGuard ─────────────► ToolResult(...)                  [executed=False]
   │        ├─ 1671  Layer-2 resolver ──────────────► ToolResult(status="forbidden")   [executed=False]
   │        ├─ 1704  if return_tool_result:  ← FEAT-536 envelope branch
   │        │        1718/1720  await tool.function(...) / to_thread(...)              [EXECUTED]
   │        │        1745/1753  return envelope (copy; never mutates the tool-owned one)
   │        └─ 1757  await tool.function(...) / to_thread(...)                         [EXECUTED]
   ├─ 1764  elif isinstance(tool, AbstractTool):
   │        ├─ 1776  tool._get_full_result_lock() ── acquired here, released in finally
   │        ├─ 1793  GrantGuard ───────────────────► ToolResult(...)                   [executed=False]
   │        ├─ 1821  ConfirmationGuard ────────────► ToolResult(...)                   [executed=False]
   │        ├─ 1862  resolver / broker wiring
   │        ├─ 1870  await tool.execute(**exec_kwargs)                                 [EXECUTED]
   │        ├─ 1872  if return_tool_result: _finish_abstract_tool_full_result(...) @1876
   │        ├─ 1889  status == "forbidden" → return;  status == "error" → tee + raise ValueError
   │        └─ 1945  compression stage → return out
   └─ 1956  except AuthorizationRequired ──────────► ToolResult(status="authorization_required")
      1974  except Exception → log + re-raise
      1977  finally: release full_result_lock
```

Design consequences pinned here:

1. **`tool_started` must be persisted after the last guard and immediately
   before the marked `[EXECUTED]` lines** — four of them, not one.
2. Every `[executed=False]` exit is an **unsuccessful dispatch outcome**,
   not a failed tool body. Guard order must not move; the observer wraps,
   it does not reorder.
3. The `status == "error"` branch already calls the tee and then **raises
   `ValueError`**. An error-as-data result therefore reaches the caller as
   an exception in default mode and as an envelope in full-result mode —
   the result adapter must handle both without re-deriving success from
   text.
4. `CancelledError` propagates through the bare `except Exception` (it is a
   `BaseException`) and only touches the `finally`. Cancellation recording
   must be shielded and bounded there.
5. `clone()` (`:2439`) shares tool *instances* while giving the clone
   its own mutable manager state — so any per-manager observer registry is
   per-clone, but a per-tool-instance one would leak across clones. Attach
   the observer to the manager.

### 1.4 Plan receipt boundary

`packages/ai-parrot/src/parrot/bots/flows/plan/node.py`

- `_call_with_retry` (`:414`) dispatches at `:431` inside a `for attempt in
  range(1, policy.max_attempts + 1)` loop. **Each iteration is one physical
  attempt**; the node's aggregate result is not an extra execution.
- `_store` (`:347`) awaits `working_memory.store_result` at `:350`
  **after** `_call_with_retry` has already returned. By then the manager
  has reset its per-invocation context, so `producer_call_id` is lost
  unless `PlanToolNode` explicitly retains the attempt receipt across that
  boundary. This is the concrete FEAT-538 correlation hazard.
- `_store` already writes `metadata={"plan_node", "tool", "index"}` —
  plan run/node/item correlation has a place to live without a new
  parameter on the tool schema.
- The factory closure that injects the live `ToolManager` +
  `WorkingMemoryToolkit` (`make_tool_node_factory`) starts at `:530`.

### 1.5 Compression tee

`packages/ai-parrot/src/parrot/tools/compression/tee.py`

- `store()` (`:95`) awaits `store_result` (`:119`), and on **any**
  exception logs a warning and returns `None` (`:127`). A `None` return is
  the *only* signal that persistence failed — it must become
  `tracking_degraded`, never silent evidence.
- `_retain()` (`:133`) evicts past `max_retained` via `drop_stored` (`:140`).
  `drop_stored` removes the **live alias only**; pinned snapshots must
  survive it.
- Keys are `__tee__:{tool}:{turn_id}:{counter}` with a per-tool counter
  added precisely because `put_generic` overwrites silently.

### 1.6 Bot turn lifetime

| Site | File:line | Role |
|---|---|---|
| Render (ordinary) | `bots/base.py:348`, `:717`, `:1147`, `:1788` | 4 render calls in the base bot alone |
| Render (data) | `bots/data.py:1362` | |
| Render (voice/streaming) | `bots/voice.py:795` | discards the `CompactionResult` (`_compaction_result`) |
| Turn construction | `bots/base.py:541`, `:770`, `:1377`; `bots/data.py:2125` | |
| Implementation | `bots/abstract.py:1742` | `render_context_history` |
| Stage 2 signal | `memory/compaction/compact.py:325` → `CompactionResult.stage2_needed` | the render-time flag |
| Stage 2 event | `bots/abstract.py:1985` | fires only on persisted `False→True` **after** save — too late to inject |
| Stable identity | `bots/abstract.py:1864` | `memory_key_id` = explicit chatbot id, else `self.name` |

`ConversationTurn.from_ai_message` (`memory/abstract.py:178`) builds
`ToolInvocation`s with the list comprehension at `:229`. The enabled path
must **replace** that list, not append to it.

### 1.7 Redis association

`memory/redis.py:65` `_get_key` → `{prefix}[:{chatbot}]:{user}:{session}`.
`_store_turn` (`:261`) does `hget("metadata")` → mutate →
`hset(mapping=...)` (`:290-297`) — a **non-atomic read-modify-write**. A concurrent
task-association write and a compaction-state write will lose one of the
two. A task-only lock is insufficient because the compaction writer does
not take it. Non-hash mode (`:301`) is worse: full `get_history` →
mutate → `update_history`.

### 1.8 REPL worker transport

`tools/repl_worker/transport.py:55` `encode_dataframe` catches
`(ArrowInvalid, ArrowNotImplementedError, ArrowTypeError)` at `:74` and
**silently produces `pickle.dumps(df)`** at `:81` (with a warning).
`EncodedDataFrame` carries `format ∈ {"arrow","pickle"}`, `shm_name`,
`size`, `payload`. Strict task-evidence mode must reject before the
pickle payload is created, and must not change the legacy default.

---

## 2. Snapshot and fingerprint measurements

### 2.1 Method

Deterministic fixtures (seeded `numpy.random.default_rng`), row counts
**calibrated by measurement** rather than a hard-coded bytes-per-row guess.
Snapshot = `df.copy(deep=True)` / canonical byte encoding. Fingerprint =
BLAKE2b-8 over canonical content (shape + ordered columns + dtypes + index
metadata + `pd.util.hash_pandas_object` row hashes for frames; canonical
sorted-key UTF-8 bytes for JSON). Timings are wall clock; `peak_MiB` is
`tracemalloc` peak (Python allocations only — it does **not** see numpy
buffer allocation, which is why the numeric copy shows a small peak).

### 2.2 Environment

| | |
|---|---|
| Python | 3.12.3 |
| Platform | `Linux-7.0.0-31-generic-x86_64-with-glibc2.39` |
| pandas / numpy | 2.2.3 / 2.4.6 |
| Command | `uv run python packages/ai-parrot/tests/tools/working_memory/task_memory/bench_snapshot_costs.py` |

### 2.3 Results

| Payload | Target | Actual bytes | Snapshot s | Peak MiB | Fingerprint s |
|---|---:|---:|---:|---:|---:|
| numeric/string DF | 8 MiB | 8,387,492 | 0.001 | 4.0 | 0.390 |
| numeric/string DF | 64 MiB | 67,099,582 | 0.006 | 32.3 | 2.301 |
| numeric/string DF | 256 MiB | 268,398,217 | 0.030 | 129.3 | **9.458** |
| nested-object DF | 8 MiB | 8,388,132 | 0.001 | 0.6 | 3.949 |
| nested-object DF | 64 MiB | 67,104,532 | 0.004 | 5.1 | 31.191 |
| nested-object DF | 256 MiB | 268,417,732 | 0.015 | 20.5 | **122.741** |
| JSON/text (stdlib `json`) | 8 MiB | 9,017,605 | 1.993 | 40.6 | 0.012 |
| JSON/text (stdlib `json`) | 64 MiB | 72,919,121 | 16.647 | 328.9 | 0.113 |
| JSON/text (stdlib `json`) | 256 MiB | 294,957,391 | **65.097** | 1331.2 | 0.417 |
| JSON/text (`orjson`) | 8 MiB | 9,017,605 | 0.050 | 31.7 | 0.013 |
| JSON/text (`orjson`) | 64 MiB | 72,919,121 | 0.434 | 253.5 | 0.115 |
| JSON/text (`orjson`) | 256 MiB | 294,957,391 | **1.614** | 1014.0 | 0.417 |

### 2.4 Findings

1. **The copy is not the expensive part; the fingerprint is.** A 256 MiB
   numeric frame copies in 30 ms but fingerprints in 9.5 s. Registration
   must therefore run hashing in a thread (spec §2 already requires this)
   and must never hold the catalog lock across it.
2. **Nested-object frames are ~13× worse and the result is worthless.**
   122 s at 256 MiB — *and* pandas does not raise on unhashable cells: it
   silently falls back to hashing each object's **string repr**. A
   fingerprint over nested-object cells is therefore **not proof of content
   integrity**. This is the concrete mechanism behind AC5's "nested mutable
   data never receives a false verification claim": the implementation must
   detect nested mutable cells and set `evidence_verifiable=False` rather
   than trusting a fingerprint it *can* compute.
3. **`df.copy(deep=True)` does not detach nested cells.** Verified by
   object identity, not assumed: `df["obj"].iloc[0] is snapshot["obj"].iloc[0]`
   → `True` at every size. D4's "verified safe snapshot adapter or
   `evidence_verifiable=False`" is mandatory, not advisory.
4. **Use `orjson`, not stdlib `json`, for canonical bytes.** Byte-identical
   output, ~40× faster (1.6 s vs 65 s at 256 MiB) and ~25 % lower peak.
   `orjson>=3.9` is already a core dependency; no new dependency is
   implied.
5. **Serialization, not the payload, dominates JSON peak memory.** Encoding
   a ~281 MiB payload peaked at 1014 MiB (orjson) / 1331 MiB (stdlib) —
   3.6–4.7× the payload. Byte budgets must be enforced **while**
   serializing and **before** materialization, and live vs. snapshot copies
   must be accounted separately (spec §2).
6. `memory_usage(deep=True)` is an estimate; `tracemalloc` sees only Python
   allocations. Neither proves retained bytes. Where a real byte count is
   needed, use actual snapshot/payload bytes.

### 2.5 OQ3 — `snapshot_max_bytes` default

**Recommendation: keep 64 MiB.** At 64 MiB a supported numeric frame costs
2.3 s to fingerprint, which is already at the edge of acceptable for a
registration that blocks a tool result even when threaded; 256 MiB (9.5 s)
is not. The cap governs the optional **RAM snapshot** only — in Delivery B
durable mode, supported artifacts below the cap are still written through
to durable storage, so raising the cap buys retained bytes, not
durability.

---

## 3. File-manager API (pinned, not invented)

`parrot.interfaces.file` (`__init__.py:18`) is a re-export shim over
`navigator.utils.file`; the interface really lives at
`navigator.utils.file.abstract.FileManagerInterface`.

Declared abstract methods: `copy_file`, `create_file`, `delete_file`,
`download_file`, `exists`, `get_file_metadata`, `get_file_url`,
`list_files`, `upload_file`.

Operations selected for bounded blob I/O — **exact installed signatures**:

```python
async def create_from_bytes(self, path: str, data: bytes | BytesIO | StringIO) -> bool
async def download_file(self, source: str, destination: Path | BinaryIO) -> Path
async def get_file_metadata(self, path: str) -> FileMetadata
async def exists(self, path: str) -> bool
async def delete_file(self, path: str) -> bool
```

`FileMetadata` fields: `name, path, size, content_type, modified_at, url`.

Notes for the Delivery B blob adapter (M8):

- **Write** with `create_from_bytes` (single call, whole payload). There is
  **no chunked/streaming writer** on the interface — do not invent one.
- **Bounded read**: `get_file_metadata(...).size` first, reject over the
  ceiling, only then `download_file(source, BytesIO())`. `download_file`
  accepts a `BinaryIO`, so no temp file is required, but it does **not**
  take a byte limit — the size pre-check is the enforcement point.
- `LocalFileManager(base_path, create_base=True, follow_symlinks=False,
  sandboxed=True)` resolves paths inside its sandbox and runs the blocking
  work via `asyncio.to_thread`.
- `S3FileManager` / `GCSFileManager` are **lazy** exports (`__getattr__`);
  importing the shim does not pull `aioboto3` / `google-cloud-storage`.
- Durability caveat: `LocalFileManager` is durable only on a shared,
  persistent mount. A pod-local temp dir is not durable, and
  `TempFileManager` never is.
- `parrot/storage/overflow.py:20` (`OverflowStore`) is confirmed
  **JSON-definition oriented**: `json.dumps` above a 200 KB
  `INLINE_THRESHOLD`, written to a `{prefix}.json` key. It is **not** a
  versioned Parquet artifact store and is not a substitute. It is however
  a useful precedent: it already uses `create_from_bytes` as its write
  primitive (`:66`) and `download_file` into a `BytesIO` (`:104-105`) to read
  back.

---

## 4. Decisions recorded by this task

| ID | Decision | Basis |
|---|---|---|
| OQ3 | `snapshot_max_bytes` default stays **64 MiB** | §2.5 measurements |
| OQ1 | Archive on terminal deletion: **JSONL when `archive_uri` is set, else delete** (spec default, unchanged) | Not blocking; no measurement contradicts it |
| OQ2 | Plan runs **do not** auto-create tasks or steps; attribute only when a task already exists (`attribution=plan`) | Spec default, unchanged; §1.4 confirms plan node ids are not step ids |
| P0-1 | Canonical JSON uses **`orjson` + `OPT_SORT_KEYS`** | §2.4 finding 4 |
| P0-2 | Nested mutable object cells ⇒ `evidence_verifiable=False`; never trust a computable fingerprint over them | §2.4 findings 2–3 |
| P0-3 | Blob I/O uses `create_from_bytes` / `get_file_metadata` / `download_file(BytesIO)`; size pre-check is the byte ceiling | §3 |
| P0-4 | The observer attaches to the **`ToolManager`**, not to tool instances (clone semantics) | §1.3 note 5 |

## 5. Verification limitations

- Measurements are **single-host, single-run**, on one CPU/pandas/numpy
  combination. They establish orders of magnitude, not an SLO. The spec
  explicitly forbids claiming a latency SLO before measurement, and this
  document claims none.
- `tracemalloc` peaks understate numpy buffer allocation. Treat peak
  columns as a lower bound.
- The contract inventory is **static** (regex over pinned source). It
  proves the sites exist; it does not prove they are the only ones a
  future refactor might add. `test_contract_inventory` fails loudly if a
  pinned site disappears, which is the intended regression signal.
- No production behaviour was implemented, executed or benchmarked here.
  No PostgreSQL, Redis, or worker subprocess was contacted.
