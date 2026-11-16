# TASK-5703: Episodic recall visibility — same user across sessions plus agent-level episodes

**Feature**: FEAT-892 — Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5663, TASK-5670
**Assigned-to**: claude (sdd-fix)
**Discovered-from**: `issue:2a40a9f62877` (ledger, severity major)

## Context

`UnifiedMemoryManager._get_episodic_candidates` recalls with `_namespace_for_scope(scope)`, which copies the
request's `user_id` and `session_id` into the namespace, and `MemoryNamespace.build_filter` turns every set
dimension into an exact filter. `BaseBot` always sets a session, so automatic recall only ever saw episodes of
the same user **and** the same session. A lesson never reached the user's next session, and episodes recorded with
neither a user nor a session were never recalled at all: the agent's own `record_lesson` episodes (the toolkit
namespace is `(tenant, agent)`), crew episodes, and rows written before request scoping existed.

Owner decision (2026-11-16, asked by `/sdd-fix issue:2a40a9f62877`): **recall the same user across all sessions,
plus the NULL-user episodes; never another user's**. Writes keep the full request namespace.

One correction to the issue text, verified on `origin/dev`: the legacy unified manager did **not** write
`user_id` NULL. `_record_episodic` stamped `user_id` and `session_id` and recalled with `self.namespace`
(`(tenant, agent)`, every user). Those rows are recalled again by the same user under this task. Rows with no
user and no session come from the toolkit, the crew recorder and anonymous callers.

## Scope

- `MemoryNamespace.build_filter(null_dimensions=...)`: a named unset dimension is emitted as `None`, meaning
  "match only episodes that leave it unset". Without it an unset dimension stays unconstrained.
- `EpisodicMemoryStore.recall_similar(null_dimensions=...)` forwards it, on the embedding path and on the lexical
  fallback.
- Backends apply a `None` filter value before their limit: pgvector emits `IS NULL` (four filter loops);
  SQLite and FAISS already do; Redis cannot (unset is an unindexed empty TAG) and returns no rows instead of
  ignoring the filter.
- `HybridBM25Strategy._namespace_key` keeps `None` apart from the text `"None"`, so an unset-only filter never
  shares a lexical index with a user spelled `None`.
- `UnifiedMemoryManager._get_episodic_candidates` recalls each visibility scope, re-checks every returned
  episode, merges, and keeps `episodic_max_warnings`:
  - identified user → that user's episodes in every session;
  - anonymous request with a session → that session's episodes with `user_id` unset;
  - always → agent-level episodes: `user_id` **and** `session_id` unset.
  Set room, crew and model dimensions keep narrowing every scope.
- An episode that was not recorded under the exact request namespace is tagged `episodic_context`. It is
  delivered, but it stays out of the review manifest (`_delivered_memory_ref` only accepts `episodic`).
- Document the visibility in `wiki/memory/agent-memory.md`.

**NOT in scope**:

- Citing or reviewing an episode from another session or from the agent level. Review identity is the exact
  namespace in `EpisodicMemoryStore.cite/review`, `validate_citation` and `MemoryRef.canonical_key` (spec B1–B3).
- Matching unset dimensions on Redis (needs `INDEXEMPTY`/`INDEXMISSING` and an index migration).
- The agent-facing `search_episodic_memory` tool, which searches the toolkit namespace `(tenant, agent)`.
- `get_context_for_query` / `_get_episodic_warnings`, the legacy path that recalls with `self.namespace`.
- Where an episode is recorded: `_record_response_event` and `_namespace_for_scope` do not change.

Agent-level means user **and** session unset, not user unset alone: an anonymous session's episodes carry the
visitor's query text, and showing them to every user would break "never another user's".

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/models.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/episodic/store.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/episodic/recall.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py` | MODIFY (docstring) |
| `packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py` | MODIFY |
| `packages/ai-parrot/src/parrot/memory/unified/manager.py` | MODIFY |
| `packages/ai-parrot/tests/memory/unified/test_manager_real_store.py` | MODIFY |
| `packages/ai-parrot/tests/memory/dynamics/test_backend_scope.py` | MODIFY |
| `wiki/memory/agent-memory.md` | MODIFY |

## Codebase Contract (Anti-Hallucination)

Verified at `9201044d88` (feature branch head when the task was written).

### Verified Imports

```python
from parrot.memory.agent_memory.models import MemoryRequestScope      # agent_memory/models.py:52
from parrot.memory.episodic.models import MemoryNamespace             # episodic/models.py:210
from parrot.memory.episodic.store import EpisodicMemoryStore          # episodic/store.py
from parrot.memory.episodic.recall import HybridBM25Strategy          # episodic/recall.py:192
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend  # backends/sqlite.py:153
from parrot.memory.unified.manager import UnifiedMemoryManager        # unified/manager.py:60
```

### Existing Signatures to Use

- `MemoryNamespace.build_filter(self) -> dict[str, Any]` — `episodic/models.py:235`, 1 occurrence.
- `EpisodicMemoryStore.recall_similar(self, query, namespace, top_k=5, score_threshold=0.3, category=None, include_failures_only=False)` — `episodic/store.py:816`.
- `EpisodicMemoryStore._fallback_lexical_search(self, query, namespace, *, top_k, score_threshold, include_failures_only)` — `episodic/store.py:352`.
- `HybridBM25Strategy._namespace_key(self, namespace_filter) -> str` — `episodic/recall.py:227`.
- `UnifiedMemoryManager._get_episodic_candidates(self, query, scope) -> list[MemoryCandidate]` — `unified/manager.py:592`.
- `UnifiedMemoryManager._namespace_for_scope(scope) -> MemoryNamespace` (staticmethod) — `unified/manager.py:737`.
- `UnifiedMemoryManager._delivered_memory_ref(delivered_ref, scope)` returns `None` unless the ref source is
  `episodic` — `unified/manager.py:403`.
- `ContextAssembler._candidate_ref` renders `f"{source}:{memory_id}:{content_version}"` — `unified/context.py:244`;
  the section comes from `candidate_type`, not from `source`.
- SQLite already turns a `None` filter value into `IS NULL` — `backends/sqlite.py` (`clauses.append(f"{field} IS NULL")`, 2 occurrences).
- FAISS compares with `getattr(episode, field, None) != value` — `backends/faiss.py:44`, so `None` matches unset.

### Does NOT Exist

- No `IS NULL` support in `backends/pgvector.py` filter loops: `{field} = $n` with `None` matches nothing.
- No way to match an unset TAG in `backends/redis_vector.py`: unset is stored as `""` and the index has neither
  `INDEXEMPTY` nor `INDEXMISSING`.
- No `MemoryNamespace` field or flag for unset-only matching; do not add one (the namespace is part of
  `MemoryRef`, whose canonical key is frozen by B3).
- No episodic backend other than SQLite in `AgentMemoryConfig` (`episodic_backend: Literal["sqlite"]`).
- `MemoryCandidate` has no namespace field (`extra="forbid"`); the candidate `source` is the only marker.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/memory/episodic/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/episodic/store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/episodic/recall.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/unified/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/memory/unified/test_manager_real_store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/test_backend_scope.py", "action": "MODIFY"},
    {"path": "wiki/memory/agent-memory.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace.build_filter",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.recall_similar",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager._namespace_for_scope",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager._get_episodic_candidates"
  ]
}
```

## Implementation Notes

### Key Constraints

- Scope before top-k (spec §3, line 130): each visibility scope is one backend query with its own filter and its
  own `top_k`; the merged list is cut to `top_k` again. Never fetch wide and filter afterwards.
- The manager re-checks every returned episode with the same visibility rule. The backend filter gives a correct
  top-k; the re-check keeps a backend that ignores a `None` filter value from widening recall.
- One failing scope must not hide the other: gather with `return_exceptions=True`, log the exception class.
- `null_dimensions` is a parameter of `recall_similar` only. The cached paths (`get_failure_warnings`,
  `get_user_preferences`, `get_room_context`) key their cache by namespace and must not learn it here.
- `store.py` and `recall.py` are being edited by sibling review-fix tasks (TASK-5701, TASK-5702): keep those two
  diffs to the listed lines and add no import to `store.py`.

## Implementation Blueprint

### Steps (in order)

1. `models.py`: `build_filter(self, *, null_dimensions: Collection[str] = ())`. After the existing dimensions, for
   each named dimension: reject one outside `("user_id", "session_id", "room_id", "crew_id", "model_id")`, reject
   one that is set on the namespace, else `filters[dimension] = None` — because asking for "unset only" on a set
   dimension is a caller bug, not a filter.
2. `store.py`: add `null_dimensions: tuple[str, ...] = ()` to `recall_similar` and `_fallback_lexical_search`;
   build both filters with `namespace.build_filter(null_dimensions=null_dimensions)`.
   `# occurrences: ns_filter = namespace.build_filter() → 3; edit only the one inside recall_similar (store.py:841)`
   `# occurrences: namespace_filter = namespace.build_filter() → 2; edit only the one inside _fallback_lexical_search (store.py:365)`
3. `backends/pgvector.py`: in each of the 4 loops, `if value is None: conditions.append(f"{field} IS NULL"); continue`
   before the bound parameter — because `= NULL` is never true and a bound `None` would shift nothing.
4. `backends/redis_vector.py`: module helper `_matches_unset_dimension(namespace_filter) -> bool`; in
   `search_similar`, `get_recent` and `count`, return `[]` / `[]` / `0` right after the `_redis is None` guard —
   because skipping the value (today's `if value is not None`) would widen the scope to every value.
5. `backends/abstract.py`: state the `None` contract in the protocol docstring.
6. `recall.py`: `f"{k}={v!r}"` in `_namespace_key`; `invalidate` drops every cached index of the same tenant and
   agent — because recall now reads through wider filters than the one an episode is written under.
7. `manager.py`: `_recall_scopes(scope)` (classmethod), `_visible_to_scope(episode, scope)`,
   `_recorded_under(episode, namespace)`, module constant `_CONTEXT_ONLY_EPISODIC_SOURCE = "episodic_context"`;
   rewrite the retrieval half of `_get_episodic_candidates` (gather → re-check → merge by `episode_id` → sort by
   `(-ranking_score, episode_id)` → cut to `top_k`) and pick the candidate `source`.
8. Tests, then the wiki page.

### FILL IN checklist

- [x] Anonymous request with a session never reads an identified user's episode of that session.
- [x] A request with neither user nor session recalls agent-level episodes only.
- [x] Room, crew and model set on the request narrow the agent-level scope too.

## Acceptance Criteria

- [ ] A failure recorded for user `u1` in session `s1` is recalled for `u1` in session `s2`, and for no other user.
- [ ] An episode with no user and no session is recalled for every request of the agent, on SQLite, pgvector and FAISS.
- [ ] An anonymous session's episode is recalled only inside that session.
- [ ] A backend that ignores an unset-only filter does not leak another user's episode.
- [ ] Only episodes recorded under the exact request namespace enter the review manifest; the others are delivered
      as `episodic_context`.
- [ ] Redis returns no rows, and issues no search, for an unset-only filter.
- [ ] `ruff check` and `black --check -l 120` pass on the changed files.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/unified/test_manager_real_store.py -q`
- `pytest packages/ai-parrot/tests/memory/dynamics/test_backend_scope.py -q`
- `pytest packages/ai-parrot/tests/memory/unified/test_manager.py packages/ai-parrot/tests/memory/unified/test_context.py -q`
- `pytest packages/ai-parrot/tests/memory/agent_memory/test_documentation.py -q`

## Test Specification

`tests/memory/unified/test_manager_real_store.py` (real `EpisodicMemoryStore` over FAISS, lexical fallback):

- `test_recall_crosses_sessions_of_the_same_user`
- `test_recall_includes_agent_level_episodes` (identified user, anonymous session, other anonymous session, no identity)
- `test_set_room_keeps_narrowing_every_recall_scope`
- `test_only_exact_scope_episodes_enter_the_review_manifest`
- `test_backend_ignoring_unset_filters_cannot_widen_recall`
- `test_one_failing_recall_scope_does_not_hide_the_other`
- `test_response_episode_is_still_recorded_under_the_full_request_namespace`

`tests/memory/dynamics/test_backend_scope.py`:

- `test_build_filter_emits_unset_only_dimensions`
- `test_unset_only_filter_is_applied_before_limits` (FAISS and SQLite end to end; pgvector SQL; Redis fail-closed)
- `test_hybrid_index_key_separates_unset_from_the_text_none`
- `test_hybrid_invalidation_reaches_wider_indexes_of_the_same_agent`

## Agent Instructions

1. Verify the Codebase Contract against the source before editing.
2. Touch only the files listed above.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` from the feature worktree.
4. Commit code with `feat(agent-memory-mixin): TASK-5703 — episodic recall visibility`, then close the task with
   `scripts/sdd/close_task.sh`.

## Completion Note

**Completed by**: claude (`/sdd-fix`, actor `agent:sdd-fix:436cb5fa`)
**Date**: 2026-11-16
**Notes**: Implemented as scoped. Developed in an isolated baseline tree because three sibling `/sdd-fix`
sessions were editing this worktree, then replayed onto the branch (code commit `47eb4be4ba`). The feature's
validation contract (35 files) passes on the branch head: 303 passed, 2 skipped. The new tests were
mutation-checked: reverting each source file fails the test that covers it.

External review (codex, neutral brief), three findings, all adopted:

- CONFIRM — an anonymous request could read an identified user's episode recorded in the same session. The
  anonymous scope now also requires `user_id` unset, in the backend filter and in the re-check.
- CONFIRM — a write under `(user, session)` did not invalidate the wider hybrid BM25 indexes that recall now
  reads. `HybridBM25Strategy.invalidate` drops every cached index of the same tenant and agent.
- CONFIRM — the write-scope test never wrote. It now records a response event and reads the stored episode.

Follow-ups filed, not fixed here: `issue:3b9765e02458` (the `search_episodic_memory` tool returns other users'
episodes), plus the two limits listed under "NOT in scope" (cross-scope review identity, Redis unset matching).

**Deviations from spec**: none. Spec §3 line 130 says episode filters "may narrow by session"; recall no longer
does, by owner decision. Agent-level is read as user **and** session unset, narrower than the decision's wording
("user_id is NULL"), so that an anonymous session's text never reaches other users.
