# TASK-1986: DreamCycleRunner — collect → cluster → distill → archive → mark → promote

**Feature**: FEAT-390 — Dream Cycle — Episodic→Wiki Brain Consolidation
**Spec**: `sdd/specs/dream-cycle-brain-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1983, TASK-1984, TASK-1985
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 — the heart of the feature. One dream cycle distills a batch
of eligible episodes into wiki pages in the agent's brain, marks the episodes,
and promotes recurrently-reinforced pages to the org wiki. Full pipeline
definition: spec §2 Overview (steps 1–6) and the flow diagram approved in the
brainstorm.

---

## Scope

Implement `parrot/memory/dream/runner.py` with class `DreamCycleRunner`:

- `__init__(self, episodic_store, brain, namespace, llm_client=None,
  org_brain=None, config: DreamConfig | None = None)`.
- `async run_cycle(self, state: DreamState) -> DreamCycleReport` orchestrating:
  1. **collect** — `backend.get_recent(namespace_filter, limit=<generous>,
     since=state.last_run)`; filter eligibility: (`importance >=
     config.importance_threshold` OR non-empty `lesson_learned`) AND
     `"consolidated_into" not in episode.metadata`.
  2. **cluster** — embed `episode.situation + lesson_learned` via the store's
     embedding provider when available; greedy grouping by cosine >=
     `config.similarity_threshold` (0.75). Fallback (no provider): group by
     `(category, tuple(sorted(related_tools)))`. Cap at
     `config.max_groups_per_cycle` (defer the rest).
  3. **distill** — one LLM call per group with a JSON-only prompt (pattern:
     `REFLECTION_PROMPT` in `episodic/reflection.py`) → parse into
     `DistilledKnowledge`. Malformed JSON or LLM error → count in
     `groups_skipped`, log WARNING, continue. No `llm_client` → heuristic
     fallback: concatenate the group's `lesson_learned` lines, title from the
     dominant category. `confidence < 0.3` → force `category="note"`.
  4. **archive** — `brain.remember(body, title=..., category=...)`; collect
     page_ids in the report; increment `state.reinforcement_counts[page_id]`
     ONCE per cycle per page (status "updated" counts as reinforcement).
  5. **mark** — `episodic_store.mark_consolidated(group_episode_ids, page_id)`.
  6. **promote** — when `org_brain` is set and
     `state.reinforcement_counts[page_id] >= config.org_promotion_cycles`
     and `page_id not in state.promoted_pages` →
     `brain.copy_page_to(page_id, org_brain)`; record in
     `state.promoted_pages` and the report.
- Watermark rule: on success set `state.last_run` to the **`created_at` of the
  newest consolidated episode** (NOT `datetime.now()`); leave unchanged if
  nothing consolidated. Update `state.cycles_completed`,
  `state.episodes_consolidated`.
- Wiki-store failure (archive step raises) → abort the cycle cleanly:
  `report.aborted=True`, `abort_reason` set; do NOT advance the watermark.
- Unit tests in `tests/memory/dream/test_runner.py`.

**NOT in scope**: scheduling/locking/state persistence (TASK-1987), unified
retrieval (TASK-1988), mixin flags (TASK-1989).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/dream/runner.py` | CREATE | `DreamCycleRunner` |
| `packages/ai-parrot/src/parrot/memory/dream/__init__.py` | MODIFY | Export `DreamCycleRunner` |
| `tests/memory/dream/test_runner.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory.dream import (  # created by TASK-1983/1984
    BrainStore, DistilledKnowledge, DreamConfig, DreamCycleReport, DreamState,
)
from parrot.memory.episodic.models import EpisodicMemory, MemoryNamespace
# models.py:55 / :214
from parrot.memory.episodic.store import EpisodicMemoryStore   # store.py:57
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py:51
async def get_recent(self, namespace_filter: dict[str, Any], limit: int = 10,
                     since: datetime | None = None) -> list[EpisodicMemory]
# `since` EXISTS — collect() needs no new read method.
# Verify how EpisodicMemoryStore builds namespace_filter dicts from
# MemoryNamespace (read store.py recall/record methods) and reuse that idiom.

# packages/ai-parrot/src/parrot/memory/episodic/models.py
class EpisodicMemory(BaseModel):          # :55
    episode_id: str                       # :65
    lesson_learned: str | None            # :126
    importance: int                       # :138
    metadata: dict[str, Any]              # :164
    # `created_at` — verify exact field name at models.py:55-165 before use

# packages/ai-parrot/src/parrot/memory/episodic/store.py
class EpisodicMemoryStore:                # :57
    # embedding provider stored as self._embedding (:97); may be None.
    # TASK-1985 adds: async def mark_consolidated(episode_ids, page_id) -> int

# packages/ai-parrot/src/parrot/memory/dream/brain.py (TASK-1984)
class BrainStore:
    async def remember(text, title=None, category="note",
                       related_pages=None) -> dict   # {page_id,title,category,status}
    async def copy_page_to(page_id, other) -> str

# Distill prompt pattern — packages/ai-parrot/src/parrot/memory/episodic/reflection.py:~20
# REFLECTION_PROMPT: JSON-only contract ("Respond ONLY with the JSON object").
# AbstractClient imported under TYPE_CHECKING from parrot.clients.base;
# runner accepts llm_client: Any and calls it the same way ReflectionEngine
# does — READ reflection.py's LLM-call method to copy the exact invocation.
```

### Does NOT Exist
- ~~`EpisodicMemoryStore.get_unconsolidated()`~~ — use `backend.get_recent(since=...)` + in-runner filtering
- ~~`ReflectionEngine.distill()`~~ — ReflectionEngine is a *pattern reference* only; do not import/extend it
- ~~page-level reinforcement metadata~~ — counts live in `DreamState.reinforcement_counts`
- ~~`datetime.now()` watermark~~ — forbidden; watermark = newest consolidated episode's `created_at`

---

## Implementation Notes

### Pattern to Follow
```python
# reflection.py's JSON-contract style for the distill prompt:
DISTILL_PROMPT = """Analyze these related agent episodes and distill ONE piece of durable knowledge.

## Episodes
{episodes_block}

## Instructions
Respond with a JSON object with exactly these fields:
- "title": short title (max 80 chars)
- "body": the distilled knowledge in markdown (what to remember and why)
- "category": one of "lesson", "decision", "concept", "note"
- "confidence": 0.0-1.0 — how well-supported this knowledge is by the episodes

Respond ONLY with the JSON object, no markdown or extra text."""
```

### Key Constraints
- Async throughout; Pydantic models; `self.logger`; Google-style docstrings.
- **Memory never raises**: `run_cycle` catches per-group errors (skip) and
  store-level errors (clean abort with report) — it must never propagate.
- Cosine similarity: plain-python/numpy helper in the runner (no new deps);
  greedy single-pass clustering is sufficient (first episode of a cluster is
  its centroid).
- Body length cap (e.g. 4000 chars) on distilled output (spec §7 risk).
- One reinforcement increment per page per cycle, even if several groups map
  to the same page id.

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/episodic/reflection.py` — LLM call + JSON parse + heuristic fallback style
- `packages/ai-parrot/src/parrot/memory/episodic/recall.py` — scoring/similarity idioms
- Spec §2 Overview — authoritative step-by-step definition

---

## Acceptance Criteria

- [ ] Eligibility: importance>=threshold OR lesson_learned; already-consolidated skipped; `since` watermark respected
- [ ] Clustering: fake embeddings group at 0.75; provider-less fallback groups by category+tools
- [ ] Distill: mock LLM → `DistilledKnowledge`; malformed JSON → group skipped, cycle continues
- [ ] Heuristic fallback distills without any LLM client
- [ ] Idempotent: running twice over the same episodes yields one page and no duplicate marks
- [ ] Group cap defers excess; watermark = newest consolidated `created_at`
- [ ] Promotion fires only at >= `org_promotion_cycles` distinct cycles; recorded in `promoted_pages`
- [ ] Store failure → `aborted=True`, watermark unchanged
- [ ] All tests pass: `pytest tests/memory/dream/test_runner.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/dream/`

---

## Test Specification

```python
# tests/memory/dream/test_runner.py
import pytest
from parrot.memory.dream import DreamConfig, DreamCycleRunner, DreamState


class TestCollect:
    async def test_eligibility_threshold_or_lesson(self, runner_with_episodes): ...
    async def test_skips_consolidated(self, runner_with_episodes): ...
    async def test_respects_watermark(self, runner_with_episodes): ...


class TestCluster:
    async def test_groups_by_embedding_similarity(self, runner_fake_embeddings): ...
    async def test_fallback_category_grouping(self, runner_no_embeddings): ...
    async def test_group_cap_defers_excess(self, runner_many_groups): ...


class TestDistill:
    async def test_llm_json_contract(self, runner_mock_llm): ...
    async def test_malformed_json_skips_group(self, runner_bad_llm): ...
    async def test_heuristic_fallback_no_llm(self, runner_no_llm): ...
    async def test_low_confidence_becomes_note(self, runner_mock_llm): ...


class TestCycle:
    async def test_idempotent_two_runs(self, runner_full): ...
    async def test_watermark_advances_to_newest_consolidated(self, runner_full): ...
    async def test_promotion_after_n_cycles(self, runner_with_org): ...
    async def test_store_failure_aborts_clean(self, runner_broken_brain): ...
```

Fixtures: FAISS episodic backend (offline), `BrainStore` on tmp_path,
deterministic fake embedding provider, stub LLM client returning canned JSON.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1983, TASK-1984, TASK-1985 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — especially `EpisodicMemory.created_at`
   field name, `EpisodicMemoryStore` backend/embedding attribute names, and
   `reflection.py`'s exact LLM invocation
4. **Update status** in `sdd/tasks/index/dream-cycle-brain-consolidation.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1986-dream-runner.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-30
**Notes**: Implemented `DreamCycleRunner` (`parrot/memory/dream/runner.py`)
per spec §2 Overview: `_collect` filters `get_recent(since=state.last_run)`
by (`importance>=threshold` OR `lesson_learned`) AND not already
`consolidated_into`, sorted **ascending** by `created_at` (a deliberate
implementation detail — see Deviations); `_cluster` embeds
`situation + lesson_learned` via the store's `_embedding` provider
(greedy single-pass, cosine >= 0.75, first episode = centroid) or falls
back to `(category, sorted related_tools)` grouping; `_distill` makes one
LLM call per group via `AbstractClient.ask(structured_output=
DistilledKnowledge)` (same extraction idiom as `ReflectionEngine`,
verified against `reflection.py` before writing) with a deterministic
heuristic fallback when no `llm_client` is configured; `_archive` calls
`brain.remember()` and aborts the cycle cleanly (watermark untouched) if
it raises; `_mark` calls the TASK-1985 `mark_consolidated()`; `_promote`
copies to `org_brain` once `reinforcement_counts[page_id] >=
org_promotion_cycles`. Confidence < 0.3 forces `category="note"`. 14 new
unit tests pass covering collect eligibility/watermark/consolidated-skip,
embedding + fallback clustering, group cap, LLM JSON contract + malformed
JSON skip + heuristic fallback + low-confidence override, idempotent
double-run, watermark advance, promotion after N cycles, and clean abort
on archive failure. `ruff check` clean.

**Deviations from spec**: The spec's watermark rule ("advances to the
`created_at` of the newest **consolidated** episode... so the excess is
picked up next cycle") only holds correctly if excess/deferred groups are
never *older* than the watermark advanced from processed groups —
otherwise a deferred-but-older episode would fall outside next cycle's
`since` filter and be silently lost. Backend `get_recent()` returns
episodes newest-first (DESC), so `_collect` explicitly re-sorts the
eligible episodes **ascending** by `created_at` before clustering/capping,
guaranteeing capped/deferred groups are always the newest ones (i.e.
always newer than the watermark advanced from the processed, older
groups). This is an implementation detail filling a gap the spec doesn't
spell out explicitly, not a behavioral deviation from the stated
acceptance criteria — `test_group_cap_and_watermark`-equivalent coverage
(`TestCluster::test_group_cap_defers_excess`,
`TestCycle::test_watermark_advances_to_newest_consolidated`) passes.
