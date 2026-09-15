# LanceDB vector, full-text and hybrid store (FEAT-542)

`LanceDBStore` is a local-directory `AbstractStore` backend with persistent
vector search, native full-text search (FTS) and native hybrid (RRF) fusion
— no PostgreSQL, no Docker, no storage service. It integrates with the
existing `VectorStoreSearchTool`/`VectorStoreOrigin` and adds an explicit
`LanceDBOrigin` for `MultiStoreSearchToolkit` federation, including
composition with `GraphIndexOrigin`.

## Install

```bash
pip install "ai-parrot-embeddings[lancedb]"
```

Pins the exact release proven by TASK-3057's SDK compatibility gate:
`lancedb==0.38.0` against the existing core `pyarrow>=25.0` constraint (see
`sdd/state/FEAT-542/lancedb-sdk-contract.md` for the full evidence). The
`lancedb` extra is also included in `ai-parrot-embeddings[all]`.

## Configure

`StoreConfig.index_type` defaults to `"IVF_FLAT"` (`parrot/models/stores.py`)
— LanceDB v1 supports `FLAT` only, so a factory user **must** override it
explicitly, or construction raises a `pydantic.ValidationError` naming
`'FLAT'`:

```python
from parrot.models.stores import StoreConfig

config = StoreConfig(
    vector_store="lancedb",
    table="agent_knowledge",
    dimension=768,
    metric_type="COSINE",
    index_type="FLAT",              # required override — IVF_FLAT is rejected
    embedding_model={
        "model_type": "huggingface",
        "model_name": "sentence-transformers/all-mpnet-base-v2",
    },
    extra={"uri": "./data/agent-knowledge"},
)
```

Constructing `LanceDBStore` directly accepts the same kwargs, plus the
compatibility aliases existing factories already send: `table`
(→`collection_name`), `name`/`vector_database`/`vector_store` (routing
fields, consumed and ignored), `schema=None`/`"public"` (no-op namespace —
anything else raises), and a **null** `dsn` (a non-null `dsn` is rejected in
favor of explicit `uri`). Unknown kwargs raise `ValueError` rather than
being silently dropped.

## Query modes and what each score means

| Mode | Result type | Score | Direction |
|---|---|---|---|
| Vector | `SearchResult` | raw cosine distance | lower is better |
| FTS | `SearchResult` | native BM25 | higher is better |
| Hybrid | `LanceDBHybridHit` | native RRF relevance | higher is better |

> **The FTS `distance` alias is not a distance.** `SearchResult.distance`
> returns `score` unchanged, so on the FTS path it is numerically BM25 —
> higher is better, the opposite direction of the vector path's distance.
> This is documented here because the shared `SearchResult` model was
> deliberately left alone rather than special-cased per backend.

```python
# Vector — raw cosine distance, lower is better; 0.0 disables thresholding
results = await store.similarity_search("onboarding steps", limit=5, similarity_threshold=0.3)

# FTS — model-free; never constructs or invokes an embedding provider
results = await store.fulltext_search("ZXQ731", limit=5)

# Hybrid — explicit query vector + query text; native RRF fusion
hits = await store.hybrid_search("onboarding steps", limit=5)
# hits: list[LanceDBHybridHit] — score_kind="rrf", higher_is_better=True, no `.distance`
```

`similarity_threshold=0.0` (the base default) disables vector thresholding.
The `VectorStoreSearchTool`'s `score_threshold` kwarg, when supplied
(including an explicit `0.0`, which is **not** a disable sentinel there),
also means minimum cosine similarity in `[0, 1]`; when both thresholds are
enabled, the stricter one wins.

## Write ownership and concurrency

Mutations (upsert, delete, collection/FTS-index creation) within one
process/event loop are serialized by an in-process `asyncio.Lock`. That
lock is **not** a cross-process mechanism. The approved requirement is that
**independent OS processes may write the same local directory
concurrently** — correctness for that rests on `MutationCoordinator`
(`parrot.stores.lancedb_concurrency`): a `fcntl.flock`-guarded critical
section that reopens the table handle to the latest committed version
before every mutation. This is the proven mechanism, not a convenience —
TASK-3057's gate found the pinned SDK raises **no distinguishable conflict
exception** for a colliding-insert race between two processes; an
in-process lock or a catch-and-retry loop alone reproduces duplicate rows.
See `sdd/state/FEAT-542/lancedb-sdk-contract.md` §"Concurrency contract"
for the full evidence.

What this guarantees, verified with real `multiprocessing.Process` workers
(`packages/ai-parrot-embeddings/tests/test_lancedb_multiprocess.py`):

- Disjoint-ID writes from independent processes all land.
- Colliding-ID writes converge to exactly one logical row, never duplicated
  or lost.
- A reader looping throughout a concurrent FTS-index rebuild never observes
  a partial or erroring table.
- A `SIGKILL`ed writer's lock is released by the OS itself (no PID/age
  "stolen lock" heuristic) — a subsequent mutation proceeds without
  deadlock.
- Cancellation releases mutation ownership but does **not** imply rollback
  of a write already committed by the SDK.

**Not guaranteed**: network/remote filesystems, cloud object-storage URIs,
or distributed transactions — this is a single local filesystem directory.

## Storage locality vs. offline

A local LanceDB directory needs **zero network** for connect/ingest/vector/
FTS/hybrid — proven directly in
`packages/ai-parrot-embeddings/tests/test_lancedb_sdk_contract.py::test_offline_storage_path_denies_sockets`
and again at end-to-end scope in `test_lancedb_store.py::TestNoNetwork`.
But **storage locality alone does not make an agent offline** — a remote
embedding provider or a remote LLM still dials out. See
[`docs/lancedb-offline-profile.md`](lancedb-offline-profile.md) for the
fully offline local-agent profile (local embedding model + local LLM,
egress denied end to end) and its provisioning/failure-mode documentation.

## Safe reopen, deletion and unsupported modes

- **Reopen with a mismatched schema/dimension/metric/embedding identity**
  raises `ValueError` naming the mismatch; the existing table is never
  overwritten or migrated (`CollectionManifest.check_compatible`).
- **`delete_documents(documents=..., pk=..., values=...)`** requires
  exactly one of `documents` (Document objects or raw logical IDs) or
  `pk`+`values` — `pk="id"` targets raw logical IDs, any other key must be
  a declared metadata field. There is no implicit delete-all; an empty or
  missing selector raises `ValueError`.
- **`delete_documents_by_filter(search_filter)`** compiles the same
  metadata predicate as search, deliberately **without** the search-only
  parent-exclusion clause — deleting `source="x"` reaches matching parent
  rows too.
- **`mmr_search()`** always raises `NotImplementedError`: v1 ships exact
  cosine search only.

## Composing hybrid with graph

`LanceDBOrigin` (`parrot_tools.multistoresearch.origins`) borrows an
already-configured `LanceDBStore` — it never opens or closes it — and
federates alongside `GraphIndexOrigin` in a real `MultiStoreSearchToolkit`:

```python
from parrot_tools.multistoresearch import MultiStoreSearchToolkit
from parrot_tools.multistoresearch.origins import GraphIndexOrigin, LanceDBOrigin

lancedb_origin = LanceDBOrigin(store, mode="hybrid", collection="agent_knowledge")
graph_origin = GraphIndexOrigin(retriever=my_retriever)

toolkit = MultiStoreSearchToolkit(origins=[lancedb_origin, graph_origin])
response = await toolkit.store_search("onboarding and related context")
```

`response.sections` preserves each origin's **native** order/score/rank —
including LanceDB's RRF relevance and provenance in the `_lancedb` metadata
block. `response.merged_top_k` is the toolkit's **existing**, unchanged
BM25-over-content rerank + ID/content-hash dedup — native RRF order
survives only *within* the grouped section, not in the merged list (this
feature does not alter toolkit ranking/dedup — verified in
`test_lancedb_integration.py::test_merged_ranking_and_dedup_are_unchanged`).
A failing LanceDB hybrid leg fails that origin's section (`status="error"`)
while the graph origin's results are retained — no partial/vector-only
fallback.

## Benchmark baseline (NOT an SLO)

Deterministic 1,000-row ingest + per-mode search timing, recorded via
`examples/lancedb_benchmark.py --rows 1000 --dimension 8 --warmup 3 --samples 10`
(full JSON at `artifacts/logs/lancedb-vector-store-benchmark.log`):

| Item | Value |
|---|---|
| lancedb | 0.38.0 |
| pyarrow | 25.0.1 |
| Python | 3.12.3 |
| Platform | Linux-7.0.0-31-generic-x86_64 |
| Rows | 1,000 (dimension 8, deterministic synthetic corpus) |
| Ingest | 0.073 s |
| Vector search (10 samples, post-warmup) | ~0.0050 s avg |
| FTS search (10 samples, post-warmup) | ~0.0051 s avg |
| Hybrid search (10 samples, post-warmup) | ~0.0067 s avg |

**No latency or recall target (p95, SLO, etc.) was ever supplied for this
feature, and none is claimed here.** This table exists so a future change
can be compared against a known-reproducible baseline — reproduce it with
the exact command above; the script asserts nothing and is not a CI gate.
