# TASK-3057: Reconcile approved requirements and prove SDK contracts

**Feature**: FEAT-542 — Local LanceDB Vector, Full-Text and Hybrid Search
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
  - **Largely done already — verify, do not redo.** Commit `12f552ff8` (spec v0.2, FEAT-545 design-research cross-check, spec §9) already corrected the stale §1 Draft Decision Baseline and §8 preamble, moved concurrent writers and the fully-offline profile out of Non-Goals, rewrote the §2 cross-process mutation paragraph, widened I8 to deny sockets across the whole path, added I9 for multi-process writers, and updated AC6/AC8. Read spec §9 first, confirm those edits say what this task needs, and spend the time on the SDK/concurrency/offline **proof** below rather than re-editing prose. Report any remaining contradiction you find; do not assume the reconciliation is complete just because this note exists.
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

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived from
> the spec's §2 New Public Interfaces and re-verified against the Codebase Contract above
> when this task was written. This is NOT the full implementation: business-logic branches,
> edge cases and test bodies are `FILL IN` stubs by design. Never change a signature, class
> name, or file path the blueprint fixes.

### Steps (in order)
1. Read spec §9 (Design Research Cross-Check) and the v0.2/v0.3 rows in the Revision History — *why*: commit `12f552ff8` already performed the prose reconciliation this task was originally scoped to do; re-editing it burns the 4h budget that belongs to the SDK proof.
2. Create the probe module and run it in an isolated environment with `lancedb==0.38.0` installed — *why*: the default suite must stay green without the optional extra, so the probes gate on `importorskip`.
3. Record every observed signature, keyword and result column verbatim in the evidence document — *why*: TASK-3059/3061/3065 consume this document as their contract; a paraphrase is not a contract.
4. Append the gate outcome to spec §7 — *why*: §7 currently states the pin is untested, and that sentence must stop being true or the pin must change.
5. If any required behavior is absent, stop and leave this task `blocked` with the exact conflict — *why*: this gate exists precisely to prevent implementation against an unproven API (AC1).

### `packages/ai-parrot-embeddings/tests/test_lancedb_sdk_contract.py` (CREATE)
```python
"""Bounded real-SDK compatibility probes for LanceDB (FEAT-542, AC1).

Skipped unless the optional extra is installed. These are not product tests:
each probe records one fact the spec depends on, and a failure here means the
candidate pin is wrong, not that the backend is broken.
"""
from __future__ import annotations

import pytest

lancedb = pytest.importorskip("lancedb", reason="requires ai-parrot-embeddings[lancedb]")

pytestmark = pytest.mark.asyncio


async def test_async_connect_and_persisted_schema_metadata(tmp_path):
    """connect_async opens a local dir; schema metadata survives reopen."""
    # FILL IN: open tmp_path, create a table with an explicit pyarrow schema carrying
    # manifest metadata, reopen in a fresh connection, assert metadata round-trips
    # — bounded by spec §2 "Data Models and Persistent Schema" (schema version 1)
    raise NotImplementedError


async def test_cosine_distance_column_name_and_direction(tmp_path):
    """Record the distance column name and whether lower is better."""
    # FILL IN: run a vector query, capture the exact result column, assert direction
    # — bounded by spec §2 "Search and Score Contracts" (raw cosine, lower is better)
    raise NotImplementedError


async def test_native_fts_index_and_hybrid_fusion(tmp_path):
    """Native FTS index creation, BM25 order, and explicit vector+text hybrid."""
    # FILL IN: create the FTS index via the async index API (NOT create_fts_index),
    # run hybrid with an explicit query vector plus text, record the relevance column
    # and whether pre-fusion component scores are exposed (spec §8 Q6)
    # — bounded by spec §7 "Async/native FTS API drift"
    raise NotImplementedError


async def test_prefilter_merge_insert_delete_and_freshness(tmp_path):
    """One conjunctive prefilter on all modes; merge-insert; delete; post-write reads."""
    # FILL IN: assert the prefilter applies to vector, FTS and both hybrid legs, that
    # merge-insert upserts by the stable id, and that rows written after index creation
    # are visible to all three modes — bounded by spec §2 "Filters" and §7 "FTS index freshness"
    raise NotImplementedError


async def test_two_process_concurrent_commit_behavior(tmp_path):
    """Two real OS processes commit to one directory; record the conflict contract."""
    # FILL IN: spawn two processes doing merge-insert and index creation on the same dir;
    # record whether the SDK retries, raises a distinguishable conflict error, or corrupts.
    # An asyncio lock is NOT sufficient evidence — bounded by AC8 and spec §2 concurrency
    raise NotImplementedError
```
**Why this shape**: each probe maps to exactly one spec claim that is currently unverified, so a failure names the claim that must change. `importorskip` keeps the default suite green without the extra (AC1). The concurrency probe must use real processes because the whole point of the §8 answer is that an in-process lock cannot prove it. Do not turn these into mocks — a mocked probe proves nothing and would let the pin ship untested.

### `sdd/state/FEAT-542/lancedb-sdk-contract.md` (CREATE)
```markdown
# FEAT-542 — LanceDB SDK contract evidence

**Gate task**: TASK-3057 · **Date**: <YYYY-MM-DD> · **Verdict**: pass | blocked

## Environment
| Item | Value |
|---|---|
| lancedb | <exact version resolved> |
| pyarrow | <exact version resolved> |
| Python | <exact version> |

## Verified API surface
<!-- One row per call the backend will make. Signature verbatim, not paraphrased. -->
| Operation | Exact call | Result columns | Notes |
|---|---|---|---|

## Concurrency contract (consumed by TASK-3061)
<!-- FILL IN: conflict behavior, whether a bounded retry suffices, and the exact
     coordinator interface + configuration TASK-3061 must implement -->

## Offline profile (consumed by TASK-3068)
<!-- FILL IN: model/server fixture, provisioning steps, egress-denial mechanism -->

## Spec §8 Q6 input
<!-- FILL IN: does a hybrid result expose pre-fusion vector/lexical score columns? -->

## Blockers
<!-- FILL IN: exact conflict and proposed revised pin, or "none" -->
```
**Why this shape**: TASK-3061, TASK-3065 and TASK-3068 all name this document as their input, so the headings are a contract, not decoration. The Q6 row exists because the design-research escalation (spec §9 S2) can be decided cheaply from this gate's observation rather than by a separate investigation.

### `sdd/specs/lancedb-vector-store.spec.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c 'If the candidate fails resolution or required behavior' sdd/specs/lancedb-vector-store.spec.md)
# AFTER — insert below `If the candidate fails resolution or required behavior, stop that implementation gate with the exact conflict and propose a revised pin/spec; do not silently switch to cloud storage, an older FTS engine, a mock-only test, or a global dependency downgrade.` (verified: sdd/specs/lancedb-vector-store.spec.md:384)

**Gate outcome (TASK-3057, <date>)**: <pass | blocked>. Resolved versions and the verified
API surface are recorded in `sdd/state/FEAT-542/lancedb-sdk-contract.md`. <One sentence on
what changed, if the pin moved.>
```
**Why**: §7 currently says the candidate pin's "resolution and runtime behavior were not tested during specification" — once this gate runs, that sentence needs an outcome next to it or the next reader re-does the work. Do not delete the original sentence; it is the honest record of what was known at spec time.

### FILL IN checklist
- [ ] `test_lancedb_sdk_contract.py` — all five probe bodies; bounded by AC1/AC8 and the spec sections named in each stub
- [ ] `lancedb-sdk-contract.md::Concurrency contract` — the exact coordinator interface TASK-3061 implements; bounded by AC8
- [ ] `lancedb-sdk-contract.md::Offline profile` — fixture and egress-denial mechanism; bounded by AC6
- [ ] `lancedb-sdk-contract.md::Spec §8 Q6 input` — whether pre-fusion component columns exist; bounded by spec §9 S2
- [ ] Spec §7 gate-outcome line — pass or blocked; bounded by AC1

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

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-10
**Notes**: Verified spec §9/v0.2/v0.3 reconciliation is complete (no stale prose remained). Installed `lancedb==0.38.0` in an isolated worktree venv (`uv venv --python /usr/bin/python3.12`) and wrote 6 real-SDK probes in `packages/ai-parrot-embeddings/tests/test_lancedb_sdk_contract.py` — all pass (`uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_sdk_contract.py -v`, 6 passed, log at `artifacts/logs/TASK-3057-lancedb.log`). Verified `importorskip` keeps the suite green with the SDK absent. Full evidence, including the concurrency coordinator interface for TASK-3061 and the offline profile for TASK-3068, recorded in `sdd/state/FEAT-542/lancedb-sdk-contract.md`. Verdict: **pass**, gate outcome appended to spec §7, §8 Q6 resolved and checked.
**Deviations from spec**: None from the task's declared scope. One addition beyond the blueprint's 5 stub functions: added a 6th probe, `test_offline_storage_path_denies_sockets`, directly proving the storage half of AC6/I8 (socket-denied local path) inside the same file already owned by this task — no new file was created for it.
**Key findings for downstream tasks**:
1. Default LanceDB vector-query `distance_type` is squared L2, not cosine — TASK-3059/3064 must call `.distance_type("cosine")` explicitly on every vector query.
2. Cross-process upsert correctness requires a `fcntl.flock`-guarded critical section that reopens the table handle (`conn.open_table`) before mutating — an in-process lock and/or catching a conflict exception is insufficient (no distinguishable conflict exception was observed). TASK-3061 must implement this exact pattern (reference implementation in the probe file's `_mutate_worker`).
3. Spec §8 Q6 resolved: hybrid queries expose only `_relevance_score` (fused RRF), no pre-fusion component columns — `LanceDBHybridHit` ships the single fused score for v1.
4. This dev environment's system default Python is 3.14, which `uv sync` cannot use for this workspace (`asyncdb==2.15.10` has no cp314 wheel); the worktree venv must be created with `--python /usr/bin/python3.12` (or 3.11/3.13).
5. Offline agent profile (embedding + LLM provisioning) is fully specified for TASK-3068 but not executed here — no embedding-model weights are cached in this environment, and downloading them is out of this 4-hour gate's scope and a documented spec Non-Goal to vendor.
