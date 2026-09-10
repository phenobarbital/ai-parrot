# TASK-3068: Deliver a fully offline local-agent profile

**Feature**: FEAT-542 - Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h) — target 4 hours
**Depends-on**: TASK-3067
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Can run alongside integration tests after registration because owned files are disjoint. File ownership is disjoint from other eligible parallel tasks; dependencies still gate start.
**Acceptance coverage**: AC6, AC10

---

## Context

Implements the approved 'fully offline agent' answer, beyond storage-only deterministic tests.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Build the gate-selected local-agent example using existing LocalLLMClient, a pre-provisioned local embedding provider, LanceDBOrigin and optional existing GraphIndex artifacts. Verify the actual bot/client initialization and tool-registration APIs before invoking them.
- Separate provisioning from runtime; never download missing weights or fall back to a remote provider at runtime. Make missing assets, nonlocal URLs, unavailable local server and incompatible dimensions actionable failures.
- Limit the profile to needed retrieval tools and local memory/configuration; ensure no implicit remote tool, default remote LLM or storage service is required.
- Prove one agent retrieval/answer cycle with real provisioned embedding/LLM assets and external egress denied. Permit only documented local loopback inference, if used; disable outside DNS/HTTP and automatic model fetches. Deterministic fake-provider tests are supplementary, not offline certification.
- Provide runnable explicit local paths/model identity and a dependency/provisioning checklist; no PostgreSQL/Docker requirement for persistence.

**NOT in scope**: New LLM provider, mandatory whole-framework offline mode, provider core rewrites, remote asset downloads during runtime and graph seed replacement.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/lancedb_local_agent.py` | CREATE | Runnable offline agent profile using existing client and local assets |
| `packages/ai-parrot-tools/tests/multistoresearch/test_lancedb_offline_agent.py` | CREATE | Profile validation and real local-model acceptance |
| `docs/lancedb-offline-profile.md` | CREATE | Provisioning, egress boundary and offline run instructions |

Ownership is exclusive to this task for the listed responsibility. You are not alone in the codebase: preserve others' changes, do not revert unrelated edits, and accommodate completed dependency work. New files listed here are proposed outputs, not already-verified imports. Shared backend files are deliberately sequenced by dependencies.

---

## Codebase Contract (Anti-Hallucination)

Verified by source inspection on `dev` on 2026-09-10. This is not a claim of runtime SDK/import testing. Re-read relevant definitions before implementation; if paths/signatures changed, update the contract first. Symbols delivered by dependencies must be verified in their committed files before import.

### Verified Imports

```python
from parrot.clients.local import LocalLLMClient  # packages/ai-parrot-client-local/src/parrot/clients/local/__init__.py:1
from parrot.stores import AbstractStore  # packages/ai-parrot-embeddings/tests/test_namespace_imports.py:151
from parrot.models import OriginHit, SearchOriginKind  # packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:10
from parrot_tools.multistoresearch.origins.base import SearchOrigin  # packages/ai-parrot-tools/tests/multistoresearch/test_toolkit.py:6
```

### Existing Signatures to Use

| Verified source | Existing contract |
|---|---|
| `packages/ai-parrot-client-local/src/parrot/clients/local/client.py:79` | LocalLLMClient.__init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None, **kwargs); explicit base_url needed to constrain profile endpoint. |
| `packages/ai-parrot-client-local/src/parrot/clients/local/client.py:117` | async ask(self, prompt: str, model: Union[str, LocalLLMModel] = None, **kwargs) delegates to existing OpenAI-compatible client machinery. |
| `packages/ai-parrot-client-local/pyproject.toml:5` | Existing ai-parrot-client-local distribution; provider entry points at :22 include local/localllm/ollama/llamacpp. |
| `packages/ai-parrot/src/parrot/bots/agent.py:69` | BasicAgent.__init__(self, name: str = 'Agent', agent_id: str = 'agent', use_llm: str = 'google', llm: str = None, tools: List[AbstractTool] = None, system_prompt: str = None, human_prompt: str = None, use_tools: bool = True, instructions: Optional[str] = None, dataframes: Optional[Dict[str, pd.DataFrame]] = None, **kwargs); default remote provider must be overridden. |
| `packages/ai-parrot/src/parrot/bots/__init__.py:2` | BasicAgent and Agent are exported; re-verify actual configure/ask/tool wiring before constructing the offline profile. |
| `pyproject.toml:216` | Pytest strict-config/strict-markers; registered real_llm marker at :234. Do not silently introduce unregistered markers. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:326` | create_embedding(self, embedding_model: dict, **kwargs) uses registry.get_or_create_sync; arbitrary dict fields are not automatically forwarded (Matryoshka is explicitly forwarded). |
| `packages/ai-parrot/src/parrot/stores/abstract.py:383` | async generate_embedding(self, documents: List[Any]) -> List[Any] initializes a default provider if absent, then awaits embed_documents. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:391` | _apply_contextual_augmentation(self, documents: list, _log: bool = True) -> list[str] mutates document.metadata['contextual_header']; use copies. |
| `packages/ai-parrot/src/parrot/embeddings/base.py:169` | async embed_documents(self, texts: List[str], batch_size: Optional[int] = None) -> List[List[float]]. |
| `packages/ai-parrot/src/parrot/embeddings/base.py:188` | async embed_query(self, text: str, as_nparray: bool = False) -> Union[List[float], List[np.ndarray]]; default is a single flat vector. |
| `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py:134` | SentenceTransformerModel.__init__(self, model_name: str, matryoshka: Optional[dict] = None, backend: Optional[str] = None, file_name: Optional[str] = None, **kwargs). |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:42` | async search(self, query: str, k: int) -> List[OriginHit]; optional async fts_search(self, query: str, k: int) -> List[OriginHit] at :54; adapters raise errors. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:50` | VectorStoreOrigin.search calls self.store.similarity_search(query, limit=k); fts_search at :66 calls self.store.fulltext_search; _normalize at :90 preserves score/metadata and 1-based rank. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py:7` | Current exports: SearchOrigin, VectorStoreOrigin, PageIndexOrigin, GraphIndexOrigin and ParrotWikiOrigin. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:65` | MultiStoreSearchToolkit.__init__(self, origins: List[SearchOrigin], k: int = 10, k_per_origin: int = 20, default_timeout: float = 30.0, bm25_weights: Optional[Dict[str, float]] = None, **kwargs: Any) -> None. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:85` | async store_search(self, query: str, k: Optional[int] = None) -> MultiSearchResponse; _run_origins at :268 isolates origin timeouts/errors. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:246` | _build_response reranks then deduplicates; BM25 at :359 leaves scores untouched; dedup at :390 uses ID then content hash. |

### Does NOT Exist

- LocalLLMClient is a client of a local server, not an in-process inference engine or weight provisioner.
- No existing LanceDB offline agent profile or automatic guarantee that every enabled tool is offline exists.
- Calling base generate_embedding is not model-free lexical retrieval.
- Do not assume arbitrary offline/local_files_only fields in embedding_model reach the provider; verify forwarding before relying on them.
- LanceDBOrigin is new; the current VectorStoreOrigin has no hybrid mode.
- Toolkit merged_top_k does not preserve native RRF order; only grouped sections preserve origin order.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

Can run alongside integration tests after registration because owned files are disjoint. Use existing real_llm marker from root pyproject.toml; avoid unregistered custom markers. No new provider/core source edits without updated task scope.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3068-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

### References in Codebase

The task-specific locations above and the spec's sections 2, 4, 5, 6 and 8 are authoritative. Read any additional implementation API before relying on it; do not guess builder methods from a class name.

---

## Acceptance Criteria

- [ ] A fully offline agent run after provisioning is demonstrated with recorded model/server versions and external-egress denial.
- [ ] Cold missing-asset and remote-fallback tests fail explicitly, with no hidden model downloads.
- [ ] Existing client/provider abstractions are reused; optional graph federation uses local artifacts.
- [ ] General tests may skip real_llm when unprovisioned, but feature acceptance cannot claim AC6 complete until the actual real-model run passes.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_offline_profile_rejects_remote_or_missing_assets` | Profile fails closed instead of contacting remote providers or downloading. |
| `test_offline_agent_real_models_retrieve_and_answer` | A provisioned local model produces an agent answer grounded in retrieved local content with egress disabled. |
| `test_offline_restart_preserves_store` | Fresh agent process reuses the persistent corpus and identity. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-tools/tests/multistoresearch/test_lancedb_offline_agent.py -v
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
7. Move this task to `sdd/tasks/completed/TASK-3068-lancedb-offline-agent-profile.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: not started
**Date**: not completed
**Notes**: Pending execution; no implementation or acceptance tests run during task decomposition.
**Deviations from spec**: The checked answers supersede stale prose; TASK-3057 reconciles that discrepancy before implementation.
