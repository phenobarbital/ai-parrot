# TASK-811: Unit tests for ticket-created handler + webhook payload shape

**Feature**: FEAT-110 — jiraspecialist-webhook-ticket-creation
**Spec**: `sdd/specs/FEAT-110-jiraspecialist-webhook-ticket-creation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-3h)
**Depends-on**: TASK-810
**Assigned-to**: unassigned

---

## Context

Spec § 4. This task adds the full unit coverage for FEAT-110: the
nine scenarios listed in the test matrix, across both the webhook
payload shape (TASK-808) and the handler behaviour (TASK-810), plus a
regression guard for the `handle_jira_assignment` caller update.

Pattern to mirror: `packages/ai-parrot/tests/test_jira_assignment.py`
already isolates external deps (Redis, JiraToolkit, navconfig) and
exercises another `handle_*` method on the same class.

---

## Scope

Create a single new test file covering:

1. `handle_jira_ticket_created` — the eight handler scenarios:
   - reporter already in allow-list → skipped
   - reporter not in allow-list → reassigned + commented
   - no reporter email in payload → skipped
   - empty `JIRA_ALLOWED_REPORTERS` → skipped
   - `jira_toolkit is None` → error, toolkit not called
   - `jira_set_reporter` raises → error, handler still returns cleanly
   - `JIRA_DEFAULT_REPORTER` is set and in list → picked as replacement
   - `JIRA_DEFAULT_REPORTER` set but NOT in list → fallback to first
2. `handle_hook_event` routes `jira.created` events to the new handler.
3. `handle_jira_assignment` regression: given a reporter DICT, the
   method extracts `display_name` (not the whole dict) when building
   its LLM instruction — guards TASK-810's caller fix.
4. `JiraWebhookHook._handle_post` emits a `reporter` dict with the four
   expected keys when POSTed a `jira:issue_created` body.

**NOT in scope**:
- Integration tests against a live Jira. Deferred in the spec.
- Testing `jira_set_reporter` / `jira_add_comment` themselves — those
  live in `packages/ai-parrot-tools/tests/`.
- Modifying existing `test_jira_assignment.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_jira_ticket_created.py` | CREATE | All tests for this feature — handler + routing + webhook shape + assignment regression. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Mirrors tests/test_jira_assignment.py (the pattern to follow)
import unittest
from unittest.mock import AsyncMock, patch

from parrot.bots.jira_specialist import Developer, JiraSpecialist
from parrot.core.hooks.models import HookEvent, HookType
```

### Existing Signatures to Use

```python
# packages/ai-parrot/tests/test_jira_assignment.py — pattern reference
class TestJiraAssignmentHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis_patcher = patch("redis.asyncio.from_url")
        self.mock_redis = self.redis_patcher.start()
        self.mock_redis.return_value = AsyncMock()
        self.jira_patcher = patch("parrot.bots.jira_specialist.JiraToolkit")
        self.jira_patcher.start()
        self.config_patcher = patch("parrot.bots.jira_specialist.config")
        mock_config = self.config_patcher.start()
        mock_config.get.return_value = "dummy"
        mock_config.getlist.return_value = []
        self.agent = JiraSpecialist()
        self.agent.ask = AsyncMock(return_value=object())
```

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py (post-TASK-810)
class JiraSpecialist(Agent):
    jira_toolkit: Optional[JiraToolkit]
    async def handle_hook_event(self, event: HookEvent) -> Optional[Dict[str, Any]]:
    async def handle_jira_ticket_created(
        self, payload: Dict[str, Any],
    ) -> Dict[str, Any]:
    async def handle_jira_assignment(
        self, payload: Dict[str, Any],
    ) -> Dict[str, Any]:
```

```python
# packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py
class JiraWebhookHook(BaseHook):
    async def _handle_post(
        self, request: web.Request,
    ) -> web.Response:
    # Tests can call _handle_post with a fake aiohttp request OR
    # they can test the *_classify_event / payload construction*
    # helpers directly by invoking a real aiohttp test server via
    # aiohttp.test_utils.TestClient. Prefer the latter — see
    # packages/ai-parrot/tests/test_jira_webhook.py if it exists;
    # otherwise build a minimal aiohttp test app in the test file.
```

### Does NOT Exist
- ~~`pytest-asyncio` conventions~~ — the sibling test file uses
  `unittest.IsolatedAsyncioTestCase`. Stick with `unittest` style for
  consistency with `test_jira_assignment.py`.
- ~~`JiraSpecialist.set_toolkit`~~ — not a real method. Set
  `self.agent.jira_toolkit = AsyncMock()` directly in each test's
  setup, the way `test_jira_assignment.py` sets `self.agent.ask`.
- ~~`from parrot.conf import JIRA_ALLOWED_REPORTERS` in the test~~ —
  patch via `patch.multiple("parrot.bots.jira_specialist",
  JIRA_ALLOWED_REPORTERS=[...], JIRA_DEFAULT_REPORTER=...)` so every
  test case can vary the values without polluting global state.
- ~~`unittest.mock.call_kwargs`~~ — it's `.call_args.kwargs`.
- ~~`aiohttp.test_utils.setup_test_loop`~~ for the webhook test — use
  `AioHTTPTestCase` if needed, or mock the request object and call
  `_handle_post` with a stub whose `.read()` / `.json()` / `.headers`
  behave correctly.

---

## Implementation Notes

### Shared fixture pattern

```python
class TestJiraTicketCreatedHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Isolate external deps the same way test_jira_assignment.py does
        self.redis_patcher = patch("redis.asyncio.from_url")
        self.mock_redis = self.redis_patcher.start()
        self.mock_redis.return_value = AsyncMock()

        self.jira_patcher = patch("parrot.bots.jira_specialist.JiraToolkit")
        self.jira_patcher.start()

        self.config_patcher = patch("parrot.bots.jira_specialist.config")
        mock_config = self.config_patcher.start()
        mock_config.get.return_value = "dummy"
        mock_config.getlist.return_value = []

        self.agent = JiraSpecialist()
        self.agent.ask = AsyncMock(return_value=object())
        self.agent.jira_toolkit = AsyncMock()
        self.agent.jira_toolkit.jira_set_reporter = AsyncMock(
            return_value={"ok": True, "issue": "NAV-9999", "reporter": "xyz"}
        )
        self.agent.jira_toolkit.jira_add_comment = AsyncMock(
            return_value={"ok": True}
        )

    async def asyncTearDown(self):
        self.redis_patcher.stop()
        self.jira_patcher.stop()
        self.config_patcher.stop()
```

### Per-test config patching

Use `patch.multiple` to override the module-level constants per case:

```python
async def test_created_reporter_disallowed_is_reassigned(self):
    payload = {
        "issue_key": "NAV-9999",
        "reporter": {
            "email": "stranger@example.com",
            "display_name": "Outside Stranger",
            "account_id": "acc-1",
            "name": None,
        },
    }
    with patch.multiple(
        "parrot.bots.jira_specialist",
        JIRA_ALLOWED_REPORTERS=["allowed@example.com"],
        JIRA_DEFAULT_REPORTER=None,
    ):
        result = await self.agent.handle_jira_ticket_created(payload)

    self.assertEqual(result["status"], "ok")
    self.assertEqual(result["issue_key"], "NAV-9999")
    self.assertEqual(result["original_reporter"], "stranger@example.com")
    self.assertEqual(result["new_reporter"], "allowed@example.com")
    self.agent.jira_toolkit.jira_set_reporter.assert_awaited_once_with(
        issue="NAV-9999", email="allowed@example.com",
    )
    self.agent.jira_toolkit.jira_add_comment.assert_awaited_once()
```

### Case-insensitive allow-list test

```python
async def test_created_reporter_matches_allow_list_case_insensitive(self):
    payload = {"issue_key": "NAV-1",
               "reporter": {"email": "ALLOWED@Example.com",
                            "display_name": "A", "account_id": "x",
                            "name": None}}
    with patch.multiple(
        "parrot.bots.jira_specialist",
        JIRA_ALLOWED_REPORTERS=["allowed@example.com"],
        JIRA_DEFAULT_REPORTER=None,
    ):
        result = await self.agent.handle_jira_ticket_created(payload)
    self.assertEqual(result["status"], "skipped")
    self.agent.jira_toolkit.jira_set_reporter.assert_not_awaited()
```

### Toolkit-missing test

```python
async def test_created_toolkit_missing_returns_error(self):
    self.agent.jira_toolkit = None
    with patch.multiple(
        "parrot.bots.jira_specialist",
        JIRA_ALLOWED_REPORTERS=["a@x.com"],
        JIRA_DEFAULT_REPORTER=None,
    ):
        result = await self.agent.handle_jira_ticket_created(
            {"issue_key": "NAV-1",
             "reporter": {"email": "b@x.com",
                          "display_name": "B",
                          "account_id": "acc",
                          "name": None}}
        )
    self.assertEqual(result["status"], "error")
    self.assertIn("jira_toolkit", result["reason"])
```

### Toolkit-raises test

```python
async def test_created_toolkit_set_reporter_raises_is_error(self):
    self.agent.jira_toolkit.jira_set_reporter = AsyncMock(
        side_effect=ValueError("No Jira user found for email: bogus@x.com")
    )
    with patch.multiple(
        "parrot.bots.jira_specialist",
        JIRA_ALLOWED_REPORTERS=["bogus@x.com"],
        JIRA_DEFAULT_REPORTER=None,
    ):
        result = await self.agent.handle_jira_ticket_created(
            {"issue_key": "NAV-1",
             "reporter": {"email": "outsider@x.com",
                          "display_name": "X", "account_id": "y",
                          "name": None}}
        )
    self.assertEqual(result["status"], "error")
    self.assertIn("No Jira user found", result["error"])
```

### Routing test

```python
async def test_handle_hook_event_routes_jira_created(self):
    self.agent.handle_jira_ticket_created = AsyncMock(
        return_value={"status": "ok"}
    )
    event = HookEvent(
        hook_id="h1",
        hook_type=HookType.JIRA_WEBHOOK,
        event_type="jira.created",
        payload={"issue_key": "NAV-1"},
    )
    result = await self.agent.handle_hook_event(event)
    self.assertEqual(result, {"status": "ok"})
    self.agent.handle_jira_ticket_created.assert_awaited_once_with(
        {"issue_key": "NAV-1"},
    )
```

### Regression test for handle_jira_assignment

```python
async def test_assignment_handler_extracts_reporter_display_name(self):
    payload = {
        "issue_key": "NAV-5",
        "summary": "x",
        "priority": "High",
        "status": "Open",
        "reporter": {
            "email": "rep@example.com",
            "display_name": "The Reporter",
            "account_id": "acc",
            "name": None,
        },
        "new_assignee": {"email": "jesuslarag@gmail.com",
                         "display_name": "Jesus Lara"},
    }
    self.agent._developers = [
        Developer(id="35", name="Jesus Lara", username="jlara@trocglobal.com",
                  jira_username="jesuslarag@gmail.com",
                  telegram_chat_id=286137732, manager_chat_id=286137732)
    ]
    await self.agent.handle_jira_assignment(payload)

    called_question = self.agent.ask.call_args.kwargs.get("question") \
        or self.agent.ask.call_args.args[0]
    self.assertIn("The Reporter", called_question)
    # And the raw dict repr must NOT leak into the instruction.
    self.assertNotIn("account_id", called_question)
```

### Webhook payload shape test

For the webhook test, build a minimal aiohttp app using
`aiohttp.test_utils.AioHTTPTestCase` or mock the request directly. The
simpler approach: call `_handle_post` with a fake request whose
`.read()` returns the bytes of a sample Jira body and `.json()` returns
the parsed dict. Intercept `hook.on_event` to capture the emitted
`HookEvent`:

```python
class TestJiraWebhookReporterPayload(unittest.IsolatedAsyncioTestCase):
    async def test_webhook_reporter_payload_is_dict(self):
        from parrot.core.hooks.jira_webhook import JiraWebhookHook
        from parrot.core.hooks.models import JiraWebhookConfig
        hook = JiraWebhookHook(JiraWebhookConfig(url="/hook"))
        captured = []
        async def fake_callback(event):
            captured.append(event)
        hook.set_callback(fake_callback)

        jira_body = {
            "webhookEvent": "jira:issue_created",
            "issue": {
                "key": "NAV-42",
                "id": "99",
                "fields": {
                    "summary": "s",
                    "status": {"name": "Open"},
                    "priority": {"name": "Low"},
                    "project": {"key": "NAV"},
                    "reporter": {
                        "accountId": "acc-1",
                        "emailAddress": "rep@example.com",
                        "displayName": "The Reporter",
                        "name": "rep",
                    },
                    "assignee": None,
                },
            },
            "user": {},
            "timestamp": 0,
        }

        class FakeRequest:
            headers = {}
            async def read(self):
                import json; return json.dumps(jira_body).encode()
            async def json(self):
                return jira_body

        resp = await hook._handle_post(FakeRequest())
        self.assertEqual(resp.status, 202)
        self.assertEqual(len(captured), 1)
        reporter = captured[0].payload["reporter"]
        self.assertEqual(reporter["email"], "rep@example.com")
        self.assertEqual(reporter["display_name"], "The Reporter")
        self.assertEqual(reporter["account_id"], "acc-1")
        self.assertEqual(reporter["name"], "rep")
```

### Key Constraints
- Use `unittest.IsolatedAsyncioTestCase` for consistency with
  `test_jira_assignment.py`. Do NOT introduce `pytest-asyncio`.
- Patch module-level constants with `patch.multiple` — don't mutate
  `parrot.conf` directly in tests.
- Every test must `stop()` its patchers in `asyncTearDown` or use
  `with patch(...)` context managers.
- Tests must run with the venv activated:
  `source .venv/bin/activate && pytest packages/ai-parrot/tests/test_jira_ticket_created.py -v`

---

## Acceptance Criteria

- [ ] New file `packages/ai-parrot/tests/test_jira_ticket_created.py` exists.
- [ ] All nine scenarios in the spec's test matrix are covered.
- [ ] `pytest packages/ai-parrot/tests/test_jira_ticket_created.py -v`
      passes with zero failures.
- [ ] `pytest packages/ai-parrot/tests/test_jira_assignment.py -v`
      still passes (regression check after TASK-810's caller change).
- [ ] `ruff check packages/ai-parrot/tests/test_jira_ticket_created.py`
      is clean.
- [ ] No network calls; no live Jira access.
- [ ] No `sleep` calls; no real Redis access.

---

## Test Specification

The tests ARE the spec for this task. See the per-scenario snippets
above — each maps 1:1 to a row of the test matrix in `spec.md § 4`.

---

## Agent Instructions

1. Verify TASK-810 is in `sdd/tasks/completed/`. If not, stop.
2. Copy the fixture pattern from
   `packages/ai-parrot/tests/test_jira_assignment.py`.
3. Implement every listed scenario. Run the full file in the venv:
   ```bash
   source .venv/bin/activate
   pytest packages/ai-parrot/tests/test_jira_ticket_created.py -v
   pytest packages/ai-parrot/tests/test_jira_assignment.py -v
   ```
4. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
