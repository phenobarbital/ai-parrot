---
type: Wiki Overview
title: 'TASK-1610: Mode A — end-to-end validation against the sandbox'
id: doc:sdd-tasks-completed-task-1610-mode-a-e2e-validation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mode A (text/voice + LITE avatar, FEAT-231 + FEAT-242) is implemented and
  wired,
---

# TASK-1610: Mode A — end-to-end validation against the sandbox

**Feature**: FEAT-249 — LiveAvatar + Voice Consolidation
**Spec**: `sdd/specs/liveavatar-voice-consolidation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1604
**Assigned-to**: unassigned

---

## Context

Mode A (text/voice + LITE avatar, FEAT-231 + FEAT-242) is implemented and wired,
but every existing test uses fakes — there is **no real e2e**. Add at least one
real integration test and fix anything the run surfaces. (Spec §4 M-A1, §5.)

---

## Scope

- Add a real integration test (marked `@pytest.mark.integration`, gated by
  `LIVEAVATAR_API_KEY`) that:
  1. starts a LITE avatar session via `/api/v1/agents/avatar/{agent_id}/start`,
  2. drives a chat turn via `/api/v1/agents/chat/{agent_id}` (stream) and
     confirms the avatar "mouth" path runs (`AvatarTurnSpeaker` feeds PCM),
  3. stops via `/stop`.
- Run against the **production** avatar (set `LIVEAVATAR_SANDBOX=false`,
  avatar `5761a14c`) per the known sandbox 400 issue; document required env.
- Fix any real-world breakage surfaced (no redesign — bugfix only).

**NOT in scope**: new features; FULL mode (Mode B); Gemini (Mode D).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/handlers/test_mode_a_e2e.py` | CREATE | real sandbox/prod integration test (gated) |
| (bugfixes) | MODIFY | only if the e2e surfaces real defects |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / Signatures
```python
# handlers/avatar.py  _start_avatar_session :77 ; _stop_avatar_session :223 ; AvatarSessionView :455
#   AVATAR_SESSIONS_KEY = "avatar_sessions"
# handlers/agent.py   AgentTalk :100 ; LITE mouth: _speak_text_to_avatar (~:2038),
#   _maybe_start_avatar_speaker (~:2374/:2544), avatar_speaker.feed (~:2565)
# liveavatar/speaker.py  AvatarTurnSpeaker :56  (assume_connected=True :95)
# liveavatar/voice_provider.py  AvatarVoiceProvider :74 ; _resample_pcm_int16 :39 (44100→24000)
#   app['avatar_voice_provider'] set at manager.py:1525
# env: LIVEAVATAR_API_KEY, LIVEAVATAR_AVATAR_ID, LIVEAVATAR_SANDBOX=false (prod avatar)
```

### Does NOT Exist
- ~~a passing real e2e test today~~ — all current avatar tests use MagicMock/AsyncMock
- ~~sandbox support for the production avatar `5761a14c`~~ — it is production-only (needs `LIVEAVATAR_SANDBOX=false`)

---

## Implementation Notes
- Gate the test so CI without `LIVEAVATAR_API_KEY` skips it cleanly.
- Reference memory: sandbox sessions cap duration at ~60s; the prod avatar 400s
  under `LIVEAVATAR_SANDBOX=true`.
- This task is the final gate — run after all deletions + feature tasks merge.

---

## Acceptance Criteria
- [ ] One real integration test exercises start → chat turn (mouth runs) → stop, green with credentials present, skipped without.
- [ ] Any real defect surfaced is fixed (bugfix only, no redesign).
- [ ] Required env documented in the test module docstring.

---

## Agent Instructions
Standard SDD flow.

## Completion Note
*(Agent fills this in when done)*
