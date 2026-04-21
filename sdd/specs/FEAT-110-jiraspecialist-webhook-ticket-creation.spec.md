# Feature Specification: JiraSpecialist Webhook — Autonomous Reporter Re-assignment on Ticket Creation

**Feature ID**: FEAT-110
**Date**: 2026-04-21
**Author**: Jesus Lara
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

Navigator's Jira instance emits `jira:issue_created` webhooks every time a
ticket is opened. Today, `JiraWebhookHook` classifies these as either
`jira.created` (no assignee) or `jira.assigned` (assignee populated at
creation) and `JiraSpecialist.handle_hook_event` only routes the
`jira.assigned` and `jira.ready_for_test` flavours.

This leaves the `jira.created` path completely unhandled. Business teams
are now creating tickets through external surfaces (HR form intake,
Navigator forms, third-party integrations) where the **reporter** is a
service account, a non-engineering user, or a person whose account is not
authorized to own engineering tickets in the target project. Those tickets
then sit in the project with an invalid owner of record, breaking:

- Standup / assignment flows that assume the reporter is a real engineer.
- Reporting & audits ("who filed this?" resolves to a mailbox, not a person).
- Permission-scoped transitions that require the reporter to belong to the
  engineering group.

Manually fixing the reporter on each new ticket does not scale and defeats
the purpose of the webhook pipeline we already ship (FEAT-108 assignment
intake, `jira.ready_for_test` QA notification).

### Goals

- On every `jira.created` event, compare the ticket's reporter against an
  allow-list (`JIRA_ALLOWED_REPORTERS`) and, if the reporter is **not**
  on the list, autonomously re-point the ticket's `reporter` field to an
  email drawn from that list using `JiraToolkit.jira_set_reporter`.
- Enrich the webhook payload so the downstream handler receives the
  reporter's **email** and **accountId** in addition to the current
  `displayName`-only value. Without email/accountId we cannot match
  against an email allow-list, and the webhook is the only place the
  full reporter object is available without a second Jira round-trip.
- Post an auditable comment on the affected ticket explaining the
  automatic re-assignment and log the outcome so the action is traceable.
- Ship unit tests that cover: allowed reporter (no-op), disallowed
  reporter (re-assign), empty allow-list (no-op), missing reporter
  (skip), and toolkit failure (error status returned).

### Non-Goals (explicitly out of scope)

- Re-routing the **assignee** field. FEAT-108 already owns assignment
  intake; this feature only manipulates the reporter.
- Changing how tickets are classified by `JiraWebhookHook._classify_event`.
  The existing classification (`created` vs `assigned` when an assignee
  is present at creation) is preserved as-is.
- Introducing a rule engine or DSL for per-project reporter policies.
  The allow-list is global; per-project policy can be a follow-up.
- Notifying the original reporter on Telegram/email. Out of scope —
  comment on the ticket is sufficient for this iteration.
- Re-opening already-created tickets for back-fill. This only handles
  events as they arrive.

---

## 2. Architectural Design

### Overview

A single new async handler (`handle_jira_ticket_created`) is added to
`JiraSpecialist`, registered in `handle_hook_event`'s routing table for
`jira.created` events. The handler:

1. Reads the reporter from the event payload.
2. Reads the `JIRA_ALLOWED_REPORTERS` list from `parrot.conf`.
3. Compares (case-insensitive, email-only). If the reporter's email is
   already in the list, or no reporter is present, or the allow-list is
   empty, the handler returns a `skipped` result.
4. Otherwise, it picks a **replacement reporter** (configurable strategy:
   default = `JIRA_DEFAULT_REPORTER` if set and itself on the list, else
   the first entry of `JIRA_ALLOWED_REPORTERS`) and invokes
   `self.jira_toolkit.jira_set_reporter(issue=<key>, email=<replacement>)`.
5. Posts a Jira comment noting the original reporter's display name + the
   new reporter's email, so the audit trail survives.

To make step 1 viable, `JiraWebhookHook._handle_post` is modified so that
the `reporter` key in the emitted payload is a **dict** (account_id,
email, display_name, name) — matching the shape already used for
`assignee`, and strictly additive (no key is removed, only enriched).

### Component Diagram

```
 ┌───────────────────────────────┐
 │ Atlassian Cloud               │
 │  (fires jira:issue_created)   │
 └──────────────┬────────────────┘
                │ POST /api/v1/hooks/jira
                ▼
 ┌───────────────────────────────┐
 │ JiraWebhookHook               │  ← enrich reporter → dict
 │ core/hooks/jira_webhook.py    │
 └──────────────┬────────────────┘
                │ HookEvent(event_type="jira.created", payload=…)
                ▼
 ┌───────────────────────────────┐
 │ HookManager                   │
 └──────────────┬────────────────┘
                │ callback → handle_hook_event(event)
                ▼
 ┌───────────────────────────────────────────────────────────┐
 │ JiraSpecialist                                            │
 │  bots/jira_specialist.py                                  │
 │                                                           │
 │  handle_hook_event                                        │
 │   └─► if event.event_type == "jira.created":              │
 │         handle_jira_ticket_created(payload)               │
 │           ├─ reporter ∈ JIRA_ALLOWED_REPORTERS? skip      │
 │           ├─ pick replacement email                       │
 │           ├─ await jira_toolkit.jira_set_reporter(...)    │
 │           └─ await jira_toolkit.jira_add_comment(...)     │
 └───────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component                    | Integration Type | Notes |
|---|---|---|
| `JiraWebhookHook` (`core/hooks/jira_webhook.py`) | extend | Enrich reporter payload (dict instead of scalar). Strictly additive. |
| `JiraSpecialist` (`bots/jira_specialist.py`) | extend | New `handle_jira_ticket_created(payload)` coroutine + new `jira.created` branch in `handle_hook_event`. |
| `JiraToolkit` (`parrot_tools.jiratoolkit`) | call | Use existing `jira_set_reporter(issue, email)` and `jira_add_comment(issue, body)`. No toolkit changes. |
| `parrot.conf` | add constants | `JIRA_ALLOWED_REPORTERS: list[str]`, `JIRA_DEFAULT_REPORTER: str | None`. |
| `HookEvent` / `HookManager` | consume | No change — consumes existing `HookEvent` routing. |

### Data Models

```python
# parrot/bots/jira_specialist.py — result shape returned by handler.
class ReporterReassignResult(TypedDict, total=False):
    """Result of handle_jira_ticket_created.

    status:
        "ok"         reporter was changed
        "skipped"    reporter was already allowed / no allow-list / no reporter
        "error"      JiraToolkit raised or no toolkit attached
    """
    status: Literal["ok", "skipped", "error"]
    issue_key: str
    original_reporter: Optional[str]  # email if available, else display name
    new_reporter: Optional[str]       # email
    reason: Optional[str]
    error: Optional[str]
```

Pydantic is NOT needed here — result dict matches the shape already used
by `handle_jira_assignment` (plain `dict[str, Any]`), which remains the
convention for webhook handlers in this class.

### New Public Interfaces

```python
# parrot/bots/jira_specialist.py

class JiraSpecialist(Agent):

    async def handle_jira_ticket_created(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Auto-repoint the reporter of a freshly-created Jira ticket when
        the original reporter is not in ``JIRA_ALLOWED_REPORTERS``.

        Emits a Jira comment documenting the change and returns a result
        dict compatible with the other handle_* webhook methods.
        """
```

No new env var parsing helper is needed — `parrot.conf` already uses
`config.get` / `config.getlist` from `navconfig`.

---

## 3. Module Breakdown

### Module 1: Webhook reporter enrichment
- **Path**: `packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py`
- **Responsibility**: In `_handle_post`, replace the scalar `reporter`
  key with a dict exposing `email`, `display_name`, `account_id`, `name`.
  Preserve the top-level position so downstream code that only reads
  `payload["reporter"]["display_name"]` keeps working after a trivial
  one-line adjustment in callers.
- **Depends on**: nothing new — uses fields already present in the
  Jira cloud webhook body.

### Module 2: Configuration constants
- **Path**: `packages/ai-parrot/src/parrot/conf.py`
- **Responsibility**: Add two new constants:
  - `JIRA_ALLOWED_REPORTERS: list[str]` — parsed via `config.getlist`;
    emails of users authorized to be reporters on new tickets.
  - `JIRA_DEFAULT_REPORTER: Optional[str]` — optional single email that
    takes precedence when picking a replacement; falls back to the
    first entry of `JIRA_ALLOWED_REPORTERS`.
- **Depends on**: Module 1 (so the handler downstream has emails to
  compare against — though technically independent, both land together).

### Module 3: JiraSpecialist handler + routing
- **Path**: `packages/ai-parrot/src/parrot/bots/jira_specialist.py`
- **Responsibility**:
  1. Add `handle_jira_ticket_created(payload)` coroutine.
  2. Add `if event.event_type == "jira.created":` branch in
     `handle_hook_event` (existing method) that forwards to the new
     coroutine.
  3. Read `JIRA_ALLOWED_REPORTERS` / `JIRA_DEFAULT_REPORTER` from
     `parrot.conf` (import alongside the existing `JIRA_USERS` import).
  4. Call `self.jira_toolkit.jira_set_reporter(...)` and
     `self.jira_toolkit.jira_add_comment(...)` when re-assigning.
  5. Gracefully return `status="error"` when `self.jira_toolkit` is
     `None` (service-account path not yet wired) and never raise out of
     the handler — webhook handlers must not crash the orchestrator.
  6. Update the **existing** `handle_jira_assignment` method at
     `jira_specialist.py:1393` to read `reporter` as a dict:
     `reporter_display = (payload.get("reporter") or {}).get("display_name") or "—"`
     (the only in-repo consumer of the old scalar shape).
- **Depends on**: Module 1 (enriched reporter), Module 2 (config).

### Module 4: Unit tests
- **Path**: `packages/ai-parrot/tests/test_jira_ticket_created.py`
- **Responsibility**: Cover the five scenarios enumerated in `## 5.
  Acceptance Criteria`. Mirror the isolation pattern used by
  `tests/test_jira_assignment.py` (patch `redis.asyncio.from_url`,
  patch `parrot.bots.jira_specialist.JiraToolkit`, patch
  `parrot.bots.jira_specialist.config`).
- **Depends on**: Module 3.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_created_reporter_already_allowed_is_skipped` | 3 | Reporter email is in `JIRA_ALLOWED_REPORTERS` → handler returns `status="skipped"`, `jira_set_reporter` is NOT called. |
| `test_created_reporter_disallowed_is_reassigned` | 3 | Reporter email is NOT in list → handler calls `jira_set_reporter` with the default replacement email and posts a comment. Returns `status="ok"` with both emails. |
| `test_created_no_reporter_is_skipped` | 3 | `payload["reporter"]` is `None` or missing email → returns `status="skipped"` with reason `"missing reporter email"`. |
| `test_created_empty_allow_list_is_skipped` | 3 | `JIRA_ALLOWED_REPORTERS == []` → returns `status="skipped"` with reason `"JIRA_ALLOWED_REPORTERS is not configured"`. |
| `test_created_toolkit_missing_returns_error` | 3 | `self.jira_toolkit is None` → returns `status="error"` with reason `"jira_toolkit not attached"`, nothing is called on the toolkit. |
| `test_created_toolkit_set_reporter_raises_is_error` | 3 | `jira_set_reporter` raises → handler returns `status="error"` and still attempts to log. |
| `test_default_reporter_takes_precedence` | 3 | When `JIRA_DEFAULT_REPORTER` is set and is itself in the allow-list, it is picked as the replacement. Otherwise, the first allow-list entry is picked. |
| `test_handle_hook_event_routes_jira_created` | 3 | A `HookEvent(event_type="jira.created")` is dispatched through `handle_hook_event` and reaches `handle_jira_ticket_created` exactly once. |
| `test_webhook_reporter_payload_is_dict` | 1 | A `jira:issue_created` POST with a full reporter dict results in a `HookEvent.payload["reporter"]` that has `email`, `display_name`, `account_id`, `name` keys. |
| `test_assignment_handler_extracts_reporter_display_name` | 3 | `handle_jira_assignment` given a `reporter` **dict** formats its LLM instruction using `display_name` (regression guard for the caller update). |

### Integration Tests

| Test | Description |
|---|---|
| *(deferred)* | End-to-end against a Jira sandbox requires creds not present in CI. We rely on the unit coverage above plus a manual smoke test described in `## 7.`. |

### Test Data / Fixtures

```python
# Key fixtures needed (mirroring tests/test_jira_assignment.py)

@pytest.fixture
def jira_specialist_with_mock_toolkit(monkeypatch):
    """Return a JiraSpecialist whose jira_toolkit is an AsyncMock with
    jira_set_reporter / jira_add_comment as AsyncMocks."""

SAMPLE_CREATED_PAYLOAD = {
    "issue_key": "NAV-9999",
    "summary": "Example ticket",
    "priority": "Medium",
    "status": "To Do",
    "reporter": {
        "account_id": "5f0...abc",
        "email": "stranger@example.com",
        "display_name": "Outside Stranger",
        "name": None,
    },
}
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `JiraWebhookHook` emits a `reporter` dict with `email`, `display_name`,
      `account_id`, `name` on every issue event (not just `jira.created`).
- [ ] `JiraSpecialist.handle_hook_event` routes `"jira.created"` to
      `handle_jira_ticket_created` without touching the existing
      `jira.assigned` / `jira.ready_for_test` branches.
- [ ] When the reporter's email is in `JIRA_ALLOWED_REPORTERS` (case-insensitive
      compare), the handler is a no-op and returns `status="skipped"`.
- [ ] When the reporter's email is NOT in the list and the list is non-empty,
      `jira_set_reporter` is called exactly once with the picked replacement
      email, `jira_add_comment` is called with a human-readable note, and the
      handler returns `status="ok"` with both emails in the result.
- [ ] When `JIRA_ALLOWED_REPORTERS` is empty OR the payload has no reporter
      email, the handler returns `status="skipped"` with the correct reason
      and does NOT call the toolkit.
- [ ] When `self.jira_toolkit is None` OR the toolkit raises, the handler
      returns `status="error"` — it never raises out of the webhook path.
- [ ] All unit tests pass:
      `pytest packages/ai-parrot/tests/test_jira_ticket_created.py -v`
- [ ] Existing tests still pass:
      `pytest packages/ai-parrot/tests/test_jira_assignment.py -v`
- [ ] No breaking changes to existing public API (new constants, new method).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every reference below has been
> verified against the current source tree (`HEAD = 9dbce540`).

### Verified Imports

```python
# Hook plumbing
from parrot.core.hooks.models import HookEvent  # packages/ai-parrot/src/parrot/core/hooks/models.py:30
from parrot.core.hooks.jira_webhook import JiraWebhookHook  # .../jira_webhook.py:12 (lazy via __init__.py:39)

# Bot
from parrot.bots.jira_specialist import JiraSpecialist, Developer  # packages/ai-parrot/src/parrot/bots/jira_specialist.py:465

# Toolkit (already attached to JiraSpecialist via post_configure)
from parrot_tools.jiratoolkit import JiraToolkit  # packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:609

# Config
from parrot.conf import JIRA_USERS  # packages/ai-parrot/src/parrot/conf.py:551
# After Module 2 lands:
from parrot.conf import JIRA_ALLOWED_REPORTERS, JIRA_DEFAULT_REPORTER  # to be added
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py
class JiraWebhookHook(BaseHook):
    hook_type = HookType.JIRA_WEBHOOK                                    # line 20
    def __init__(self, config: JiraWebhookConfig, **kwargs) -> None:     # line 22
    async def _handle_post(self, request: web.Request) -> web.Response:  # line 49
    @staticmethod
    def _classify_event(payload: Dict[str, Any]) -> Optional[str]:       # line 117
    #   returns "created" | "assigned" | "unassigned" | "updated" |
    #           "closed" | "ready_for_test" | "deleted" | None
```

The existing `_handle_post` currently emits (line 76):
```python
"reporter": (fields.get("reporter") or {}).get("displayName"),
```
This MUST change to a dict matching the shape already used for
`assignee` at line 77–82 of the same file:
```python
"assignee": {
    "account_id": assignee_field.get("accountId"),
    "email": assignee_field.get("emailAddress"),
    "display_name": assignee_field.get("displayName"),
    "name": assignee_field.get("name"),
},
```

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(Agent):
    jira_toolkit: Optional[JiraToolkit]                                   # line 501
    async def post_configure(self) -> None:                               # line 545
    async def handle_hook_event(                                          # line 1278
        self, event: HookEvent,
    ) -> Optional[Dict[str, Any]]:
        if event.event_type == "jira.assigned":       # line 1292
            return await self.handle_jira_assignment(event.payload)
        if event.event_type == "jira.ready_for_test": # line 1294
            return await self.handle_ready_for_test(event.payload)
        # ← NEW branch goes here.
    async def handle_jira_assignment(                                     # line 1343
        self, payload: Dict[str, Any],
    ) -> Dict[str, Any]:
    async def handle_ready_for_test(                                      # line 1469
        self, payload: Dict[str, Any],
    ) -> Dict[str, Any]:
```

```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):                                       # line 609
    async def jira_set_reporter(                                          # line 2620
        self, issue: str, email: str,
    ) -> Dict[str, Any]:
        # Resolves email → accountId → jira_update_issue(
        #   fields={"reporter": {"accountId": account_id}})
        # Returns {"ok": True, "issue": issue, "reporter": account_id}
    async def _resolve_account_id(                                         # line 2744
        self, email_or_id: str,
    ) -> str:
    async def jira_add_comment(                                           # line 1578
        self, issue: str, body: str,
    ) -> Dict[str, Any]:
    # jira_add_comment is used from JiraSpecialist prompts; calling it
    # directly from a handler is allowed. Keep body short — this is an
    # audit trail comment, not a conversation.
```

```python
# packages/ai-parrot/src/parrot/core/hooks/models.py
class HookEvent(BaseModel):                                               # line 30
    hook_id: str
    hook_type: HookType
    event_type: str            # we'll match "jira.created"
    payload: Dict[str, Any]
    metadata: Dict[str, Any]
    timestamp: datetime
    target_type: Optional[str]
    target_id: Optional[str]
    task: Optional[str]
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `handle_jira_ticket_created` | `JiraToolkit.jira_set_reporter` | `await self.jira_toolkit.jira_set_reporter(issue=..., email=...)` | `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:2620` |
| `handle_jira_ticket_created` | `JiraToolkit.jira_add_comment` | `await self.jira_toolkit.jira_add_comment(issue=..., body=...)` | `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (existing tool) |
| `handle_hook_event` | `handle_jira_ticket_created` | new `elif event.event_type == "jira.created":` | `packages/ai-parrot/src/parrot/bots/jira_specialist.py:1292` |
| `JiraWebhookHook._handle_post` | reporter dict | keys: `email`, `display_name`, `account_id`, `name` | `packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py:76` |
| `parrot.conf` | allow-list | `JIRA_ALLOWED_REPORTERS = config.getlist("JIRA_ALLOWED_REPORTERS", fallback=[])` | `packages/ai-parrot/src/parrot/conf.py:551` (add just after `JIRA_USERS`) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.conf.JIRA_ALLOWED_REPORTERS`~~ — **does not exist yet**; this
  spec creates it. `grep -R "JIRA_ALLOWED_REPORTERS" packages/` returns
  zero matches at `HEAD`.
- ~~`JiraSpecialist.handle_jira_ticket_created`~~ — **does not exist
  yet**; this spec creates it.
- ~~`JiraSpecialist.handle_jira_created`~~ — NOT a real method; do not
  invent a shorter name. Use `handle_jira_ticket_created` for consistency
  with `handle_jira_assignment` / `handle_ready_for_test`.
- ~~`JiraToolkit.jira_change_reporter`~~ — NOT a real method. Use
  `jira_set_reporter` (the real name, verified at line 2620).
- ~~`JiraToolkit.jira_update_reporter`~~ — NOT a real method.
- ~~`Developer.is_allowed_reporter`~~ — NOT a real attribute. The
  allow-list is a flat list of emails in config; no per-developer flag.
- ~~`JiraWebhookHook.on_created`~~ — NOT a real method. Classification
  happens in `_classify_event`; emission happens in `_handle_post`.
- ~~`HookEvent.reporter`~~ — NOT a field on `HookEvent`. Reporter lives
  inside `HookEvent.payload["reporter"]`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Mirror `handle_jira_assignment` structure (`packages/ai-parrot/src/parrot/bots/jira_specialist.py:1343`):
  - Return `{"status": "skipped" | "ok" | "error", "issue_key": ..., ...}`.
  - Guard-clause missing `issue_key` early.
  - Catch the broad `Exception` at the toolkit boundary, `self.logger.error`
    with `exc_info=True`, and return `status="error"`.
- Log INFO on skip/success, ERROR with `exc_info=True` on failure —
  consistent with `handle_ready_for_test`.
- Use `self.logger`, never `print`. The existing `print('DEVELOPERS
  CONFIG', ...)` / `print('JIRA USERS > ', ...)` at
  `jira_specialist.py:527-528` is pre-existing debug noise; do **not**
  add new prints.
- Case-insensitive email comparison (`.lower()` both sides). Jira returns
  emails in mixed case via the webhook.

### Known Risks / Gotchas

- **Reporter email may be missing from the webhook body** even when
  `reporter` is set. Atlassian Cloud hides `emailAddress` from webhook
  bodies unless the integration has `user:email` scope. If the email is
  `None` but `accountId` is present, the handler MUST fall back to
  `status="skipped"` with `reason="reporter email not available"` —
  do NOT re-assign on display-name match alone (display names are not
  unique and can spoof).
- **`jira_set_reporter` requires the replacement email to resolve** via
  `_resolve_account_id`. If the admin configures an email that is not a
  real Jira user, the toolkit raises `ValueError("No Jira user found for
  email: ...")`. We convert that to `status="error"` and log loudly.
- **Reporter change consumes a Jira audit entry.** If an automated
  service account is the reporter on many tickets, comment spam can
  become noisy. Keep the comment short and single-line.
- **Payload shape change requires ONE in-repo caller update.**
  `JiraSpecialist.handle_jira_assignment` at
  `packages/ai-parrot/src/parrot/bots/jira_specialist.py:1393` reads
  `reporter = payload.get("reporter") or "—"` and formats it as a
  string inside the LLM instruction (line 1403). When Module 1 lands
  and `reporter` becomes a dict, that line will stringify the dict
  (`{'account_id': ..., 'email': ...}`) in the prompt — ugly but not
  a crash. Module 3 MUST also update that caller to extract
  `display_name` from the new dict shape, e.g.:
  `reporter_display = (payload.get("reporter") or {}).get("display_name") or "—"`.
  Do **not** skip this — it's the only in-repo consumer of the old shape
  (`grep -Rn 'payload\[.reporter.\]\|payload\.get\(.reporter.\)' packages/`
  returns exactly one hit at line 1393).
- **Webhook must not crash the orchestrator.** All branches of
  `handle_jira_ticket_created` must return — never raise.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| *(none new)* | — | Feature composes existing `JiraToolkit` / hook infrastructure. |

### Manual Smoke Test (one-time, after merge)

1. Add `JIRA_ALLOWED_REPORTERS=you@example.com` to `.env`.
2. Start the app; ensure `JiraSpecialist.post_configure` logs the
   expected tool count.
3. In Jira, create a ticket as a user whose email is NOT in the list.
4. Within a few seconds, observe: reporter flips to the allowed email,
   a comment is posted explaining the change, and the handler logs
   `status="ok"` with both emails.

---

## 8. Open Questions

- [ ] Should we also honor a **per-project** allow-list
      (`JIRA_ALLOWED_REPORTERS__NAV=...`, etc.) for teams with different
      policies? — *Owner: Jesus* — deferred unless needed.
- [ ] Should we expose a "notify original reporter via Jira comment
      @mention" flag? — *Owner: Jesus* — deferred; current comment already
      names them by display name.
- [ ] Do we want to rate-limit comments when a bulk-import creates many
      tickets at once? — *Owner: Jesus* — deferred; Jira itself rate-limits.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`. Tasks run sequentially in one
  worktree because Module 3 imports the constants added in Module 2 and
  the tests in Module 4 exercise Module 3.
- **Cross-feature dependencies**: none. FEAT-108 (assignment flow) and
  the existing `jira.ready_for_test` handler are already merged on `main`.
- **Branch name**: `feat-110-jiraspecialist-webhook-ticket-creation`.
- **Create from**: current `dev` HEAD (not `main`).

Worktree creation:
```bash
git worktree add -b feat-110-jiraspecialist-webhook-ticket-creation \
  .claude/worktrees/feat-110-jiraspecialist-webhook-ticket-creation HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-21 | Jesus Lara | Initial draft — webhook ticket creation autonomous reporter re-assignment. |
