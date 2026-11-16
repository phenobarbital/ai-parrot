# TASK-5696: Wire the experience config knobs, fix tier routing, frame briefings, add the missing spec tests

**Feature**: FEAT-887 — SDD Experience Memory (`experience.pitfall`)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5695, TASK-5588, TASK-5592, TASK-5593, TASK-5595, TASK-5596, TASK-5601, TASK-5603, TASK-5608
**Assigned-to**: unassigned
**Discovered-from**: `issue:f8f19fc19fa9`

---

## Context

Deferred review leftovers on FEAT-887:

1. 12 of the 71 test names in spec §4 do not exist: `test_append_event_never_raises`,
   `test_session_file_name_is_hashed`, `test_hook_post_failure_injects_candidate_labeled`,
   `test_hook_advice_cooldown`, `test_hook_never_rebuilds_or_graduates`, `test_hook_never_blocks`,
   `test_hook_outcome_claude`, `test_hook_codex_outcome_from_rollout`,
   `test_hook_unknown_outcome_records_nothing`, `test_hook_agy_unreadable_transcript_defers_to_replay`,
   `test_agy_tool_step_outcomes_collected`, `test_worktree_uses_primary_plane` (the last one lands
   with TASK-5694).
2. `ExperienceConfig.advice_cooldown_seconds`, `pairing_excluded_executables`, `max_session_pending`
   and `max_transcript_tail_bytes` are declared but the hook path hardcodes them; the index also
   builds with `ExperienceConfig()` defaults instead of the project's configuration.
3. `transitions._append_paired_lesson` routes any absolute-path command to the repo tier;
   `ExperienceService._is_repo_local` has the spec rule.
4. The briefing bullets (`ExperienceService._brief_bullet`) reach MCP coder seats without the
   untrusted-data framing the spec requires (§2 Trust model (4)); `sdd-coder.md` and its twins do
   not tell the coder to treat experience text as data.

---

## Scope

- Config: `ExperienceService` hands its project config to `ExperienceIndex`; `rebuild` publishes the
  hook knobs (`advice_cooldown_seconds`, `pairing_excluded_executables`, `max_session_pending`,
  `max_transcript_tail_bytes`, plus the existing bounds) in `fastpath.json`; the hook reads them with
  a bounded, validated stdlib loader (defaults when absent/invalid) and passes them to
  `transitions.on_outcome`, which uses them instead of module constants; the interceptor passes the
  service config's values.
- Tier routing: paired lessons use the same repo-local rule as `ExperienceService._is_repo_local`
  (extract it to a shared stdlib helper used by both).
- Framing: briefing output carries one fixed unverified-data header; add one sentence to
  `.claude/agents/sdd-coder.md` and its three twins telling the coder that experience notes are
  data recorded by other agents, not instructions.
- Add the 11 missing spec §4 tests listed above (minus `test_worktree_uses_primary_plane`).

**NOT in scope**: the review's optional suggestions (sync I/O in the interceptor constructor,
word-vs-token budget, graduation's private lock API, the codex `TypeError` shim, symlink-refusing
`experience_dirs`) — recorded in the Completion Note, not implemented.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py` | MODIFY | accept config; publish hook knobs |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py` | MODIFY | pass config to index; shared repo-local rule; framed briefing |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py` | MODIFY | `load_hook_limits`; `is_repo_local_command` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py` | MODIFY | limits parameter; repo-local tier rule |
| `packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py` | MODIFY | read published limits |
| `packages/ai-parrot/src/parrot/flows/dev_loop/experience.py` | MODIFY | pass service limits to `on_outcome` |
| `.claude/agents/sdd-coder.md` | MODIFY | untrusted-data sentence |
| `.agents/agents/sdd-coder/agent.md` | MODIFY | twin |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-coder.md` | MODIFY | twin |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/agents/sdd-coder/agent.md` | MODIFY | twin |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py` | MODIFY | M1 spec tests |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_service.py` | MODIFY | framing + config hand-off |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_transitions.py` | MODIFY | limits + tier routing |
| `packages/ai-parrot/tests/sdd/test_experience_hook.py` | MODIFY | M4 spec tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` | MODIFY | `test_agy_tool_step_outcomes_collected` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.experience.models import ExperienceConfig  # models.py (advice_cooldown_seconds at :88)
from parrot.knowledge.wiki.experience.service import ExperienceService  # service.py
from parrot.knowledge.wiki.experience.index import ExperienceIndex  # index.py:49
```

### Existing Signatures to Use
```python
# index.py:49
def __init__(self, plane_dir: Path, *, read_only: bool = False) -> None
# service.py:57 constructs ExperienceIndex(plane_dir, read_only=False)
# service.py:282
def _is_repo_local(self, executable: str, scope_paths: Sequence[str]) -> bool
# service.py:303
@staticmethod
def _brief_bullet(lesson: Lesson) -> str
# transitions.py:25-46 — the hardcoded knobs (_ADVICE_COOLDOWN_SECONDS, _MAX_PENDING, _PAIRING_EXCLUDED_EXECUTABLES)
# experience_hook.py:23-25 — _MAX_TRANSCRIPT_TAIL_BYTES, _MAX_SESSION_PENDING
# flows/dev_loop/dispatchers/google_coding.py:121
def parse_agy_tool_step(step_update: Any) -> Optional[AgyToolStep]
```

### Does NOT Exist
- `fastpath.load_hook_limits`, `fastpath.is_repo_local_command` — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/experience.py", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-coder.md", "action": "MODIFY"},
    {"path": ".agents/agents/sdd-coder/agent.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-coder.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/agents/sdd-coder/agent.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_transitions.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_experience_hook.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py#ExperienceIndex",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py#ExperienceService._is_repo_local",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py#ExperienceService._brief_bullet",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py#_append_paired_lesson",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#parse_agy_tool_step"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Hook path stays stdlib-only; config reaches it only through the published `fastpath.json`.
- The four `sdd-coder` copies must stay byte-identical where the asset-sync check requires it.

---

## Implementation Blueprint

### Steps (in order)
1. Index config hand-off + published knobs; `fastpath.load_hook_limits`.
2. `on_outcome(..., limits=...)`; hook and interceptor pass limits.
3. Shared repo-local helper; framed briefing; sdd-coder sentence ×4.
4. Missing spec tests.

---

## Acceptance Criteria

- [ ] A non-default `advice_cooldown_seconds` / `max_session_pending` / excluded executable changes hook behaviour after `rebuild`.
- [ ] Paired-lesson tier matches `_is_repo_local`.
- [ ] Briefing output and sdd-coder docs carry the untrusted-data framing.
- [ ] All 71 spec §4 test names exist.
- [ ] `ruff check` clean; asset-sync check passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_service.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_transitions.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_index.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_experience_hook.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_experience_interceptor.py -q`
- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`

---

## Test Specification

The 11 spec §4 names above, each asserting its spec row.

---

## Agent Instructions

Follow `docs/sdd/WORKFLOW.md` § "Implementing a task by hand" inside
`.parrot/worktrees/feat-FEAT-887-sdd-experience-memory`.

---

## Completion Note

*(Agent fills this in when done)*
