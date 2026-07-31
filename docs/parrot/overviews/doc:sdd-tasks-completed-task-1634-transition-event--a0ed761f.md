---
type: Wiki Overview
title: 'TASK-1634: Transition Event Classification & Payload Enrichment'
id: doc:sdd-tasks-completed-task-1634-transition-event-classification-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task modifies the Jira webhook hook to detect all status transitions
---

# TASK-1634: Transition Event Classification & Payload Enrichment

**Feature**: FEAT-258 — JiraSpecialist Webhook Transition Detection
**Spec**: `sdd/specs/jiraspecialist-webhooks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task modifies the Jira webhook hook to detect all status transitions
(not just `closed` and `ready_for_test`) and enrich the event payload with
`from_status` and `to_status`. Implements Spec §2 "Component Diagram" and
§3 "Module 1".

Currently, `_classify_event` returns `"updated"` for all status changes
except `closed` and `ready_for_test`. After this task, those other changes
return `"transitioned"` instead, and the payload includes the transition
details.

---

## Scope

- Add `_extract_status_change(payload)` static method to `JiraWebhookHook`
  that reads the changelog items and returns `(from_status, to_status)` or
  `(None, None)`.
- Modify `_classify_event` to return `"transitioned"` instead of `"updated"`
  when a status change is detected that is NOT `closed` or `ready_for_test`.
- Modify `_handle_post` to enrich `event_payload` with `from_status` and
  `to_status` when the event involves a status field change.
- Extend existing tests in `test_jira_webhook_classify.py`.

**NOT in scope**: `TransitionAction` model (TASK-1633), dispatch logic
(TASK-1635), or dispatch tests (TASK-1636).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py` | MODIFY | Add `_extract_status_change`, modify `_classify_event` and `_handle_post` |
| `packages/ai-parrot/tests/core/hooks/test_jira_webhook_classify.py` | MODIFY | Add tests for `"transitioned"` classification and status extraction |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already imported in jira_webhook.py (verified: jira_webhook.py:1-9)
import hashlib
import hmac
from typing import Any, Dict, Optional, Tuple
from aiohttp import web
from .base import BaseHook
from .models import HookType, JiraWebhookConfig
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py

class JiraWebhookHook(BaseHook):  # line 12
    hook_type = HookType.JIRA_WEBHOOK  # line 20

    async def _handle_post(self, request: web.Request) -> web.Response:  # line 49
        # Builds event_payload dict (lines 67-92)
        # Currently enriches for "assigned" (lines 94-97)
        # Calls _make_event then on_event (lines 99-104)

    @staticmethod
    def _classify_event(payload: Dict[str, Any]) -> Optional[str]:  # line 122
        # Current logic (lines 122-149):
        #   jira:issue_created → "created" or "assigned"
        #   jira:issue_deleted → "deleted"
        #   jira:issue_updated:
        #     assignee change → "assigned" / "unassigned" (lines 136-139)
        #     status "closed" → "closed" (line 144)
        #     status "ready for test*" → "ready_for_test" (lines 145-146)
        #     status other → "updated" (line 147)  ← THIS IS WHAT WE CHANGE
        #     no status → "updated" (line 148)

    @staticmethod
    def _extract_assignee_change(
        payload: Dict[str, Any],
    ) -> Tuple[Optional[Dict], Optional[Dict]]:  # line 151
```

### Does NOT Exist

- ~~`JiraWebhookHook._extract_status_change()`~~ — does not exist yet (this task creates it)
- ~~`event_payload["from_status"]`~~ — not in current payload (this task adds it)
- ~~`event_payload["to_status"]`~~ — not in current payload (this task adds it)

---

## Implementation Notes

### Pattern to Follow

**`_extract_status_change`** — follow the same pattern as `_extract_assignee_change`
(line 151): a `@staticmethod` that reads `changelog.items` and returns a tuple.

```python
@staticmethod
def _extract_status_change(
    payload: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str]]:
    """Extract (from_status, to_status) from a Jira changelog payload.

    Returns (None, None) if no status change is found.
    """
    items = (payload.get("changelog") or {}).get("items") or []
    for item in items:
        if item.get("field") == "status":
            return (
                (item.get("fromString") or "").strip() or None,
                (item.get("toString") or "").strip() or None,
            )
    return None, None
```

**`_classify_event` change** — replace `return "updated"` at line 147:

```python
# Current (line 147):
                    return "updated"
# Change to:
                    return "transitioned"
```

This is the ONLY change in `_classify_event`. The `"closed"` and `"ready_for_test"`
branches above remain unchanged.

**`_handle_post` enrichment** — after line 92 (end of `event_payload` dict), add
extraction for all status-change events (not just `transitioned`):

```python
            # Enrich with status transition details when applicable
            from_status, to_status = self._extract_status_change(payload)
            if from_status is not None or to_status is not None:
                event_payload["from_status"] = from_status
                event_payload["to_status"] = to_status
```

### Key Constraints

- **Backward compat**: `"closed"` and `"ready_for_test"` MUST still classify
  as their existing values. Only the `return "updated"` at line 147 changes.
- **Assignee priority**: the existing check for assignee changes (lines 136-139)
  runs BEFORE the status check. This order must not change.
- **`from_status`/`to_status` are added for ALL status changes** (including
  `closed` and `ready_for_test`) — they're payload enrichment, not classification.
  This gives downstream consumers transition context even for specific events.

### References in Codebase

- `jira_webhook.py:151-188` — `_extract_assignee_change` pattern to follow
- `tests/core/hooks/test_jira_webhook_classify.py` — existing test structure

---

## Acceptance Criteria

- [ ] `_classify_event` returns `"transitioned"` for status changes to "In Progress", "Code Review", "Done", etc.
- [ ] `_classify_event` still returns `"closed"` for status change to "Closed"
- [ ] `_classify_event` still returns `"ready_for_test"` for "Ready For Test" / "Ready for Testing"
- [ ] Assignee changes still take precedence over status changes
- [ ] `_extract_status_change` returns `(from_status, to_status)` from changelog
- [ ] `_extract_status_change` returns `(None, None)` when no status change present
- [ ] `_handle_post` includes `from_status` and `to_status` in event payload for status changes
- [ ] All existing tests in `test_jira_webhook_classify.py` still pass (no regressions)
- [ ] New tests for `"transitioned"` classification pass
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py`

---

## Test Specification

```python
# Extend tests/core/hooks/test_jira_webhook_classify.py

class TestClassifyEventTransitioned:
    """New tests for the 'transitioned' classification."""

    @pytest.mark.parametrize("to_status", [
        "In Progress", "Code Review", "QA", "Done",
        "Blocked", "In Review", "Deployed",
    ])
    def test_status_change_is_transitioned(self, to_status):
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {"key": "NAV-1"},
            "changelog": {
                "items": [
                    {"field": "status", "fromString": "Open", "toString": to_status}
                ]
            },
        }
        assert JiraWebhookHook._classify_event(payload) == "transitioned"

    def test_closed_still_classified_as_closed(self):
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {"key": "NAV-1"},
            "changelog": {
                "items": [{"field": "status", "toString": "Closed"}]
            },
        }
        assert JiraWebhookHook._classify_event(payload) == "closed"

    def test_ready_for_test_still_classified(self):
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {"key": "NAV-1"},
            "changelog": {
                "items": [{"field": "status", "toString": "Ready For Test"}]
            },
        }
        assert JiraWebhookHook._classify_event(payload) == "ready_for_test"


class TestExtractStatusChange:
    def test_extracts_from_to(self):
        payload = {
            "changelog": {
                "items": [
                    {"field": "status", "fromString": "Open", "toString": "In Progress"}
                ]
            }
        }
        from_s, to_s = JiraWebhookHook._extract_status_change(payload)
        assert from_s == "Open"
        assert to_s == "In Progress"

    def test_returns_none_when_no_status(self):
        payload = {
            "changelog": {
                "items": [{"field": "priority", "toString": "High"}]
            }
        }
        assert JiraWebhookHook._extract_status_change(payload) == (None, None)

    def test_returns_none_when_no_changelog(self):
        assert JiraWebhookHook._extract_status_change({}) == (None, None)

    def test_strips_whitespace(self):
        payload = {
            "changelog": {
                "items": [
                    {"field": "status", "fromString": "  Open  ", "toString": "  Done  "}
                ]
            }
        }
        from_s, to_s = JiraWebhookHook._extract_status_change(payload)
        assert from_s == "Open"
        assert to_s == "Done"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jiraspecialist-webhooks.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `_classify_event` at `jira_webhook.py:122-149`
4. **Update status** in per-spec index → `"in-progress"`
5. **Implement** the classification change, extraction helper, and payload enrichment
6. **Run tests**: `pytest tests/core/hooks/test_jira_webhook_classify.py -v`
7. **Verify** all acceptance criteria
8. **Move this file** to `sdd/tasks/completed/`
9. **Update per-spec index** → `"done"`

---

## Completion Note

Implemented by sdd-worker on 2026-06-24.

Modified `packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py`:
- `_classify_event`: changed `return "updated"` at the status-change branch to
  `return "transitioned"` for all non-closed, non-ready_for_test status changes.
  Backward compat preserved: `"closed"` and `"ready_for_test"` unchanged.
- `_extract_status_change`: new `@staticmethod` returning `(from_status, to_status)`
  tuple from changelog, following the `_extract_assignee_change` pattern.
- `_handle_post`: enriches event_payload with `from_status` / `to_status` for
  all status-change events.

Extended `tests/core/hooks/test_jira_webhook_classify.py` with
`TestClassifyEventTransitioned` (4 tests, 7 parametrize variants) and
`TestExtractStatusChange` (5 tests). All 29 tests pass.
