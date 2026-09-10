# TASK-3057: Reconcile approved requirements and prove SDK contracts

**Feature**: FEAT-542 - Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h) — target 4 hours
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Sequential/gated task. Only initial runnable task; all implementation is downstream of this decision/API gate.
**Acceptance coverage**: AC1, AC6, AC8

---

## Context

Prerequisite to M1–M5. The approved spec's checked section 8 answers supersede older single-writer/storage-only prose. Establish an implementable, internally consistent contract before any backend work.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Preserve all five answered questions verbatim. Resolve stale draft/unchecked wording, offline non-goals, one-process restrictions, I7/I8 and AC6/AC8/AC10. Do not change the user's decisions or feature identity.
- Probe candidate lancedb==0.38.0 in an isolated environment against existing Python>=3.11 and pyarrow>=25.0 constraints. Verify async local connection, persisted schema metadata, cosine distances, native FTS/index creation, explicit vector/text hybrid, one conjunctive prefilter, merge-insert, delete and post-write freshness. Capture exact signatures/result columns.
- Specify concurrent independent processes on one local filesystem: creation/index races, same-ID upserts, count-and-delete consistency, commit conflict retries or process-shared exclusion, bounded waits, crashes and cancellation. Prove with at least two real processes; a per-instance asyncio lock is not sufficient. Record concrete coordinator interface/configuration used by TASK-3061.
- Define a fully offline agent acceptance profile after provisioning: local cached embedding and LLM assets, existing local client, local graph artifacts, no remote fallback, external-network denial and explicit loopback-only inference if used. Identify supported model/server fixture and provisioning steps without requiring a PostgreSQL container.
- Record API/configuration choices and test commands in the evidence document. Update the spec's Codebase Contract for any newly selected existing provider APIs; align task-owned module paths. If compatibility or a necessary product choice is unresolved at four hours, report the precise blocker and leave this gate pending/blocked, never done.

**NOT in scope**: Production backend/origin implementation, permanent manifest/lock changes, cloud service adoption, new LLM client, or changing resolved product requirements.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/specs/lancedb-vector-store.spec.md` | MODIFY | Reconcile sections 1–7, acceptance criteria, module paths and revision history with existing checked answers |
| `packages/ai-parrot-embeddings/tests/test_lancedb_sdk_contract.py` | CREATE | Bounded real-SDK compatibility probes |
| `sdd/state/FEAT-542/lancedb-sdk-contract.md` | CREATE | Versioned API evidence and offline/concurrency decisions |

Ownership is exclusive to this task for the listed responsibility. You are not alone in the codebase: preserve others' changes, do not revert unrelated edits, and accommodate completed dependency work. New files listed here are proposed outputs, not already-verified imports. Shared backend files are deliberately sequenced by dependencies.

---

## Codebase Contract (Anti-Hallucination)

Verified by source inspection on `dev` on 2026-09-10. This is not a claim of runtime SDK/import testing. Re-read relevant definitions before implementation; if paths/signatures changed, update the contract first. Symbols delivered by dependencies must be verified in their committed files before import.

### Verified Imports

```python
import importlib  # packages/ai-parrot-embeddings/tests/test_store_backends_present.py:2
from parrot.stores import AbstractStore  # packages/ai-parrot-embeddings/tests/test_namespace_imports.py:151
from parrot.clients.local import LocalLLMClient  # packages/ai-parrot-client-local/src/parrot/clients/local/__init__.py:1
```

### Existing Signatures to Use

| Verified source | Existing contract |
|---|---|
| `packages/ai-parrot-embeddings/pyproject.toml:10` | requires-python >=3.11; optional dependencies at :32; backend extras at :62; all aggregator at :97. No LanceDB declaration. |
| `packages/ai-parrot/pyproject.toml:157` | Core pyarrow>=25.0; existing faiss-cpu at :163, rustworkx at :169 and aiosqlite at :172. |
| `uv.lock:1` | uv-generated workspace lockfile; requires-python >=3.11 and Linux supported markers. Regenerate with the resolver, not manual package entries. |
| `.github/workflows/ci.yml:1` | Existing monorepo CI uses checkout/setup-python/setup-uv and explicit workspace/test commands; a dedicated new workflow must not silently skip SDK-present tests. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:117` | AbstractStore.__init__(self, embedding_model: Union[dict, str] = None, embedding: Union[dict, Callable] = None, **kwargs); configured provider eagerly created at :155. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:202` | async connection(self) -> tuple; get_connection(self) -> Any at :205; engine(self) at :208; async disconnect(self) -> None at :212. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:216` | Nested __aenter__/__aexit__; _free_resources at :222 calls provider.free(). Subclass must preserve borrowed-provider ownership. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:238` | get_vector(self, metric_type: str = None, **kwargs); get_vectorstore(self) at :241 delegates. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:276` | async from_documents(self, documents: List[Any], collection: Union[str, None] = None, **kwargs) -> Callable. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:295` | async create_collection(self, collection: str) -> None; async add_documents(self, documents: List[Any], collection: Union[str, None] = None, **kwargs) -> None at :308. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:455` | async prepare_embedding_table(self, tablename: str, conn: Any = None, embedding_column: str = 'embedding', document_column: str = 'document', metadata_column: str = 'cmetadata', dimension: int = None, id_column: str = 'id', use_jsonb: bool = True, drop_columns: bool = False, create_all_indexes: bool = True, **kwargs). |
| `packages/ai-parrot/src/parrot/stores/abstract.py:494` | async delete_documents(self, documents: Optional[Any] = None, pk: str = 'source_type', values: Optional[Union[str, List[str]]] = None, table: Optional[str] = None, schema: Optional[str] = None, collection: Optional[str] = None, **kwargs) -> int. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:520` | async delete_documents_by_filter(self, search_filter: Dict[str, Union[str, List[str]]], table: Optional[str] = None, schema: Optional[str] = None, collection: Optional[str] = None, **kwargs) -> int. |
| `packages/ai-parrot-client-local/src/parrot/clients/local/client.py:79` | LocalLLMClient.__init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None, **kwargs); explicit base_url needed to constrain profile endpoint. |
| `packages/ai-parrot-client-local/src/parrot/clients/local/client.py:117` | async ask(self, prompt: str, model: Union[str, LocalLLMModel] = None, **kwargs) delegates to existing OpenAI-compatible client machinery. |
| `packages/ai-parrot-client-local/pyproject.toml:5` | Existing ai-parrot-client-local distribution; provider entry points at :22 include local/localllm/ollama/llamacpp. |
| `packages/ai-parrot/src/parrot/bots/agent.py:69` | BasicAgent.__init__(self, name: str = 'Agent', agent_id: str = 'agent', use_llm: str = 'google', llm: str = None, tools: List[AbstractTool] = None, system_prompt: str = None, human_prompt: str = None, use_tools: bool = True, instructions: Optional[str] = None, dataframes: Optional[Dict[str, pd.DataFrame]] = None, **kwargs); default remote provider must be overridden. |
| `packages/ai-parrot/src/parrot/bots/__init__.py:2` | BasicAgent and Agent are exported; re-verify actual configure/ask/tool wiring before constructing the offline profile. |
| `pyproject.toml:216` | Pytest strict-config/strict-markers; registered real_llm marker at :234. Do not silently introduce unregistered markers. |

### Does NOT Exist

- No existing lancedb optional extra or resolved SDK contract; TASK-3057 supplies version/API evidence.
- No satellite parrot/stores/__init__.py may be created; core owns namespace extension.
- LanceDBStore and a LanceDB process-shared coordinator do not yet exist.
- AbstractStore's connection/context state is not a cross-process transaction mechanism.
- LocalLLMClient is a client of a local server, not an in-process inference engine or weight provisioner.
- No existing LanceDB offline agent profile or automatic guarantee that every enabled tool is offline exists.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

No production code until this gate is done. Provisioning and SDK installation during this future task still follow dependency/approval policy. Do not mark an unsupported SDK or a mock-only probe as passing.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3057-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

### References in Codebase

The task-specific locations above and the spec's sections 2, 4, 5, 6 and 8 are authoritative. Read any additional implementation API before relying on it; do not guess builder methods from a class name.

---

## Acceptance Criteria

- [ ] The spec no longer excludes fully offline operation or concurrent independent writers, and checked answers are unchanged.
- [ ] The SDK evidence identifies one proven release/API and a concrete concurrency contract; all compatibility probes pass without mocks or feature-job skips.
- [ ] Offline profile defines real local model assets and an agent-level external-egress-denied test, not only deterministic storage tests.
- [ ] Downstream task contracts are reconciled with the spec; materially new scope choices are returned for user approval rather than guessed.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_sdk_local_async_roundtrip` | Persist manifest, reopen and query via real async SDK. |
| `test_sdk_native_fts_hybrid_filter_contract` | Native FTS and hybrid preserve required filters, score columns and fresh rows. |
| `test_sdk_two_process_mutations` | Two separately initialized processes overlap operations; no lost acknowledged writes or duplicate logical IDs; capture actual coordination requirements. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_sdk_contract.py -v
```

These are test contracts, not executed test results or placeholder production implementations. Use pytest-asyncio for async cases, temporary directories for datasets, bounded subprocess joins, and explicit process barriers for race tests. Reuse the deterministic 8-D fixture unless real local model evidence is explicitly required. Required feature tests may not all skip just because the SDK or assets were omitted.

---

## Agent Instructions

1. Read the spec and the approved-answer precedence in this task.
2. Work only inside the FEAT-542 feature worktree. Verify dependency tasks are `done` in `sdd/tasks/index/lancedb-vector-store.json` and their task files are under `sdd/tasks/completed/`.
3. Re-verify every needed import/signature and dependency-produced helper before writing code.
4. Update only this task entry in `sdd/tasks/index/lancedb-vector-store.json` to `in-progress`, with assignment/start timestamps. Never use the historical monolithic index.
5. Outline the implementation plan and uncertainties, then implement within the listed file ownership. Preserve unrelated work.
6. Run all task acceptance checks and save logs; unresolved gate failures prevent completion.
7. Move this task to `sdd/tasks/completed/TASK-3057-lancedb-approved-contract-gate.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: not started
**Date**: not completed
**Notes**: Pending execution; no implementation or acceptance tests run during task decomposition.
**Deviations from spec**: The checked answers supersede stale prose; TASK-3057 reconciles that discrepancy before implementation.
