"""Unit tests for FEAT-110: JiraSpecialist webhook ticket-created handler.

Covers:
- handle_jira_ticket_created scenarios (allowed, disallowed, missing, empty
  allow-list, toolkit missing, toolkit raises, default reporter priority)
- handle_hook_event routing for 'jira.created'
- handle_jira_assignment regression: reporter dict → display_name extraction
- JiraWebhookHook._handle_post: reporter payload is a dict with the four keys
"""
import json
import logging
import unittest
from unittest.mock import AsyncMock, patch

from parrot.bots.jira_specialist import Developer, JiraSpecialist
from parrot.core.hooks.models import HookEvent, HookType


# ---------------------------------------------------------------------------
# Shared sample payload
# ---------------------------------------------------------------------------
SAMPLE_CREATED_PAYLOAD = {
    "issue_key": "NAV-9999",
    "summary": "Example ticket",
    "priority": "Medium",
    "status": "To Do",
    "reporter": {
        "account_id": "5f0abc",
        "email": "stranger@example.com",
        "display_name": "Outside Stranger",
        "name": None,
    },
}


# ---------------------------------------------------------------------------
# Tests for handle_jira_ticket_created
# ---------------------------------------------------------------------------
class TestJiraTicketCreatedHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Isolate external deps the same way test_jira_assignment.py does.
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
        self.agent.logger = logging.getLogger("test.jira_ticket_created")
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

    # -----------------------------------------------------------------------
    # 1. Reporter already in allow-list → skipped
    # -----------------------------------------------------------------------
    async def test_created_reporter_already_allowed_is_skipped(self):
        payload = {
            "issue_key": "NAV-9999",
            "reporter": {
                "email": "allowed@example.com",
                "display_name": "Allowed User",
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

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "reporter already allowed")
        self.agent.jira_toolkit.jira_set_reporter.assert_not_awaited()
        self.agent.jira_toolkit.jira_add_comment.assert_not_awaited()

    # -----------------------------------------------------------------------
    # 2. Reporter not in allow-list → reassigned + commented
    # -----------------------------------------------------------------------
    async def test_created_reporter_disallowed_is_reassigned(self):
        with patch.multiple(
            "parrot.bots.jira_specialist",
            JIRA_ALLOWED_REPORTERS=["allowed@example.com"],
            JIRA_DEFAULT_REPORTER=None,
        ):
            result = await self.agent.handle_jira_ticket_created(
                SAMPLE_CREATED_PAYLOAD
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["issue_key"], "NAV-9999")
        self.assertEqual(result["original_reporter"], "stranger@example.com")
        self.assertEqual(result["new_reporter"], "allowed@example.com")
        self.agent.jira_toolkit.jira_set_reporter.assert_awaited_once_with(
            issue="NAV-9999", email="allowed@example.com"
        )
        self.agent.jira_toolkit.jira_add_comment.assert_awaited_once()

    # -----------------------------------------------------------------------
    # 3. No reporter email in payload → skipped
    # -----------------------------------------------------------------------
    async def test_created_no_reporter_is_skipped(self):
        payload = {
            "issue_key": "NAV-9999",
            "reporter": {
                "email": None,
                "display_name": "Someone",
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

        self.assertEqual(result["status"], "skipped")
        self.assertIn("reporter email", result["reason"])
        self.agent.jira_toolkit.jira_set_reporter.assert_not_awaited()

    # -----------------------------------------------------------------------
    # 4. Empty allow-list → skipped
    # -----------------------------------------------------------------------
    async def test_created_empty_allow_list_is_skipped(self):
        with patch.multiple(
            "parrot.bots.jira_specialist",
            JIRA_ALLOWED_REPORTERS=[],
            JIRA_DEFAULT_REPORTER=None,
        ):
            result = await self.agent.handle_jira_ticket_created(
                SAMPLE_CREATED_PAYLOAD
            )

        self.assertEqual(result["status"], "skipped")
        self.assertIn("JIRA_ALLOWED_REPORTERS", result["reason"])
        self.agent.jira_toolkit.jira_set_reporter.assert_not_awaited()

    # -----------------------------------------------------------------------
    # 5. jira_toolkit is None → error
    # -----------------------------------------------------------------------
    async def test_created_toolkit_missing_returns_error(self):
        self.agent.jira_toolkit = None
        with patch.multiple(
            "parrot.bots.jira_specialist",
            JIRA_ALLOWED_REPORTERS=["a@x.com"],
            JIRA_DEFAULT_REPORTER=None,
        ):
            result = await self.agent.handle_jira_ticket_created(
                {
                    "issue_key": "NAV-1",
                    "reporter": {
                        "email": "b@x.com",
                        "display_name": "B",
                        "account_id": "acc",
                        "name": None,
                    },
                }
            )
        self.assertEqual(result["status"], "error")
        self.assertIn("jira_toolkit", result["reason"])

    # -----------------------------------------------------------------------
    # 6. jira_set_reporter raises → error, handler still returns cleanly
    # -----------------------------------------------------------------------
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
                {
                    "issue_key": "NAV-1",
                    "reporter": {
                        "email": "outsider@x.com",
                        "display_name": "X",
                        "account_id": "y",
                        "name": None,
                    },
                }
            )
        self.assertEqual(result["status"], "error")
        self.assertIn("No Jira user found", result["error"])

    # -----------------------------------------------------------------------
    # 7. JIRA_DEFAULT_REPORTER set and in list → picked as replacement
    # -----------------------------------------------------------------------
    async def test_default_reporter_takes_precedence(self):
        with patch.multiple(
            "parrot.bots.jira_specialist",
            JIRA_ALLOWED_REPORTERS=["first@example.com", "default@example.com"],
            JIRA_DEFAULT_REPORTER="default@example.com",
        ):
            result = await self.agent.handle_jira_ticket_created(
                SAMPLE_CREATED_PAYLOAD
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["new_reporter"], "default@example.com")
        self.agent.jira_toolkit.jira_set_reporter.assert_awaited_once_with(
            issue="NAV-9999", email="default@example.com"
        )

    # -----------------------------------------------------------------------
    # 7b. JIRA_DEFAULT_REPORTER set but NOT in list → first entry used
    # -----------------------------------------------------------------------
    async def test_default_reporter_not_in_list_falls_back_to_first(self):
        with patch.multiple(
            "parrot.bots.jira_specialist",
            JIRA_ALLOWED_REPORTERS=["first@example.com"],
            JIRA_DEFAULT_REPORTER="notinlist@example.com",
        ):
            result = await self.agent.handle_jira_ticket_created(
                SAMPLE_CREATED_PAYLOAD
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["new_reporter"], "first@example.com")

    # -----------------------------------------------------------------------
    # 8. Case-insensitive allow-list matching
    # -----------------------------------------------------------------------
    async def test_created_reporter_matches_allow_list_case_insensitive(self):
        payload = {
            "issue_key": "NAV-1",
            "reporter": {
                "email": "ALLOWED@Example.com",
                "display_name": "A",
                "account_id": "x",
                "name": None,
            },
        }
        with patch.multiple(
            "parrot.bots.jira_specialist",
            JIRA_ALLOWED_REPORTERS=["allowed@example.com"],
            JIRA_DEFAULT_REPORTER=None,
        ):
            result = await self.agent.handle_jira_ticket_created(payload)
        self.assertEqual(result["status"], "skipped")
        self.agent.jira_toolkit.jira_set_reporter.assert_not_awaited()

    # -----------------------------------------------------------------------
    # 9. Missing issue_key → skipped immediately
    # -----------------------------------------------------------------------
    async def test_created_missing_issue_key_is_skipped(self):
        with patch.multiple(
            "parrot.bots.jira_specialist",
            JIRA_ALLOWED_REPORTERS=["a@x.com"],
            JIRA_DEFAULT_REPORTER=None,
        ):
            result = await self.agent.handle_jira_ticket_created({})
        self.assertEqual(result["status"], "skipped")
        self.assertIn("issue_key", result["reason"])


# ---------------------------------------------------------------------------
# Routing test: handle_hook_event routes jira.created to the new handler
# ---------------------------------------------------------------------------
class TestHandleHookEventRoutingJiraCreated(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis_patcher = patch("redis.asyncio.from_url")
        self.redis_patcher.start()
        self.jira_patcher = patch("parrot.bots.jira_specialist.JiraToolkit")
        self.jira_patcher.start()
        self.config_patcher = patch("parrot.bots.jira_specialist.config")
        mock_config = self.config_patcher.start()
        mock_config.get.return_value = "dummy"
        mock_config.getlist.return_value = []

        self.agent = JiraSpecialist()
        self.agent.logger = logging.getLogger("test.jira_routing")
        self.agent.handle_jira_ticket_created = AsyncMock(
            return_value={"status": "ok"}
        )

    async def asyncTearDown(self):
        self.redis_patcher.stop()
        self.jira_patcher.stop()
        self.config_patcher.stop()

    async def test_handle_hook_event_routes_jira_created(self):
        event = HookEvent(
            hook_id="h1",
            hook_type=HookType.JIRA_WEBHOOK,
            event_type="jira.created",
            payload={"issue_key": "NAV-1"},
        )
        result = await self.agent.handle_hook_event(event)
        self.assertEqual(result, {"status": "ok"})
        self.agent.handle_jira_ticket_created.assert_awaited_once_with(
            {"issue_key": "NAV-1"}
        )


# ---------------------------------------------------------------------------
# Regression: handle_jira_assignment extracts display_name from reporter dict
# ---------------------------------------------------------------------------
class TestAssignmentHandlerReporterDictRegression(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis_patcher = patch("redis.asyncio.from_url")
        self.redis_patcher.start()
        self.jira_patcher = patch("parrot.bots.jira_specialist.JiraToolkit")
        self.jira_patcher.start()
        self.config_patcher = patch("parrot.bots.jira_specialist.config")
        mock_config = self.config_patcher.start()
        mock_config.get.return_value = "dummy"
        mock_config.getlist.return_value = []

        self.agent = JiraSpecialist()
        self.agent.logger = logging.getLogger("test.jira_assignment_regression")
        self.agent.ask = AsyncMock(return_value=object())
        self.agent._developers = [
            Developer(
                id="35",
                name="Jesus Lara",
                username="jlara@trocglobal.com",
                jira_username="jesuslarag@gmail.com",
                telegram_chat_id=286137732,
                manager_chat_id=286137732,
            )
        ]

    async def asyncTearDown(self):
        self.redis_patcher.stop()
        self.jira_patcher.stop()
        self.config_patcher.stop()

    async def test_assignment_handler_extracts_reporter_display_name(self):
        """After TASK-808, reporter is a dict — handler must use display_name."""
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
            "new_assignee": {
                "email": "jesuslarag@gmail.com",
                "display_name": "Jesus Lara",
            },
        }
        await self.agent.handle_jira_assignment(payload)

        self.agent.ask.assert_called_once()
        called_question = (
            self.agent.ask.call_args.kwargs.get("question")
            or self.agent.ask.call_args.args[0]
        )
        # display_name must appear in the LLM instruction
        self.assertIn("The Reporter", called_question)
        # The raw dict repr must NOT leak
        self.assertNotIn("account_id", called_question)


# ---------------------------------------------------------------------------
# Webhook payload shape test: reporter is a dict with the four keys
# ---------------------------------------------------------------------------
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
                return json.dumps(jira_body).encode()

            async def json(self):
                return jira_body

        resp = await hook._handle_post(FakeRequest())
        self.assertEqual(resp.status, 202)
        self.assertEqual(len(captured), 1)
        reporter = captured[0].payload["reporter"]
        self.assertIsInstance(reporter, dict)
        self.assertEqual(reporter["email"], "rep@example.com")
        self.assertEqual(reporter["display_name"], "The Reporter")
        self.assertEqual(reporter["account_id"], "acc-1")
        self.assertEqual(reporter["name"], "rep")


if __name__ == "__main__":
    unittest.main()
