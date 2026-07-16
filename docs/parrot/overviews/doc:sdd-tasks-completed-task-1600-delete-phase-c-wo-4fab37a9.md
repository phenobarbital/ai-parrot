---
type: Wiki Overview
title: 'TASK-1600: Delete Phase C LiveKit Agents worker stack'
id: doc:sdd-tasks-completed-task-1600-delete-phase-c-worker-stack-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase C (FEAT-243/246) — the LiveKit Agents STT/VAD/TTS worker that ran in
  a
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
---

# TASK-1600: Delete Phase C LiveKit Agents worker stack

**Feature**: FEAT-249 — LiveAvatar + Voice Consolidation
**Spec**: `sdd/specs/liveavatar-voice-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1599
**Assigned-to**: unassigned

---

## Context

Phase C (FEAT-243/246) — the LiveKit Agents STT/VAD/TTS worker that ran in a
separate process — is the rejected "Option C" intermediate. No canonical mode
(A/B/C/D) uses it; it has no e2e run, only fake tests. Delete it entirely.
(Spec §1, §3.1, §5.) No backward-compat / shim imports.

---

## Scope

- Delete the whole `liveavatar/livekit_agent/` subpackage:
  `agent.py` (`LiveAvatarAgent`), `worker.py`, `pipeline.py`,
  `voice_adapters.py`, `models.py` (`AvatarJobMetadata` — note
  `StructuredOutputMessage` already moved in TASK-1599), `__init__.py`,
  `VOICE_ADAPTERS.md`.
- Delete the worker launcher `examples/liveavatar_voice_worker.py`.
- Delete `build_standalone_bot_resolver` from `manager/bot_resolver.py`
  (delete the whole file **iff** no other consumer — grep first).
- Remove all `livekit_agent` / `AvatarJobMetadata` / `LiveAvatarAgent` re-exports
  from `liveavatar/__init__.py`.
- Delete Phase-C-only tests: `test_livekit_worker.py`, `test_livekit_agent.py`,
  pipeline/adapter tests, `test_livekit_agent_models.py` (its
  `StructuredOutputMessage` assertions moved in TASK-1599).

**NOT in scope**: server endpoints/`stream.py`/`room_manager` (TASK-1601); the
Redis transport (`output_transport.py` / `liveavatar_output.py` are KEPT —
TASK-1603); pyproject extras (TASK-1604).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../liveavatar/livekit_agent/` (entire dir) | DELETE | Phase C worker package |
| `examples/liveavatar_voice_worker.py` | DELETE | worker launcher |
| `packages/ai-parrot-server/src/parrot/manager/bot_resolver.py` | MODIFY/DELETE | remove `build_standalone_bot_resolver` (delete file if unused) |
| `.../liveavatar/__init__.py` | MODIFY | drop Phase C re-exports |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_livekit_*.py` | DELETE | Phase C tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures / Anchors
```python
# liveavatar/livekit_agent/  — files: __init__.py, models.py, agent.py,
#   worker.py, pipeline.py, voice_adapters.py, VOICE_ADAPTERS.md
# liveavatar/livekit_agent/agent.py:60   class LiveAvatarAgent(_LiveKitAgent)  (llm_node :221)
# liveavatar/livekit_agent/models.py:22  class AvatarJobMetadata(BaseModel)   (DELETE)
# examples/liveavatar_voice_worker.py  — calls worker.configure(..., agent_name="liveavatar-voice"); worker.run()
# packages/ai-parrot-server/.../manager/bot_resolver.py  — build_standalone_bot_resolver()
```

### Verify before deleting
```bash
grep -rn "livekit_agent\|AvatarJobMetadata\|LiveAvatarAgent\|build_standalone_bot_resolver" packages/ --include=*.py | grep -v "/tests/"
# After this task, the ONLY remaining hits should be in TASK-1601 targets (avatar.py/stream.py/manager.py), which that task removes.
```

### Does NOT Exist (after this task)
- ~~`parrot.integrations.liveavatar.livekit_agent`~~ — package deleted
- ~~`AvatarJobMetadata`~~ — deleted (was Phase-C-only)

---

## Implementation Notes
- Order matters: TASK-1599 must be done first (so `StructuredOutputMessage` no
  longer lives here).
- `import parrot.integrations.liveavatar` must still succeed after deletion —
  check `__init__.py` has no dangling `from .livekit_agent...`.
- If `bot_resolver.py` has other consumers, keep the file and remove only the
  Phase-C function.

---

## Acceptance Criteria
- [ ] `liveavatar/livekit_agent/` does not exist.
- [ ] `python -c "import parrot.integrations.liveavatar"` succeeds.
- [ ] No non-test references to `livekit_agent`, `AvatarJobMetadata`, `LiveAvatarAgent` outside TASK-1601 targets.
- [ ] Phase C tests removed; remaining integration test suite collects without ImportError.

---

## Agent Instructions
Standard SDD flow.

## Completion Note
Implemented 2026-06-19. Deleted entire `livekit_agent/` subpackage (6 files),
`examples/liveavatar_voice_worker.py`, `manager/bot_resolver.py` (no other consumers),
VOICE_ADAPTERS.md, and all Phase C tests (test_livekit_agent.py, test_livekit_worker.py,
test_livekit_agent_models.py, test_voice_adapters.py). `import parrot.integrations.liveavatar`
still succeeds. 151 remaining integration tests pass.
