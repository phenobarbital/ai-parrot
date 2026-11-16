# TASK-5695: One deterministic failure matcher for the hook, the interceptor and the service

**Feature**: FEAT-887 — SDD Experience Memory (`experience.pitfall`)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5694, TASK-5588, TASK-5591, TASK-5592, TASK-5595, TASK-5596, TASK-5601
**Assigned-to**: unassigned
**Discovered-from**: `issue:e0f0c2637a0a`

---

## Context

Deferred review finding on FEAT-887. Spec §2 Matching: a lesson matches when executable and
subcommand equal its trigger family and the Jaccard similarity of normalized error tokens is ≥
`inject_min_score` (exact signature = 1.0); repo tier wins over global at equal score, then confirmed
over candidate, then `lesson_id`. Three implementations disagree today:

- `ExperienceService.match_failure` follows the spec.
- `experience_hook._trigger_matcher` returns the first stub (in `lesson_id` order) whose
  `error_tokens` are all substrings of the lowercased error — no threshold, no tier/state ranking
  (stubs carry no tier), and an empty `error_signature` matches every failure of that family.
- `flows/dev_loop/experience.ExperienceInterceptor._matcher` uses Jaccard but ignores tier/state.

---

## Scope

- Add stdlib-only `fastpath.signature_similarity(expected_signature, error)` and
  `fastpath.best_trigger(stubs, executable, subcommand, error, *, min_score)` implementing §2
  Matching, including the tie-break order.
- `reducer.match_score` delegates its scoring to `signature_similarity` (one formula).
- `index._triggers` publishes `tier` in every stub, and `fastpath.json` publishes `inject_min_score`.
- The hook matcher and the interceptor matcher both call `best_trigger`; the hook reads the
  threshold from `fastpath.json` (default 0.35 when absent/invalid).
- `transitions._valid_stub` accepts an optional `tier` in `{"repo", "global"}`; a stub without it
  ranks as `global` (older published indexes keep working until the next rebuild).
- Tests: two competing stubs (repo vs global at equal score; confirmed vs candidate) resolve the
  same way in hook, interceptor and service; an empty-signature stub does not match an unrelated
  error; a below-threshold stub never matches.

**NOT in scope**: other config knobs (TASK-5696), BM25 briefing ranking.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py` | MODIFY | `signature_similarity`, `best_trigger` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/reducer.py` | MODIFY | `match_score` delegates scoring |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py` | MODIFY | stub `tier`; `inject_min_score` in `fastpath.json` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py` | MODIFY | `_valid_stub` accepts `tier` |
| `packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py` | MODIFY | matcher uses `best_trigger` + published threshold |
| `packages/ai-parrot/src/parrot/flows/dev_loop/experience.py` | MODIFY | interceptor matcher uses `best_trigger` |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py` | MODIFY | matcher unit tests |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_index.py` | MODIFY | stub carries tier; threshold published |
| `packages/ai-parrot/tests/sdd/test_experience_hook.py` | MODIFY | competing-stubs hook test |
| `packages/ai-parrot/tests/flows/dev_loop/test_experience_interceptor.py` | MODIFY | competing-stubs interceptor test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.experience.fastpath import normalize_error, load_triggers  # fastpath.py:193, 327
from parrot.knowledge.wiki.experience.reducer import match_score  # reducer.py:39
```

### Existing Signatures to Use
```python
# reducer.py:39
def match_score(lesson: Lesson, executable: str, subcommand: str, error: str) -> float
# service.py:147 — the reference ordering: (-score, tier != "repo", state != "confirmed", lesson_id)
async def match_failure(self, command: str, error: str, *, session: str) -> Lesson | None
# index.py:239 — builds the executable-keyed stub map
def _triggers(self, lessons, recording_sessions) -> dict[str, list[dict[str, Any]]]
# experience_hook.py:422
def _trigger_matcher(plane_dir: Path)
# flows/dev_loop/experience.py:103
async def _matcher(self) -> Callable[[str, str, str], Mapping[str, Any] | None] | None
# transitions.py:301
def _valid_stub(stub: Mapping[str, Any] | None) -> bool
```

### Does NOT Exist
- Stubs have no `tier` key today; `fastpath.json` has no `inject_min_score` today.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/reducer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/experience.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_index.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_experience_hook.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_experience_interceptor.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/reducer.py#match_score",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py#ExperienceService.match_failure",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py#ExperienceIndex._triggers",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py#_trigger_matcher",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/experience.py#ExperienceInterceptor._matcher",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py#_valid_stub"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `fastpath.py`/`experience_hook.py` are protected control files — implemented from the host.
- `best_trigger` must not raise on malformed stubs; skip them.

---

## Implementation Blueprint

### Steps (in order)
1. `signature_similarity` (normalize both sides; equal → 1.0; else Jaccard; empty union → 0.0).
2. `best_trigger` filters family + `min_score`, ranks `(-score, tier_rank, state_rank, lesson_id)`.
3. Wire reducer, index, hook, interceptor and `_valid_stub`.

### FILL IN checklist
- [ ] stub tokens joined before normalizing (mirrors the interceptor today)

---

## Acceptance Criteria

- [ ] Hook, interceptor and service pick the same lesson for the same failure.
- [ ] Empty or low-similarity triggers never match.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_index.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_reducer.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_experience_hook.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_experience_interceptor.py -q`

---

## Test Specification

```python
def test_best_trigger_prefers_repo_then_confirmed_at_equal_score(): ...
def test_best_trigger_empty_signature_does_not_match_unrelated_error(): ...
def test_hook_matcher_ranks_competing_stubs(tmp_path): ...
async def test_interceptor_matcher_ranks_competing_stubs(tmp_path): ...
```

---

## Agent Instructions

Follow `docs/sdd/WORKFLOW.md` § "Implementing a task by hand" inside
`.parrot/worktrees/feat-FEAT-887-sdd-experience-memory`.

---

## Completion Note

*(Agent fills this in when done)*
