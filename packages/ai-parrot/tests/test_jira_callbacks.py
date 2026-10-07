import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio
from datetime import datetime

# Adjust import path if needed, assuming running from project root
from parrot.bots.jira_specialist import JiraSpecialist, Developer, CallbackResult, CallbackContext, DailyStandupConfig


class TestJiraSpecialistCallbacks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Patch Redis
        self.redis_patcher = patch("redis.asyncio.from_url")
        self.mock_redis = self.redis_patcher.start()
        self.mock_redis_instance = AsyncMock()
        self.mock_redis.return_value = self.mock_redis_instance

        # Patch JiraToolkit
        self.jira_patcher = patch("parrot.bots.jira_specialist.JiraToolkit")
        self.mock_jira = self.jira_patcher.start()

        # Patch config to avoid real file loads or missing env vars
        self.config_patcher = patch("parrot.bots.jira_specialist.config")
        self.mock_config = self.config_patcher.start()
        self.mock_config.get.return_value = "dummy"

        self.agent = JiraSpecialist()
        # Mock wrapper
        self.mock_wrapper = AsyncMock()
        self.agent.set_wrapper(self.mock_wrapper)

        # Mock ask method to simulate tool execution
        self.agent.ask = AsyncMock()

    async def asyncTearDown(self):
        self.redis_patcher.stop()
        self.jira_patcher.stop()
        self.config_patcher.stop()

    async def test_on_ticket_selected(self):
        # Prepare context
        ctx = CallbackContext(
            prefix="tsel",
            payload={"t": "NAV-123", "d": "dev1"},
            chat_id=100,
            user_id=200,
            message_id=300,
            first_name="Test User",
        )

        # Execute
        result = await self.agent.on_ticket_selected(ctx)

        # Verify result
        self.assertIsInstance(result, CallbackResult)
        self.assertIn("NAV-123", result.answer_text)
        self.assertIn("In Progress", result.answer_text)
        self.assertTrue(result.remove_keyboard)

        # Verify Jira transition call (via self.ask)
        self.agent.ask.assert_called()
        call_args = self.agent.ask.call_args[1]
        self.assertIn("jira_transition_issue", call_args["question"])
        self.assertIn("NAV-123", call_args["question"])

        # Verify Redis update
        self.mock_redis_instance.set.assert_called()
        key = self.mock_redis_instance.set.call_args[0][0]
        self.assertIn("standup:responded", key)
        self.assertIn("dev1", key)

    async def test_on_ticket_skipped(self):
        ctx = CallbackContext(
            prefix="tskp", payload={"d": "dev1"}, chat_id=100, user_id=200, message_id=300, first_name="Test User"
        )

        result = await self.agent.on_ticket_skipped(ctx)

        self.assertIsInstance(result, CallbackResult)
        self.assertIn("Got it", result.answer_text)  # FEAT-638: unset language renders English
        self.assertTrue(result.remove_keyboard)

        # Verify Redis update
        self.mock_redis_instance.set.assert_called()

    def _ctx(self, prefix, payload):
        return CallbackContext(
            prefix=prefix,
            payload=payload,
            chat_id=100,
            user_id=200,
            message_id=300,
            first_name="Test User",
        )

    async def test_on_ticket_skipped_spanish(self):
        agent = JiraSpecialist(language="es")
        agent.set_wrapper(self.mock_wrapper)

        result = await agent.on_ticket_skipped(self._ctx("tskp", {"d": "dev1"}))

        self.assertIn("Entendido", result.answer_text)

    async def test_on_ticket_selected_spanish_keeps_status(self):
        agent = JiraSpecialist(language="es")
        agent.set_wrapper(self.mock_wrapper)
        agent.ask = AsyncMock()

        result = await agent.on_ticket_selected(self._ctx("tsel", {"t": "NAV-123", "d": "dev1"}))

        self.assertIn("NAV-123", result.answer_text)
        self.assertIn("In Progress", result.answer_text)
        self.assertIn("ha sido marcado como", result.edit_message)

    async def test_escalation_messages_follow_language(self):
        agent = JiraSpecialist(language="es")
        agent.set_wrapper(self.mock_wrapper)
        agent._developers = [
            Developer(
                id="d1",
                name="Ana",
                username="ana",
                jira_username="ana@x",
                telegram_chat_id=1,
                manager_chat_id=2,
            )
        ]
        self.mock_redis_instance.exists = AsyncMock(side_effect=lambda key: key.startswith("standup:dispatched"))

        await agent.escalate_non_responders()

        self.assertEqual(
            self.mock_wrapper.send_interactive_message.call_args.kwargs["text"],
            "👋 *Ana*, aún no has seleccionado tu ticket para hoy.\n\n¿Necesitas ayuda con la priorización?",
        )
        self.assertIn("Escalación Daily Standup", self.mock_wrapper.bot.send_message.call_args.kwargs["text"])


if __name__ == "__main__":
    unittest.main()
