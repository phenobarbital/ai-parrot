---
type: Wiki Overview
title: 'Feature Specification: JiraSpecialist Webhook Transition Detection'
id: doc:sdd-specs-jiraspecialist-webhooks-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The Jira webhook infrastructure (`JiraWebhookHook` at `POST /api/v1/hooks/jira`)
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.core.hooks.base
  rel: mentions
- concept: mod:parrot.core.hooks.models
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: JiraSpecialist Webhook Transition Detection

**Feature ID**: FEAT-258
**Date**: 2026-06-24
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.next
**Proposal**: `sdd/proposals/jiraspecialist-webhooks.proposal.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The Jira webhook infrastructure (`JiraWebhookHook` at `POST /api/v1/hooks/jira`)
already receives and classifies Jira issue events, but the event classifier
(`_classify_event`) only recognises three specific status transitions: `closed`,
`ready_for_test`, and the catch-all `updated`. The `JiraSpecialist.handle_hook_event()`
router only acts on three event types (`jira.created`, `jira.assigned`,
`jira.ready_for_test`) — all other status changes are logged and silently discarded.

This means the system cannot react when a ticket moves to "In Progress", "Code Review",
"QA", "Done", or any custom workflow status. The GitHub Reviewer Agent demonstrates the
pattern: webhooks arrive, the agent filters and dispatches to handler methods. The same
approach should extend to Jira status transitions so the agent can trigger notifications,
invoke other agents, or kick off workflows when tickets change state.

### Goals

- Detect **all** Jira status transitions via the existing webhook endpoint, emitting a
  `jira.transitioned` event with `from_status` and `to_status` in the payload.
- Provide a **configurable transition-to-action registry** on `JiraSpecialist` so
  deployments can map `(from_status, to_status)` patterns to handler actions without
  code changes.
- Ship **built-in action handlers** for common use cases: channel notification,
  agent triggering, and structured logging.
- Follow the **GitHubReviewer pattern** for event filtering and dispatch.

### Non-Goals (explicitly out of scope)

- Changing existing `jira.created` / `jira.assigned` / `jira.ready_for_test` handlers
  — they continue to work exactly as today.
- Jira-side webhook subscription management — webhook registration in Jira remains
  manual (same as GitHub webhooks when no admin PAT is configured).
- Two-way sync — this feature covers Jira→Agent direction only. Agent→Jira actions
  (transitions, comments) already work via `JiraToolkit`.
- Changes to `BaseHook`, `HookManager`, or `AutonomousOrchestrator` — the existing
  hook infrastructure is sufficient.

---

## 2. Architectural Design

### Overview

The design adds a new event type (`jira.transitioned`) to the existing Jira webhook
pipeline and a configurable action registry to `JiraSpecialist`. The approach mirrors
`GitHubReviewer`: the hook emits all transition events, and the agent decides what to
act on via a registry of `TransitionAction` entries.

```
Jira Cloud
  │ POST /api/v1/hooks/jira  (existing endpoint)
  ▼
JiraWebhookHook._handle_post()
  │ _classify_event() → "transitioned" (NEW) for status changes
  │ Payload now includes from_status + to_status
  ▼
HookEvent(event_type="jira.transitioned", payload={..., from_status, to_status})
  │
  ▼
JiraSpecialist.handle_hook_event()
  │ NEW: jira.transitioned branch
  │ Iterates transition_actions registry
  │ Matches (from_status, to_status) against each TransitionAction
  ▼
Matched action handler(s) execute:
  ├─ notify_channel  → Telegram message to configured channel
  ├─ trigger_agent   → ExecutionRequest to invoke another agent
  └─ log_transition  → Structured log entry (always runs)
```

**Classification priority** (preserved from current code): assignee changes take
precedence over status changes. If a single webhook event contains both an assignee
change and a status change, only the assignee event fires (existing behaviour). The
`transitioned` classification applies only to status-field changes without an
accompanying assignee change.

**Backward compatibility for `closed` / `ready_for_test`**: these two statuses keep
their current specific classification. They do NOT also emit `jira.transitioned` — this
avoids double-firing and keeps existing handlers untouched. All **other** status changes
that currently fall through to `"updated"` will now classify as `"transitioned"`.

### Component Diagram

```
┌─────────────────────────────────────────────────────┐
│  JiraWebhookHook (core/hooks/jira_webhook.py)       │
│                                                     │
│  _classify_event()                                  │
│    ├─ assignee change  → "assigned" / "unassigned"  │
│    ├─ status: closed   → "closed"                   │
│    ├─ status: ready_for_test → "ready_for_test"     │
│    ├─ status: other    → "transitioned"  ◄── NEW    │
│    └─ no status change → "updated"                  │
│                                                     │
│  _handle_post()                                     │
│    └─ extracts from_status / to_status  ◄── NEW     │
│                                                     │
│  _extract_status_change()               ◄── NEW     │
│    └─ helper: reads changelog items                 │
└─────────────────────────────────────────────────────┘
           │
           ▼ HookEvent
┌─────────────────────────────────────────────────────┐
│  JiraSpecialist (bots/jira_specialist.py)           │
│                                                     │
│  handle_hook_event()                                │
│    ├─ jira.created       → handle_jira_ticket_created│
│    ├─ jira.assigned      → handle_jira_assignment   │
│    ├─ jira.ready_for_test→ handle_ready_for_test    │
│    └─ jira.transitioned  → _dispatch_transition ◄NEW│
│                                                     │
│  _dispatch_transition()                  ◄── NEW    │
│    └─ matches payload against transition_actions    │
│    └─ invokes matched handler(s)                    │
│                                                     │
│  Built-in handlers:                      ◄── NEW    │
│    ├─ _action_notify_channel()                      │
│    ├─ _action_trigger_agent()                       │
│    └─ _action_log_transition()                      │
└─────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────┐
│  models.py (core/hooks/models.py)                   │
│                                                     │
│  TransitionAction (Pydantic model)       ◄── NEW    │
│  JiraWebhookConfig.transition_actions    ◄── NEW    │
└─────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `JiraWebhookHook` | modifies | Enhanced `_classify_event` + payload enrichment |
| `JiraSpecialist` | modifies | New `jira.transitioned` branch in `handle_hook_event` + transition action dispatch |
| `JiraWebhookConfig` | modifies | New `transition_actions` field |
| `HookEvent` | uses (unchanged) | Carries the new event type through existing pipeline |
| `HookManager` | uses (unchanged) | Routes events as-is — event-type agnostic |
| `AutonomousOrchestrator` | uses (unchanged) | Dispatches to agent — event-type agnostic |

### Data Models

```python
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class TransitionActionType(str, Enum):
    """Supported action types for transition handlers."""
    NOTIFY_CHANNEL = "notify_channel"
    TRIGGER_AGENT = "trigger_agent"
    CALL_HANDLER = "call_handler"
    LOG = "log"


class TransitionAction(BaseModel):
    """A single transition-to-action mapping.

    Matches when the ticket's from_status and to_status match the
    configured patterns. Use "*" as a wildcard for either field.
    """
    from_status: str = Field(
        default="*",
        description="Source status to match (case-insensitive), or '*' for any",
    )
    to_status: str = Field(
        ...,
        description="Target status to match (case-insensitive), or '*' for any",
    )
    action_type: TransitionActionType
    action_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific configuration",
    )
    project_key: Optional[str] = Field(
        default=None,
        description="Restrict to a specific Jira project (None = all)",
    )
    enabled: bool = True

    @model_validator(mode="after")
    def validate_not_both_wildcards(self):
        if self.from_status == "*" and self.to_status == "*":
            raise ValueError(
                "At least one of from_status or to_status must be non-wildcard"
            )
        return self
```

**`action_config` schemas** per action type:

| `action_type` | `action_config` keys | Description |
|---|---|---|
| `notify_channel` | `channel_id: str`, `template: Optional[str]` | Telegram channel to notify; optional message template with `{issue_key}`, `{summary}`, `{from_status}`, `{to_status}`, `{assignee}` placeholders |
| `trigger_agent` | `agent_id: str`, `task_template: Optional[str]` | Agent to invoke via orchestrator; optional task prompt template |
| `call_handler` | `method_name: str` | Name of a method on `JiraSpecialist` to call with `(payload, config)` |
| `log` | `level: str` (default `"info"`) | Structured log level |

### New Public Interfaces

```python
# On JiraSpecialist (bots/jira_specialist.py)

async def _dispatch_transition(
    self,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Match a transition event against the action registry and execute matches."""
    ...

async def _action_notify_channel(
    self,
    payload: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Send a formatted Telegram notification about a transition."""
    ...

async def _action_trigger_agent(
    self,
    payload: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Invoke another agent via the orchestrator with transition context."""
    ...

def _action_log_transition(
    self,
    payload: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Emit a structured log entry for the transition."""
    ...
```

```python
# On JiraWebhookHook (core/hooks/jira_webhook.py)

@staticmethod
def _extract_status_change(
    payload: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str]]:
    """Extract (from_status, to_status) from a Jira changelog payload.

    Returns (None, None) if no status change is found.
    """
    ...
```

---

## 3. Module Breakdown

### Module 1: Transition Event Classification & Payload Enrichment
- **Path**: `packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py`
- **Responsibility**: Enhance `_classify_event` to return `"transitioned"` for
  non-closed, non-ready_for_test status changes. Add `_extract_status_change`
  helper. Enrich `_handle_post` payload with `from_status` and `to_status`.
- **Depends on**: nothing

### Module 2: TransitionAction Model & Config
- **Path**: `packages/ai-parrot/src/parrot/core/hooks/models.py`
- **Responsibility**: Define `TransitionActionType` enum, `TransitionAction`
  Pydantic model, and add `transition_actions: List[TransitionAction]` to
  `JiraWebhookConfig`.
- **Depends on**: nothing

### Module 3: Transition Dispatch & Built-in Action Handlers
- **Path**: `packages/ai-parrot/src/parrot/bots/jira_specialist.py`
- **Responsibility**: Add `jira.transitioned` routing in `handle_hook_event`,
  implement `_dispatch_transition` matcher, and built-in action handlers
  (`_action_notify_channel`, `_action_trigger_agent`, `_action_log_transition`).
  Load transition actions from config during `__init__` or `post_configure`.
- **Depends on**: Module 1, Module 2

### Module 4: Tests
- **Path**: `packages/ai-parrot/tests/core/hooks/test_jira_webhook_classify.py` (extend),
  `packages/ai-parrot/tests/test_jira_transition_dispatch.py` (new)
- **Responsibility**: Test the new classification, payload enrichment, action matching,
  and built-in handlers.
- **Depends on**: Module 1, Module 2, Module 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_status_in_progress_is_transitioned` | M1 | Status change to "In Progress" classifies as `"transitioned"` |
| `test_status_code_review_is_transitioned` | M1 | Status change to "Code Review" classifies as `"transitioned"` |
| `test_status_done_is_transitioned` | M1 | Status change to "Done" classifies as `"transitioned"` |
| `test_status_closed_still_classified_as_closed` | M1 | Backward compat: "Closed" still returns `"closed"` |
| `test_status_ready_for_test_still_classified` | M1 | Backward compat: "Ready For Test" still returns `"ready_for_test"` |
| `test_assignee_change_takes_precedence_over_status` | M1 | When both assignee and status change, assignee wins |
| `test_extract_status_change_returns_from_to` | M1 | Extracts `fromString`/`toString` from changelog |
| `test_extract_status_change_returns_none_when_no_status` | M1 | Returns `(None, None)` for non-status changes |
| `test_payload_includes_from_status_to_status` | M1 | `_handle_post` puts both fields in event payload |
| `test_transition_action_both_wildcards_rejected` | M2 | `TransitionAction(from_status="*", to_status="*")` raises `ValidationError` |
| `test_transition_action_single_wildcard_ok` | M2 | `TransitionAction(from_status="*", to_status="Done")` validates |
| `test_dispatch_matches_exact` | M3 | Action with exact `(from, to)` match fires |
| `test_dispatch_matches_wildcard_from` | M3 | Action with `from_status="*"` matches any source |
| `test_dispatch_matches_wildcard_to` | M3 | Action with `to_status="*"` matches any target |
| `test_dispatch_skips_disabled_action` | M3 | Action with `enabled=False` is skipped |
| `test_dispatch_filters_by_project_key` | M3 | Action with `project_key="NAV"` only fires for NAV tickets |
| `test_action_notify_channel` | M3 | Sends Telegram message with correct formatting |
| `test_action_log_transition` | M3 | Emits structured log at configured level |
| `test_handle_hook_event_routes_transitioned` | M3 | `jira.transitioned` event reaches `_dispatch_transition` |
| `test_existing_events_still_routed` | M3 | `jira.created`/`assigned`/`ready_for_test` unchanged |

### Integration Tests

| Test | Description |
|---|---|
| `test_webhook_to_transition_dispatch_e2e` | Full flow: POST webhook → classify → dispatch → action handler |
| `test_transition_with_no_matching_actions` | Transition event with empty registry logs and returns |

### Test Data / Fixtures

```python
@pytest.fixture
def jira_status_change_payload():
    """Jira webhook payload for a status change: Open → In Progress."""
    return {
        "webhookEvent": "jira:issue_updated",
        "issue": {
            "key": "NAV-1234",
            "id": "12345",
            "fields": {
                "summary": "Fix login timeout",
                "description": "Users report timeout on login",
                "status": {"name": "In Progress"},
                "priority": {"name": "High"},
                "project": {"key": "NAV"},
                "reporter": {
                    "accountId": "r1",
                    "emailAddress": "reporter@example.com",
                    "displayName": "Reporter",
                },
                "assignee": {
                    "accountId": "a1",
                    "emailAddress": "dev@example.com",
                    "displayName": "Developer",
                },
            },
        },
        "changelog": {
            "items": [
                {
                    "field": "status",
                    "fieldtype": "jira",
                    "from": "10000",
                    "fromString": "Open",
                    "to": "10001",
                    "toString": "In Progress",
                }
            ]
        },
        "user": {"displayName": "Developer", "name": "dev"},
        "timestamp": 1719216000000,
    }


@pytest.fixture
def sample_transition_actions():
    """A list of TransitionAction entries for testing dispatch."""
    return [
        TransitionAction(
            from_status="*",
            to_status="In Progress",
            action_type=TransitionActionType.NOTIFY_CHANNEL,
            action_config={
                "channel_id": "-1001234567890",
                "template": "🚀 {issue_key}: {assignee} started work on *{summary}*",
            },
        ),
        TransitionAction(
            from_status="Code Review",
            to_status="Done",
            action_type=TransitionActionType.TRIGGER_AGENT,
            action_config={
                "agent_id": "deploy_bot",
                "task_template": "Ticket {issue_key} is done. Check if deploy is needed.",
            },
        ),
        TransitionAction(
            from_status="*",
            to_status="Blocked",
            action_type=TransitionActionType.LOG,
            action_config={"level": "warning"},
        ),
    ]
```

---

## 5. Acceptance Criteria

- [ ] `_classify_event` returns `"transitioned"` for all status changes except
      `closed` and `ready_for_test` (which keep their existing classifications).
- [ ] `_classify_event` maintains existing priority: assignee changes win over
      status changes when both are present in the same changelog.
- [ ] Event payload includes `from_status` and `to_status` string fields when
      the event involves a status change.
- [ ] `TransitionAction` model validates that at least one of `from_status` /
      `to_status` is non-wildcard.
- [ ] `JiraWebhookConfig` accepts an optional `transition_actions` list.
- [ ] `handle_hook_event` routes `jira.transitioned` events to `_dispatch_transition`.
- [ ] `_dispatch_transition` matches actions case-insensitively on
      `(from_status, to_status)` with wildcard (`*`) support.
- [ ] `_dispatch_transition` filters by `project_key` when set on the action.
- [ ] `_dispatch_transition` skips actions with `enabled=False`.
- [ ] `_action_notify_channel` sends a formatted Telegram message via `self._wrapper.bot`.
- [ ] `_action_trigger_agent` logs the trigger intent (actual orchestrator integration
      deferred to a follow-up if the agent doesn't have orchestrator access).
- [ ] `_action_log_transition` emits a structured log entry at the configured level.
- [ ] Existing `jira.created`, `jira.assigned`, `jira.ready_for_test` handlers
      work exactly as before (no regressions).
- [ ] All new unit tests pass: `pytest tests/core/hooks/test_jira_webhook_classify.py tests/test_jira_transition_dispatch.py -v`
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Verified: packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py:1-9
from parrot.core.hooks.base import BaseHook
from parrot.core.hooks.models import HookType, JiraWebhookConfig

# Verified: packages/ai-parrot/src/parrot/core/hooks/models.py:1-6
from pydantic import BaseModel, Field, model_validator
from enum import Enum

# Verified: packages/ai-parrot/src/parrot/bots/jira_specialist.py:50
from parrot.core.hooks.models import HookEvent

# Verified: packages/ai-parrot/src/parrot/bots/jira_specialist.py:34
from parrot.bots import Agent
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py
class JiraWebhookHook(BaseHook):  # line 12
    hook_type = HookType.JIRA_WEBHOOK  # line 20

    def __init__(self, config: JiraWebhookConfig, **kwargs) -> None:  # line 22
    async def start(self) -> None:  # line 33
    async def stop(self) -> None:  # line 38
    def setup_routes(self, app: Any) -> None:  # line 41
    async def _handle_post(self, request: web.Request) -> web.Response:  # line 49
    def _verify_signature(self, request: web.Request, body: bytes) -> bool:  # line 111

    @staticmethod
    def _classify_event(payload: Dict[str, Any]) -> Optional[str]:  # line 122
        # Returns: "created" | "assigned" | "unassigned" | "deleted" |
        #          "closed" | "ready_for_test" | "updated" | None
        # Priority: assignee changes checked BEFORE status changes (line 136-139)

    @staticmethod
    def _extract_assignee_change(
        payload: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Optional[str]]], Optional[Dict[str, Optional[str]]]]:  # line 151
```

```python
# packages/ai-parrot/src/parrot/core/hooks/models.py
class HookType(str, Enum):  # line 9
    JIRA_WEBHOOK = "jira_webhook"  # line 14

class HookEvent(BaseModel):  # line 31
    hook_id: str  # line 33
    hook_type: HookType  # line 34
    event_type: str  # line 35
    payload: Dict[str, Any] = Field(default_factory=dict)  # line 36
    metadata: Dict[str, Any] = Field(default_factory=dict)  # line 37
    timestamp: datetime = Field(default_factory=datetime.now)  # line 38
    target_type: Optional[str] = None  # line 41
    target_id: Optional[str] = None  # line 42
    task: Optional[str] = None  # line 43

class JiraWebhookConfig(BaseModel):  # line 110
    name: str = "jira_webhook"  # line 112
    enabled: bool = True  # line 113
    url: str = "/api/v1/hooks/jira"  # line 114
    secret_token: Optional[str] = None  # line 115
    target_type: str = "agent"  # line 116
    target_id: str = ""  # line 117
    metadata: Dict[str, Any] = Field(default_factory=dict)  # line 118
```

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(Agent):  # line 157
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW  # line 191

    def __init__(self, **kwargs):  # line 207
        # self._wrapper = None  # line 232 — TelegramAgentWrapper reference
        # self.jira_toolkit: Optional[JiraToolkit] = None  # line 234

    async def handle_hook_event(self, event: HookEvent) -> Optional[Dict[str, Any]]:  # line 1096
        # Routes: jira.created (line 1110), jira.assigned (line 1112),
        #         jira.ready_for_test (line 1114). Others: log + return None (line 1116).

    async def handle_jira_assignment(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # line 1163
    async def handle_jira_ticket_created(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # line 1293
    async def handle_ready_for_test(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # line 1405
```

```python
# packages/ai-parrot/src/parrot/core/hooks/base.py
class BaseHook(ABC):  # line 96
    def _make_event(self, event_type: str, payload: dict | None = None,
                    *, task: str | None = None) -> HookEvent:  # line 149
    async def on_event(self, event_data: HookEvent) -> None:  # line 135
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_classify_event` (modified) | `_handle_post` | return value | `jira_webhook.py:59` |
| `_extract_status_change` (new) | `_handle_post` | called inline | will be called near `jira_webhook.py:94` |
| `TransitionAction` (new) | `JiraWebhookConfig` | `transition_actions` field | `models.py:118` (append after) |
| `_dispatch_transition` (new) | `handle_hook_event` | new branch | `jira_specialist.py:1116` (replace ignore) |
| `_action_notify_channel` | `self._wrapper.bot.send_message` | Telegram API | `jira_specialist.py:1478` (existing pattern) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.core.hooks.models.TransitionAction`~~ — does not exist yet (this feature creates it)
- ~~`parrot.core.hooks.models.TransitionActionType`~~ — does not exist yet
- ~~`JiraWebhookConfig.transition_actions`~~ — field does not exist yet
- ~~`JiraSpecialist._dispatch_transition()`~~ — does not exist yet
- ~~`JiraSpecialist._action_notify_channel()`~~ — does not exist yet
- ~~`JiraSpecialist._action_trigger_agent()`~~ — does not exist yet
- ~~`JiraSpecialist._action_log_transition()`~~ — does not exist yet
- ~~`JiraWebhookHook._extract_status_change()`~~ — does not exist yet
- ~~`HookEvent.from_status`~~ — there is no dedicated field; `from_status` lives in `HookEvent.payload` dict

…(truncated)…
