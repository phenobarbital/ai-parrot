---
type: Wiki Overview
title: 'TASK-1603: Decouple + rename the Redis structured-output transport'
id: doc:sdd-tasks-completed-task-1603-decouple-rename-redis-transport-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The server is multi-process (gunicorn `(2×CPUs)+1`) and
---

# TASK-1603: Decouple + rename the Redis structured-output transport

**Feature**: FEAT-249 — LiveAvatar + Voice Consolidation
**Spec**: `sdd/specs/liveavatar-voice-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1601
**Assigned-to**: unassigned

---

## Context

The server is multi-process (gunicorn `(2×CPUs)+1`) and
`UserSocketManager.broadcast_to_channel` (`user.py:357`) is in-process only.
Structured outputs from `/agents/chat` may be produced in a different worker
than the one holding the `/ws/userinfo` connection, so the Redis pub/sub bridge
(`output_transport.py` + `liveavatar_output.py`) is **mandatory and KEPT**
(Q-redis-transport resolved). This task removes its Phase-C coupling and makes
it a transport-neutral, always-relevant component. (Spec §1, §3.4, §7.)

---

## Scope

- Rename the env gate `ENABLE_LIVEAVATAR_VOICE` → `ENABLE_STRUCTURED_OUTPUT_TRANSPORT`
  in `conf.py` and `manager.py` (`_setup_liveavatar_voice` → e.g.
  `_setup_structured_output_transport`). No backward-compat alias.
- Remove any `AvatarJobMetadata` / Phase-C worker references from
  `output_transport.py` and `handlers/liveavatar_output.py`.
- In `_FanOutSink` (`liveavatar_output.py`): keep the `UserSocketManager` arm,
  drop the `StreamHandler` arm (its avatar channel plumbing was removed in
  TASK-1601).
- Ensure `StructuredOutputMessage` import points to `liveavatar/models.py`
  (post TASK-1599).
- Update/keep `test_liveavatar_output.py` / `test_unified_voice_integration.py`
  (FakeRedis) for the renamed/decoupled component.

**NOT in scope**: the Mode B publisher that *uses* this transport (TASK-1607);
deleting the transport (it is kept).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | rename gate (`:95`) |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | rename `_setup_liveavatar_voice` (`:1573`), gate check (`:1580`), import (`:78`), call site (`:1645`) |
| `.../liveavatar/output_transport.py` | MODIFY | drop Phase-C coupling; import SOM from `..models` |
| `packages/ai-parrot-server/src/parrot/handlers/liveavatar_output.py` | MODIFY | drop StreamHandler arm of `_FanOutSink`; rename references |
| `tests/.../test_liveavatar_output.py` | MODIFY | reflect rename/decouple |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures / Anchors (verified)
```python
# conf.py:95  ENABLE_LIVEAVATAR_VOICE = config.getboolean(..., fallback=False)
# manager.py:78 import ENABLE_LIVEAVATAR_VOICE ; :1573 _setup_liveavatar_voice ; :1580 gate ; :1645 call
# liveavatar/output_transport.py  RedisBroadcastForwarder (:40), run_output_subscriber (:100),
#   DEFAULT_OUTPUT_CHANNEL = "liveavatar:structured-outputs" (:35)
# handlers/liveavatar_output.py  configure_liveavatar_output_subscriber + _FanOutSink (:53)
# handlers/user.py:357  UserSocketManager.broadcast_to_channel(channel, message, exclude_ws)  (in-process)
# StructuredOutputMessage now in liveavatar/models.py (TASK-1599)
```

### Does NOT Exist (after this task)
- ~~`ENABLE_LIVEAVATAR_VOICE`~~ — renamed to `ENABLE_STRUCTURED_OUTPUT_TRANSPORT`
- ~~`AvatarJobMetadata` reference in the transport~~ — removed
- ~~`UserSocketManager` Redis-backed channel fanout~~ — broadcast is in-process; cross-process delivery is THIS transport's job

---

## Implementation Notes
- Keep `DEFAULT_OUTPUT_CHANNEL` Redis channel name stable (or rename to
  `parrot:structured-outputs` — pick one and update both publisher/subscriber).
- The subscriber must run as an `on_startup` task **in every server process**.
- Mode B/A/C all rely on this; do not gate it behind any avatar flag.

---

## Acceptance Criteria
- [ ] `ENABLE_STRUCTURED_OUTPUT_TRANSPORT` gates the subscriber; old name gone.
- [ ] No `AvatarJobMetadata` / Phase-C references in transport or subscriber.
- [ ] `_FanOutSink` fans only to `UserSocketManager`.
- [ ] `pytest tests/.../test_liveavatar_output.py -q` (FakeRedis) green.
- [ ] A two-process simulation test shows a message published on worker-A reaches a WS subscriber on worker-B (FakeRedis acceptable).

---

## Agent Instructions
Standard SDD flow.

## Completion Note
Implemented 2026-06-19. Renamed `ENABLE_LIVEAVATAR_VOICE` → `ENABLE_STRUCTURED_OUTPUT_TRANSPORT`
in conf.py. Renamed `_setup_liveavatar_voice` → `_setup_structured_output_transport` in manager.py.
Dropped `StreamHandler` arm from `_FanOutSink` in liveavatar_output.py (only `UserSocketManager`
arm remains). Updated docstrings to remove Phase C language. Updated test_liveavatar_output.py to
use new names and remove stream_handler-only fan-out test. 8 liveavatar_output tests pass.
test_cross_process_simulation passes with worktree PYTHONPATH; fails with installed pkg (environment
limitation, resolved on merge).
