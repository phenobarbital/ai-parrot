"""Tests for the Jira → Telegram assignment intake flow on JiraSpecialist."""
import unittest
from unittest.mock import AsyncMock, patch

from parrot.bots.jira_specialist import Developer, JiraSpecialist


class TestJiraAssignmentHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Isolate external dependencies the same way test_jira_callbacks.py does.
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

    async def test_resolve_developer_by_email(self):
        dev = self.agent._resolve_developer_from_assignee(
            {"email": "jesuslarag@gmail.com", "display_name": "Jesus Lara"}
        )
        self.assertIsNotNone(dev)
        self.assertEqual(dev.id, "35")

    async def test_resolve_developer_by_display_name(self):
        dev = self.agent._resolve_developer_from_assignee(
            {"display_name": "Jesus Lara"}
        )
        self.assertIsNotNone(dev)

    async def test_resolve_developer_unknown_returns_none(self):
        dev = self.agent._resolve_developer_from_assignee(
            {"email": "stranger@example.com"}
        )
        self.assertIsNone(dev)

    async def test_handle_assignment_skips_when_assignee_unknown(self):
        result = await self.agent.handle_jira_assignment(
            {
                "issue_key": "NAV-123",
                "summary": "New ticket",
                "new_assignee": {"email": "stranger@example.com"},
            }
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["issue_key"], "NAV-123")
        self.agent.ask.assert_not_called()

    async def test_handle_assignment_skips_without_issue_key(self):
        result = await self.agent.handle_jira_assignment({})
        self.assertEqual(result["status"], "skipped")
        self.agent.ask.assert_not_called()

    async def test_handle_assignment_asks_developer(self):
        result = await self.agent.handle_jira_assignment(
            {
                "issue_key": "NAV-456",
                "summary": "Fix login bug",
                "priority": "High",
                "status": "To Do",
                "reporter": "PM",
                "new_assignee": {
                    "email": "jesuslarag@gmail.com",
                    "display_name": "Jesus Lara",
                },
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["issue_key"], "NAV-456")
        self.assertEqual(result["developer_id"], "35")

        self.agent.ask.assert_called_once()
        call = self.agent.ask.call_args
        question = call.kwargs["question"]
        self.assertIn("NAV-456", question)
        self.assertIn("Jesus Lara", question)
        self.assertIn("due_date", question)
        self.assertIn("estimate", question)
        self.assertIn("decision", question)
        self.assertEqual(call.kwargs["user_id"], "35")


class TestHandleHookEventRouting(unittest.IsolatedAsyncioTestCase):
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
        self.agent.handle_jira_assignment = AsyncMock(
            return_value={"status": "ok"}
        )
        self.agent.handle_ready_for_test = AsyncMock(
            return_value={"status": "ok", "channel_id": "-100123"}
        )

    async def asyncTearDown(self):
        self.redis_patcher.stop()
        self.jira_patcher.stop()
        self.config_patcher.stop()

    async def test_assigned_event_routes_to_handler(self):
        from parrot.core.hooks.models import HookEvent, HookType

        event = HookEvent(
            hook_id="h1",
            hook_type=HookType.JIRA_WEBHOOK,
            event_type="jira.assigned",
            payload={"issue_key": "NAV-1"},
        )
        result = await self.agent.handle_hook_event(event)
        self.agent.handle_jira_assignment.assert_awaited_once_with(
            {"issue_key": "NAV-1"}
        )
        self.assertEqual(result, {"status": "ok"})

    async def test_ready_for_test_event_routes_to_handler(self):
        from parrot.core.hooks.models import HookEvent, HookType

        event = HookEvent(
            hook_id="h1",
            hook_type=HookType.JIRA_WEBHOOK,
            event_type="jira.ready_for_test",
            payload={"issue_key": "NAV-1"},
        )
        result = await self.agent.handle_hook_event(event)
        self.agent.handle_ready_for_test.assert_awaited_once_with(
            {"issue_key": "NAV-1"}
        )
        self.assertEqual(result["status"], "ok")

    async def test_other_events_are_ignored(self):
        from parrot.core.hooks.models import HookEvent, HookType

        event = HookEvent(
            hook_id="h1",
            hook_type=HookType.JIRA_WEBHOOK,
            event_type="jira.closed",
            payload={"issue_key": "NAV-1"},
        )
        result = await self.agent.handle_hook_event(event)
        self.assertIsNone(result)
        self.agent.handle_jira_assignment.assert_not_awaited()
        self.agent.handle_ready_for_test.assert_not_awaited()


class TestHandleReadyForTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis_patcher = patch("redis.asyncio.from_url")
        self.redis_patcher.start()
        self.jira_patcher = patch("parrot.bots.jira_specialist.JiraToolkit")
        self.jira_patcher.start()
        self.config_patcher = patch("parrot.bots.jira_specialist.config")
        self.mock_config = self.config_patcher.start()
        self.mock_config.getlist.return_value = []

        def _config_get(key, *args, **kwargs):
            if key == "JIRA_TEST_WEBHOOK_CHANNEL":
                return "-1001234567890"
            return "dummy"

        self.mock_config.get.side_effect = _config_get

        self.agent = JiraSpecialist()
        self.mock_wrapper = AsyncMock()
        self.mock_wrapper.bot = AsyncMock()
        self.agent.set_wrapper(self.mock_wrapper)

    async def asyncTearDown(self):
        self.redis_patcher.stop()
        self.jira_patcher.stop()
        self.config_patcher.stop()

    async def test_skips_when_missing_issue_key(self):
        result = await self.agent.handle_ready_for_test({})
        self.assertEqual(result["status"], "skipped")
        self.mock_wrapper.bot.send_message.assert_not_called()

    async def test_skips_when_channel_not_configured(self):
        self.mock_config.get.side_effect = lambda *a, **kw: None
        result = await self.agent.handle_ready_for_test(
            {"issue_key": "NAV-1"}
        )
        self.assertEqual(result["status"], "skipped")
        self.assertIn("JIRA_TEST_WEBHOOK_CHANNEL", result["reason"])
        self.mock_wrapper.bot.send_message.assert_not_called()

    async def test_errors_when_wrapper_missing(self):
        self.agent._wrapper = None
        result = await self.agent.handle_ready_for_test(
            {"issue_key": "NAV-1"}
        )
        self.assertEqual(result["status"], "error")

    async def test_sends_notification_to_channel(self):
        payload = {
            "issue_key": "NAV-789",
            "summary": "Fix login flow",
            "priority": "High",
            "assignee": {"display_name": "Jesus Lara"},
        }
        result = await self.agent.handle_ready_for_test(payload)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["channel_id"], "-1001234567890")

        self.mock_wrapper.bot.send_message.assert_awaited_once()
        kwargs = self.mock_wrapper.bot.send_message.call_args.kwargs
        self.assertEqual(kwargs["chat_id"], "-1001234567890")
        self.assertIn("NAV-789", kwargs["text"])
        self.assertIn("Ready For Test", kwargs["text"])
        self.assertIn("Jesus Lara", kwargs["text"])
        self.assertIn("testing", kwargs["text"].lower())


if __name__ == "__main__":
    unittest.main()
