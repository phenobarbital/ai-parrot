---
type: Wiki Overview
title: 'TASK-1679: Real dispatch in `_action_trigger_agent` + tests'
id: doc:sdd-tasks-completed-task-1679-real-dispatch-in-action-trigger-agent-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Core of FEAT-265 (spec §2 Overview, §3 Module 2 + Module 4). Replaces the
relates_to:
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.bots._types
  rel: mentions
- concept: mod:parrot.bots.jira_specialist
  rel: mentions
- concept: mod:parrot.core.hooks.models
  rel: mentions
---

# TASK-1679: Real dispatch in `_action_trigger_agent` + tests

**Feature**: FEAT-265 — JiraSpecialist trigger_agent → Orchestrator Dispatch
**Spec**: `sdd/specs/jiraspecialist-trigger-agent-orchestrator.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1678
**Assigned-to**: unassigned

---

## Context

Core of FEAT-265 (spec §2 Overview, §3 Module 2 + Module 4). Replaces the
log-only stub `_action_trigger_agent` with a real dispatch through the
injected `_agent_dispatcher` added in TASK-1678. Keeps backward compatibility
(log-only degrade when no dispatcher) and mirrors the error-handling shape of
`_action_notify_channel`.

---

## Scope

- Rewrite `JiraSpecialist._action_trigger_agent` (jira_specialist.py:1282-1330):
  - Keep the existing `agent_id` resolution and `task_template` rendering
    (same placeholders, same `KeyError` → raw-template fallback).
  - **dispatch branch**: if `self._agent_dispatcher` is set, `await` it once
    with `(agent_id, task)` (pass `user_id`/`session_id` from payload when
    available); return `{"status": "dispatched", "agent_id", "task",
    "result": <short summary>}`.
  - **skip branch**: if no dispatcher, log intent (INFO/WARNING) and return
    `{"status": "skipped", "reason": "no dispatcher wired", "agent_id", "task"}`.
  - **error branch**: wrap the dispatcher call in try/except; on failure log
    (`exc_info=True`) and return `{"status": "error", "agent_id", "error": str(exc)}`.
    A downstream failure must NOT break the transition loop or the webhook 200.
- Update the existing test `test_logs_trigger_intent` (now asserts `"skipped"`
  when no dispatcher, not the removed synthetic `"triggered"`).
- Add the new unit tests + the end-to-end integration test (see Test Spec).

**NOT in scope**: the protocol/slot (TASK-1678); the app.py wiring doc
(TASK-1680); changing the other three action handlers; result fan-back to Jira.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | Rewrite `_action_trigger_agent` body |
| `packages/ai-parrot/tests/test_jira_transition_dispatch.py` | MODIFY | Update `test_logs_trigger_intent`; add dispatch/skip/error/template tests + integration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.jira_specialist import JiraSpecialist
# verified: packages/ai-parrot/src/parrot/bots/jira_specialist.py:154
from parrot.core.hooks.models import TransitionAction, TransitionActionType
# verified: packages/ai-parrot/src/parrot/core/hooks/models.py:119 (TransitionAction)
from parrot.bots._types import AgentDispatcher  # created in TASK-1678
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(Agent):
    self._agent_dispatcher: Optional[AgentDispatcher]   # added in TASK-1678
    async def _invoke_transition_action(
        self, action: TransitionAction, payload: dict) -> dict   # line 1194
        # dispatches TRIGGER_AGENT → _action_trigger_agent       # line 1210-1211
    async def _action_notify_channel(self, payload, config)      # line 1221
        # ^ MIRROR this try/except → {"status": "error", ...} shape
    async def _action_trigger_agent(self, payload, config)       # line 1282 (REWRITE)
        # current keys read from config: "agent_id", "task_template"
        # template placeholders: {issue_key} {summary} {from_status}
        #                        {to_status} {assignee}
        # assignee_name = (payload.get("assignee") or {}).get("display_name", "—")
```

### Does NOT Exist
- ~~`status="triggered"`~~ — REMOVED by this task; replaced by
  `dispatched`/`skipped`/`error` (spec §8 resolved). Do not keep the old value.
- ~~extra `action_config` keys beyond `agent_id` + `task_template`~~ — only
  these two are read; do not invent others.
- ~~`asyncio.create_task` fire-and-forget~~ — v1 is `await` inline (spec §8);
  do NOT background the call in this task.
- ~~core importing `parrot.autonomous.*`~~ — MUST NOT be added.

---

## Implementation Notes

### Pattern to Follow
```python
# mirror the error handling of _action_notify_channel (line 1261-1280):
try:
    result = await self._agent_dispatcher(agent_id, task,
                                          user_id=..., session_id=...)
    return {"status": "dispatched", "agent_id": agent_id,
            "task": task, "result": str(result)[:500]}
except Exception as exc:  # noqa: BLE001 — must not break the transition loop
    self.logger.error("trigger_agent dispatch failed for %s: %s",
                      agent_id, exc, exc_info=True)
    return {"status": "error", "agent_id": agent_id, "error": str(exc)}
```

### Key Constraints
- async throughout; always `await` the dispatcher.
- Preserve the exact template rendering + `KeyError` fallback already present.
- `self.logger` at dispatch (INFO) and skip (WARNING).
- No new external dependency.

### References in Codebase
- `jira_specialist.py:1221-1280` — `_action_notify_channel` (error pattern)
- `jira_specialist.py:1194-1219` — `_invoke_transition_action` (caller)

---

## Acceptance Criteria

- [ ] With a dispatcher wired, `_action_trigger_agent` awaits it exactly once
      with resolved `agent_id` + rendered `task`; returns `status="dispatched"`.
- [ ] With no dispatcher, returns `status="skipped"` and does NOT raise.
- [ ] Dispatcher exception → `status="error"`; loop continues.
- [ ] Template rendering unchanged (placeholders + KeyError fallback).
- [ ] `test_logs_trigger_intent` updated (no `"triggered"` assertion remains).
- [ ] No `parrot.autonomous` import in core (grep-clean).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/test_jira_transition_dispatch.py -v`

---

## Test Specification

```python
class _RecordingDispatcher:
    def __init__(self): self.calls = []
    async def __call__(self, agent_name, task, *, user_id=None, session_id=None):
        self.calls.append((agent_name, task)); return {"ok": True}


async def test_dispatches_to_wired_dispatcher(specialist, status_change_payload):
    disp = _RecordingDispatcher()
    specialist.set_agent_dispatcher(disp)
    result = await specialist._action_trigger_agent(
        status_change_payload,
        {"agent_id": "deploy_bot", "task_template": "Deploy {issue_key}"},
    )
    assert result["status"] == "dispatched"
    assert len(disp.calls) == 1
    assert disp.calls[0][0] == "deploy_bot"


async def test_skips_when_no_dispatcher(specialist, status_change_payload):
    result = await specialist._action_trigger_agent(
        status_change_payload, {"agent_id": "deploy_bot"})
    assert result["status"] == "skipped"


async def test_dispatcher_error_is_caught(specialist, status_change_payload):
    async def boom(*a, **k): raise RuntimeError("nope")
    specialist.set_agent_dispatcher(boom)
    result = await specialist._action_trigger_agent(
        status_change_payload, {"agent_id": "deploy_bot"})
    assert result["status"] == "error"
    assert "nope" in result["error"]


async def test_transition_triggers_agent_end_to_end(specialist, ...):
    """jira.transitioned w/ TRIGGER_AGENT action → dispatcher invoked once."""
    ...
```

---

## Agent Instructions

1. Confirm TASK-1678 is in `sdd/tasks/completed/` before starting.
2. Verify the Codebase Contract (re-check line numbers — file is large).
3. Update index → `in-progress`.
4. Implement per scope; mirror `_action_notify_channel` error handling.
5. Run the test file; ensure the old `"triggered"` assertion is gone.
6. Move this file to `sdd/tasks/completed/`; update index → `done`.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-01
**Notes**: Rewrote `_action_trigger_agent` to branch on `self._agent_dispatcher`:
dispatch (await once, `status="dispatched"` with truncated `result`), skip
(`status="skipped"`, `WARNING` log, no dispatcher set), and error (caught
`Exception`, `exc_info=True`, `status="error"`) — mirroring
`_action_notify_channel`'s try/except shape. `agent_id` resolution and
`task_template` rendering (incl. `KeyError` → raw-template fallback) are
unchanged. Updated `test_logs_trigger_intent` to assert `"skipped"` (the old
`"triggered"` synthetic status is fully removed — grep-clean). Added
`_RecordingDispatcher` fixture-class plus
`test_dispatches_to_wired_dispatcher`, `test_skips_when_no_dispatcher`,
`test_dispatcher_error_is_caught`, `test_task_template_rendered_before_dispatch`,
`test_no_agent_id_skips`, and the end-to-end
`test_transition_triggers_agent_end_to_end` (drives `handle_hook_event` →
`_dispatch_transition` → `_action_trigger_agent` → dispatcher, asserts one
recorded call). All 46 tests in `test_jira_transition_dispatch.py` pass;
`ruff check` clean; grep-verified no `parrot.autonomous` import in core.
**Deviations from spec**: none
