# TASK-1384: HITL-web suspend/resume integration tests

**Feature**: FEAT-204 — HITL over Stateless Web Request/Response (AgentTalk HTTP)
**Spec**: `sdd/specs/hitl_web.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1379, TASK-1380, TASK-1381, TASK-1382, TASK-1383
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 + §4 Integration Tests. End-to-end coverage of the full
stateless suspend→paused→resume→success cycle and its failure modes, exercising
all prior tasks together against an in-memory Redis.

---

## Scope

Implement the integration tests in spec §4 against a stub agent whose LLM calls
`ask_human` once (SUSPEND), wired with `SuspendingWebHumanTool`, a real
`HumanInteractionManager` on `fakeredis.aioredis`, and the `AgentTalk` handler:

- `test_e2e_suspend_returns_paused` — first POST returns HTTP 200 `paused` with
  rehydrated `options`/`form_schema` and a `turn_id`; assert both
  `hitl:suspended:{id}` and `hitl:interaction:{id}` exist in Redis.
- `test_e2e_resume_to_success` — second POST with `hitl_response{turn_id,value}`
  → `hitl:result` persisted, agent resumed, reply `status="success"`.
- `test_resume_expired` — neither interaction nor result present → fast
  "expired" reply.
- `test_resume_already_answered` — `hitl:result` present (tombstone) → "already
  answered", tool-loop NOT re-run.
- `test_resume_cross_session_rejected` — respondent not in `target_humans` → 403.
- `test_structured_types_survive` — `single_choice`/`form` options/schema arrive
  intact in the paused envelope after rehydration.

**NOT in scope**: implementation changes (all in TASK-1379..1383). If a test
reveals a bug, file it against the owning task; only add the test here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/test_hitl_web_suspend_resume.py` | CREATE | Integration tests per spec §4 |
| `packages/ai-parrot-server/tests/conftest.py` | MODIFY | Add `fake_redis` / `fake_manager` / `stub_agent` fixtures if not present |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.human import HumanInteractionManager, WaitStrategy        # human/__init__.py (+TASK-1379)
from parrot.human.models import HumanResponse, InteractionType, HumanInteraction  # human/models.py
from parrot.handlers.web_hitl import SuspendingWebHumanTool           # TASK-1381
from parrot.handlers.agent import PausedEnvelope                      # TASK-1382
from parrot.human.suspended_store import SuspendedExecutionStore      # TASK-1380 (verify path)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/human/manager.py
class HumanInteractionManager:
    def __init__(self, channels=None, redis_url=None, reject_detector=None, on_event=None): ...  # 73-94
    async def request_human_input_async(self, interaction, channel="telegram") -> str: ...       # 471
    async def receive_response(self, response) -> None: ...                                      # 580
    async def get_result(self, ...): ...                                                         # 511
    async def is_valid_respondent(self, interaction_id, respondent) -> bool: ...                 # 222
# Redis keys to assert: hitl:interaction:{id}, hitl:result:{id}, hitl:suspended:{id}

# Existing FEAT-146 test reference (similar harness):
#   packages/ai-parrot-server/tests/ — grep for test_e2e_human_tool_over_web (web-hitl spec §4)
```

### Does NOT Exist
- ~~a live Redis requirement~~ — use `fakeredis.aioredis`; do NOT require a real
  server. Add `fakeredis` to test deps if missing (`uv pip install fakeredis`).
- ~~a real LLM call~~ — stub the agent/client so the tool-loop deterministically
  calls `ask_human` once, then (after resume) returns a final message.
- ~~a `/resume` endpoint~~ — resume goes through the chat route with a
  `hitl_response` body tag.

---

## Implementation Notes

### Pattern to Follow
Look for the FEAT-146 `test_e2e_human_tool_over_web` harness (web-hitl spec §4
references it) and adapt it: swap the blocking `WebHumanTool` for
`SuspendingWebHumanTool`, drop the WebSocket channel, and assert on the returned
`paused` envelope + Redis keys instead of a resolved future.

### Key Constraints
- Async tests (`pytest-asyncio`); isolate Redis per test (flush between).
- Assert TTLs exist (not exact seconds) on `hitl:suspended:{id}`.
- Deterministic stub agent — no network, no real model.

### References in Codebase
- web-hitl spec §4 harness; `parrot/human/manager.py`; `SuspendingWebHumanTool`.

---

## Acceptance Criteria

- [ ] All six integration tests from spec §4 implemented and passing.
- [ ] Tests use `fakeredis.aioredis` — no real Redis/LLM dependency.
- [ ] `pytest packages/ai-parrot-server/tests/test_hitl_web_suspend_resume.py -v` is green.
- [ ] The FEAT-146 WebSocket tests still pass (no regression):
      `pytest packages/ai-parrot-server/tests -k hitl -v`.
- [ ] No lint errors: `ruff check packages/ai-parrot-server/tests/test_hitl_web_suspend_resume.py`

---

## Test Specification

See Scope — the six named tests are the deliverable. Skeleton:

```python
# packages/ai-parrot-server/tests/test_hitl_web_suspend_resume.py
import pytest

async def test_e2e_suspend_returns_paused(client, fake_redis):
    resp = await client.post("/api/v1/agents/chat/stub", json={"query":"approve?","session_id":"s"})
    body = await resp.json()
    assert resp.status == 200 and body["status"] == "paused"
    assert body["options"]  # structured type survived
    assert await fake_redis.get(f"hitl:suspended:{body['interaction_id']}") is not None
    assert await fake_redis.get(f"hitl:interaction:{body['interaction_id']}") is not None

async def test_e2e_resume_to_success(client, fake_redis):
    ...  # POST hitl_response{turn_id, value} -> status == "success"
```

---

## Agent Instructions

Standard flow. Verify TASK-1379..1383 are in `sdd/tasks/completed/` first.
Implement, run, move this file to `sdd/tasks/completed/`, update
`sdd/tasks/index/hitl_web.json` to `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
