---
id: FG-004
query_id: Q053
type: git_log
intent: "Recent activity on working_memory toolkit (handles/dataframes)."
executed_at: 2026-10-25T22:41:00Z
duration_ms: 300
parent_id: null
depth: 0
---

# FG-004 — WorkingMemory history (120 days): the task_memory sub-package (Sep 2026) added versioned artifacts, blob tier, durable Postgres store

## Summary

~17 commits, 2026-09-08 → 2026-09-22, all Jesus Lara / Jesus, one theme: **FEAT workingmemory-toolkit (Recoverable Task Memory)** — TASK-2983..3004 created `tools/working_memory/task_memory/` with `observer.py`, `association.py`, `context.py`, `recall.py`, `repl.py`, `retention.py`, `blob.py`, `store/postgres.py`, `tools.py`, `config.py`; plus TASK-2985 "cap raw reads" in `tool.py`/`models.py`, and TASK-3592 (plan-then-execute-hardening) on `tool.py`. The companion proposal (read) fixes decisions relevant to this brainstorm: D1 one artifact store (`ArtifactStore` as `WorkingMemoryCatalog` backend, `artifact_id@version` identity, `ArtifactDescriptor` as read projection), D2 Postgres durable tier + Redis hot tier, D4 snapshot/spill policy with `fingerprint`, §6.4 `ArtifactStore` protocol (`put/get_current/get_version/load_payload(max_bytes)/invalidate/list/evict`), §7.4 `ResultPolicy` byte caps. Parquet via `pyarrow`, "no pickle". No Arrow zero-copy / by-reference sharing between agents; catalog is per-process and per-agent.

## Citations

- sha: `306e774927` date: 2026-09-08 author: Jesus Lara — TASK-2983 — canonical invocation observer lifecycle — files: `task_memory/observer.py`
- sha: `da893d6539` date: 2026-09-08 author: Jesus Lara — TASK-2985 — Route enabled working-memory operations and cap raw reads — files: `working_memory/models.py`, `working_memory/tool.py`
- sha: `a2381e729f` date: 2026-09-08 author: Jesus Lara — TASK-2997 — atomic durable aliases, versions and evidence pins — files: `task_memory/store/postgres.py`
- sha: `736191198d` date: 2026-09-08 author: Jesus Lara — TASK-2989 — expose enabled task command, selection and recall tools — files: `working_memory/__init__.py`, `task_memory/tools.py`, `working_memory/tool.py`
- sha: `ada582eae1` date: 2026-09-08 author: Jesus Lara — TASK-2998 — fenced call ownership and crash reconciliation — files: `task_memory/{association,context,observer}.py`, `store/postgres.py`
- sha: `9448651814` date: 2026-09-09 author: Jesus Lara — TASK-3000 — verified archive and crash-safe durable cleanup — files: `task_memory/blob.py`, `retention.py`, `store/postgres.py`
- sha: `ec59fa5707` date: 2026-09-09 author: Jesus Lara — TASK-3003 — wire durable backend lifecycle and retention scheduling — files: `task_memory/config.py`, `working_memory/tool.py`
- sha: `4eb5769181` date: 2026-09-22 author: Jesus — feat(plan-then-execute-hardening): TASK-3592 — files: `working_memory/tool.py`
- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  symbol: `WorkingMemoryToolkit`
  excerpt: |
    # proposal §2: catalog of DataFrames/objects, declarative ops (wm_compute_and_store), AnswerMemory bridge
- path: `packages/ai-parrot/src/parrot/tools/working_memory/internals.py`
  symbol: `WorkingMemoryCatalog`
  excerpt: |
    # proposal §2: plain in-process dict, no lock/TTL/byte limit; CatalogEntry(source_operation, parent_keys, description, turn_id, session_id)
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  excerpt: |
    (TASK-3000 — blob tier; proposal §6.4: PostgresArtifactStore index + blobs via storage_ref, Parquet via pyarrow, no pickle)
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/store/postgres.py`
  excerpt: |
    (TASK-2997 — durable aliases, versions, evidence pins → artifact_id@version)
- path: `sdd/proposals/workingmemory-toolkit.proposal.md`
  lines: 11-24
  symbol: `Closed decisions D1-D8`
  excerpt: |
    D1 One artifact store: ArtifactStore is the pluggable backend of WorkingMemoryCatalog; CatalogEntry gains
    version/identity; ArtifactDescriptor is a read projection. D2 No SQLite: Postgres (asyncpg) durable, Redis hot.
    D4 RAM snapshot: copy-on-register ≤64 MiB, else spill; deterministic fingerprint.
- path: `sdd/proposals/workingmemory-toolkit.proposal.md`
  lines: 252-270
  symbol: `ArtifactStore`
  excerpt: |
    class ArtifactStore(Protocol):
        async def put(self, entry: CatalogEntry, payload: Any) -> CatalogEntry
        async def get_current(self, scope: TaskScope, key: str) -> CatalogEntry | None
        async def get_version(self, artifact_id: str, version: int) -> CatalogEntry | None
        async def load_payload(self, artifact_id: str, version: int, *, max_bytes: int) -> Any
        async def invalidate(...); async def list(...); async def evict(...)
    # parrot/interfaces/artifact_store.py — "Pydantic-only, lazily implemented" (⚠️ VERIFY it landed)

## Notes

- The parent brainstorm's "handle + descriptor + provenance + blob store" has a near-match on paper: `artifact_id@version` + `ArtifactDescriptor` + `ArtifactStore` blob tier. The local spec should reuse this identity space rather than invent `key = sha256`.
- Content-addressing differs: WM uses `artifact_id` + `fingerprint` (blake2b-8), not a sha256 content key.
- Per-agent/per-process catalog → a shared blob index across agents (the blackboard `artifacts` key) does not exist.
- [cross-lane: type=grep, intent=verify whether parrot/interfaces/artifact_store.py and class ArtifactDescriptor exist in the tree]
- [cross-lane: type=read, intent=read task_memory/blob.py to see the blob tier API (storage_ref, verify-readable publish order)]
