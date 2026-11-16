# TASK-5702: Earned FSRS state in episodic recall ranking

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5701, TASK-5661, TASK-5664, TASK-5665
**Assigned-to**: claude (sdd-fix)
**Discovered-from**: `issue:c0ed6dfab09e` (ledger, severity major)

## Context

Feature review of FEAT-892 (`issue:c0ed6dfab09e`). `rank_episodes` passes `states={}` to `rank_candidates` and never sets
`MemoryCandidate.dynamics_state_ref`, and no backend can read `memory_state`. Reviews therefore commit state that no ranking
code reads: `EpisodeSearchResult.retrievability`, `stability` and `review_count` are never populated and a reviewed memory
ranks exactly like an unreviewed one.

Owner decision (Jesus Lara, 2026-11-16): retrieval-time state ranking is in scope for FEAT-892. Parameter fitting stays
deferred.

## Scope

- `SQLiteEpisodeBackend.get_memory_states(ref_keys)` reads committed state by canonical ref key
  (`packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py`).
- `episode_state_ref(episode)` and a `states` argument on `rank_episodes`; reviewed results carry retrievability, stability
  and review count (`packages/ai-parrot/src/parrot/memory/episodic/recall.py`).
- `EpisodicMemoryStore` resolves state for the four ranked routes through the optional backend capability
  (`packages/ai-parrot/src/parrot/memory/episodic/store.py`).
- Tests for the backend read, the store routes and the neutral fallbacks.

**NOT in scope:** parameter fitting or any optimizer dependency (deferred, §8 Q6); FEAT-889 brain stores; a state-read
capability for the pgvector, Redis or FAISS backends (they keep ranking neutrally); changes to `MemoryCandidate` or to
`clients/base.py`; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` | MODIFY | `get_memory_states` |
| `packages/ai-parrot/src/parrot/memory/episodic/recall.py` | MODIFY | `episode_state_ref`, `states` argument, result fields |
| `packages/ai-parrot/src/parrot/memory/episodic/store.py` | MODIFY | `_resolve_dynamics_states` on the four ranked routes |
| `packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py` | MODIFY | State-read test |
| `packages/ai-parrot/tests/memory/dynamics/test_recall.py` | MODIFY | State-driven ranking and neutral fallbacks |

## Codebase Contract

### Verified Imports

- `from parrot.memory.dynamics.models import MemoryRef, MemoryState, MemoryParameters`
- `from parrot.memory.dynamics.fsrs import retrievability`
- `from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend`
- `from parrot.memory.episodic.store import EpisodicMemoryStore`

### Existing Signatures and Anchors

- `memory_state (ref_key TEXT PRIMARY KEY, apply_revision, state, updated_at)`; `state` is JSON whose `memory_state` key
  holds `MemoryState.model_dump(mode="json")` when the review carried a grade (`backends/sqlite.py`, `apply_review`).
- `ref_key = command.ref.canonical_key`; `MemoryRef.canonical_key` hashes tenant, agent, user, session, room, crew, kind,
  memory id and content version (`dynamics/models.py`).
- `EpisodicMemoryStore.review` admits an episode only when `_episode_matches_namespace(episode, namespace)`, so the ref
  namespace of a committed review equals the episode's own namespace.
- `_EPISODIC_REVIEW_PARAMETERS.parameter_id == "episodic-neutral-v1"` (`episodic/store.py`), the id `rank_episodes` uses.
- `retrievability(state, *, now, parameters)` raises `ValueError` when `state.parameter_id` differs from the parameters.
- `EpisodeSearchResult.retrievability | stability | review_count` exist (`episodic/models.py`).

### Does NOT Exist

- A state-read method on `AbstractEpisodeBackend` or `ReviewBackend`: reading state is an optional capability detected
  with `getattr`, the same way the store detects `apply_review` and `list_reviews`.
- A `now` argument on the store's recall routes; they rank at the wall clock.

## Complexity Contract

One indexed read per ranked route, batched at 500 keys per statement. No schema change, no new dependency.

## Implementation Notes

- The spec keeps uninitialized state neutral (retrievability 1.0) and a reviewed state decays from 1.0. A reviewed episode
  therefore never outranks an otherwise equal never-reviewed one; the observable effect is that a stronger review outranks
  a weaker one as time passes. The issue's suggested "reviewed outranks unreviewed" assertion contradicts that accepted
  rule and is not implemented.
- State earned under another `parameter_id`, a backend without the capability, and a failed read all rank neutrally and
  never fail recall.

## Implementation Blueprint

1. `sqlite.py`: `get_memory_states(ref_keys) -> dict[str, MemoryState]`, batched `IN` query, unreadable rows skipped.
2. `recall.py`: `episode_state_ref`; `rank_episodes(..., states=None)` sets `dynamics_state_ref`, filters usable states and
   copies retrievability, stability and review count onto reviewed `EpisodeSearchResult`s.
3. `store.py`: `_resolve_dynamics_states` and its use in `recall_similar`, `get_failure_warnings`, `get_user_preferences`
   and `get_room_context`.
4. Tests.

## Acceptance Criteria

- [ ] A committed graded review is readable by its exact canonical ref key only; a review without state exposes none.
- [ ] `recall_similar` reports retrievability, stability and review count for a reviewed episode and none for an
      unreviewed one.
- [ ] With time elapsed, a GOOD-reviewed episode outranks an otherwise equal HARD-reviewed one, and the score equals
      relevance × retrievability × (1 + importance/10).
- [ ] A failed state read and state under foreign parameters rank neutrally.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py packages/ai-parrot/tests/memory/dynamics/test_recall.py packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py -q`

## Test Specification

- `get_memory_states_reads_committed_state_by_exact_ref`: AC11/AC14: scoped state read, batching, no state for a stateless review.
- `earned_review_state_drives_recall_ranking`: AC14: reviews change ranking and are reported per result.
- `state_read_failure_and_foreign_parameters_rank_neutrally`: AC14: recall degrades to neutral, never fails.

## Agent Instructions

1. Verify the Codebase Contract against the source before editing.
2. Touch only the files listed above.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` from the feature worktree.
4. Commit code with `feat(agent-memory-mixin): TASK-5702 — Earned FSRS state in episodic recall ranking`, then close the task with `scripts/sdd/close_task.sh`.

## Completion Note

