# Dream Cycle — episodic → wiki brain consolidation

> An offline, periodic "dream cycle" that distills an agent's episodic
> memories into durable semantic knowledge on its personal LLM wiki (its
> **brain**), then retro-feeds that knowledge back into `ask()`.

## The idea

`EpisodicMemoryStore` ([Episodic memory](./chapters/memory-knowledge.md))
accumulates raw evidence of what an agent did and what happened — but that
evidence is eventually pruned by TTL/compaction, and nothing turns recurring
experience into durable, reusable knowledge. The **LLM Wiki**
(`parrot.knowledge.wiki`, see [LLM Wiki](./llm-wiki.md)) can hold durable
pages, but it only grows when an agent explicitly calls `wiki_remember`.

The dream cycle is the missing consolidation stage — working → episodic →
**semantic** — modeled on how sleep consolidates memory in biological
systems: periodically, offline, an agent "dreams" over its recent episodes,
distills the recurring patterns into wiki pages, and wakes up with a
slightly better brain.

## How the pieces map

| Concept | AI-Parrot subsystem | Module |
| --- | --- | --- |
| raw evidence | `EpisodicMemoryStore` | `parrot.memory.episodic` |
| the agent's brain | `BrainStore` (lean LLM-wiki wrapper) | `parrot.memory.dream.brain` |
| one consolidation pass | `DreamCycleRunner` | `parrot.memory.dream.runner` |
| periodic execution + catch-up | `DreamScheduler` | `parrot.memory.dream.scheduler` |
| retro-feed into `ask()` | `UnifiedMemoryManager` fourth section | `parrot.memory.unified.manager` |
| opt-in wiring | `LongTermMemoryMixin` brain flags | `parrot.memory.unified.mixin` |

## The pipeline (one cycle)

`DreamCycleRunner.run_cycle()` runs six steps:

1. **collect** — pulls episodes since the last watermark where
   `importance >= threshold` OR the episode carries a `lesson_learned`, and
   which are not already consolidated.
2. **cluster** — groups episodes by embedding cosine similarity when an
   embedding provider is configured; otherwise falls back to grouping by
   `(category, related_tools)`.
3. **distill** — one LLM call per group (JSON-only contract, same pattern
   as `ReflectionEngine`) produces a title/body/category/confidence; with
   no LLM client configured, a deterministic heuristic (concatenated
   lessons) is used instead. Low-confidence output (`< 0.3`) is archived as
   `category="note"` rather than a `"lesson"`, so it never masquerades as a
   learned rule.
4. **archive** — upserts the distilled page into the agent's brain wiki via
   `BrainStore.remember()` — a deterministic page id
   (`mem-<sha1(title::category)>`) makes re-running a crashed cycle safe
   (idempotent, no duplicate pages).
5. **mark** — patches the consolidated episodes with
   `metadata["consolidated_into"] = <page_id>` via
   `AbstractEpisodeBackend.update_metadata()`. Episodes are **never
   deleted** by the dream cycle — existing TTL/compaction keeps pruning
   them on its own schedule.
6. **promote** — a page reinforced across `org_promotion_cycles` distinct
   cycles is copied into an org-level wiki (`BrainStore.copy_page_to()`)
   with `asserted_by` attribution preserved.

The watermark advances only to the `created_at` of the newest **consolidated**
episode (never `datetime.now()`), so anything deferred by the per-cycle group
cap is picked up on the next run.

## Scheduling — in-process, with catch-up

`DreamScheduler` is a plain asyncio background task, not a cron job or
external scheduler (an explicit brainstorm decision — see the spec's Open
Questions). State (watermark, lock, reinforcement counters) persists as a
JSON sidecar (`dream_state.json`) next to the brain's `wiki.db`, written
atomically (temp file + `os.replace`).

- **Catch-up**: if `next_due` is already in the past at `start()` (the
  server was down when a cycle should have run), one cycle fires
  immediately, after a small random jitter.
- **Stale-lock detection**: a `running`/`running_since` flag pair detects a
  crash mid-cycle. A lock older than 2× the interval is treated as stale
  and ignored. Two *live* processes sharing one state file is
  unsupported — this is a single-process design, like the rest of the
  in-process memory stack.
- **Backoff**: an aborted cycle (e.g. the wiki store was unreachable)
  reschedules at `interval / failure_backoff_divisor` instead of the full
  interval.

## Retrieval — retro-feeding `ask()`

`UnifiedMemoryManager.get_context_for_query()` gains a fourth parallel
retrieval branch, `_get_brain_knowledge()`, alongside the existing episodic
warnings, relevant skills, and conversation history. It calls
`BrainStore.search()` (FTS, budgeted with `pack_results`) against the
agent's brain and, when configured, the org brain — results land in
`MemoryContext.semantic_knowledge` and the `<brain_knowledge>` section of
`to_prompt_string()`. Like every other subsystem in the unified layer, a
brain failure degrades to an empty section (WARNING logged) — it never
breaks `ask()`.

## Turning it on

Everything is opt-in via `LongTermMemoryMixin` flags — with `enable_brain=False`
(the default) zero new objects are constructed and behavior is byte-identical
to today:

```python
class MyAgent(LongTermMemoryMixin, Agent):
    enable_long_term_memory = True
    enable_brain = True                 # master toggle for the dream cycle
    dream_interval_hours = 24.0         # hours between cycles
    dream_importance_threshold = 5      # episodes below this need a lesson_learned
    brain_storage_dir = None            # default: ~/.parrot/brains/<agent_id>
    brain_promote_to_org = False        # also maintain + promote to an org wiki
    org_promotion_cycles = 3            # distinct-cycle reinforcement before promotion
```

`_configure_long_term_memory()` builds the `BrainStore`(s), a
`DreamCycleRunner`, and starts a `DreamScheduler` when `enable_brain=True`;
`_cleanup_long_term_memory()` stops the scheduler. Brain construction
failures degrade the same way every other subsystem in the mixin does — a
WARNING is logged and the agent boots without a brain.

## Notes

- The brain's `wiki.db` uses the exact same SQLite format as
  `LLMWikiToolkit` / the `wikitoolkit` CLI — `BrainStore` is a lean
  wrapper over `create_wiki_store()`, not a new storage format, so a
  brain-enabled agent's pages are fully inspectable with
  `wikitoolkit page <id>` or `wikitoolkit query`.
- One LLM call per **group**, never per episode, and capped at
  `max_groups_per_cycle` per run — cost stays bounded regardless of
  episode volume.
- No new external dependencies: `aiosqlite`, `pydantic>=2`, `faiss-cpu`, and
  `redis`/`asyncpg` (for the corresponding episodic backends) were already
  project dependencies.
- Importing `parrot.memory` never touches the wiki plane / `aiosqlite`
  unless a brain symbol is actually used — the dream package's exports
  are resolved lazily (PEP 562), the same pattern `parrot.knowledge.wiki`
  uses for its own exports.

### Known limitations

- **Collection is not paginated.** `_collect()` fetches the most recent
  `_COLLECT_LIMIT` (currently 5000) episodes since the watermark in a
  single call — `AbstractEpisodeBackend.get_recent()` has no
  offset/cursor. If more than that many *ineligible* episodes accumulate
  between dream cycles for one agent, older eligible episodes further
  back in that backlog can be starved until the backlog shrinks. This is
  a known, accepted boundary of the current read-path contract (not a bug
  fixed in this feature) — worth tracking for very high-volume agents or
  long brain-disabled periods before re-enabling.

## Read next

- [LLM Wiki](./llm-wiki.md) — the underlying wiki architecture the brain
  wiki reuses.
- [Memory & Knowledge](./chapters/memory-knowledge.md) — episodic memory
  and the unified long-term memory layer this feature extends.
