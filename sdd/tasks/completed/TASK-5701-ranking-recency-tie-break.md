# TASK-5701: Newest-first tie-break in experiential ranking

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (<2h)
**Depends-on**: TASK-5659, TASK-5665
**Assigned-to**: claude (sdd-fix)
**Discovered-from**: `issue:a296823bbc4a` (ledger, severity major)

## Context

Feature review of FEAT-892 (`issue:a296823bbc4a`). `rank_candidates` sorts by `(group, -score, memory_id, content_version)`.
On the non-search routes (`get_failure_warnings`, `get_user_preferences`, `get_room_context`) every candidate has relevance
1.0 and neutral state, so equal-importance episodes tie and order by `episode_id`, a random UUID. The routes then truncate
with `[:limit]`, returning an arbitrary subset where the previous behaviour returned the newest. That conflicts with AC14's
baseline-behaviour requirement.

Owner decision (Jesus Lara, 2026-11-16): add creation time, newest first, as a documented tie-break before `memory_id`.

## Scope

- `rank_candidates` accepts caller-resolved creation times and breaks score ties newest first, then by `memory_id`, then by
  `content_version` (`packages/ai-parrot/src/parrot/memory/dynamics/ranking.py`).
- `rank_episodes` passes each episode's `created_at` (`packages/ai-parrot/src/parrot/memory/episodic/recall.py`).
- Tests for the tie-break and for the truncated routes.
- The spec ranking paragraph and `wiki/memory/memory-dynamics.md` state the tie-break.

**NOT in scope:** parameter fitting or any optimizer dependency (deferred, §8 Q6); FEAT-889 brain stores; a state-read
capability for the pgvector, Redis or FAISS backends (they keep ranking neutrally); changes to `MemoryCandidate` or to
`clients/base.py`; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/dynamics/ranking.py` | MODIFY | `recency` argument and newest-first tie-break |
| `packages/ai-parrot/src/parrot/memory/episodic/recall.py` | MODIFY | Pass `created_at` per episode to `rank_candidates` |
| `packages/ai-parrot/tests/memory/dynamics/test_ranking.py` | MODIFY | Tie-break test |
| `packages/ai-parrot/tests/memory/dynamics/test_recall.py` | MODIFY | Truncated routes keep the newest |
| `sdd/specs/agent-memory-mixin.spec.md` | MODIFY | Ranking paragraph, `rank_candidates` signature, revision 0.9 |
| `wiki/memory/memory-dynamics.md` | MODIFY | Recall Ranking section |

## Codebase Contract

### Verified Imports

- `from parrot.memory.dynamics.ranking import rank_candidates`
- `from parrot.memory.unified.models import MemoryCandidate`
- `from parrot.memory.episodic.recall import rank_episodes`

### Existing Signatures and Anchors

- `rank_candidates(candidates, *, now, parameters, states, anti_pattern_ids=frozenset()) -> list[MemoryCandidate]`
  in `dynamics/ranking.py`; its sort key is `item[:4]` over `(group, -score, memory_id, content_version, ranked)`.
- `rank_episodes(episodes, *, namespace, now=None)` in `episodic/recall.py` builds one `MemoryCandidate` per episode.
- `EpisodicMemory.created_at: datetime` (`episodic/models.py`).

### Does NOT Exist

- `MemoryCandidate.created_at` — the model is `extra="forbid"` and is not changed; recency is passed beside the candidates,
  the same way `anti_pattern_ids` is.

## Complexity Contract

One pure function gains one optional keyword argument and one sort-key element. No I/O, no new dependency.

## Implementation Notes

A candidate without a creation time orders after the dated ones. A naive datetime is read as UTC. Existing callers that
pass no `recency` keep the previous `memory_id` order.

## Implementation Blueprint

1. `ranking.py`: add `recency: Mapping[str, datetime] | None = None`; sort by
   `(group, -score, -created_at.timestamp() or inf, memory_id, content_version)`.
2. `recall.py`: pass `recency={episode.episode_id: episode.created_at for episode in episodes}`.
3. Tests, spec and wiki.

## Acceptance Criteria

- [ ] Equal-score candidates order newest first, then by `memory_id`; the result does not depend on input order.
- [ ] A higher score still outranks a newer candidate.
- [ ] `get_user_preferences`, `get_room_context` and `get_failure_warnings` return the newest equal-importance episodes
      when truncated.
- [ ] Spec and wiki state the tie-break.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_ranking.py packages/ai-parrot/tests/memory/dynamics/test_recall.py -q`

## Test Specification

- `equal_scores_order_newest_first_then_stable_id`: AC14: ties resolve by creation time, then stable ID; undated last.
- `equal_importance_routes_keep_the_newest`: AC14: truncated non-search routes keep the newest episodes.

## Agent Instructions

1. Verify the Codebase Contract against the source before editing.
2. Touch only the files listed above.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` from the feature worktree.
4. Commit code with `feat(agent-memory-mixin): TASK-5701 — Newest-first tie-break in experiential ranking`, then close the task with `scripts/sdd/close_task.sh`.

## Completion Note

- Task: TASK-5701
- Feature: agent-memory-mixin
- Implementation SHA: ce7693c6bb
- Closed at (UTC): 2026-11-16T09:34:40+00:00
- Resolves: `issue:a296823bbc4a`
- Validation: `test_ranking.py` and `test_recall.py` pass in a clean tree of the commit. The new route test fails when
  `rank_episodes` passes no recency.
- The spec ranking paragraph, the `rank_candidates` signature in the spec and `wiki/memory/memory-dynamics.md` state the tie-break
  (spec revision 0.9).
- Implemented by Claude through `/sdd-fix`, by hand (no coder seat).
