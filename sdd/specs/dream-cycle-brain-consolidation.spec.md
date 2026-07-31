---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Dream Cycle — Episodic→Wiki Brain Consolidation

**Feature ID**: FEAT-390
**Date**: 2026-07-30
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.26.0

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

AI-Parrot agents accumulate episodic memories (`EpisodicMemoryStore`, FEAT-045)
and can maintain a personal LLM Wiki (`LLMWikiToolkit`, FEAT-260), but the two
are disconnected: episodes pile up as raw evidence and are eventually pruned by
TTL/compaction, while the wiki only grows when an agent explicitly calls
`wiki_remember`. There is no consolidation path that distills recurring
episodic experience into durable semantic knowledge, and no retrieval path that
feeds that knowledge back into `ask()`.

This feature adds the missing memory-consolidation stage (working → episodic →
**semantic**): an offline, periodic **dream cycle** that summarizes batches of
episodes into wiki pages (the agent's "brain"), plus a fourth retrieval
subsystem in `UnifiedMemoryManager.get_context_for_query()` so the brain
retro-feeds the agent's context.

Design was resolved in an interactive brainstorm (2026-07-30). Key resolved
decisions (see §8):

- Consolidation is **offline** ("dream cycle"): in-process asyncio scheduler
  with persisted state and **catch-up at startup** when a scheduled run was
  missed (server shutdown/restart).
- Brain scope is **hybrid**: per-agent wiki (`brain-<agent_id>`) plus selective
  promotion to an org-level wiki (`org-<org_id>`).
- Episodes are **marked as consolidated** (metadata patch), never deleted by
  the dream cycle; existing TTL/compaction keeps pruning them.
- Wiki access is via a **lean `BrainStore`** wrapper over the SQLite wiki
  store (`create_wiki_store`), NOT via the full `LLMWikiToolkit` (which drags
  PageIndex/GraphIndex/OKF toolkits into every brain-enabled agent).

### Goals

- Implement `parrot/memory/dream/` — `DreamState`, `DreamCycleRunner`,
  `DreamScheduler`, `BrainStore`.
- Extend `AbstractEpisodeBackend` with `update_metadata()` (PgVector, Redis,
  FAISS implementations) so episodes can be marked `consolidated_into=<page_id>`.
- Extend the unified layer (FEAT-055): `MemoryContext.semantic_knowledge`,
  `ContextAssembler` fourth section, `MemoryConfig.enable_brain`/`brain_weight`
  with weight rebalancing, `UnifiedMemoryManager` optional `brain` subsystem
  queried in parallel.
- Extend `LongTermMemoryMixin` with brain/dream flags and scheduler lifecycle.
- Zero breaking changes: with `enable_brain=False` (default) behavior is
  byte-identical to today.

### Non-Goals (explicitly out of scope)

- Working-memory (`WorkingMemoryToolkit`) unification or promotion into
  episodic memory — explicitly deferred in brainstorm; possible fifth source
  later.
- A mega-toolkit merging `wm_*`/`ep_*`/skills/wiki tools (rejected in
  brainstorm: tool-selection degradation, huge blast radius).
- External cron/CLI scheduling as the primary mechanism (rejected in
  brainstorm in favor of in-process scheduler; a CLI entry can come later).
- Modifying `LLMWikiToolkit`, PageIndex, GraphIndex, or OKF internals.
- Cross-agent episodic sharing changes (`CrossDomainRouter` untouched).
- Skill auto-extraction changes (existing FEAT-055 behavior untouched).

---

## 2. Architectural Design

### Overview

A new `parrot/memory/dream/` package implements the consolidation pipeline.
`DreamScheduler` (asyncio, in-process) persists its state as a JSON sidecar
next to the brain wiki DB and wakes on a configurable interval (default 24h).
If `next_due` has already passed at agent startup (missed run due to
shutdown), it executes a catch-up cycle immediately (with 0–60s jitter).

Each cycle, `DreamCycleRunner`:

1. **collect** — pulls eligible episodes since the `last_run` watermark
   (`importance >= threshold` OR non-empty `lesson_learned`, and not already
   marked `consolidated_into`), via `backend.get_recent(..., since=...)`.
2. **cluster** — groups episodes by embedding cosine similarity
   (threshold 0.75) using `EpisodeEmbeddingProvider`; falls back to grouping
   by `(category, related_tools)` when no embedding provider is configured.
3. **distill** — ONE LLM call per group (default model
   `gemini-3.1-flash-lite`, consistent with FEAT-055 reflection decision)
   producing `{title, body, category, confidence}` — same JSON-prompt pattern
   as `ReflectionEngine`.
4. **archive** — upserts the distilled page into the agent's brain wiki via
   `BrainStore.remember()` (deterministic `mem-<sha1(title::category)>` page
   id — idempotent, re-running a crashed cycle is safe).
5. **mark** — patches consolidated episodes with
   `metadata["consolidated_into"] = <page_id>` via the new
   `backend.update_metadata()`.
6. **promote** — pages reinforced in >= `org_promotion_cycles` distinct cycles
   (counter tracked in `DreamState.reinforcement_counts`) are copied into the
   org wiki with attribution (`asserted_by="agent:<id>"`).

Retrieval: `UnifiedMemoryManager.get_context_for_query()` gains a parallel
`_get_brain_knowledge(query)` step that runs `BrainStore.search()` (FTS,
plus vector when embeddings exist) against the agent brain and org wiki,
packs results into a token-budgeted `semantic_knowledge` section, and the
`ContextAssembler` allocates it `brain_weight` of the budget.

Cost control: max `dream_max_groups_per_cycle` (default 20) groups per cycle;
the watermark advances to the `created_at` of the newest **consolidated**
episode (not `now`), so the excess is picked up next cycle.

### Component Diagram

```
LongTermMemoryMixin (flags: enable_brain, dream_*)
        │ configure()                       ask()
        ▼                                    ▼
DreamScheduler ──────────────►  UnifiedMemoryManager.get_context_for_query()
  (interval, catch-up,            ├─ _get_episodic_warnings   (existing)
   lock, run_now, backoff)        ├─ _get_relevant_skills     (existing)
        │ triggers                ├─ _get_conversation        (existing)
        ▼                         └─ _get_brain_knowledge  🆕 (parallel)
DreamCycleRunner                              │
  collect → cluster → distill                 ▼
        │        │        │            BrainStore.search()
        │        │        └── AbstractClient (distill LLM)
        │        └── EpisodeEmbeddingProvider
        ▼
  BrainStore.remember() ──► wiki.db  brain-<agent_id>
        │                       │ promote (reinforcement >= N)
        │                       ▼
        │                   wiki.db  org-<org_id>
        └── backend.update_metadata(consolidated_into=page_id)
                    │
        EpisodicMemoryStore backends (PgVector / Redis / FAISS)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `EpisodicMemoryStore` | uses | `collect` reads via `store.backend.get_recent(since=...)`; store gains a thin `mark_consolidated()` passthrough |
| `AbstractEpisodeBackend` | extends (protocol) | New `update_metadata(episode_ids, patch) -> int` method + 3 backend implementations |
| `create_wiki_store` / `SQLiteWikiStore` | uses | `BrainStore` wraps it; same `wiki.db` format → brain remains readable by `LLMWikiToolkit` / `wikitoolkit` CLI |
| `UnifiedMemoryManager` | extends | New optional `brain: BrainStore` constructor param; parallel retrieval branch |
| `ContextAssembler` | extends | Fourth section `semantic_knowledge` with `brain_weight` allocation |
| `MemoryConfig` / `MemoryContext` | extends | New fields; weight validator covers 4 weights only when `enable_brain=True` |
| `LongTermMemoryMixin` | extends | New flags; starts/stops `DreamScheduler` in configure/cleanup |
| `ReflectionEngine` | pattern reference | Distill prompt follows its JSON-contract + fallback style (does not reuse the class) |
| `AbstractClient` | uses | Distill LLM calls go through the unified client interface |

### Data Models

```python
# parrot/memory/dream/models.py  (all Pydantic v2)

class DreamState(BaseModel):
    """Persisted scheduler/runner state (JSON sidecar, atomic write)."""
    agent_id: str
    last_run: datetime | None = None          # watermark (newest consolidated episode)
    next_due: datetime | None = None
    interval_hours: float = 24.0
    running: bool = False                     # lock flag
    running_since: datetime | None = None     # stale-lock detection (> 2x interval)
    cycles_completed: int = 0
    episodes_consolidated: int = 0
    reinforcement_counts: dict[str, int] = {} # page_id -> distinct-cycle count
    promoted_pages: list[str] = []            # page_ids already in org wiki

class DistilledKnowledge(BaseModel):
    """Output contract of one distill LLM call."""
    title: str
    body: str
    category: str = "lesson"                  # lesson | decision | concept | note
    confidence: float = 0.5                   # 0-1, from the LLM

class DreamCycleReport(BaseModel):
    """Structured result of one cycle (logged + returned by run_now)."""
    started_at: datetime
    finished_at: datetime | None = None
    episodes_collected: int = 0
    groups_formed: int = 0
    groups_distilled: int = 0
    groups_skipped: int = 0                   # LLM failures — retried next cycle
    pages_written: list[str] = []
    pages_promoted: list[str] = []
    aborted: bool = False
    abort_reason: str | None = None
```

### New Public Interfaces

```python
# parrot/memory/dream/brain.py
class BrainStore:
    """Lean wiki writer/reader over create_wiki_store (no PI/GI/OKF deps)."""
    def __init__(self, storage_dir: Path, wiki_name: str,
                 asserted_by: str = "agent") -> None: ...
    async def remember(self, text: str, title: str | None = None,
                       category: str = "note",
                       related_pages: list[str] | None = None) -> dict: ...
    async def search(self, query: str, top_k: int = 5,
                     max_tokens: int = 600) -> str: ...   # packed, budgeted
    async def copy_page_to(self, page_id: str, other: "BrainStore") -> str: ...

# parrot/memory/dream/runner.py
class DreamCycleRunner:
    def __init__(self, episodic_store: EpisodicMemoryStore,
                 brain: BrainStore, namespace: MemoryNamespace,
                 llm_client: Any = None,          # AbstractClient; heuristic fallback when None
                 org_brain: BrainStore | None = None,
                 config: DreamConfig | None = None) -> None: ...
    async def run_cycle(self, state: DreamState) -> DreamCycleReport: ...

# parrot/memory/dream/scheduler.py
class DreamScheduler:
    def __init__(self, runner: DreamCycleRunner, state_path: Path,
                 interval_hours: float = 24.0) -> None: ...
    async def start(self) -> None:      # loads state; catch-up if next_due < now
    async def stop(self) -> None: ...
    async def run_now(self) -> DreamCycleReport: ...

# Extension to the episodic backend protocol (backends/abstract.py)
async def update_metadata(self, episode_ids: list[str],
                          patch: dict[str, Any]) -> int:
    """Merge patch into metadata of the given episodes. Returns rows updated."""
```

`DreamConfig` (Pydantic, in `models.py`) carries: `importance_threshold=5`,
`similarity_threshold=0.75`, `max_groups_per_cycle=20`,
`org_promotion_cycles=3`, `distill_model="gemini-3.1-flash-lite"`,
`startup_jitter_seconds=60`, `failure_backoff_divisor=4`.

New `LongTermMemoryMixin` flags (class attributes, same style as existing):
`enable_brain: bool = False`, `dream_interval_hours: float = 24.0`,
`dream_importance_threshold: int = 5`, `brain_storage_dir: str | None = None`,
`brain_promote_to_org: bool = False`, `org_promotion_cycles: int = 3`.

New `MemoryConfig` fields: `enable_brain: bool = False`,
`brain_weight: float = 0.20`. When `enable_brain=True` the default weights
rebalance to `episodic=0.25, skill=0.25, brain=0.20, conversation=0.30`; the
sum-to-one validator includes `brain_weight` only when `enable_brain=True`
(existing three-weight configs keep validating unchanged).

---

## 3. Module Breakdown

> Modules map to Task Artifacts. Linear dependency chain except Modules 2/3
> which are parallelizable after Module 1.

### Module 1: Dream Models & Config
- **Path**: `parrot/memory/dream/models.py`, `parrot/memory/dream/__init__.py`
- **Responsibility**: `DreamState`, `DreamConfig`, `DistilledKnowledge`,
  `DreamCycleReport`; JSON sidecar persistence helpers for `DreamState`
  (atomic tmp+rename write, tolerant load-or-default read).
- **Depends on**: `parrot/memory/episodic/models.py` (reuses `MemoryNamespace`)

### Module 2: BrainStore
- **Path**: `parrot/memory/dream/brain.py`
- **Responsibility**: Lean wrapper over `create_wiki_store()`. `remember()`
  replicates `LLMWikiToolkit.remember()` semantics exactly (deterministic
  `mem-<sha1(title::category)[:12]>` page id, `WikiPageRecord` with
  `origin="memory"`, `asserted_by`, `references/asserted` edges).
  `search()` = `search_fts` (+ `search_vector` when embeddings rows exist),
  packed with `pack_results` under a token budget. `copy_page_to()` for org
  promotion.
- **Depends on**: `parrot.knowledge.wiki` retrieval plane (lazy exports — no
  agent framework import)

### Module 3: Backend `update_metadata`
- **Path**: `parrot/memory/episodic/backends/abstract.py` (+ `pgvector.py`,
  `redis_vector.py`, `faiss.py`), `parrot/memory/episodic/store.py`
- **Responsibility**: Add `update_metadata(episode_ids, patch) -> int` to the
  `AbstractEpisodeBackend` protocol and all three backends (SQL JSONB merge
  for PgVector; JSON field rewrite for Redis; in-memory dict merge + persist
  for FAISS). Add `EpisodicMemoryStore.mark_consolidated(episode_ids, page_id)`
  passthrough. Runner must tolerate backends lacking the method
  (`hasattr` check → watermark-only mode).
- **Depends on**: nothing new (parallel with Module 2)

### Module 4: DreamCycleRunner
- **Path**: `parrot/memory/dream/runner.py`
- **Responsibility**: collect → cluster → distill → archive → mark → promote
  pipeline per §2 Overview. One LLM call per group; group cap; skip-on-failure
  per group (WARNING + retry next cycle); watermark advance rule; heuristic
  distill fallback when no LLM client configured (concatenate lessons,
  title from dominant category — mirrors `ReflectionEngine`'s
  heuristic-fallback philosophy).
- **Depends on**: Modules 1, 2, 3

### Module 5: DreamScheduler
- **Path**: `parrot/memory/dream/scheduler.py`
- **Responsibility**: asyncio task lifecycle (`start`/`stop`/`run_now`),
  DreamState load/persist, catch-up on start when `next_due < now` (with
  0–60s jitter), per-agent lock via `running`/`running_since` (stale after
  2× interval), reschedule with `interval/4` backoff when the wiki store is
  unavailable, structured cycle logging (`DreamCycleReport`).
- **Depends on**: Modules 1, 4

### Module 6: Unified Layer Integration
- **Path**: `parrot/memory/unified/models.py`, `context.py`, `manager.py`
- **Responsibility**: `MemoryContext.semantic_knowledge` field +
  `to_prompt_string()` section; `ContextAssembler.assemble()` fourth
  parameter; `MemoryConfig.enable_brain`/`brain_weight` + conditional weight
  validation and rebalanced defaults; `UnifiedMemoryManager.__init__` gains
  `brain: BrainStore | None = None` and optional `org_brain`;
  `_get_brain_knowledge()` runs in the existing parallel gather; brain
  failures degrade to empty section (never raise).
- **Depends on**: Module 2

### Module 7: Mixin Wiring, Exports & Docs
- **Path**: `parrot/memory/unified/mixin.py`, `parrot/memory/dream/__init__.py`,
  `parrot/memory/__init__.py`, `docs/`
- **Responsibility**: `LongTermMemoryMixin` brain flags; construct
  `BrainStore`(s) + `DreamCycleRunner` + `DreamScheduler` in
  `_configure_long_term_memory()` when `enable_brain=True`; stop scheduler in
  cleanup; public exports; short doc page `docs/dream-cycle.md` linking to
  `docs/llm-wiki.md`.
- **Depends on**: Modules 5, 6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_dream_state_roundtrip` | 1 | JSON sidecar persist/load; atomic write; load-or-default on missing/corrupt file |
| `test_dream_config_defaults` | 1 | Threshold 5, cap 20, promotion cycles 3, interval 24h |
| `test_brainstore_remember_idempotent` | 2 | Same title+category twice → one page, status updated |
| `test_brainstore_page_id_matches_llmwikitoolkit` | 2 | `mem-<sha1(title::category)[:12]>` — byte-identical to `LLMWikiToolkit.remember()` scheme |
| `test_brainstore_search_fts` | 2 | FTS retrieval returns packed, budgeted text |
| `test_brainstore_copy_page_to` | 2 | Page copied to org store with attribution preserved |
| `test_update_metadata_faiss` | 3 | Patch merged; returns count; unknown ids ignored |
| `test_update_metadata_pgvector` | 3 | JSONB merge SQL (mocked/asyncpg fake) |
| `test_update_metadata_redis` | 3 | JSON rewrite (fakeredis or mock) |
| `test_collect_eligibility` | 4 | importance>=threshold OR lesson_learned; skips already-consolidated; respects watermark `since` |
| `test_cluster_by_embedding` | 4 | Fake embeddings; 0.75 threshold; fallback grouping by category+tools when provider absent |
| `test_distill_llm_contract` | 4 | Mock LLM → `DistilledKnowledge` parsed; malformed JSON → group skipped (not crash) |
| `test_distill_heuristic_fallback` | 4 | No LLM client → deterministic distillation from lessons |
| `test_cycle_idempotent` | 4 | Two runs over same episodes → one page, no duplicate marks |
| `test_group_cap_and_watermark` | 4 | >20 groups → excess deferred; last_run = newest consolidated episode, not now |
| `test_promotion_after_n_cycles` | 4 | reinforcement_counts crosses 3 → page in org store, recorded in promoted_pages |
| `test_scheduler_catchup_on_start` | 5 | next_due in the past → immediate cycle at start() |
| `test_scheduler_stale_lock` | 5 | running=True, running_since > 2×interval → lock ignored |
| `test_scheduler_backoff_on_store_failure` | 5 | Store raises → abort clean, next_due = now + interval/4 |
| `test_context_assembler_four_sections` | 6 | semantic_knowledge budgeted at brain_weight |
| `test_memory_config_weight_rebalance` | 6 | enable_brain=True → 4-weight validation; False → legacy 3-weight validation intact |
| `test_manager_brain_parallel_and_degrade` | 6 | Brain queried in gather; brain exception → empty section, ask context still produced |
| `test_mixin_brain_disabled_noop` | 7 | enable_brain=False → no scheduler, zero behavior change |
| `test_mixin_brain_lifecycle` | 7 | configure starts scheduler; cleanup stops it |

### Integration Tests

| Test | Description |
|---|---|
| `test_dream_end_to_end` | FAISS episodic backend + SQLite wiki in tmpdir: record episodes → `run_now()` → page exists in brain wiki → `get_context_for_query()` on a similar query returns the distilled knowledge in `semantic_knowledge` |
| `test_dream_crash_recovery` | Simulate crash mid-cycle (kill after archive, before state save) → rerun → no duplicate pages, marks converge |

### Test Data / Fixtures

```python
@pytest.fixture
def namespace():
    return MemoryNamespace(org_id="test-org", agent_id="test-agent", user_id="u1")

@pytest.fixture
def fake_embeddings(monkeypatch):
    """Deterministic EpisodeEmbeddingProvider substitute (no model download)."""

@pytest.fixture
def mock_distill_llm():
    """AbstractClient stub returning canned DistilledKnowledge JSON."""

@pytest.fixture
async def brain_store(tmp_path):
    return BrainStore(tmp_path / "brain", wiki_name="brain-test-agent")
```

All tests run offline — no API keys, no network, no model downloads (pattern:
existing `tests/` episodic suites). Location: `tests/memory/dream/` (new) and
existing `tests/memory/unified/` extended.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `pytest tests/memory/dream/ -v` passes (all new unit tests)
- [ ] `pytest tests/memory/unified/ -v` passes (extended + pre-existing tests untouched)
- [ ] Integration `test_dream_end_to_end` passes offline (no API keys)
- [ ] With `enable_brain=False` (default): zero behavior change — full
      existing test suite for `parrot/memory/` passes without modification
- [ ] Dream cycle is idempotent: re-running over the same episodes produces no
      duplicate pages (deterministic page ids) and no duplicate marks
- [ ] Missed-run catch-up: a `DreamState` with `next_due` in the past triggers
      a cycle at `scheduler.start()`
- [ ] Consolidated episodes carry `metadata["consolidated_into"] = <page_id>`
      on all three backends
- [ ] Org promotion only after >= `org_promotion_cycles` distinct-cycle
      reinforcements, with `asserted_by` attribution
- [ ] One LLM call per group (never per episode); groups capped per cycle;
      watermark advances only over consolidated episodes
- [ ] Memory never raises into `ask()`: brain retrieval/store failures degrade
      to an empty `semantic_knowledge` section (WARNING logged)
- [ ] Brain `wiki.db` remains readable by `LLMWikiToolkit` and the
      `wikitoolkit` CLI (same store format, verified in a test)
- [ ] Docs: `docs/dream-cycle.md` added; `docs/llm-wiki.md` cross-linked
- [ ] No new external dependencies

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `wikitoolkit query`
> / `grep` / `read`. All paths relative to `packages/ai-parrot/src/`.

### Verified Imports

```python
from parrot.memory.episodic.models import (        # models.py
    EpisodicMemory,        # class at models.py:55; metadata dict field at :164;
                           # episode_id :65; lesson_learned :126; importance :138
    MemoryNamespace,       # models.py:214
    EpisodeCategory, EpisodeOutcome,
)
from parrot.memory.episodic.store import EpisodicMemoryStore   # store.py:57
from parrot.memory.episodic.backends.abstract import AbstractEpisodeBackend  # abstract.py:11
from parrot.memory.episodic.embedding import EpisodeEmbeddingProvider  # embedding.py:20
from parrot.memory.unified import (                # unified/__init__.py (eager imports)
    MemoryContext,         # models.py:12; to_prompt_string() :43
    MemoryConfig,          # models.py:78; weights :119/:125/:131; validator :145
    ContextAssembler,      # context.py:17; assemble() :49
    UnifiedMemoryManager,  # manager.py:49; __init__ :79; get_context_for_query :131
    LongTermMemoryMixin,   # mixin.py:21; _configure_long_term_memory :63;
                           # get_memory_context :119; _post_response_memory_hook :154
)
from parrot.knowledge.wiki import (                # lazy PEP 562 exports, __init__.py
    create_wiki_store,     # store.py (factory)
    WikiPageRecord,        # store.py:194
    SQLiteWikiStore,       # store.py:420
    pack_results,          # context.py
)
```

### Existing Class Signatures

```python
# parrot/memory/episodic/backends/abstract.py
@runtime_checkable
class AbstractEpisodeBackend(Protocol):                       # line 11
    async def store(self, episode: EpisodicMemory) -> str: ...            # :18
    async def search_similar(self, embedding, namespace_filter,
                             top_k=5, score_threshold=0.3,
                             include_failures_only=False) -> list[...]: ... # :29
    async def get_recent(self, namespace_filter: dict[str, Any],
                         limit: int = 10,
                         since: datetime | None = None) -> list[EpisodicMemory]: ...  # :51
                         # ^ `since` already exists — collect() needs NO new read method
    async def get_failures(self, agent_id, tenant_id="default", limit=5): ...  # :69
    async def delete_expired(self) -> int: ...                              # :87
    async def count(self, namespace_filter) -> int: ...                     # :95

# Backend implementations (concrete classes, NOT Protocol subclasses):
#   PgVectorBackend    backends/pgvector.py:66
#   RedisVectorBackend backends/redis_vector.py:145
#   FAISSBackend       backends/faiss.py:54

# parrot/memory/episodic/store.py
class EpisodicMemoryStore:                                    # line 57
    def __init__(self, backend, embedding_provider: EpisodeEmbeddingProvider | None = None,
                 ...):                                        # :86; stores self._embedding :97
    async def record_episode(...) -> EpisodicMemory: ...      # :106
    async def recall_similar(...) -> list[EpisodeSearchResult]: ...  # :377
    async def get_failure_warnings(...) -> str: ...           # :436

# parrot/memory/unified/manager.py
class UnifiedMemoryManager:                                   # line 49
    def __init__(self, namespace: MemoryNamespace,
                 conversation_memory=None, episodic_store=None,
                 skill_registry=None, config=None,
                 cross_domain_router=None) -> None: ...       # :79  ← add brain here
    async def get_context_for_query(...): ...                 # :131
    async def record_interaction(...): ...                    # :167
    def _subsystems(self) -> list[tuple[str, Any]]: ...       # :360

# parrot/knowledge/wiki/toolkit.py — reference semantics for BrainStore.remember()
class LLMWikiToolkit(AbstractToolkit):                        # line 46
    def __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit,
                 config: WikiConfig, agent_id: str = "agent", **kwargs): ...  # :76
    async def remember(self, wiki_name, text, title=None, category="note",
                       related_pages=None) -> dict: ...       # :660
        # page_id = "mem-" + sha1(f"{title}::{category}").hexdigest()[:12]
        # WikiPageRecord(origin="memory", asserted_by=f"agent:{self.agent_id}",
        #                summary=text[:300], token_count=estimate_tokens(text))
        # edges: (page_id, related, "references", "asserted")
    async def search_compact(...): ...                        # :865

# parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):                                     # line 268
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...  # :287
    async def add_edges(self, edges: list[tuple]) -> int: ...              # :290
    async def get_page(self, concept_id, include_body=False): ...          # :310
    async def search_fts(...): ...                                         # :323
    async def search_vector(...): ...                                      # :328
class SQLiteWikiStore(BaseWikiStore):                         # line 420
    def __init__(self, db_path: str | Path, wiki_name: str = "") -> None:  # :435
# WikiPageRecord fields (store.py:194): concept_id, node_id, title, category,
#   summary, body, token_count, origin, asserted_by (verify full list before use)

# parrot/memory/episodic/reflection.py — pattern reference for distill
# REFLECTION_PROMPT (line ~20): JSON-only contract prompt; AbstractClient is
# imported TYPE_CHECKING-only from parrot.clients.base
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DreamCycleRunner.collect` | `AbstractEpisodeBackend.get_recent(since=...)` | method call | `backends/abstract.py:51` |
| `DreamCycleRunner.mark` | new `update_metadata()` | method call (hasattr-guarded) | added by Module 3 |
| `BrainStore.remember` | `BaseWikiStore.upsert_pages` / `add_edges` | method call | `wiki/store.py:287,290` |
| `BrainStore.search` | `search_fts` / `search_vector` + `pack_results` | method call | `wiki/store.py:323,328` |
| `UnifiedMemoryManager._get_brain_knowledge` | `BrainStore.search` | parallel gather branch | `unified/manager.py:131` (pattern) |
| `ContextAssembler.assemble` | new 4th param | signature extension | `unified/context.py:49` |
| `LongTermMemoryMixin._configure_long_term_memory` | `DreamScheduler.start` | lifecycle call | `unified/mixin.py:63` |
| `DreamCycleRunner.distill` | `AbstractClient` completion | JSON-contract prompt | pattern at `episodic/reflection.py:20` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractEpisodicBackend`~~ — the protocol is named **`AbstractEpisodeBackend`** (no "ic")
- ~~`AbstractEpisodeBackend.update_metadata()`~~ — does NOT exist yet; Module 3 creates it
- ~~`EpisodicMemoryStore.mark_consolidated()`~~ — does NOT exist yet; Module 3 creates it
- ~~`EpisodicMemoryToolkit` in `parrot/tools/`~~ — it lives at `parrot/memory/episodic/tools.py:22`
- ~~a `dream_state` table in `wiki.db`~~ — DreamState is a **JSON sidecar** (`dream_state.json` next to the wiki dir), NOT a SQLite table; do not touch the wiki schema
- ~~`WikiPageRecord.metadata` / `reinforcement_count` on pages~~ — unverified; reinforcement is tracked in `DreamState.reinforcement_counts`, NOT on the page record
- ~~`LLMWikiToolkit` lightweight constructor~~ — it REQUIRES pageindex/graphindex/okf toolkits (`toolkit.py:76`); that is exactly why `BrainStore` exists
- ~~`UnifiedMemoryManager.get_context()`~~ — the method is `get_context_for_query()` (`manager.py:131`)
- ~~`parrot/bots/` hooks for dream~~ — scheduler is wired ONLY through `LongTermMemoryMixin`; no `AbstractBot` changes in this feature

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first throughout; Pydantic v2 models; Google-style docstrings +
  strict type hints; `self.logger` (never print).
- **Memory never raises — it degrades**: every retrieval/consolidation failure
  logs WARNING and continues (same principle as FEAT-055 subsystems and
  `OntologyRAGMixin`).
- Distill prompt: JSON-only contract with heuristic fallback, mirroring
  `ReflectionEngine` (`episodic/reflection.py`). Import `AbstractClient` under
  `TYPE_CHECKING` only, accept `Any` at runtime (same file shows the pattern).
- `BrainStore.remember()` MUST reproduce `LLMWikiToolkit.remember()` page-id
  and record semantics byte-for-byte (`toolkit.py:660-725`) so both surfaces
  stay interoperable on the same `wiki.db`.
- Wiki naming: `brain-<agent_id>` and `org-<org_id>`; storage dir from
  `brain_storage_dir` mixin flag (default: a `.brain/` dir under the agent's
  working/static dir — resolve concretely during Module 7).
- DreamState JSON writes: `tempfile` + `os.replace` (atomic), tolerant reads.
- Follow existing test layout under `tests/memory/` (offline, fixture-driven).

### Known Risks / Gotchas

- **MemoryConfig weight validator**: existing validator (`models.py:145`)
  hard-fails when 3 weights != 1.0. The conditional 4-weight extension must
  keep every existing config valid — cover with regression tests.
- **`update_metadata` on FAISS**: FAISS backend persists episodes in-memory /
  file; ensure the patch survives its persistence round-trip.
- **PgVector JSONB merge**: use `metadata || $patch::jsonb` (merge), never
  full-column overwrite (concurrent writers).
- **Stale locks**: `running_since` older than 2× interval is ignored —
  document that two *live* processes sharing one state file is unsupported
  (single-process assumption, like the rest of the in-process stack).
- **Distill hallucination**: cap body length; `confidence` below 0.3 →
  archive as `category="note"` (not `lesson`) so low-confidence output never
  masquerades as a learned rule.
- **Watermark vs clock skew**: watermark derives from episode `created_at`
  (DB-side), never `datetime.now()` at the runner.
- **aiosqlite is already a dependency** of the wiki plane (`store.py:37`) —
  no new packages.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | None new. `aiosqlite`, `pydantic>=2`, `faiss-cpu`, `redis`, `asyncpg` already in project |

---

## 8. Open Questions

> Resolved during the 2026-07-30 interactive brainstorm (decision trail):

- [x] Online vs offline consolidation — *Resolved in brainstorm*: offline
  "dream cycle", in-process scheduler, periodic + explicit, catch-up at
  startup after missed runs.
- [x] Brain scope — *Resolved in brainstorm*: hybrid — per-agent wiki
  (`brain-<agent_id>`) + promotion to org wiki (`org-<org_id>`) after
  reinforcement in >= 3 distinct cycles.
- [x] Scheduler host — *Resolved in brainstorm*: in-process asyncio with
  persisted state (option "In-process + estado persistido"); CLI entry point
  deferred.
- [x] Episode lifecycle post-consolidation — *Resolved in brainstorm*: mark
  with `consolidated_into=<page_id>`; existing TTL/compaction prunes; dream
  cycle never deletes.
- [x] Wiki access layer — *Resolved in brainstorm*: lean `BrainStore` over
  `create_wiki_store` (same `wiki.db` format); full `LLMWikiToolkit` NOT
  required for brain-enabled agents.
- [x] Distill LLM — *Resolved in brainstorm*: configurable, default
  `gemini-3.1-flash-lite` (consistent with FEAT-055 reflection decision).

> Still open (do not block implementation):

- [ ] Default `brain_storage_dir` resolution when the agent has no working
  dir configured (env var? `~/.parrot/brains/<agent_id>`?) — decide in
  Module 7. — *Owner: Jesus Lara*: `~/.parrot/brains/<agent_id>`
- [x] Should `record_lesson` (episodic toolkit) episodes get an eligibility
  fast-path (always consolidate regardless of importance)? Current rule
  already includes them via non-empty `lesson_learned`. — *Owner: Jesus Lara*: preferable yes, but not a must.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — one worktree, tasks sequential.
- **Parallelizable exception**: Modules 2 (BrainStore) and 3 (backend
  `update_metadata`) are independent after Module 1; MAY be split across
  agents, but the default sdd-worker sequential flow is fine.
- **Cross-feature dependencies**: FEAT-055 (`parrot/memory/unified/`) and
  FEAT-260 (`parrot/knowledge/wiki/` retrieval plane) — both already merged
  on `dev`. No pending-merge blockers.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-30 | Jesus Lara | Initial draft from interactive brainstorm (Claude-assisted) |
