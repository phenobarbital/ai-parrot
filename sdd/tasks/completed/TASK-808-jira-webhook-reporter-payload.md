# TASK-808: Enrich JiraWebhookHook reporter payload to a dict

**Feature**: FEAT-110 — jiraspecialist-webhook-ticket-creation
**Spec**: `sdd/specs/FEAT-110-jiraspecialist-webhook-ticket-creation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec § 3 / Module 1. `JiraWebhookHook._handle_post` currently emits the
reporter as a scalar `displayName` string. The reporter-reassignment
handler (TASK-810) needs email + accountId to compare against
`JIRA_ALLOWED_REPORTERS`. This task enriches the payload to a dict
matching the exact shape already used for `assignee` in the same
function.

---

## Scope

- Replace the scalar `reporter` key in the dict built inside
  `_handle_post` with a dict exposing `email`, `display_name`,
  `account_id`, `name` — mirroring the `assignee` block immediately
  below it.
- Source all four sub-fields from the existing `fields.get("reporter")`
  object that Jira Cloud already includes in the webhook body.
- Strictly additive: no existing key is removed; no new event type is
  classified. The `_classify_event` function is NOT touched.
- The payload shape change applies to **every** Jira event the hook
  emits (`jira.created`, `jira.assigned`, `jira.updated`, `jira.closed`,
  `jira.ready_for_test`, `jira.unassigned`, `jira.deleted`) — not just
  `jira.created`.

**NOT in scope**:
- The `handle_jira_assignment` caller update (belongs to TASK-810,
  bundled with the handler because the caller lives in the same file
  the handler lands in).
- Adding any new config constant.
- Writing the handler logic or any tests (TASK-810 / TASK-811).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py` | MODIFY | In `_handle_post`, replace the one-liner `reporter` string with a dict of four fields. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No new imports required. The file already has:
```python
from aiohttp import web                                    # line 6
from .base import BaseHook                                 # line 8
from .models import HookType, JiraWebhookConfig            # line 9
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py
class JiraWebhookHook(BaseHook):                           # line 12
    hook_type = HookType.JIRA_WEBHOOK                      # line 20
    async def _handle_post(                                # line 49
        self, request: web.Request,
    ) -> web.Response:
        # The current reporter emission at line 76 reads:
        #   "reporter": (fields.get("reporter") or {}).get("displayName"),
        # The assignee emission at lines 77-82 already uses the dict
        # shape we are aligning to:
        #   "assignee": {
        #       "account_id": assignee_field.get("accountId"),
        #       "email":      assignee_field.get("emailAddress"),
        #       "display_name": assignee_field.get("displayName"),
        #       "name":       assignee_field.get("name"),
        #   },
```

### Does NOT Exist
- ~~`jira_webhook.set_reporter_enricher`~~ — not a pattern in this repo.
- ~~`JiraWebhookHook.on_created`~~ — events are dispatched via
  `self.on_event(event)` inherited from `BaseHook`; do not add a per-
  event method.
- ~~`fields.get("reporter").get("email")`~~ — Jira Cloud uses
  `emailAddress` (not `email`) on the raw webhook body. The dict we
  emit exposes `email`, but the source key is `emailAddress`.
- ~~`payload.get("reporter")` returning a dict today~~ — today it returns
  a string; this task is the change.

---

## Implementation Notes

Pattern to follow — exactly mirror the `assignee` block already present
in the same function:

```python
reporter_field = fields.get("reporter") or {}
event_payload: Dict[str, Any] = {
    ...
    "reporter": {
        "account_id": reporter_field.get("accountId"),
        "email": reporter_field.get("emailAddress"),
        "display_name": reporter_field.get("displayName"),
        "name": reporter_field.get("name"),
    },
    ...
}
```

Place the `reporter_field = fields.get("reporter") or {}` line next to
the existing `assignee_field = fields.get("assignee") or {}` (currently
at line 65) so reviewers can see the parallel structure at a glance.

### Key Constraints
- No behaviour change other than the payload dict shape. The HMAC
  signature check, event classification, route registration, and error
  handling are all untouched.
- Do not introduce a Pydantic model for the reporter dict — the
  `event_payload` around it is already a plain `dict[str, Any]`;
  staying consistent is more important than typing it.
- Do not log the reporter payload — it contains a PII email.

---

## Acceptance Criteria

- [ ] `payload["reporter"]` is always a dict with keys `email`,
      `display_name`, `account_id`, `name` (any of which may be `None`).
- [ ] The four keys are sourced from `fields["reporter"]["emailAddress"]`,
      `displayName`, `accountId`, `name` respectively.
- [ ] Every existing event classification still works (no regressions
      in `_classify_event`).
- [ ] `ruff check packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py`
      is clean.
- [ ] The file still type-checks under whatever checker the repo uses
      (import it in a python shell to smoke-test).

---

## Test Specification

Tests for this task live in TASK-811 (`test_webhook_reporter_payload_is_dict`).
You do NOT need to add tests here — but the implementation MUST be
written so that a test mocking a full Jira webhook POST can assert the
dict shape. See spec § 4.

---

## Agent Instructions

1. Read the spec at `sdd/specs/FEAT-110-jiraspecialist-webhook-ticket-creation.spec.md`.
2. Verify lines 49-103 of `jira_webhook.py` still match the contract above.
3. Apply the one-liner swap + `reporter_field` destructure.
4. Move this file to `sdd/tasks/completed/` and mark the index entry
   `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
