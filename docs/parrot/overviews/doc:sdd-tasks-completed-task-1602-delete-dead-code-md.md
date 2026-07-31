---
type: Wiki Overview
title: 'TASK-1602: Delete remaining dead/duplicate code'
id: doc:sdd-tasks-completed-task-1602-delete-dead-code-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Several modules are unwired/superseded and confirmed dead by the audit
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.voice
  rel: mentions
---

# TASK-1602: Delete remaining dead/duplicate code

**Feature**: FEAT-249 — LiveAvatar + Voice Consolidation
**Spec**: `sdd/specs/liveavatar-voice-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1601
**Assigned-to**: unassigned

---

## Context

Several modules are unwired/superseded and confirmed dead by the audit
(Spec §3.2, §3.3, §3.4). Remove them. No backward-compat / shim imports.

---

## Scope

- `liveavatar/orchestrator.py` — delete `AvatarSessionOrchestrator` +
  `make_supertonic_pcm_fn` (dead one-shot LITE predecessor, never instantiated).
- `liveavatar/fullmode_observer.py` — delete `FullModeRoomObserver` (dead stub;
  `connect()` never connects, not wired, `livekit-rtc` never declared).
- `models.py` — delete `TenantAvatarConfig` (defined, consumed nowhere).
- `voice/server.py` — delete `VoiceChatServer` (standalone Gemini POC dup of
  `VoiceChatHandler`). **Verify no entrypoint imports `create_voice_server` from
  `server.py`** before deleting (note: `handler.py` also defines a
  `create_voice_server` — keep that one).
- `voice/session.py` — delete `VoiceSession` / `VoiceSessionManager` (third
  unused realtime impl; latent `session.close()` bug).
- Remove all corresponding `__init__.py` re-exports and delete their tests
  (`test_orchestrator.py`, `test_fullmode_observer.py`, and any `voice/session`/
  `voice/server` tests).

**NOT in scope**: `voice_session.py` (`VoiceAvatarSession` — KEEP, FEAT-245 Mode
D); `output_bridge.py` / `output_transport.py` (KEEP — TASK-1603);
`speaker.py` / `voice_provider.py` / `avatar_ws.py` / `client.py` / `speakable.py`
/ `tenant_config.py` (KEEP).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../liveavatar/orchestrator.py` | DELETE | dead predecessor |
| `.../liveavatar/fullmode_observer.py` | DELETE | dead stub |
| `.../liveavatar/models.py` | MODIFY | remove `TenantAvatarConfig` |
| `packages/ai-parrot-integrations/src/parrot/voice/server.py` | DELETE | Gemini POC dup |
| `packages/ai-parrot-integrations/src/parrot/voice/session.py` | DELETE | unused realtime dup |
| `.../liveavatar/__init__.py` | MODIFY | drop dead re-exports |
| tests for the above | DELETE | |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures / Anchors (verified)
```python
# liveavatar/orchestrator.py:93  AvatarSessionOrchestrator ; :47 make_supertonic_pcm_fn   (DELETE)
# liveavatar/fullmode_observer.py:64  FullModeRoomObserver  (DELETE)
# liveavatar/models.py:187  TenantAvatarConfig(BaseModel)   (DELETE)
# voice/server.py  VoiceChatServer (class) + create_voice_server (DELETE this file's copy)
# voice/handler.py:1443  create_voice_server  (KEEP — this is the maintained one)
# voice/session.py  VoiceSession / VoiceSessionManager  (DELETE)
# liveavatar/__init__.py re-exports include: AvatarSessionOrchestrator, FullModeRoomObserver, TenantAvatarConfig  (REMOVE)
```

### Verify before deleting `voice/server.py`
```bash
grep -rn "from parrot.voice.server import\|voice.server\|VoiceChatServer" packages/ examples/ --include=*.py | grep -v "/tests/"
# If any non-test entrypoint imports create_voice_server FROM server.py, redirect it to handler.py first.
```

### Does NOT Exist (after this task)
- ~~`AvatarSessionOrchestrator`, `FullModeRoomObserver`, `TenantAvatarConfig`~~ — deleted
- ~~`parrot.voice.server`, `parrot.voice.session`~~ — deleted
- ~~`VoiceAvatarSession`~~ — **NOT deleted** (kept for Mode D)

---

## Implementation Notes
- After removal: `python -c "import parrot.integrations.liveavatar; import parrot.voice"` must succeed.
- `VoiceAvatarSession` (`voice_session.py`) is a different file from
  `voice/session.py` — do not confuse them.

---

## Acceptance Criteria
- [ ] All five targets deleted; `__init__.py` re-exports removed.
- [ ] `python -c "import parrot.integrations.liveavatar"` and `import parrot.voice` succeed.
- [ ] `VoiceAvatarSession` still importable.
- [ ] Integration + voice test suites collect with no ImportError.

---

## Agent Instructions
Standard SDD flow.

## Completion Note
Implemented 2026-06-19. Deleted: orchestrator.py (AvatarSessionOrchestrator),
fullmode_observer.py (FullModeRoomObserver), voice/server.py (VoiceChatServer),
voice/session.py (VoiceSession/VoiceSessionManager). Removed TenantAvatarConfig
from models.py. Cleaned liveavatar/__init__.py to remove re-exports of
AvatarSessionOrchestrator, FullModeRoomObserver, and TenantAvatarConfig.
Deleted test_orchestrator.py, test_fullmode_observer.py. Removed TestObserverLifecycle
from test_fullmode_integration.py. Removed deleted-method tests from test_room_manager.py.
Removed TenantAvatarConfig tests from test_models.py.
Both `import parrot.integrations.liveavatar` and `import parrot.voice` verified OK.
133 liveavatar + 97 voice tests pass.
