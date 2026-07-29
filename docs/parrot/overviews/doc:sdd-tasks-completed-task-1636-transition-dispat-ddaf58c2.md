---
type: Wiki Overview
title: 'TASK-1636: Transition Dispatch Tests'
id: doc:sdd-tasks-completed-task-1636-transition-dispatch-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task adds comprehensive tests for the transition dispatch logic and
relates_to:
- concept: mod:parrot.bots.jira_specialist
  rel: mentions
- concept: mod:parrot.core.hooks.jira_webhook
  rel: mentions
- concept: mod:parrot.core.hooks.models
  rel: mentions
- concept: mod:parrot.utils
  rel: mentions
- concept: mod:parrot.utils.parsers
  rel: mentions
---

# TASK-1636: Transition Dispatch Tests

**Feature**: FEAT-258 — JiraSpecialist Webhook Transition Detection
**Spec**: `sdd/specs/jiraspecialist-webhooks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1633, TASK-1634, TASK-1635
**Assigned-to**: unassigned

---

## Context

This task adds comprehensive tests for the transition dispatch logic and
built-in action handlers implemented in TASK-1635. Also includes an
end-to-end integration test covering the full flow from webhook POST
to action handler execution.

Implements Spec §4 "Test Specification".

---

## Scope

- Create `tests/test_jira_transition_dispatch.py` with tests for:
  - `_dispatch_transition` matching logic (exact, wildcard, project filter, disabled)
  - `_action_notify_channel` (success, no wrapper, no channel_id)
  - `_action_trigger_agent` (logs intent)
  - `_action_log_transition` (structured log)
  - `handle_hook_event` routing for `jira.transitioned`
  - End-to-end: webhook payload → classification → dispatch → action

**NOT in scope**: Model validation tests (those are in TASK-1633).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_jira_transition_dispatch.py` | CREATE | Dispatch and handler tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# For test file
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.core.hooks.models import (
    HookEvent, HookType, TransitionAction, TransitionActionType,
)
from parrot.core.hooks.jira_webhook import JiraWebhookHook
# JiraSpecialist cannot be imported directly in unit tests (heavy deps).
# Test the dispatch method by constructing a minimal mock or using the
# actual class with mocked dependencies.
```

### Existing Signatures to Use

```python
# After TASK-1635:
# JiraSpecialist._dispatch_transition(payload: Dict[str, Any]) -> Dict[str, Any]
# JiraSpecialist._action_notify_channel(payload, config) -> Dict[str, Any]
# JiraSpecialist._action_trigger_agent(payload, config) -> Dict[str, Any]
# JiraSpecialist._action_log_transition(payload, config) -> Dict[str, Any]
# JiraSpecialist._transition_actions: List[TransitionAction]

# HookEvent (verified: models.py:31-43)
class HookEvent(BaseModel):
    hook_id: str
    hook_type: HookType
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    # ...
```

### Does NOT Exist

- ~~`parrot.bots.jira_specialist.JiraSpecialist`~~ as a direct import in test context — this class has heavy dependencies (Redis, Telegram, etc.). Use mocking or partial instantiation.
- ~~`JiraSpecialist.orchestrator`~~ — the agent has no orchestrator reference

---

## Implementation Notes

### Pattern to Follow

Follow the existing test style from `test_jira_webhook_classify.py`: plain
`TestXxx` classes, descriptive method names, `@pytest.mark.parametrize` for
variations.

Since `JiraSpecialist` has heavy dependencies, the recommended approach is:
1. Test `_dispatch_transition` and action handlers by calling them directly
   on a mock-constructed instance (mock out `__init__` or use `object.__new__`).
2. Alternatively, use `@patch` to mock the dependencies.

```python
def _make_specialist(transition_actions=None):
    """Create a minimal JiraSpecialist-like object for testing dispatch."""
    from parrot.bots.jira_specialist import JiraSpecialist
    obj = object.__new__(JiraSpecialist)
    obj._transition_actions = transition_actions or []
    obj._wrapper = None
    obj.logger = MagicMock()
    return obj
```

### Key Constraints

- Tests must not require Redis, Telegram, or Jira connections.
- Use `MagicMock` / `AsyncMock` for external dependencies.
- Match the fixture style from the spec's §4 Test Specification.

### References in Codebase

- `tests/core/hooks/test_jira_webhook_classify.py` — test style reference
- `tests/test_jira_ticket_created.py` — another JiraSpecialist test pattern
- `tests/test_jira_assignment.py` — mocking pattern for JiraSpecialist

---

## Acceptance Criteria

- [ ] Test file `tests/test_jira_transition_dispatch.py` created
- [ ] Tests cover: exact match, wildcard from, wildcard to, project filter, disabled skip
- [ ] Tests cover: `_action_notify_channel` success + skip cases
- [ ] Tests cover: `_action_trigger_agent` logging
- [ ] Tests cover: `_action_log_transition` at configured level
- [ ] Tests cover: `handle_hook_event` routes `jira.transitioned` correctly
- [ ] Tests cover: existing events (`jira.created`, `jira.assigned`, `jira.ready_for_test`) still routed
- [ ] All tests pass: `pytest tests/test_jira_transition_dispatch.py -v`
- [ ] No linting errors: `ruff check tests/test_jira_transition_dispatch.py`

---

## Test Specification

```python
# tests/test_jira_transition_dispatch.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.core.hooks.models import (
    HookEvent, HookType, TransitionAction, TransitionActionType,
)


def _make_specialist(transition_actions=None):
    """Minimal JiraSpecialist for testing dispatch logic."""
    from parrot.bots.jira_specialist import JiraSpecialist
    obj = object.__new__(JiraSpecialist)
    obj._transition_actions = transition_actions or []
    obj._wrapper = None
    obj.logger = MagicMock()
    return obj


@pytest.fixture
def status_change_payload():
    return {
        "issue_key": "NAV-1234",
        "summary": "Fix login timeout",
        "from_status": "Open",
        "to_status": "In Progress",
        "project_key": "NAV",
        "assignee": {"display_name": "Developer"},
    }


class TestDispatchTransition:
    @pytest.mark.asyncio
    async def test_exact_match_fires(self, status_change_payload):
        actions = [
            TransitionAction(
                from_status="Open",
                to_status="In Progress",
                action_type=TransitionActionType.LOG,
            )
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["status"] == "ok"
        assert result["actions_matched"] >= 1

    @pytest.mark.asyncio
    async def test_wildcard_from_matches(self, status_change_payload):
        actions = [
            TransitionAction(
                from_status="*",
                to_status="In Progress",
                action_type=TransitionActionType.LOG,
            )
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["actions_matched"] >= 1

    @pytest.mark.asyncio
    async def test_case_insensitive_match(self, status_change_payload):
        actions = [
            TransitionAction(
                from_status="open",
                to_status="in progress",
                action_type=TransitionActionType.LOG,
            )
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["actions_matched"] >= 1

    @pytest.mark.asyncio
    async def test_disabled_action_skipped(self, status_change_payload):
        actions = [
            TransitionAction(
                from_status="*",
                to_status="In Progress",
                action_type=TransitionActionType.LOG,
                enabled=False,
            )
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["actions_matched"] == 0

    @pytest.mark.asyncio
    async def test_project_key_filter(self, status_change_payload):
        actions = [
            TransitionAction(
                from_status="*",
                to_status="In Progress",
                action_type=TransitionActionType.LOG,
                project_key="OTHER",
            )
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["actions_matched"] == 0

    @pytest.mark.asyncio
    async def test_no_actions_configured(self, status_change_payload):
        specialist = _make_specialist([])
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["status"] == "ok"
        assert result["actions_matched"] == 0


class TestActionNotifyChannel:
    @pytest.mark.asyncio
    async def test_sends_telegram_message(self, status_change_payload):
        specialist = _make_specialist()
        mock_bot = AsyncMock()
        specialist._wrapper = MagicMock(bot=mock_bot)
        result = await specialist._action_notify_channel(
            status_change_payload,
            {"channel_id": "-100123"},
        )
        assert result["status"] == "ok"
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_no_wrapper(self, status_change_payload):
        specialist = _make_specialist()
        specialist._wrapper = None
        result = await specialist._action_notify_channel(
            status_change_payload,
            {"channel_id": "-100123"},
        )
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_skips_when_no_channel_id(self, status_change_payload):
        specialist = _make_specialist()
        result = await specialist._action_notify_channel(
            status_change_payload, {},
        )
        assert result["status"] == "skipped"


class TestActionTriggerAgent:
    @pytest.mark.asyncio
    async def test_logs_trigger_intent(self, status_change_payload):
        specialist = _make_specialist()
        result = await specialist._action_trigger_agent(
            status_change_payload,
            {"agent_id": "deploy_bot", "task_template": "Deploy {issue_key}"},
        )
        assert result["status"] == "triggered"
        assert result["agent_id"] == "deploy_bot"
        specialist.logger.info.assert_called()


class TestActionLogTransition:
    def test_logs_at_info_by_default(self, status_change_payload):
        specialist = _make_specialist()
        result = specialist._action_log_transition(status_change_payload, {})
        assert result["status"] == "logged"
        assert result["level"] == "info"

    def test_logs_at_custom_level(self, status_change_payload):
        specialist = _make_specialist()
        result = specialist._action_log_transition(
            status_change_payload, {"level": "warning"}
        )
        assert result["level"] == "warning"
        specialist.logger.warning.assert_called()


class TestHandleHookEventRouting:
    @pytest.mark.asyncio
    async def test_transitioned_event_dispatched(self, status_change_payload):
        specialist = _make_specialist()
        event = HookEvent(
            hook_id="test",
            hook_type=HookType.JIRA_WEBHOOK,
            event_type="jira.transitioned",
            payload=status_change_payload,
        )
        result = await specialist.handle_hook_event(event)
        assert result is not None
        assert result["status"] == "ok"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jiraspecialist-webhooks.spec.md`
2. **Check dependencies** — TASK-1633, TASK-1634, TASK-1635 must be completed
3. **Verify the Codebase Contract** — confirm dispatch methods exist on JiraSpecialist
4. **Update status** in per-spec index → `"in-progress"`
5. **Create** the test file with all test cases
6. **Run tests**: `pytest tests/test_jira_transition_dispatch.py -v`
7. **Verify** all tests pass
8. **Move this file** to `sdd/tasks/completed/`
9. **Update per-spec index** → `"done"`

---

## Completion Note

Implemented by sdd-worker on 2026-06-24.

Created `packages/ai-parrot/tests/test_jira_transition_dispatch.py` with 31
tests covering: dispatch matching (exact, wildcard from, wildcard to,
case-insensitive, disabled skip, project key filter), `_action_notify_channel`
(success, skip when no wrapper, skip when no channel_id, skip when wrapper
has no bot attribute), `_action_trigger_agent` (logs intent, formats template,
default task), `_action_log_transition` (info default, custom level warning/debug),
`handle_hook_event` routing (transitioned dispatched, unknown returns None,
existing events unchanged), and integration tests (no actions configured,
multiple actions all fire, notify+log combined).

The test file pre-stubs `parrot.utils.types` and `parrot.utils.parsers.toml`
Cython extensions via sys.modules injection to allow collection in a source-tree
test environment without compiled binaries. All 31 tests pass; lint clean.
