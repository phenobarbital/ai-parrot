# TASK-810: Implement handle_jira_ticket_created + route jira.created + update assignment caller

**Feature**: FEAT-110 — jiraspecialist-webhook-ticket-creation
**Spec**: `sdd/specs/FEAT-110-jiraspecialist-webhook-ticket-creation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-808, TASK-809
**Assigned-to**: unassigned

---

## Context

Spec § 3 / Module 3. This is the core of the feature. A ticket-created
webhook arrives with an enriched reporter dict (TASK-808) and is
compared against the configured allow-list (TASK-809). When the
original reporter is not authorized, the handler calls
`JiraToolkit.jira_set_reporter` to flip the field to a replacement email
and posts an audit comment.

This task also fixes a mechanical consequence of TASK-808: the existing
`handle_jira_assignment` method reads `payload["reporter"]` as a scalar
string; after the payload change it must read `display_name` from the
new dict.

---

## Scope

- Add two new imports at the top of `jira_specialist.py`, next to the
  existing `from parrot.conf import JIRA_USERS`:
  ```python
  from parrot.conf import JIRA_ALLOWED_REPORTERS, JIRA_DEFAULT_REPORTER
  ```
- Add a new coroutine `async def handle_jira_ticket_created(self,
  payload: Dict[str, Any]) -> Dict[str, Any]` on `JiraSpecialist`.
  Placement: immediately above or below `handle_ready_for_test` so
  the three webhook handlers sit together.
- Wire it into `handle_hook_event` with a new branch:
  ```python
  if event.event_type == "jira.created":
      return await self.handle_jira_ticket_created(event.payload)
  ```
  Place it before the existing `jira.assigned` / `jira.ready_for_test`
  branches or preserve existing ordering — either is fine, but keep it
  above the terminal "ignoring hook event" log.
- Update `handle_jira_assignment` at line 1393 to extract
  `display_name` from the new reporter dict shape:
  ```python
  reporter_display = (
      (payload.get("reporter") or {}).get("display_name")
      or "—"
  )
  ```
  Then interpolate `reporter_display` (not the raw `reporter`) into the
  Spanish-instructions string at line 1403.

**NOT in scope**:
- Webhook payload enrichment (TASK-808).
- Config constants (TASK-809).
- Any Jira Toolkit changes. `jira_set_reporter` and `jira_add_comment`
  already exist — call them as-is.
- Tests (TASK-811).
- Touching `handle_ready_for_test`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | Add `handle_jira_ticket_created` method, route `jira.created` in `handle_hook_event`, fix `handle_jira_assignment` reporter read, add config imports. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing — already in the file:
from parrot.bots import Agent                                           # line 34
from parrot.conf import JIRA_USERS                                      # line 41
from parrot_tools.jiratoolkit import JiraToolkit                        # line 43
from parrot.core.hooks.models import HookEvent                          # line 47

# NEW — add immediately after line 41:
from parrot.conf import JIRA_ALLOWED_REPORTERS, JIRA_DEFAULT_REPORTER   # landed in TASK-809
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(Agent):                                    # line 465
    jira_toolkit: Optional[JiraToolkit]                         # line 501
    self.logger                                                 # from Agent base

    async def handle_hook_event(                                # line 1278
        self, event: HookEvent,
    ) -> Optional[Dict[str, Any]]:
        if event.event_type == "jira.assigned":                 # line 1292
            return await self.handle_jira_assignment(event.payload)
        if event.event_type == "jira.ready_for_test":           # line 1294
            return await self.handle_ready_for_test(event.payload)
        # ← new "jira.created" branch goes here (before the
        #   "ignoring" log at line 1296).
        self.logger.info(                                        # line 1296
            "JiraSpecialist: ignoring hook event %s (hook_id=%s)",
            event.event_type, event.hook_id,
        )
        return None

    async def handle_jira_assignment(                           # line 1343
        self, payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        # line 1393:   reporter = payload.get("reporter") or "—"
        # line 1403:   f"Reporter: {reporter}\n\n"
        # After TASK-808, payload["reporter"] is a DICT — update the
        # extraction to read "display_name".

    async def handle_ready_for_test(                            # line 1469
        self, payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        # Copy this method's guard-clause pattern for the new handler.
```

```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):                             # line 609
    async def jira_set_reporter(                                # line 2620
        self, issue: str, email: str,
    ) -> Dict[str, Any]:
        # Resolves email → accountId, updates reporter field.
        # Returns {"ok": True, "issue": issue, "reporter": <account_id>}
        # Raises ValueError if email cannot be resolved.

    async def jira_add_comment(                                 # line 1578
        self, issue: str, body: str,
    ) -> Dict[str, Any]:
        # Standard Jira comment.
```

Payload shape we consume (from TASK-808):
```python
payload = {
    "issue_key": str,
    "summary": str,
    "priority": Optional[str],
    "status": Optional[str],
    "reporter": {
        "email": Optional[str],          # may be None per PII scope
        "display_name": Optional[str],
        "account_id": Optional[str],
        "name": Optional[str],
    },
    ...  # other keys preserved
}
```

### Does NOT Exist
- ~~`JiraToolkit.jira_change_reporter`~~ — the method is
  `jira_set_reporter`.
- ~~`JiraToolkit.jira_update_reporter`~~ — not a real method.
- ~~`JiraSpecialist.handle_jira_created`~~ — do not use a shorter name.
  Mirror `handle_jira_assignment` / `handle_ready_for_test` naming →
  `handle_jira_ticket_created`.
- ~~`self._reporter_allow_list`~~ — do not cache the list as an
  instance attribute. Read from `parrot.conf` each call so test
  monkey-patching works (see TASK-811 fixture pattern).
- ~~`payload["reporter"]` as a string~~ — after TASK-808 it is a dict.
  The assignment handler fix at line 1393 is mandatory, not optional.
- ~~`HookEvent.reporter` / `HookEvent.issue_key`~~ — both live under
  `event.payload`.

---

## Implementation Notes

### Handler skeleton (copy + adapt)

```python
async def handle_jira_ticket_created(
    self,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Auto-repoint the reporter when the creator is not in
    ``JIRA_ALLOWED_REPORTERS``.

    Returns a result dict compatible with the other webhook handlers:
    ``{"status": "ok"|"skipped"|"error", "issue_key": ..., ...}``.
    Never raises — webhook handlers must not crash the orchestrator.
    """
    issue_key = payload.get("issue_key")
    if not issue_key:
        return {"status": "skipped", "reason": "missing issue_key"}

    if self.jira_toolkit is None:
        self.logger.error(
            "handle_jira_ticket_created: jira_toolkit not attached; "
            "skipping %s.",
            issue_key,
        )
        return {
            "status": "error",
            "issue_key": issue_key,
            "reason": "jira_toolkit not attached",
        }

    allow_list = [e.lower() for e in (JIRA_ALLOWED_REPORTERS or []) if e]
    if not allow_list:
        return {
            "status": "skipped",
            "issue_key": issue_key,
            "reason": "JIRA_ALLOWED_REPORTERS is not configured",
        }

    reporter_obj = payload.get("reporter") or {}
    original_email = (reporter_obj.get("email") or "").strip().lower()
    original_display = reporter_obj.get("display_name") or "—"

    if not original_email:
        return {
            "status": "skipped",
            "issue_key": issue_key,
            "reason": "reporter email not available",
        }

    if original_email in allow_list:
        return {
            "status": "skipped",
            "issue_key": issue_key,
            "reason": "reporter already allowed",
            "original_reporter": original_email,
        }

    # Pick replacement. Default takes precedence iff itself allowed.
    default = (JIRA_DEFAULT_REPORTER or "").strip()
    if default and default.lower() in allow_list:
        replacement = default
    else:
        replacement = JIRA_ALLOWED_REPORTERS[0]

    try:
        await self.jira_toolkit.jira_set_reporter(
            issue=issue_key, email=replacement,
        )
        comment_body = (
            f"Reporter automatically updated from "
            f"{original_display} ({original_email}) to {replacement} "
            f"because the original reporter is not in the authorized list."
        )
        await self.jira_toolkit.jira_add_comment(
            issue=issue_key, body=comment_body,
        )
        self.logger.info(
            "jira_ticket_created: reassigned reporter on %s from %s to %s",
            issue_key, original_email, replacement,
        )
        return {
            "status": "ok",
            "issue_key": issue_key,
            "original_reporter": original_email,
            "new_reporter": replacement,
        }
    except Exception as exc:
        self.logger.error(
            "handle_jira_ticket_created failed for %s: %s",
            issue_key, exc, exc_info=True,
        )
        return {
            "status": "error",
            "issue_key": issue_key,
            "error": str(exc),
        }
```

### Routing change in `handle_hook_event`

Add this branch immediately before the `self.logger.info("...ignoring...")`
terminal line (currently line 1296). Ordering relative to the other
two branches is irrelevant — event types are mutually exclusive.

```python
if event.event_type == "jira.created":
    return await self.handle_jira_ticket_created(event.payload)
```

### `handle_jira_assignment` caller update

At line 1393 today:
```python
reporter = payload.get("reporter") or "—"
```
Replace with:
```python
reporter_display = (
    (payload.get("reporter") or {}).get("display_name") or "—"
)
```
Then at line 1403, replace `Reporter: {reporter}` with
`Reporter: {reporter_display}`. No other lines in that method reference
`reporter`. Verify with:
```bash
grep -n "reporter" packages/ai-parrot/src/parrot/bots/jira_specialist.py | sed -n '/handle_jira_assignment/,/handle_ready_for_test/p'
```

### Key Constraints
- Read `JIRA_ALLOWED_REPORTERS` and `JIRA_DEFAULT_REPORTER` **inside**
  the method body (or via `from parrot import conf; conf.JIRA_...`),
  NOT at class scope. This is what lets the tests monkey-patch them
  per-case without a factory fixture.
- Case-insensitive email comparison via `.lower()` on BOTH sides.
- Never call `print`. Use `self.logger`.
- Never raise out of the handler. All error paths must return a
  `{"status": "error", ...}` dict.
- Keep the comment body single-line. Jira renders multi-line bodies as
  markdown which is fine, but short is better here.

---

## Acceptance Criteria

- [ ] `handle_jira_ticket_created` exists on `JiraSpecialist` and
      returns a dict with `status` ∈ {ok, skipped, error}.
- [ ] `handle_hook_event` routes `"jira.created"` events to the new
      handler.
- [ ] `handle_jira_assignment` reads `display_name` from the reporter
      dict (regression-safe against TASK-808's shape change).
- [ ] Imports for `JIRA_ALLOWED_REPORTERS` and `JIRA_DEFAULT_REPORTER`
      land at module top alongside `JIRA_USERS`.
- [ ] The handler never raises — wrap every toolkit call in try/except.
- [ ] Case-insensitive allow-list comparison.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/jira_specialist.py`
      is clean.
- [ ] No new `print(` statements introduced.
- [ ] `pytest packages/ai-parrot/tests/test_jira_assignment.py -v`
      still passes (regression check for the caller update).

---

## Test Specification

Tests live in TASK-811. For this task, the agent may run a quick
import smoke test in the venv:
```bash
source .venv/bin/activate
python -c "from parrot.bots.jira_specialist import JiraSpecialist; \
  import inspect; \
  assert asyncio.iscoroutinefunction(JiraSpecialist.handle_jira_ticket_created)"
```

---

## Agent Instructions

1. Verify TASK-808 and TASK-809 are in `sdd/tasks/completed/`. If not,
   stop — this task depends on them.
2. Re-read lines 1278-1468 of `jira_specialist.py` to confirm the
   contract is still accurate.
3. Apply the three edits in order: (a) imports, (b) caller fix at
   line 1393, (c) new handler + routing branch.
4. Run the smoke import + the assignment regression suite.
5. Move this file to `sdd/tasks/completed/` and update the index entry
   to `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
