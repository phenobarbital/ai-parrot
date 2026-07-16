---
type: Wiki Overview
title: 'TASK-1635: Transition Dispatch & Built-in Action Handlers'
id: doc:sdd-tasks-completed-task-1635-transition-dispatch-handlers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task wires the new `jira.transitioned` event type (from TASK-1634)
relates_to:
- concept: mod:parrot.core.hooks.models
  rel: mentions
---

# TASK-1635: Transition Dispatch & Built-in Action Handlers

**Feature**: FEAT-258 — JiraSpecialist Webhook Transition Detection
**Spec**: `sdd/specs/jiraspecialist-webhooks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1633, TASK-1634
**Assigned-to**: unassigned

---

## Context

This task wires the new `jira.transitioned` event type (from TASK-1634)
into `JiraSpecialist.handle_hook_event()` and implements the configurable
dispatch logic that matches transition actions (from TASK-1633) against
incoming events. It also ships three built-in action handlers.

Implements Spec §2 "New Public Interfaces" and §3 "Module 3".

---

## Scope

- Add `jira.transitioned` routing branch in `handle_hook_event()`.
- Implement `_dispatch_transition(payload)` — iterates `self._transition_actions`,
  matches `(from_status, to_status)` case-insensitively with wildcard support,
  and invokes matched handlers.
- Accept `transition_actions` in `JiraSpecialist.__init__()` (kwarg) and/or
  load from `JiraWebhookConfig` during `post_configure()`.
- Implement three built-in action handlers:
  - `_action_notify_channel(payload, config)` — Telegram notification.
  - `_action_trigger_agent(payload, config)` — logs trigger intent.
  - `_action_log_transition(payload, config)` — structured log entry.

**NOT in scope**: Classification changes (TASK-1634), model definitions
(TASK-1633), or dedicated test file (TASK-1636).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | Add transition routing, dispatch, and action handlers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already imported in jira_specialist.py (verified lines 26-50)
from typing import Any, Dict, List, Optional
from parrot.core.hooks.models import HookEvent  # line 50

# NEW import needed (after TASK-1633 completes):
from parrot.core.hooks.models import TransitionAction, TransitionActionType
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py

class JiraSpecialist(Agent):  # line 157
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW  # line 191

    def __init__(self, **kwargs):  # line 207
        # self._wrapper = None  (line 232)
        # self.jira_toolkit: Optional[JiraToolkit] = None  (line 234)
        # self._init_kwargs: Dict[str, Any] = dict(kwargs)  (line 222)

    async def handle_hook_event(
        self, event: HookEvent
    ) -> Optional[Dict[str, Any]]:  # line 1096
        # Current routing:
        #   jira.created → handle_jira_ticket_created  (line 1110)
        #   jira.assigned → handle_jira_assignment  (line 1112)
        #   jira.ready_for_test → handle_ready_for_test  (line 1114)
        #   else: log + return None  (lines 1116-1121)

    async def handle_ready_for_test(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Any]:  # line 1405
        # Reference pattern for _action_notify_channel:
        #   Reads issue_key, summary, priority, assignee from payload
        #   Formats Telegram message
        #   Sends via self._wrapper.bot.send_message(chat_id=..., text=..., parse_mode="Markdown")
        #   Returns {"status": "ok"|"skipped"|"error", "issue_key": ...}
```

```python
# packages/ai-parrot/src/parrot/core/hooks/models.py (after TASK-1633)
class TransitionActionType(str, Enum):  # NEW
    NOTIFY_CHANNEL = "notify_channel"
    TRIGGER_AGENT = "trigger_agent"
    CALL_HANDLER = "call_handler"
    LOG = "log"

class TransitionAction(BaseModel):  # NEW
    from_status: str = Field(default="*")
    to_status: str
    action_type: TransitionActionType
    action_config: Dict[str, Any] = Field(default_factory=dict)
    project_key: Optional[str] = None
    enabled: bool = True
```

### Does NOT Exist

- ~~`JiraSpecialist._dispatch_transition()`~~ — does not exist yet (this task creates it)
- ~~`JiraSpecialist._action_notify_channel()`~~ — does not exist yet
- ~~`JiraSpecialist._action_trigger_agent()`~~ — does not exist yet
- ~~`JiraSpecialist._action_log_transition()`~~ — does not exist yet
- ~~`JiraSpecialist._transition_actions`~~ — instance attribute does not exist yet
- ~~`JiraSpecialist.orchestrator`~~ — JiraSpecialist does NOT have a reference to AutonomousOrchestrator; `_action_trigger_agent` CANNOT call the orchestrator directly

---

## Implementation Notes

### Pattern to Follow

**1. Store transition actions in `__init__`:**

```python
def __init__(self, **kwargs):
    transition_actions = kwargs.pop("transition_actions", None) or []
    # ... existing __init__ code ...
    self._transition_actions: List[TransitionAction] = transition_actions
```

**2. Add routing in `handle_hook_event` (after line 1114):**

```python
        if event.event_type == "jira.transitioned":
            return await self._dispatch_transition(event.payload)
        self.logger.info(...)  # existing fallback
```

**3. Implement `_dispatch_transition`:**

```python
async def _dispatch_transition(
    self, payload: Dict[str, Any]
) -> Dict[str, Any]:
    from_status = (payload.get("from_status") or "").strip().lower()
    to_status = (payload.get("to_status") or "").strip().lower()
    project_key = (payload.get("project_key") or "").strip().upper()
    issue_key = payload.get("issue_key", "?")

    self._action_log_transition(payload, {})

    results = []
    for action in self._transition_actions:
        if not action.enabled:
            continue
        if action.project_key and action.project_key.upper() != project_key:
            continue
        from_match = action.from_status == "*" or action.from_status.lower() == from_status
        to_match = action.to_status == "*" or action.to_status.lower() == to_status
        if from_match and to_match:
            handler = self._ACTION_HANDLERS.get(action.action_type)
            if handler:
                result = await handler(self, payload, action.action_config)
                results.append(result)

    return {
        "status": "ok",
        "issue_key": issue_key,
        "from_status": from_status,
        "to_status": to_status,
        "actions_matched": len(results),
        "results": results,
    }
```

**4. Action handler dispatch map** (class-level):

```python
_ACTION_HANDLERS = {
    TransitionActionType.NOTIFY_CHANNEL: _action_notify_channel,
    TransitionActionType.TRIGGER_AGENT: _action_trigger_agent,
    TransitionActionType.CALL_HANDLER: _action_call_handler,
    TransitionActionType.LOG: lambda self, p, c: self._action_log_transition(p, c),
}
```

Note: `_ACTION_HANDLERS` must be defined after all handler methods. Alternatively,
use `getattr(self, f"_action_{action.action_type.value}")` for dynamic dispatch.

**5. `_action_notify_channel`** — follow `handle_ready_for_test` pattern:

```python
async def _action_notify_channel(
    self, payload: Dict[str, Any], config: Dict[str, Any]
) -> Dict[str, Any]:
    channel_id = config.get("channel_id")
    if not channel_id:
        return {"status": "skipped", "reason": "no channel_id in action_config"}
    if not self._wrapper or not getattr(self._wrapper, "bot", None):
        return {"status": "skipped", "reason": "no Telegram wrapper attached"}

    template = config.get("template") or (
        "🔄 *{issue_key}* transitioned: {from_status} → {to_status}\n"
        "*{summary}*\nAssigned to: {assignee}"
    )
    text = template.format(
        issue_key=payload.get("issue_key", "?"),
        summary=payload.get("summary", ""),
        from_status=payload.get("from_status", "?"),
        to_status=payload.get("to_status", "?"),
        assignee=(payload.get("assignee") or {}).get("display_name", "—"),
    )
    await self._wrapper.bot.send_message(
        chat_id=channel_id, text=text, parse_mode="Markdown"
    )
    return {"status": "ok", "channel_id": channel_id}
```

**6. `_action_trigger_agent`** — log-only for now:

```python
async def _action_trigger_agent(
    self, payload: Dict[str, Any], config: Dict[str, Any]
) -> Dict[str, Any]:
    agent_id = config.get("agent_id")
    task_template = config.get("task_template", "")
    task = task_template.format(
        issue_key=payload.get("issue_key", "?"),
        summary=payload.get("summary", ""),
        from_status=payload.get("from_status", "?"),
        to_status=payload.get("to_status", "?"),
    ) if task_template else f"Transition: {payload.get('issue_key')}"
    self.logger.info(
        "Transition trigger_agent: agent_id=%s task=%s (orchestrator integration pending)",
        agent_id, task,
    )
    return {"status": "triggered", "agent_id": agent_id, "task": task}
```

**7. `_action_log_transition`** — always runs:

```python
def _action_log_transition(
    self, payload: Dict[str, Any], config: Dict[str, Any]
) -> Dict[str, Any]:
    level = config.get("level", "info")
    log_fn = getattr(self.logger, level, self.logger.info)
    log_fn(
        "Jira transition: %s %s → %s (%s)",
        payload.get("issue_key"),
        payload.get("from_status"),
        payload.get("to_status"),
        payload.get("summary", ""),
    )
    return {"status": "logged", "level": level}
```

### Key Constraints

- `_action_notify_channel` MUST handle missing `self._wrapper` gracefully
  (return `status: skipped`), same pattern as `handle_ready_for_test` lines 1443-1453.
- `_action_trigger_agent` CANNOT call orchestrator directly (JiraSpecialist has
  no orchestrator reference). Log the intent for now.
- `_action_call_handler` resolves `method_name` via `getattr(self, method_name)`.
  Validate the method exists before calling.
- String matching on `from_status`/`to_status` MUST be case-insensitive.

### References in Codebase

- `jira_specialist.py:1405-1504` — `handle_ready_for_test` notification pattern
- `jira_specialist.py:1096-1121` — current `handle_hook_event` routing
- `github_reviewer.py:755-773` — reference for event filtering pattern

---

## Acceptance Criteria

- [ ] `handle_hook_event` routes `jira.transitioned` to `_dispatch_transition`
- [ ] `_dispatch_transition` matches actions case-insensitively on `(from_status, to_status)`
- [ ] `_dispatch_transition` supports `"*"` wildcard matching
- [ ] `_dispatch_transition` filters by `project_key` when set
- [ ] `_dispatch_transition` skips disabled actions
- [ ] `_dispatch_transition` always calls `_action_log_transition`
- [ ] `_action_notify_channel` sends Telegram message via `self._wrapper.bot`
- [ ] `_action_notify_channel` returns `status: skipped` when no wrapper
- [ ] `_action_trigger_agent` logs the trigger intent
- [ ] `_action_log_transition` emits structured log at configured level
- [ ] Existing `jira.created`/`assigned`/`ready_for_test` routing unchanged
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/jira_specialist.py`

---

## Test Specification

```python
# Tests are created in TASK-1636. Inline quick-check:
# pytest tests/test_jira_transition_dispatch.py -v
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jiraspecialist-webhooks.spec.md` for full context
2. **Check dependencies** — TASK-1633 and TASK-1634 must be completed
3. **Verify the Codebase Contract** — confirm signatures, especially:
   - `handle_hook_event` at `jira_specialist.py:1096`
   - `handle_ready_for_test` at `jira_specialist.py:1405` (notification pattern)
   - `TransitionAction` model exists (from TASK-1633)
4. **Update status** in per-spec index → `"in-progress"`
5. **Implement** routing, dispatch, and action handlers
6. **Run smoke test**: existing tests should still pass
7. **Verify** all acceptance criteria
8. **Move this file** to `sdd/tasks/completed/`
9. **Update per-spec index** → `"done"`

---

## Completion Note

Implemented by sdd-worker on 2026-06-24.

Modified `packages/ai-parrot/src/parrot/bots/jira_specialist.py`:
- Added import: `TransitionAction, TransitionActionType` from models.
- `__init__`: pops `transition_actions` kwarg and stores as
  `self._transition_actions: List[TransitionAction]`.
- `handle_hook_event`: added `jira.transitioned` branch that calls
  `_dispatch_transition(event.payload)`.
- `_dispatch_transition`: iterates `_transition_actions`, matches
  `(from_status, to_status)` case-insensitively with wildcard support,
  filters by `project_key`, skips disabled actions, always calls
  `_action_log_transition` first.
- `_invoke_transition_action`: dispatch router for action types.
- `_action_notify_channel`: sends Telegram message, handles missing
  wrapper with `status: skipped`.
- `_action_trigger_agent`: logs trigger intent (orchestrator pending).
- `_action_log_transition`: structured log at configurable level.
- `_action_call_handler`: resolves method by name via getattr.
3 pre-existing F401 lint warnings (math, pandas, schedule_weekly_report)
already present before this task — not fixed (out of scope).
