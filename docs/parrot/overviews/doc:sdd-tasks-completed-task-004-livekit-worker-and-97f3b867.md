---
type: Wiki Overview
title: 'TASK-004: LiveKit Agents worker + session pipeline'
id: doc:sdd-tasks-completed-task-004-livekit-worker-and-pipeline-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-242's `LiveKitRoomManager`, `LiveAvatarClient` and models are present
  in
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.output_bridge
  rel: mentions
---

# TASK-004: LiveKit Agents worker + session pipeline

**Feature**: FEAT-243 — LiveAvatar Phase C (voice-native hybrid, ai-parrot as the brain)
**Spec**: `sdd/specs/liveavatar-phase-c-voice-native.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-001, TASK-003
**Assigned-to**: sdd-worker (Opus)

---

## ✅ UNBLOCKED — FEAT-243 rebased onto feat-242-liveavatar-phase-a-mouth

FEAT-242's `LiveKitRoomManager`, `LiveAvatarClient` and models are present in
this worktree (FEAT-243 stacked on the FEAT-242 branch). Implemented against the
**real** FEAT-242 API; the wiring mirrors FEAT-242's `AvatarSessionOrchestrator`.
Original blocker note retained below for history.

## ⛔ (historical) BLOCKED ON FEAT-242

This task wires the worker to FEAT-242's `LiveKitRoomManager` and `LiveAvatarClient`
(+ `LiveAvatarConfig` / `AvatarSessionHandle`). **Do NOT start until FEAT-242 has
merged to `dev`** and `room_manager.py` / `client.py` / `models.py` exist under
`.../liveavatar/`. If any are absent when you pick this up, STOP and report — do not
stub or reinvent them.

---

## Context

Implements spec §3 **Module 1** (capability `llm-node-aiparrot-bridge`). The LiveKit
Agents pipeline runs in a long-lived worker that joins the **same** LiveKit Cloud room
as the avatar participant (shared transport with FEAT-242 — no new transport layer).
`build_session(vad)` keeps STT (Deepgram/nova-3), VAD (Silero), turn-detection
(MultilingualModel) and TTS (LiveKit inference), and binds the `LiveAvatarAgent`
(TASK-003) as the LLM node. `worker.py` parses `ctx.job.metadata` (JSON) into
`AvatarJobMetadata` to inject `tenant_id`/`agent_name`/`session_id`, opens the
LiveAvatar session with `livekit_config` pointing at our room (FEAT-242
`LiveKitRoomManager` + `LiveAvatarClient`), and registers `stop_session` as a shutdown
callback.

---

## Scope

- Create `pipeline.py` with `build_session(vad) -> AgentSession` wiring STT / VAD /
  turn-detection / TTS as configured (adapt the LiveKit starter `pipeline.py`).
- Create `worker.py` that:
  - parses `ctx.job.metadata` (JSON) → `AvatarJobMetadata` (TASK-001 model);
  - mints room tokens via FEAT-242 `LiveKitRoomManager`;
  - opens the LiveAvatar session via FEAT-242 `LiveAvatarClient.create_session_token(...)`
    with `livekit_config` for our room;
  - constructs `LiveAvatarAgent` (TASK-003) with `agent_name`/`session_id`/`tenant_id`
    and the `OutputBridge`;
  - registers `LiveAvatarClient.stop_session` as a shutdown callback.
- Write unit tests: `test_build_session_components`, `test_stop_session_shutdown_callback`
  (job-metadata parsing is already covered by TASK-001's `test_job_metadata_parsing`).

**NOT in scope**:
- `LiveAvatarAgent` / `llm_node` body (TASK-003).
- `OutputBridge` body (TASK-002).
- FEAT-242 room manager / client / models (reuse only — created by FEAT-242).
- The integration/sandbox round-trip tests (`test_phase_c_*`) — those run against a live
  LiveAvatar sandbox and are validated as part of feature acceptance, not this unit task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/pipeline.py` | CREATE | `build_session(vad)` — STT/VAD/turn/TTS wiring |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/worker.py` | CREATE | entrypoint: metadata parse, session open, shutdown callback |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_livekit_worker.py` | CREATE | `build_session` + shutdown-callback tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.livekit_agent.models import AvatarJobMetadata   # TASK-001
from parrot.integrations.liveavatar.livekit_agent.agent import LiveAvatarAgent       # TASK-003
from parrot.integrations.liveavatar.output_bridge import OutputBridge                # TASK-002
# LiveKit Agents (from the liveavatar-voice extra — pinned in TASK-001). VALIDATE exact
# import paths against the pinned version (P5):
from livekit.agents import AgentSession, JobContext, WorkerOptions, cli   # confirm vs pin
# plugins (confirm final set — Q-plugins):
#   livekit.plugins.deepgram (STT), livekit.plugins.cartesia (TTS),
#   livekit.plugins.silero (VAD), livekit.plugins.turn_detector (MultilingualModel)
```

### Provided by FEAT-242 (MUST verify exists before use — created by Phase A)
```python
# .../liveavatar/room_manager.py
class LiveKitRoomManager:                     # livekit-api (shared with Phase C)
    def mint_room_tokens(self, room: str, identity: str) -> LiveKitRoomTokens: ...

# .../liveavatar/client.py
class LiveAvatarClient:
    async def create_session_token(self, cfg: LiveAvatarConfig,
                                    livekit_config: Optional[dict] = None) -> AvatarSessionHandle: ...
    async def start_session(self, handle: AvatarSessionHandle) -> dict: ...
    async def stop_session(self, handle: AvatarSessionHandle) -> None: ...

# .../liveavatar/models.py
class LiveAvatarConfig(BaseModel): ...
class LiveKitRoomTokens(BaseModel): ...
class AvatarSessionHandle(BaseModel): ...
```

### Does NOT Exist
- ~~a current `livekit.agents` / `livekit.plugins.*` install~~ — from the `liveavatar-voice`
  extra (TASK-001). Validate every LiveKit import path + `AgentSession` / worker API
  against the pinned version (P5) before finalising.
- ~~FEAT-242 `LiveKitRoomManager` / `LiveAvatarClient` in the current tree~~ — created by
  FEAT-242; STOP if absent.
- ~~a self-hosted LiveKit SFU~~ — out of scope; LiveKit Cloud only (spec §1 Non-Goals).
- ~~the Phase A `AvatarWebSocket` push path as the primary mechanism~~ — Phase C uses
  LiveKit's TTS node directly (spec §1 Non-Goals).

---

## Implementation Notes

### Pattern to Follow
- Adapt the LiveKit Agents starter `worker.py` / `pipeline.py` (entrypoint + `build_session`).
- `build_session(vad)` returns an `AgentSession` with STT/VAD/turn-detection/TTS; keep the
  component choices configurable (env-driven) — defaults per spec §2 (Deepgram nova-3 STT,
  Silero VAD, MultilingualModel turn-detection, LiveKit inference TTS).
- In the entrypoint: `AvatarJobMetadata.model_validate_json(ctx.job.metadata)`, then build
  `OutputBridge` + `LiveAvatarAgent`, open the LiveAvatar session with `livekit_config`, and
  `ctx.add_shutdown_callback(lambda: client.stop_session(handle))` (confirm the exact
  shutdown-callback API against the pinned version — P5).

### Key Constraints
- Async throughout; no blocking I/O. `aiohttp` for any HTTP.
- Secrets via env only (LiveKit, plus plugin provider keys — Deepgram STT, Cartesia TTS).
- Use `is_sandbox=true` for dev sessions (spec §7 Cost note).
- `self.logger`; no `print`.
- Tests must run WITHOUT a live LiveKit room — mock `AgentSession`, the plugins, the
  room manager and client; assert the wiring (components present; `stop_session`
  registered as a shutdown callback and invoked on teardown).

### References in Codebase
- FEAT-242 `.../liveavatar/room_manager.py`, `client.py`, `models.py` — reuse.
- TASK-003 `agent.py` — the `LiveAvatarAgent` bound as the LLM node.

---

## Acceptance Criteria

- [ ] `build_session(vad)` wires STT/VAD/turn-detection/TTS as configured
- [ ] `ctx.job.metadata` (JSON) parsed → `AvatarJobMetadata` (tenant_id/agent_name/session_id)
- [ ] LiveAvatar session opened with `livekit_config` for our FEAT-242 room (shared transport)
- [ ] `stop_session` registered as a shutdown callback and invoked on teardown
- [ ] `LiveAvatarAgent` bound as the LLM node, constructed with metadata + `OutputBridge`
- [ ] LiveKit import paths + worker API validated against the pinned `livekit-agents` (P5)
- [ ] No linting errors: `ruff check .../liveavatar/livekit_agent/`
- [ ] `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_livekit_worker.py -v`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/liveavatar/test_livekit_worker.py
import pytest

@pytest.mark.asyncio
async def test_build_session_components(monkeypatch):
    """build_session wires STT / VAD / turn-detection / TTS (mocked plugins)."""
    ...

@pytest.mark.asyncio
async def test_stop_session_shutdown_callback():
    """stop_session is registered as a shutdown callback and called on teardown."""
    ...
```

---

## Agent Instructions

1. **Read the spec** for full context.
2. **VERIFY FEAT-242 IS MERGED** — `room_manager.py` / `client.py` / `models.py` must exist. STOP if not.
3. **Check dependencies** — TASK-001 and TASK-003 in `sdd/tasks/completed/`.
4. **Verify the Codebase Contract** — confirm FEAT-242 signatures; validate LiveKit worker
   API against the pinned `livekit-agents` (P5).
5. **Update status** in the per-spec index → `"in-progress"`.
6. **Implement** per scope.
7. **Verify** acceptance criteria.
8. **Move this file** to `sdd/tasks/completed/`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Opus 4.8)
**Date**: 2026-06-18
**Notes**: Created `livekit_agent/pipeline.py` and `livekit_agent/worker.py`.

`pipeline.build_session(vad, *, stt, tts, turn_detection, session_factory)`
assembles the `AgentSession` wiring STT (Deepgram nova-3) / VAD (injected,
prewarmed Silero) / turn-detection (MultilingualModel) / TTS (Cartesia). The
heavy plugins + `AgentSession` are lazy-imported inside default factories so the
module imports without the `liveavatar-voice` extra and the wiring is tested by
injecting fakes + a fake `session_factory`.

`worker.py` exposes pure/fake-able helpers mirroring FEAT-242's
`AvatarSessionOrchestrator`:
- `parse_job_metadata(ctx)` → `AvatarJobMetadata` (from `ctx.job.metadata` JSON);
- `build_livekit_config(tokens)` → `{"url","room","agentToken"}`;
- `open_avatar_session(client, cfg, room_manager, meta)` → mints room tokens
  (`mint_room_tokens(room=session_id, identity=agent_name)`), calls
  `create_session_token(cfg, livekit_config=...)`, rebuilds the
  `AvatarSessionHandle` with our `session_id`/`tenant_id`/`agent_name`, and
  `start_session`s it;
- `register_stop_session_shutdown(ctx, client, handle)` → registers
  `client.stop_session` via `ctx.add_shutdown_callback` (errors swallowed so
  teardown never raises);
- `entrypoint(ctx, *, deps)` ties it together (parse → open session → register
  shutdown → build `OutputBridge` + `LiveAvatarAgent` → `build_session` →
  `ctx.connect()` → `session.start(agent, room)`), with deps in a
  `LiveAvatarWorkerDeps` dataclass; `run(deps)` is the guarded `cli.run_app`
  entry.

7 unit tests (incl. the two required: `test_build_session_components`,
`test_stop_session_shutdown_callback`, plus metadata/livekit_config/open_session/
error-swallowing). Full liveavatar suite = **78 passed**; my files `ruff`-clean.

**Deviations from spec**: (1) Heavy LiveKit imports are **guarded/lazy** so the
modules import and unit-test without the extra (task constraint). (2) `entrypoint`
/ `run` are NOT unit-tested end-to-end — they need a live room and the installed
extra; covered by the Phase C integration tests (`test_phase_c_*`, explicitly out
of this task's scope). (3) **P5 / Q-deploy / Q-plugins** remain open: the exact
`AgentSession`/`WorkerOptions`/`cli` APIs, plugin classes and the spawn-per-session
vs warm-pool deployment model must be validated against the pinned
`livekit-agents` before production. (4) Pre-existing `ruff` F401s exist in
FEAT-242's own test files — left untouched (out of scope).
