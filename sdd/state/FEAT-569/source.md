---
# SDD flow type and base branch.
type: feature
base_branch: dev
---

# Brainstorm: Agent Memory Dynamics — FSRS-based retention, outcome-driven reinforcement and consolidation over the existing episodic memory

**Date**: 2026-09-17
**Author**: Jesus Lara (drafted with Claude)
**Status**: exploration
**Recommended Option**: B
**Inspiration**: Ebbinghaus forgetting curve → Bjork & Bjork's *storage strength vs retrieval strength* → FSRS-6 (open-spaced-repetition); conversation with the author of `intellideep/nlproxy` on Ebbinghaus-style memory for long-lived autonomous agents in Rust
**Depends on**: FEAT-390 dream cycle (`sdd/specs/dream-cycle-brain-consolidation.spec.md`), SDD work ledger (`sdd/specs/sdd-work-ledger.spec.md`), per-turn compaction (`parrot.memory.compaction`)

---

## Problem Statement

ai-parrot already has the *storage* half of a long-term memory: `EpisodicMemoryStore` (pgvector / Redis / FAISS backends, namespace scoping, reflection), the FEAT-390 **dream cycle** that clusters episodes and distills them into `brain-<agent_id>` / `org-<org_id>` wiki pages, `UnifiedMemoryManager` that assembles four memory sections under a token budget, and — for the SDD pipeline — the `CoderFeedback` ledger plane that injects a model's confirmed prior corrections into every coder dispatch.

What it does not have is the *dynamics* half: nothing in the system decides **what deserves to stay retrievable, when something should fade, and which memories have proven themselves**. Concretely, verified against `main` on 2026-09-17:

1. **Recall is relevance-only.** `HybridBM25Strategy` fuses `bm25_weight * bm25 + semantic_weight * semantic` (0.4 / 0.6); the pgvector `search_hybrid` does the same with `ts_rank`. There is no time term, no access history, no "this one worked before" term. A lesson used successfully fifty times ranks exactly like one never used.
2. **Forgetting is a cliff, not a curve.** The only pruning is `expires_at` (TTL), `compact_namespace(keep_top_n=100, keep_all_failures=True)` (top-N by static importance, rest expired) and `CoderFeedbackStore.context(max_age_days=90)` (hard cutoff). A memory is either fully present or gone; nothing degrades gracefully, nothing revives on use.
3. **Outcomes are not fed back.** `EpisodicMemoryMixin._record_post_ask` records *every* `ask()` as `outcome=EpisodeOutcome.SUCCESS, importance=3`. `Skill.usefulness_score` is declared ("Can be updated based on feedback") and never written. `DreamState.reinforcement_counts` counts cycles-in-which-a-page-was-touched, per page, and only to decide org promotion; it never decays and never reads outcomes.
4. **Importance is static and assigned at write time.** `HeuristicScorer` maps outcome → base (7 failure / 5 partial / 3 success, +2 for known error types). It cannot rise because a memory kept being useful, nor fall because it kept being wrong.
5. **The same concern is implemented three times.** Episodic memory (`parrot.memory.episodic`), brain pages (`parrot.memory.dream`) and coder feedback (`parrot.knowledge.wiki.ledger.coder_feedback`) each keep their own record shape, ranking rule and ageing rule for what is, operationally, one thing: *what an agent learned from doing work*. `coder_feedback.py` has its own `(scope_score, recurrence, timestamp)` ranking and 90-day window; the dream cycle has `importance_threshold`; episodic has TTL + importance. Owner direction: **"menos es más"** — one memory flow that every agent (ai-parrot `BasicAgent`s *and* the out-of-process `sdd-worker` / `sdd-coder` subagents) reads and writes.
6. **Autonomous, long-horizon operation is the target.** These agents will run with minimal or no human feedback. The only "grades" available are the ones the runtime can verify itself: tool status, test results, review gates, recurrence of an error signature. Any design that needs a human to rate memories is out.

Who is affected: every `LongTermMemoryMixin` / `EpisodicMemoryMixin` agent, the dream cycle, `UnifiedMemoryManager` context assembly, the SDD coder engine (`_feedback_for`) and the `sdd-worker` / `sdd-coder` agent definitions.

## Constraints & Requirements

- **Probabilistic proposes, deterministic decides.** The LLM may propose importance, a lesson, a distilled page. Stability, difficulty, retrievability, promotion, demotion and forgetting are pure functions of the review log and the clock. A model's self-assessment ("I did well") is never a review grade.
- **No review without a verified outcome.** Absence of signal is not a signal: a memory recalled in a session that ends with no verifiable outcome gets no review and simply decays. This is what makes the scheme safe without humans.
- **Recall does not reinforce.** Reading a memory updates `last_accessed`; only a review (recalled + intervened + verified outcome) changes stability. This is the single rule that prevents self-reinforcing wrong memories.
- **Forgetting is a state, not a delete.** Consistent with the append-only `AuditLedger` and the compaction omission store: a forgotten memory leaves the retrieval index, stays in the backend, and can come back through relearning.
- **One write path, one ranking rule, one ageing rule** for episodes, brain pages and coder feedback. `CoderFeedback` is absorbed into episodic memory (owner decision); the ledger keeps its audit event.
- **Reachable out-of-process.** `sdd-worker`/`sdd-coder` are Claude Code subagents (`.claude/agents/*.md`), dispatched by `flows/dev_loop/sdd_coder/engine.py`; they cannot inherit a Python mixin. The **store is the contract**; the mixin, the MCP server and the CLI are clients of it.
- **Shared root for SDD** is the main worktree's `.parrot/` (same `find_shared_root()` the ledger uses); a file-local backend must tolerate N concurrent worktree agents on one host.
- **Backwards compatible.** Existing `EpisodicMemory` records, brain pages and `events.jsonl` keep working; new state is additive, defaulting to "no dynamics" (retrievability = 1) until the first review.
- **FSRS-6 complete** (difficulty + stability + learnable decay), not a home-grown exponential (owner decision): the formulas are published, MIT-licensed, have a reference implementation and an optimizer whose input is a review log — exactly the artifact the runtime can produce.
- **Language split**: identifiers, docs and events in English.
- **Validation-first**: spike gates in §Spikes before `/sdd-spec`.

---

## Options Explored

### Option A: Recency-weighted recall (exponential decay on `last_accessed`), no reviews

Add `last_accessed` / `access_count` to `EpisodicMemory`, multiply the recall score by `exp(-Δt / half_life)` with a per-category half-life, bump `last_accessed` on every recall.

✅ **Pros:**
- Tiny: one metadata patch on recall (`update_metadata` already exists on all three backends), one factor in `recall_similar`.
- Immediately fixes "old junk outranks recent lessons".

❌ **Cons:**
- Every recall reinforces, so a wrong memory that keeps getting recalled becomes immortal — the exact failure mode the owner flagged.
- No outcome dimension: a memory that caused failures and one that prevented them age identically.
- Half-life is a magic number per category with nothing to fit it against.
- Leaves the three ranking rules (episodic / brain / coder feedback) in place.

📊 **Effort:** Low

📦 **Libraries / Tools:** none new.

🔗 **Existing Code to Reuse:** `episodic/store.py::recall_similar`, `backends/abstract.py::update_metadata`.

---

### Option B: FSRS-6 dynamics layer over episodic + brain, outcome-graded, CoderFeedback absorbed — *recommended*

Give every long-term memory item (episode **and** brain page) an FSRS memory state `(stability S, difficulty D, last_review, review_count, lapse_count)`. Retrievability `R(t, S)` is computed at read time and multiplies the relevance score. A **review** happens only when a memory was recalled into a session/task **and** that session/task closed with a **verified outcome**; a deterministic **grade function** maps the outcome to FSRS ratings (Again / Hard / Good / Easy). Reviews are appended to a **review log** (the FSRS optimizer's input format) so parameters can be fitted offline once there is volume. The dream cycle collects by retrievability instead of static importance, propagates state to distilled pages, and uses rising difficulty as a "re-distill this lesson" signal. Memories below a retrievability floor become `forgotten` (excluded from recall/collect, still stored). `CoderFeedback` records become episodes (`category=error_recovery`, new namespace scope `model_id`), the `coder_feedback` context becomes a `recall_similar` call, and the ledger keeps emitting `insight.recorded` for audit.

✅ **Pros:**
- Published, fitted, versioned algorithm (FSRS-6, 21 parameters) with an MIT reference implementation (`py-fsrs`) and an optimizer; nothing to invent except the grade function, which is where the domain knowledge belongs.
- Separates *retrievability* (should this surface now?) from *stability* (has this proven itself?) — Bjork & Bjork's retrieval strength vs storage strength — which is precisely the split Option A collapses.
- Difficulty gives an actionable autonomous signal: a lesson that keeps being injected while its error signature keeps recurring is a lesson that does not work as written.
- Collapses three ranking/ageing rules into one; `CoderFeedback` fields map 1:1 onto `EpisodicMemory` (see §Internal Behavior).
- Additive: FSRS state lives in `metadata["fsrs"]` in v1, so **no backend DDL change** is needed for pgvector/Redis/FAISS; `update_metadata` is the write primitive.
- Review log doubles as the audit trail for "why is this memory ranked here".

❌ **Cons:**
- FSRS default parameters are fitted to human flashcard logs; agent time scales differ. Cold start needs a spike (§S1), and fitting needs volume.
- Attribution ("did this memory intervene in this outcome?") is inherently noisy for non-instructed agents; needs an explicit-citation path (SDD) and an overlap heuristic (generic agents).
- Slightly more state per item and one more append-only log.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| FSRS-6 formulas (vendored, ~150 lines) | `parrot.memory.dynamics.fsrs` | MIT; vendor to avoid a runtime dep and to control the rating source |
| `fsrs[optimizer]` (`py-fsrs`) | offline parameter fitting from `reviews.jsonl` | dev/ops extra only, never imported by the runtime |
| `aiosqlite` (already) | file-local episodic backend for SDD (spike S2) | reuse `SQLiteWikiStore.search_vector` or a sibling table |

🔗 **Existing Code to Reuse:** see §Code Context — `EpisodicMemoryStore`, `AbstractEpisodeBackend.update_metadata`, `HybridBM25Strategy`, `DreamCycleRunner`, `BrainStore`, `UnifiedMemoryManager` / `ContextAssembler`, `CoderFeedbackStore`, `CoderReviewStore`, `LedgerLog`, `find_shared_root`.

---

### Option C: ACT-R base-level activation (Anderson & Schooler) instead of FSRS

Rank by `B_i = ln Σ_j t_j^{-d}` over the full access history (recency × frequency, power-law), which is the classic rational-analysis model of memory and matches "need probability" in environments remarkably well.

✅ **Pros:**
- Strong theory; frequency and recency fall out of one formula with a single decay `d ≈ 0.5`.
- Needs only access timestamps.

❌ **Cons:**
- No outcome dimension at all; it models *how often something was needed*, not *whether it was right*. We would bolt on our own valence term and lose the "published, fitted" property.
- Requires the full access history per item at read time (or an approximation).
- No optimizer or reference implementation to lean on.

📊 **Effort:** Medium

*(Worth keeping as a **tie-breaker inside** Option B if pure FSRS proves too outcome-sparse: `access_count` and `last_accessed` are recorded anyway.)*

---

### Option D: New standalone `MemoryPlane` subsystem over the wiki graph

A new `parrot.memory.planes` package with typed planes (`recent`, `profile`, `episodic`, `errors`, `patterns`), each a wiki namespace with its own retention policy, and a new toolkit façade.

✅ **Pros:**
- Clean conceptual model; scope (session / principal / agent / org) and lifecycle become first-class types.

❌ **Cons:**
- Fourth implementation of the same concern. Directly contradicts the owner's "menos es más".
- The existing `MemoryNamespace` (tenant / agent / user / session / room / crew) plus `brain-<agent>` / `org-<org>` wikis already express every scope the planes would; what is missing is dynamics, not taxonomy.
- `profile` (bitemporal per-principal facts) is a conversational-agent feature; deferred by owner decision (`EpisodeCategory.USER_PREFERENCE` covers v1).

📊 **Effort:** High — rejected.

---

## Recommendation

**Option B.** It is the only option that (a) learns from outcomes without a human in the loop, (b) does not reinforce on mere recall, (c) reduces the number of ranking/ageing implementations from three to one, and (d) stays additive over the existing backends. FSRS is chosen over an ad-hoc curve because the owner's target is autonomous long-horizon operation: a versioned algorithm with a fitting procedure over a log the runtime already can produce is worth more than a simpler formula nobody can calibrate.

Design lines that follow from it:

1. **The grade function is the design.** Everything else is FSRS-6 verbatim. §Internal Behavior fixes the grade function and its allowed inputs.
2. **Store is the contract.** `EpisodicMemoryStore` + `BrainStore` gain the dynamics; `LongTermMemoryMixin`, `parrot mcp-local`, `wikitoolkit` CLI and the SDD coder engine are four clients of the same store.
3. **Metadata-first, promote later.** FSRS state and forgotten flag live in `metadata["fsrs"]` in v1 (zero DDL); a later task may promote them to columns/indexes once query patterns are known.
4. **CoderFeedback becomes episodes.** Same store, `model_id` scope, `pattern` slug as the error signature, `coder_record_review` as the grade source.

---

## Feature Description

### User-Facing Behavior

- **Agents (`LongTermMemoryMixin` / `EpisodicMemoryMixin`)**: `<past_failures_to_avoid>` and `<brain_knowledge>` sections are ordered by `relevance × retrievability × importance`; stale, never-confirmed memories fade out of the injected context on their own; memories that keep preventing failures stay. No config change required; `memory_dynamics: bool = True` toggle on the mixin.
- **Tools** (`EpisodicMemoryToolkit`, prefix `ep`): existing `search_episodic_memory`, `record_lesson`, `get_warnings` unchanged in signature; results carry `retrievability`, `stability_days`, `review_count`. New `cite_memory(episode_ids)` — the agent declares which recalled memories it is acting on (SDD coders are instructed to; generic agents optionally). Forgotten memories are excluded unless `include_forgotten=True`.
- **SDD coders**: the `coder_feedback` brief is produced by the same recall (`namespace(model_id=…)`), ranked by retrievability instead of the 90-day cutoff. The coder's final `summary` already has to "state which feedback patterns you checked and their results" (`.claude/agents/sdd-coder.md` §a.1); this becomes a structured `checked_patterns: [{pattern, result}]` field on the coder result, which is the citation.
- **SDD worker**: `coder_record_feedback` and `coder_record_review` keep their signatures; the latter now also **grades** the memories cited in that attempt (see grade function). No new obligations for the worker.
- **Dream cycle**: collects by retrievability-and-importance instead of `importance >= 5`; distilled pages inherit FSRS state; a page whose difficulty crosses the re-distill threshold is re-clustered with the new episodes instead of accumulating lapses. `DreamCycleReport` gains `pages_redistilled`, `memories_forgotten`.
- **CLI / MCP**: `parrot mcp-local episodic` exposes the toolkit to out-of-process agents; `wikitoolkit memory {status,recall,cite,review,forget,import-feedback,export-reviews,fit}` for bash-based slash commands and ops. `export-reviews` writes the FSRS optimizer input; `fit` runs `py-fsrs`'s optimizer (dev extra) and writes `memory.fsrs.json` parameters next to the store.
- **Ops**: `wikitoolkit memory status` reports per-namespace counts by state (`fresh` / `reviewed` / `forgotten`), mean retrievability, difficulty histogram.

### Internal Behavior

#### 1. Memory state (FSRS-6)

```python
# parrot/memory/dynamics/models.py
class MemoryState(BaseModel):
    stability: float = 0.0          # days; 0 ⇒ never reviewed, R := 1.0 (legacy-compatible)
    difficulty: float = 5.0         # 1..10
    last_review_at: datetime | None = None
    last_accessed_at: datetime | None = None
    review_count: int = 0
    lapse_count: int = 0
    access_count: int = 0
    state: Literal["fresh", "reviewed", "forgotten"] = "fresh"
    initial_grade: int | None = None
    schema_version: int = 1

class Grade(IntEnum):
    AGAIN = 1; HARD = 2; GOOD = 3; EASY = 4
```

Persisted as `EpisodicMemory.metadata["fsrs"]` (all three backends already round-trip `metadata` and implement `update_metadata`), and as a `fsrs` key in the brain page body frontmatter / `WikiPageRecord.summary` sidecar (page records have no metadata column — see Open Questions).

**Formulas** (FSRS-6, 21 parameters `w0..w20`; defaults from `py-fsrs`):

- Retrievability: `R(t, S) = (1 + FACTOR · t/S) ^ (−w20)`, `FACTOR = 0.9^(−1/w20) − 1`, so `R(S, S) = 0.9`. `t` = days since `last_review_at` (or since `created_at` when never reviewed and `stability > 0`).
- Initial stability: `S0(G) = w[G−1]`. Initial difficulty: `D0(G) = w4 − e^(w5·(G−1)) + 1`, clamped to `[1, 10]`.
- Difficulty update: `ΔD = −w6·(G−3)`; `D' = w7·D0(EASY) + (1−w7)·(D + (10−D)·ΔD/9)` (linear damping + mean reversion), clamped.
- Stability after success (`G ≥ 2`): `S'_r = S·(1 + e^{w8}·(11−D)·S^{−w9}·(e^{w10·(1−R)} − 1)·hard_penalty·easy_bonus)` with `hard_penalty = w15` if HARD, `easy_bonus = w16` if EASY, else 1.
- Stability after lapse (`G = 1`): `S'_f = min(w11·D^{−w12}·((S+1)^{w13} − 1)·e^{w14·(1−R)}, S / e^{w17·w18})`.
- Same-day review (Δt < 1 day): `S' = S·e^{w17·(G−3+w18)}·S^{−w19}`.
- Parameters are read from `<store>/memory.fsrs.json` if present, else the FSRS-6 defaults; the tuple is versioned in the review log so a refit never silently re-interprets old reviews.

All of this is a pure module `parrot.memory.dynamics.fsrs` with property-based tests (monotonicity in `t`, `R(S,S)=0.9`, clamps), vendored, no runtime dependency.

#### 2. Recall

`EpisodicMemoryStore.recall_similar` gains `oversample: int = 4` and `include_forgotten: bool = False`: fetch `top_k × oversample` by the existing relevance strategy, then rescore in Python:

```
score = relevance × R(t, S) × (1 + importance/10) × valence_factor
valence_factor = 1.0 for state ∈ {fresh, reviewed}; 0 for forgotten (unless include_forgotten)
```

Sort, cut to `top_k`, and patch `last_accessed_at` / `access_count` via `update_metadata` (fire-and-forget, never blocks the recall). `get_failure_warnings`, `get_user_preferences`, `get_room_context` and `BrainStore.search` share the same rescoring helper. `UnifiedMemoryManager._get_episodic_warnings` / `_get_brain_knowledge` get the ordering for free. **Recall never touches `stability`, `difficulty` or `review_count`.**

#### 3. Reviews and the grade function

A review is created by `EpisodicMemoryStore.review(memory_ids, signal: ReviewSignal)` where:

```python
class ReviewSignal(BaseModel):
    outcome: Literal["success", "failure"]     # verified, never model-asserted
    source: Literal["tool_status", "tests", "code_review", "coder_review",
                    "explicit_feedback", "record_lesson", "probe"]
    first_attempt: bool = True
    corrections: int = 0                       # fix commits / retries after the memory was applied
    error_signature: str | None = None         # e.g. CoderFeedback.pattern, ToolInvocation error class
    applied_via: Literal["cited", "overlap"]   # how the memory was attributed to this outcome
    episode_id: str | None = None              # the episode this review comes from (provenance)
```

Grade function (deterministic, tested with a table):

| condition | grade |
|---|---|
| `outcome=failure` and `memory.error_signature == signal.error_signature` (the lesson was injected and the same defect recurred) | AGAIN |
| `outcome=failure` otherwise (the memory was present but is not about this failure) | *no review* |
| `outcome=success`, `corrections == 0`, `first_attempt` | GOOD |
| `outcome=success`, `corrections > 0` | HARD |
| `outcome=success` and the episode is `category=error_recovery` whose `suggested_action` matches `memory.lesson_learned` (the lesson was applied and fixed it) | EASY |
| no verified outcome | *no review* — the item just decays |

`applied_via="overlap"` reviews are down-weighted by treating EASY as GOOD (the only rating with a bonus); `cited` reviews are taken as-is. Every review appends one line to the **review log** (`ReviewRecord(memory_id, grade, reviewed_at, elapsed_days, retrievability_before, stability_before, stability_after, difficulty_after, source, applied_via, episode_id, params_version)`) — a superset of the FSRS optimizer's `(card_id, rating, review_datetime)` input.

#### 4. Attribution — which memories does an outcome grade?

- **SDD coders (instructed)**: `checked_patterns` in the coder result → cited memories. `coder_record_review(fix_commits=[…])` becomes the grade source: `corrections = len(fix_commits)`, `outcome = success` when the attempt merged, `error_signature` from any `coder_record_feedback` filed against the same attempt (its `pattern` slug — the worker is already told to "reuse it for recurrences").
- **ai-parrot agents (generic)**: the memories injected by `_build_episodic_context` / `get_context_for_query` for a turn are remembered in the turn's `MemoryContext` (`injected_ids`). When the turn's tool invocations close (`ToolInvocation.status`), the tool episodes recorded by `_record_post_tool` carry `related_tools`; a memory is *attributed* to that outcome iff `memory.related_tools ∩ episode.related_tools ≠ ∅` or `memory.related_entities ∩ episode.related_entities ≠ ∅` (`applied_via="overlap"`). No overlap → no review.
- **Explicit**: `record_lesson` (tool) creates the episode with `initial_grade=EASY`; `cite_memory` marks cited ids for the current session so the next verified outcome grades them as `cited`.
- **Conversational `ask()` with no tool activity and no explicit feedback**: recorded as `outcome=PARTIAL`, `importance` from `HeuristicScorer`, **never** as SUCCESS/3; produces no review.

#### 5. Initial state

On `record_episode`: `initial_grade = EASY if (is_failure and lesson_learned) or category == ERROR_RECOVERY else GOOD if outcome == SUCCESS else HARD`; `S = S0(initial_grade)`, `D = D0(initial_grade)`, `state="fresh"`. Importance stays the LLM/heuristic proposal and remains a *multiplier* in recall, never an input to FSRS.

#### 6. Forgetting and relearning

A memory becomes `forgotten` when `R(t, S) < forget_threshold` (default `0.2`, `MemoryConfig.forget_threshold`). Computed lazily at recall/collect time (no sweeper needed) and materialised by `update_metadata` so `status` can count it. Forgotten memories: excluded from recall, warnings and dream collection; still stored; TTL / `compact_namespace` continue to apply for hard deletion. `recall_similar(include_forgotten=True)` can surface them; a subsequent review follows the FSRS lapse/relearn path (`S'_f`) and flips state back to `reviewed`.

#### 7. Consolidation (dream cycle changes)

- `DreamCycleRunner._collect`: `ep.importance >= threshold or ep.lesson_learned` → `R(ep) >= collect_min_retrievability and (importance >= threshold or lesson_learned or review_count > 0)`; forgotten episodes never collect.
- Distilled page inherits `stability = max(S of group)`, `difficulty = mean(D of group)`, `review_count = Σ`; episodes get `metadata["consolidated_into"]` as today. Reviews of a consolidated episode **forward to its page** (`consolidated_into`) so the page is what accumulates evidence.
- `DreamState.reinforcement_counts` is retired; org promotion uses `page.stability >= org_promotion_stability_days` (default: `S` such that `R` stays ≥ 0.9 for 30 days) **and** `lapse_count == 0`.
- **Re-distill**: pages with `difficulty >= redistill_difficulty` (default 8.0) are re-clustered with the episodes recorded since their last distill; the new page supersedes (`supersedes` edge, old page `state="forgotten"`). This is the autonomous "this lesson is not working as written" loop.
- **Anti-patterns**: a memory with `lapse_count >= 2` while `state="reviewed"` is tagged `metadata["anti_pattern"]=True`; `DistilledKnowledge.category` gains `"anti_pattern"`; `_get_episodic_warnings` renders anti-patterns first.

#### 8. CoderFeedback absorbed into episodic memory

| `CoderFeedback` | `EpisodicMemory` |
|---|---|
| `defect` + `evidence` | `situation` |
| `correction` | `action_taken` (and `suggested_action`) |
| `pattern` | `lesson_learned` slug + `metadata["error_signature"]` |
| `files` | `related_entities` |
| `verification` | `outcome_details`; `outcome=FAILURE` (it is a corrected defect), `is_failure=True` |
| `backend`, `model` | `MemoryNamespace.model_id` (new scope) + `metadata` |
| `task_id`, `attempt_uid`, `execution_id`, `source` | `metadata` (provenance) |
| — | `category=ERROR_RECOVERY`, `initial_grade=EASY`, `agent_id="sdd-coder"` |

- `CoderFeedbackStore.record` → `EpisodicMemoryStore.record_episode(...)` **plus** the existing `insight.recorded` ledger event (category `coder_feedback`, `actor="agent:sdd-worker"`) for audit; `feedback_id` = `episode_id`.
- `CoderFeedbackStore.context(backend, model, files, max_tokens, max_age_days)` → thin adapter: `recall_similar(query=task scope text, namespace=MemoryNamespace(agent_id="sdd-coder", model_id=f"{backend}/{model}"), top_k=…)` packed to `max_tokens`; `max_age_days` is dropped (retrievability replaces it). `engine._feedback_for` and `RosterConfig.feedback` (`FeedbackConfig`) keep their shape.
- `CoderReviewStore.record` → additionally calls `EpisodicMemoryStore.review(cited_ids, ReviewSignal(source="coder_review", corrections=len(fix_commits), …))`.
- One-time `wikitoolkit memory import-feedback` replays historical `insight.recorded` / `coder_feedback` events into episodes (idempotent by `feedback_id`).
- `coder_suspensions.py` stays as is (operational history, not a lesson).

#### 9. Storage for the SDD case (out-of-process, no Postgres)

The SDD store lives at `<shared_root>/.parrot/memory/` (resolved by the ledger's `find_shared_root`). Backend choice is spike **S2**: (a) a new `SQLiteEpisodeBackend` (aiosqlite, `episodes` table with `metadata` JSON, embeddings in a sibling table, cosine in Python — thousands of rows, not millions; same WAL/`busy_timeout`/`BEGIN IMMEDIATE` hardening the ledger already applies) vs (b) `FAISSBackend` with its `episodes.jsonl` + `episodes.faiss` snapshot files, which is single-writer by construction (`save()` rewrites both files). Recommendation going into the spike: (a).

#### 10. Review log

`ReviewLog` protocol with `append(record)` / `iter(since)`; default `JsonlReviewLog` (`reviews.jsonl`, `O_APPEND` single-`write()` lines exactly like `LedgerLog`), `PostgresReviewLog` (`parrot_memory.memory_reviews`) for pgvector deployments. `wikitoolkit memory export-reviews` emits the `py-fsrs` optimizer CSV; `fit` writes `memory.fsrs.json` with `{"version": "fsrs-6", "parameters": [...21], "fitted_at", "n_reviews"}`.

### Edge Cases & Error Handling

- **Legacy records without `metadata["fsrs"]`** → treated as `stability=0` ⇒ `R=1.0`, `state="fresh"`; first review initialises them from `initial_grade` derived from stored `outcome`/`category`. Nothing changes for them until then.
- **Clock skew / future `last_review_at`** → `t = max(0, Δt)`.
- **Review for an unknown or forgotten id** → forgotten: proceeds via relearn path; unknown: ignored, logged at debug, still appended to the review log with `memory_id` (audit).
- **Same outcome graded twice** (retry of `coder_record_review`) → idempotent by `(memory_id, episode_id, source)`; a repeated call is not a second review (mirrors "a repeated recording call is not another recurrence").
- **`update_metadata` fails (backend locked)** → recall result is still returned; the access patch is dropped; reviews are retried once then left in the review log with `applied=false` for `wikitoolkit memory sync` to replay.
- **Parameter file corrupt** → fall back to defaults, warn once, tag reviews with `params_version="default"`.
- **Consolidated episode reviewed** → forwarded to the page; if the page was superseded, forwarded to the superseding page (one hop, no chains).
- **Embedding model changed** → unrelated to dynamics; rescoring is post-fetch so it survives re-embedding.
- **Overlap attribution over-fires** (many memories share a tool name) → cap `overlap` reviews per outcome to `max_overlap_reviews` (default 3, highest relevance first); measured in spike S3.

---

## Capabilities

### New Capabilities
- `memory-dynamics-fsrs`: vendored FSRS-6 (`parrot.memory.dynamics.fsrs`), `MemoryState`, `Grade`, parameter file loading/versioning, property tests.
- `memory-review`: `ReviewSignal`, grade function, `EpisodicMemoryStore.review`, review log protocol + JSONL/Postgres sinks, idempotency.
- `memory-attribution`: injected-id tracking in `MemoryContext`, `cite_memory` tool, overlap attribution for generic agents, `checked_patterns` on coder results.
- `memory-forgetting`: retrievability floor, `forgotten` state, `include_forgotten`, relearning path.
- `memory-cli`: `wikitoolkit memory …` group and `parrot mcp-local episodic`.
- `memory-feedback-merge`: `CoderFeedback` ↔ episode mapping, `model_id` namespace scope, `import-feedback`, adapters keeping `_feedback_for` intact.
- `episodic-backend-sqlite` (spike-gated): file-local concurrent backend for the SDD shared root.

### Modified Capabilities
- `episodic-recall`: oversample + rescoring by `R × importance`, access patching, shared helper for warnings/preferences/room/brain search.
- `episodic-record`: initial FSRS state; `_record_post_ask` no longer fabricates SUCCESS/3.
- `dream-cycle`: retrievability-based collect, state inheritance, review forwarding, re-distill loop, anti-pattern category, `reinforcement_counts` retired.
- `unified-memory-context`: ordering by dynamics; `injected_ids`; `forget_threshold` / `redistill_difficulty` in `MemoryConfig`.
- `sdd-coder-engine`: `_feedback_for` backed by episodic recall; `coder_record_review` grades cited memories; coder result carries `checked_patterns`.
- `sdd-agent-definitions`: `sdd-coder.md` §a.1 emits structured `checked_patterns`; `sdd-worker.md` feedback protocol unchanged in obligations, updated in wording (feedback is "memory", `feedback_id` is an episode id).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `memory/dynamics/` (new) | new | `fsrs.py`, `models.py`, `grade.py`, `review_log.py` |
| `memory/episodic/models.py` | extends | `MemoryNamespace.model_id`; `EpisodeSearchResult.retrievability/stability/review_count`; `EpisodicMemory.fsrs` property over `metadata` |
| `memory/episodic/store.py` | extends | `review()`, `cite()`, `recall_similar(oversample, include_forgotten)`, rescoring helper, initial state on record |
| `memory/episodic/backends/*` | minimal | `model_id` in filters (pgvector: one column + index); `update_metadata` reused |
| `memory/episodic/mixin.py` | modifies | `_record_post_ask` outcome; injected-id tracking; post-tool attribution |
| `memory/episodic/tools.py` | extends | `cite_memory`; result fields |
| `memory/dream/{models,runner,brain}.py` | modifies | collect rule, state inheritance, re-distill, `anti_pattern`, `reinforcement_counts` removal, page state sidecar |
| `memory/unified/{models,manager,context}.py` | extends | `MemoryConfig.forget_threshold/redistill_difficulty`, `MemoryContext.injected_ids`, ordering |
| `knowledge/wiki/ledger/coder_feedback.py` | rewires | record → episode + audit event; `context` → recall adapter |
| `knowledge/wiki/ledger/coder_reviews.py` | extends | grades cited memories |
| `flows/dev_loop/sdd_coder/{engine,toolkit,models}.py` | extends | `checked_patterns`, store wiring at shared root |
| `knowledge/wiki/cli.py`, `mcp/local_cli.py` | extends | `memory` group; `episodic` MCP target |
| `.claude/agents/sdd-coder.md`, `sdd-worker.md`, `flows/dev_loop/_subagent_data/*` | modifies | prose for citations; keep in sync (two copies) |
| `sdd/specs/dream-cycle-brain-consolidation.spec.md` | supersedes parts | non-goal "cross-agent episodic sharing" untouched; `reinforcement_count` decision replaced |
| `pyproject.toml` | extends | optional extra `memory-fit = ["fsrs[optimizer]"]` |

No breaking API changes. New optional config: `memory_dynamics`, `forget_threshold`, `redistill_difficulty`, `org_promotion_stability_days`, `max_overlap_reviews`, `memory.fsrs.json`.

---

## Code Context

### User-Provided Code
_None — direction was given in prose: unify under one memory flow ("menos es más"), merge `CoderFeedback` into episodic memory, full FSRS because human feedback will be minimal or absent, defer the per-principal profile plane._

### Verified Codebase References
_All paths relative to `packages/ai-parrot/src/parrot/` unless noted; verified against `main` on 2026-09-17. Anchors are grep-able symbols, never line numbers._

#### Classes & Signatures
```python
# memory/episodic/models.py
class EpisodeOutcome(str, Enum): SUCCESS, FAILURE, PARTIAL, TIMEOUT
class EpisodeCategory(str, Enum): TOOL_EXECUTION, QUERY_RESOLUTION, ERROR_RECOVERY, USER_PREFERENCE, WORKFLOW_PATTERN, DECISION, HANDOFF
class ReflectionResult(BaseModel): reflection, lesson_learned, suggested_action
class EpisodicMemory(BaseModel):
    episode_id, created_at, updated_at, expires_at
    tenant_id, agent_id, user_id, session_id, room_id, crew_id
    situation, action_taken, outcome: EpisodeOutcome, outcome_details, error_type, error_message
    reflection, lesson_learned, suggested_action
    category: EpisodeCategory; importance: int (ge=1, le=10); is_failure: bool
    related_tools: list[str]; related_entities: list[str]
    embedding: list[float] | None (excluded from dumps); metadata: dict[str, Any]
class EpisodeSearchResult(EpisodicMemory): score: float
class MemoryNamespace(BaseModel): tenant_id, agent_id, user_id, session_id, room_id, crew_id
    def build_filter(self) -> dict[str, Any]   # only non-None dimension fields
    def scope_label(self) -> str

# memory/episodic/store.py
def _auto_importance(outcome, error_type) -> int          # 7 failure/timeout, 5 partial, 3 success (+2 known error)
class EpisodicMemoryStore:
    async def record_episode(self, namespace: MemoryNamespace, situation: str, action_taken: str, outcome: EpisodeOutcome,
        outcome_details=None, error_type=None, error_message=None, category=EpisodeCategory.TOOL_EXECUTION,
        importance: int | None = None, related_tools=None, related_entities=None, metadata=None,
        generate_reflection: bool = True, ttl_days: int | None = None) -> EpisodicMemory
    async def record_tool_episode(...); async def record_crew_episode(...)
    async def recall_similar(self, query: str, namespace: MemoryNamespace, top_k: int = 5, score_threshold: float = 0.3,
        category: EpisodeCategory | None = None, include_failures_only: bool = False) -> list[EpisodeSearchResult]
    async def get_failure_warnings(...); async def get_user_preferences(...); async def get_room_context(...)
    async def mark_consolidated(episode_ids, page_id)      # FEAT-390 → metadata["consolidated_into"]
    async def cleanup_expired(self) -> int
    async def compact_namespace(self, namespace, keep_top_n: int = 100, keep_all_failures: bool = True) -> int
    async def export_episodes(...)                          # JSONL
    create_pgvector / create_redis_vector / create_faiss     # factories

# memory/episodic/backends/abstract.py
class AbstractEpisodeBackend(Protocol):
    async def store(self, episode: EpisodicMemory) -> str
    async def search_similar(...); async def get_recent(self, namespace_filter, limit=10, since=None); async def get_failures(...)
    async def delete_expired(self) -> int; async def count(self, namespace_filter) -> int
    async def update_metadata(self, episode_ids: list[str], patch: dict[str, Any]) -> int   # merge patch; unknown ids ignored
# backends: pgvector.py::PgVectorBackend (DDL has `importance SMALLINT NOT NULL DEFAULT 5`, `idx_episodes_importance`, ivfflat cosine),
#           redis_vector.py::RedisVectorBackend, faiss.py::FAISSBackend (save(): episodes.faiss + episodes.jsonl + id_order.json)

# memory/episodic/recall.py
class RecallStrategy(Protocol); class SemanticOnlyStrategy
class HybridBM25Strategy: bm25_weight: float = 0.4, semantic_weight: float = 0.6   # fused = bm25_weight*bm25 + semantic_weight*semantic

# memory/episodic/scoring.py
class ImportanceScorer(Protocol): score(episode) -> float
class HeuristicScorer                      # base 7/5/3 by outcome, +2 known error_type, /10
class ValueScorer(BaseModel)               # outcome_weight=0.3, tool_usage_weight=0.2, feedback_weight=0.3 …

# memory/episodic/mixin.py
class EpisodicMemoryMixin:
    enable_episodic_memory: bool = False; episodic_backend: str = "faiss"; episodic_dsn; episodic_faiss_path; episodic_schema = "parrot_memory"
    episodic_reflection_enabled = True; episodic_inject_warnings = True; episodic_max_warnings = 3; episodic_flush_on_start = False; episodic_trivial_tools
    async def _build_episodic_context(...); async def _record_post_tool(...); async def _record_post_ask(...)   # ← outcome=EpisodeOutcome.SUCCESS, importance=3
    async def _on_post_ask(...); async def _on_pre_ask(self, question, user_id=None, session_id=None, **kwargs) -> str

# memory/episodic/tools.py
class EpisodicMemoryToolkit(AbstractToolkit): tool_prefix = "ep"
    async def search_episodic_memory(...); async def record_lesson(self, situation: str, lesson: str, ...); async def get_warnings(...)

# memory/dream/models.py
class DreamState(BaseModel): last_run, next_due, interval_hours=24.0, running, running_since, cycles_completed, episodes_consolidated,
    reinforcement_counts: dict[str, int], promoted_pages: list[str]
class DreamConfig(BaseModel): importance_threshold=5, similarity_threshold=0.75, max_groups_per_cycle=20, org_promotion_cycles=3,
    distill_model="gemini-3.1-flash-lite", startup_jitter_seconds=60, failure_backoff_divisor=4
class DistilledKnowledge(BaseModel): title, body, category: str = "lesson", confidence: float = 0.5
class DreamCycleReport(BaseModel): episodes_collected, groups_formed, groups_distilled, groups_skipped, pages_written, pages_promoted, aborted, abort_reason

# memory/dream/runner.py
DISTILL_PROMPT; _MAX_BODY_CHARS = 4000; _LOW_CONFIDENCE_THRESHOLD = 0.3; _COLLECT_LIMIT = 5000
class DreamCycleRunner:
    async def run_cycle(self, state: DreamState) -> DreamCycleReport      # collect → cluster → distill → archive → mark → promote
    async def _collect(self, state)     # keeps: ep.importance >= self._config.importance_threshold or bool(ep.lesson_learned); skips "consolidated_into" in ep.metadata
    async def _cluster(...); def _cluster_by_embedding(...); def _cluster_by_category(...)
    async def _distill(...); async def _llm_distill(...); def _heuristic_distill(...)
    # promote: state.reinforcement_counts[page_id] += 1 per cycle; copy_page_to(org_brain) when >= org_promotion_cycles

# memory/dream/brain.py
class BrainStore:                        # wraps create_wiki_store(storage_dir, wiki_name=..., backend="sqlite")
    async def remember(...)              # page_id = "mem-" + sha1(f"{title}::{category}")[:12]; origin="memory"; asserted_by
    async def search(...); async def copy_page_to(self, page_id: str, other: BrainStore) -> str
# memory/dream/scheduler.py
class DreamScheduler: start(), stop(), run_now(), _run_locked_cycle(), _loop(), _seconds_until_due()

# memory/unified/models.py
class MemoryContext(BaseModel): episodic_warnings, relevant_skills, conversation_summary, semantic_knowledge, tokens_used, tokens_budget
class MemoryConfig(BaseModel): enable_episodic, enable_skills, enable_conversation, enable_brain, max_context_tokens=2000,
    episodic_max_warnings, skill_max_context, episodic_weight, skill_weight, conversation_weight, brain_weight (_weights_sum_to_one), skill_auto_extract
# memory/unified/manager.py
class UnifiedMemoryManager:
    async def get_context_for_query(...)          # gathers _get_episodic_warnings/_get_relevant_skills/_get_conversation/_get_brain_knowledge
    async def record_interaction(query, response, tool_calls, user_id, session_id)   # writes episodic only
# memory/unified/context.py  class ContextAssembler: assemble(...), _fill_section(text, budget)
# memory/unified/mixin.py
class LongTermMemoryMixin: enable_long_term_memory, episodic_auto_record, skill_auto_extract, enable_brain, dream_interval_hours=24.0,
    dream_importance_threshold=5, brain_storage_dir, brain_promote_to_org, org_promotion_cycles=3
    async def _configure_brain(...); async def get_memory_context(...); async def _post_response_memory_hook(...); def _create_namespace(self) -> MemoryNamespace

# memory/compaction/models.py
class ToolStatus(str, Enum); class TurnState(str, Enum)   # SUMMARIZED reserved for Stage 2
class ToolInvocation; class CompactionState: stage2_needed: bool = False

# knowledge/wiki/ledger/coder_feedback.py
class CoderFeedback(BaseModel): task_id (TASK-\d{1,5}), attempt_uid, backend, model, source: Literal["review_fix_commit","code_review"],
    lesson_scope: Literal["model"] = "model", pattern (^[a-z][a-z0-9_-]{0,79}$), files: list[str] (1..10), defect, evidence, correction, verification, execution_id
    def feedback_id(self) -> str
class CoderFeedbackStore:
    def from_root(cls, root: Path); async def record(self, feedback) -> CoderFeedbackReceipt   # insight.recorded, category="coder_feedback", actor="agent:sdd-worker"
    async def context(self, backend: str, model: str, files: list[str], max_tokens: int = 1800, max_age_days: int = 90) -> str
    # ranks by (scope_score, recurrence, timestamp); "retries of the recording call are not recurrences"

# knowledge/wiki/ledger/coder_reviews.py
class CoderReview(BaseModel): task_id, attempt_uid, backend, model, fix_commits: list[CommitSha], review_evidence, execution_id
class CoderReviewMeasurement(CoderReview): exposure: Literal["with_feedback","without_feedback","unavailable"]; feedback_tokens
class CoderReviewMetrics(BaseModel): correction_commits, correction_commits_per_task, task_correction_commits, mean_feedback_tokens
class CoderReviewStore: record(review) -> CoderFeedbackReceipt; report() -> CoderReviewReport
# knowledge/wiki/ledger/coder_suspensions.py  — "operational-history plane, distinct from coder_feedback.py"
# knowledge/wiki/ledger/events.py — LedgerEventKind includes "insight.recorded", "insight.superseded"; InsightRecordedPayload; LedgerEvent
# knowledge/wiki/ledger/log.py — LedgerLog (append-only events.jsonl); service.py — LedgerService.from_root/get_context/export_snapshot/compact/audit

# flows/dev_loop/sdd_coder/engine.py
async def _feedback_for(self, ctx, task, backend: str, model: str) -> str   # policy = self.roster.feedback; CoderFeedbackStore.from_root(root); store.context(backend, model, files, policy.max_tokens, policy.max_age_days)
# prepare_native(): feedback_context = await self._feedback_for(ctx, planned, "native", model) → coder_feedback=feedback_context
# flows/dev_loop/sdd_coder/models.py — FeedbackConfig (RosterConfig.feedback): enabled, max_tokens (default 1800, ≤6000), max_age_days (default 90, 1..365)
# flows/dev_loop/sdd_coder/toolkit.py — class SddCoderToolkit(AbstractToolkit): coder_plan, coder_run_chunk, coder_prepare_native, coder_merge,
#   coder_record_feedback, coder_record_review, coder_feedback_report, coder_begin_execution, coder_end_execution, coder_suspend_model, coder_wait, coder_status, coder_cleanup

# knowledge/wiki/store.py
class BaseWikiStore(ABC): upsert_pages, add_edges, replace_source_slice, delete_page, upsert_embedding(concept_id, vector, model=""),
    get_page, list_pages, search_fts, search_vector(embedding, limit=10), neighbors, dump_pages, dump_edges, stats, orphan_sources, broken_edges, missing_bodies
class WikiPageRecord(BaseModel): concept_id, node_id, title, category, summary, body, source_id, token_count, origin, asserted_by, updated_at, content_hash   # no metadata field

# skills/models.py  class Skill: access_count: int = 0; usefulness_score: float = 0.0  # "Can be updated based on feedback" — never written
# skills/store.py   read_skill(): skill.access_count += 1; relevance = 0.7*similarity + 0.3*(usefulness/10.0)

# cli/__init__.py   "mcp-local": "parrot.mcp.local_cli"   → `parrot mcp-local memory` (WorkingMemoryToolkit today)
```

#### Verified Imports
```python
from parrot.memory.episodic.models import EpisodicMemory, EpisodeOutcome, EpisodeCategory, EpisodeSearchResult, MemoryNamespace, ReflectionResult
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.episodic.backends.abstract import AbstractEpisodeBackend
from parrot.memory.episodic.recall import HybridBM25Strategy, SemanticOnlyStrategy, RecallStrategy
from parrot.memory.episodic.scoring import HeuristicScorer, ValueScorer, ImportanceScorer
from parrot.memory.episodic.mixin import EpisodicMemoryMixin
from parrot.memory.episodic.tools import EpisodicMemoryToolkit
from parrot.memory.dream import BrainStore, DreamConfig, DreamState, DreamCycleRunner, DreamScheduler, DistilledKnowledge, DreamCycleReport   # lazy (PEP 562)
from parrot.memory.unified.models import MemoryContext, MemoryConfig
from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.memory.unified.context import ContextAssembler
from parrot.memory.unified.mixin import LongTermMemoryMixin
from parrot.memory.compaction.models import ToolInvocation, ToolStatus, TurnState, CompactionState
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback, CoderFeedbackReceipt, CoderFeedbackStore
from parrot.knowledge.wiki.ledger.coder_reviews import CoderReview, CoderReviewMeasurement, CoderReviewMetrics, CoderReviewStore
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki import create_wiki_store, pack_results
from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit
```

#### Key Attributes & Constants
- `EpisodicMemory.importance` is `int` in `[1, 10]`; pgvector column `importance SMALLINT NOT NULL DEFAULT 5` with `idx_episodes_importance (agent_id, importance DESC)`.
- `EpisodicMemoryMixin._record_post_ask` hard-codes `outcome=EpisodeOutcome.SUCCESS` and `importance=3` for every `ask()`.
- `DreamCycleRunner._collect` keeps `ep.importance >= importance_threshold or bool(ep.lesson_learned)` and skips `"consolidated_into" in ep.metadata`; `_COLLECT_LIMIT = 5000`.
- `DreamState.reinforcement_counts` increments once per cycle per page; org promotion when `>= org_promotion_cycles` (3).
- `BrainStore` page ids: `"mem-" + sha1(f"{title}::{category}")[:12]`; wikis `brain-<agent_id>` and `org-<org_id>` (wired in `unified/mixin.py`).
- `HybridBM25Strategy` defaults `bm25_weight=0.4`, `semantic_weight=0.6`; pgvector `search_hybrid` = `semantic_weight * semantic_score + text_weight * ts_rank`.
- `CoderFeedback.pattern` slug regex `^[a-z][a-z0-9_-]{0,79}$`; `sdd-worker.md`: "`pattern`: a stable slug … reuse it for recurrences"; "A repeated recording call is not another recurrence".
- `sdd-coder.md` §a.1 "Apply Previous Delivery Feedback": "In your final `summary`, state which feedback patterns you checked and their results … You do not record feedback or change the ledger; the reviewing worker owns that step."
- `sdd-worker.md`: "**At EVERY coder handoff, capture your confirmed corrections**"; "this is the model's preventive memory, independent of deferred ledger issues". Both agent files are duplicated under `flows/dev_loop/_subagent_data/`.
- `FeedbackConfig.max_tokens` default 1800 (≤ 6000), `max_age_days` default 90 (1..365).
- `FAISSBackend.save()` rewrites `episodes.faiss`, `episodes.jsonl`, `id_order.json` (single-writer snapshot); `load()` reads both.
- `AbstractEpisodeBackend.update_metadata` exists on pgvector, Redis and FAISS (added for FEAT-390) — the write primitive this design reuses.
- FSRS-6 defaults (`py-fsrs`): `(0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722, 0.1666, 0.796, 1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542)`; `w0..w3` = `S0` for Again/Hard/Good/Easy in days.

### Does NOT Exist (Anti-Hallucination)
- ~~`last_accessed`, `access_count`, `stability`, `difficulty`, `retrievability`, `valence`, `salience`, `half_life`, `forgetting`, `ebbinghaus`~~ — no matches in `packages/ai-parrot/src` for memory purposes. `decay` appears only as `cross_domain_decay=0.6` (`unified/routing.py`, cross-agent routing) and `decay_base=0.7` per graph hop (`knowledge/graphindex/retriever.py`); `stability` only as sort stability.
- ~~a time term in recall~~ — `recall.py`, pgvector `search_hybrid` and `BrainStore.search` rank by relevance only; the only time-aware ordering is `get_failure_warnings` sorting `(importance, created_at)`.
- ~~outcome feedback into any score~~ — `Skill.usefulness_score` is never written; `DreamState.reinforcement_counts` reads no outcomes; no `review`, `reinforce`, `cite` API on `EpisodicMemoryStore` or the toolkit.
- ~~`anti_pattern` category~~ — `DistilledKnowledge.category` values are lesson / decision / concept / note; `EpisodeCategory` has no anti-pattern; failures surface only as `<past_failures_to_avoid>` warnings.
- ~~`model_id` / model scope in `MemoryNamespace`~~ — scopes are tenant / agent / user / session / room / crew. Model scoping exists only in `CoderFeedback.backend/model`.
- ~~`WikiPageRecord.metadata`~~ — no metadata column on wiki pages (the FEAT-390 spec's own "Does NOT Exist" lists `reinforcement_count` on pages for the same reason).
- ~~a review / rating log~~ — nothing records "memory X was used and the outcome was Y"; `CoderReviewStore` records fix commits per attempt, not per memory.
- ~~any episodic/brain use by SDD sub-agents~~ — `sdd-worker`/`sdd-coder` reach memory only through `coder_feedback` (ledger) and `ledger context`; `_feedback_for` uses `CoderFeedbackStore`, not `EpisodicMemoryStore`.
- ~~a SQLite episodic backend~~ — backends are pgvector, Redis vector, FAISS only. `SQLiteWikiStore.search_vector` exists for wiki pages, not episodes.
- ~~Stage-2 LLM summary compaction~~ — `stage2_needed` and `TurnState.SUMMARIZED` are reserved; not implemented (no hook to attach episode creation to yet).
- ~~`parrot mcp-local episodic`~~ — `parrot mcp-local memory` exists (WorkingMemoryToolkit); no episodic MCP target.
- ~~`wikitoolkit memory …`~~ — CLI groups today: `mcp, build, upsert, query, page, related, status, communities, export, remember, note, link, memories, audit, ground, ingest, ingest-jira, symbols, ns, sync, ledger, per-agent installers`; no `memory` group.
- ~~`fsrs` / `py-fsrs` dependency~~ — not in `pyproject.toml` / `uv.lock`.

---

## Parallelism Assessment

- **Internal parallelism**: yes, after one foundation lane. **Lane 0** (`memory/dynamics/`: FSRS formulas, `MemoryState`, `Grade`, grade function, review log; pure, fully unit-testable, no I/O) unblocks everything. **Lane 1** (episodic store: initial state, rescoring recall, `review`/`cite`, `model_id` scope, mixin attribution, toolkit) and **Lane 2** (dream cycle: collect rule, inheritance, forwarding, re-distill, anti-pattern) are independent once `MemoryState` is frozen in the spec. **Lane 3** (SDD: `CoderFeedback` → episodes, adapters in `_feedback_for`/`coder_record_review`, `checked_patterns`, agent prose, `import-feedback`) depends on Lane 1's `review()` and on spike S2's backend. **Lane 4** (CLI/MCP surface, `export-reviews`/`fit`, ops `status`) depends on Lanes 1–2 interfaces only.
- **Cross-feature independence**: touches `memory/dream/*` (FEAT-390 lineage — coordinate `reinforcement_counts` removal), `knowledge/wiki/ledger/coder_*` (work-ledger lineage), `flows/dev_loop/sdd_coder/*` and both copies of the agent markdown. Does not touch `WorkingMemoryToolkit`, `parrot.skills`, `CrossDomainRouter`, GraphIndex, PageIndex or OKF.
- **Recommended isolation**: `mixed` — one worktree for Lane 0 (small, sequential), then per-lane worktrees; Lane 3 last.
- **Rationale**: Lane 0 is a pure module everything imports; the others are additive edits in different packages that merge cleanly.

---

## Spikes (gates before `/sdd-spec`)

- **S1 — Cold-start behaviour of FSRS-6 defaults on agent time scales.** Simulate 30 days of a `sdd-coder` model namespace from the existing `events.jsonl` `coder_feedback` history (import → replay `coder_record_review` outcomes as grades) and a synthetic generic-agent trace (tool episodes at minutes-to-hours cadence). Measure: fraction of lessons forgotten before their first review; retrievability of lessons that later prevented a recurrence; rank correlation between the new score and the current `(scope_score, recurrence, timestamp)` ranking. Pass: no lesson with `lapse_count == 0` and ≥ 1 GOOD review falls below `forget_threshold` within 30 days under defaults; otherwise decide between rescaling `t` (hours as "days") and shipping a pre-fitted parameter set.
- **S2 — File-local concurrent episodic backend for the SDD shared root.** Prototype `SQLiteEpisodeBackend` (aiosqlite, WAL, `busy_timeout`, `BEGIN IMMEDIATE`, cosine in Python over ≤ 10k rows) and run N=8 worktree writers + readers concurrently (the same harness the ledger spike used). Compare with `FAISSBackend` snapshot files under the same load. Pass: zero lost writes, p95 `recall_similar` < 50 ms at 5k episodes.
- **S3 — Attribution precision for generic agents.** On recorded tool traces of an existing agent with `EpisodicMemoryMixin`, compute how many injected memories the overlap rule attributes per outcome and how many of those a reviewer judges as actually relevant (sample of 50). Decide `max_overlap_reviews` and whether overlap reviews should be disabled by default outside SDD.
- **S4 — Page-state storage.** Confirm whether FSRS state for brain pages fits in the existing page record (frontmatter in `body`, or `summary` sidecar) without breaking `search_fts` / `pack_results`, or whether `WikiPageRecord` needs a `metadata` JSON column (touches `SQLiteWikiStore`, Arango, Postgres wiki backends).

---

## Open Questions

- [ ] Time unit for `t`: calendar days (FSRS native) vs "agent days" (`t = elapsed_hours / k`) for tool-cadence agents — decided by S1. — *Owner: Jesus*
- [ ] Should `overlap` attribution be on by default for generic agents, or opt-in per agent (`memory_attribution="cited"|"overlap"|"both"`)? — *Owner: Jesus* (after S3)
- [ ] Brain page state: frontmatter-in-body vs new `WikiPageRecord.metadata` column (S4). The column is cleaner and also unblocks the FEAT-390 open item about `reinforcement_count` on pages. — *Owner: Jesus*
- [ ] `CoderFeedback` merge migration: keep `CoderFeedbackStore` as a thin adapter permanently (stable tool contract for `sdd-worker`) or deprecate after one release? — *Owner: Jesus*
- [ ] Should `EpisodeCategory` gain `ANTI_PATTERN`, or is `metadata["anti_pattern"]` + `DistilledKnowledge.category="anti_pattern"` enough for v1? Enum change touches the pgvector CHECK/index only if one exists (verify in spec). — *Owner: Jesus*
- [ ] Forget threshold default (0.2) and `redistill_difficulty` (8.0): fixed config or derived from `desired_retention` like FSRS's interval formula? — *Owner: Jesus* (S1 data)
- [ ] **Probes (v2 idea):** many lessons are verifiable assertions ("`X` does NOT exist", "`Y` requires `Z`"). A `probe` field (a deterministic check: grep, import, test id) would let the dream cycle *rehearse* memories whose `R` fell below `desired_retention` and grade them without any task running — the closest thing to spaced repetition for agents. Out of v1 scope; worth a line in the spec's roadmap. — *Owner: Jesus*
- [ ] Profile plane (per-principal, bitemporal facts): deferred by decision; confirm `EpisodeCategory.USER_PREFERENCE` + `get_user_preferences` is sufficient for the conversational agents in production today. — *Owner: Jesus*
- [ ] Review log retention: unbounded JSONL (it is the fitting corpus) vs rotate after `fit`? — *Owner: Jesus*

---

## References

### Memory theory
- Ebbinghaus, H. (1885). *Über das Gedächtnis: Untersuchungen zur experimentellen Psychologie.* Leipzig: Duncker & Humblot. (English: *Memory: A Contribution to Experimental Psychology*, 1913.) — the forgetting curve and the savings method.
- Murre, J. M. J., & Dros, J. (2015). Replication and Analysis of Ebbinghaus' Forgetting Curve. *PLOS ONE* 10(7): e0120644. https://doi.org/10.1371/journal.pone.0120644 — modern replication; shows the curve is well fit by a power/exponential-with-plateau, which is what FSRS's power-law `R(t,S)` encodes.
- Bjork, R. A., & Bjork, E. L. (1992). A new theory of disuse and an old theory of stimulus fluctuation. In *From Learning Processes to Cognitive Processes* (Vol. 2, pp. 35–67). Erlbaum. — **storage strength vs retrieval strength**: the theoretical basis for keeping `stability` separate from `retrievability`, and for "retrieval when retrievability is low yields the largest gain in storage strength" (FSRS's `e^{w10·(1−R)}` term).
- Anderson, J. R., & Schooler, L. J. (1991). Reflections of the environment in memory. *Psychological Science* 2(6), 396–408. — rational analysis; ACT-R base-level activation `B_i = ln Σ t_j^{−d}` (Option C).
- McClelland, J. L., McNaughton, B. L., & O'Reilly, R. C. (1995). Why there are complementary learning systems in the hippocampus and neocortex. *Psychological Review* 102(3), 419–457. — systems consolidation (episodes → schemas), the biological analogue of the dream cycle (`episodic` → `brain`).

### Spaced-repetition algorithms
- Ye, J., Su, J., & Cao, Y. (2022). A Stochastic Shortest Path Algorithm for Optimizing Spaced Repetition Scheduling. *KDD '22*. https://doi.org/10.1145/3534678.3539081 — the FSRS paper (DSR model: Difficulty, Stability, Retrievability).
- Su, J., Ye, J., Nie, L., Cao, Y., & Chen, Y. (2023). Optimizing Spaced Repetition Schedule by Capturing the Dynamics of Memory. *IEEE Transactions on Knowledge and Data Engineering.* https://doi.org/10.1109/TKDE.2023.3251721
- The FSRS algorithm (FSRS-6, 21 parameters, learnable decay `w20`): https://github.com/open-spaced-repetition/awesome-fsrs/wiki/The-Algorithm (formerly `fsrs4anki/wiki/The-Algorithm`).
- `py-fsrs` — reference Python implementation, MIT; `Scheduler`, `Card`, `Rating {Again=1, Hard=2, Good=3, Easy=4}`, `ReviewLog`, `review_card`, `get_card_retrievability`; optimizer via `pip install "fsrs[optimizer]"` → `Optimizer.compute_optimal_parameters()`: https://github.com/open-spaced-repetition/py-fsrs · https://pypi.org/project/fsrs/
- `fsrs-optimizer` — standalone optimizer over review logs: https://github.com/open-spaced-repetition/fsrs-optimizer
- `fsrs-rs` — Rust implementation (relevant to the nlproxy author's Rust runtime; same parameter vector, so a review log exported here is fittable there): https://github.com/open-spaced-repetition/fsrs-rs
- awesome-fsrs index (implementations in Python, Rust, TS, Go, Dart…): https://open-spaced-repetition.github.io/awesome-fsrs/

### Agent memory prior art
- Park, J. S., et al. (2023). Generative Agents: Interactive Simulacra of Human Behavior. arXiv:2304.03442. — retrieval score = recency (exponential decay) × importance (LLM-rated 1–10) × relevance; **reflection** as periodic consolidation. Our importance/reflection already follow this; the decay term is what it lacks relative to FSRS (no outcome, every access refreshes).
- Packer, C., et al. (2023). MemGPT: Towards LLMs as Operating Systems. arXiv:2310.08560. — tiered memory with explicit paging; the "model must remember to consult memory" weakness our `PromptBuilder`/`UnifiedMemoryManager` injection avoids.
- Xu, W., et al. (2025). A-MEM: Agentic Memory for LLM Agents. arXiv:2502.12110. — Zettelkasten-style linked notes with LLM-driven evolution of existing memories on insert (closest analogue to re-distill).
- Chhikara, P., et al. (2025). Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory. arXiv:2504.19413. — extraction + update pipeline (ADD/UPDATE/DELETE/NOOP) over facts; no retention dynamics.
- Shinn, N., et al. (2023). Reflexion: Language Agents with Verbal Reinforcement Learning. arXiv:2303.11366. — outcome-conditioned verbal lessons; the origin of "lesson_learned from a failure" but without persistence dynamics.
- Zhao, A., et al. (2023). ExpeL: LLM Agents Are Experiential Learners. arXiv:2308.10144. — insights extracted from success/failure trajectory pairs with **upvote/downvote counters** on insights; the nearest published analogue to graded reinforcement, but count-based and non-decaying.
- Wang, G., et al. (2023). Voyager: An Open-Ended Embodied Agent with Large Language Models. arXiv:2305.16291. — skill library with verification before storage ("probabilistic proposes, deterministic decides" applied to skills).

### Internal design documents
- `sdd/specs/dream-cycle-brain-consolidation.spec.md` (FEAT-390) — collect/cluster/distill/archive/mark/promote; non-goals; `reinforcement_count` open item.
- `sdd/specs/episodicmemorystore.spec.md`, `sdd/specs/long-term-memory.spec.md`, `sdd/specs/refactor-episodic-agentcorememory.spec.md` — episodic store, unified manager and the `ValueScorer` port.
- `sdd/specs/sdd-work-ledger.spec.md` — `events.jsonl` + `ledger.db`, `find_shared_root`, `insight.recorded`, SQLite hardening; `CoderFeedback`/`CoderReview` planes.
- Project docs: `claude/per-turn-compaction-deterministic-design.md` (omission store: "forgotten but recoverable" precedent; Stage-2 hook), `claude/handle-only-execution-design.md` (`ResultPolicy`: "what you were going to put in the prompt, put in the enforcement" — the same principle behind grading only verified outcomes), `claude/sdd-work-ledger.brainstorm.md`.
- `.claude/agents/sdd-worker.md` §"Per-delivery correction feedback"; `.claude/agents/sdd-coder.md` §a.1 "Apply Previous Delivery Feedback".
