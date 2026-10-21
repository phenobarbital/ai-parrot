"""A ``/call`` result must survive Telegram's legacy Markdown parser.

``_execute_agent_method`` echoes the called method's return value back into
the chat, and ``_send_parsed_response`` sends it with
``parse_mode="Markdown"`` whenever ``TelegramConfig.use_html`` is false (its
default). Markdown v1 reads the ``_`` in a dict key like ``window_hours`` as
an italic marker, so a report's status dict used to arrive either rejected
("Bad Request: can't parse entities: Can't find end of the entity starting at
byte offset N", on an odd count) or mangled, with ``ticket_count`` showing up
as ``ticketcount``.

These tests pin the two halves of the fix: a dict/list result is rendered as
a code block, and the method name in the prefix is a code span rather than
``*bold*``.
"""

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# The status dict that broke a real run of ``/call report_resolved_tickets``.
REPORT_RESULT = {
    "status": "ok",
    "project": "NAV",
    "jql": 'project = NAV AND status CHANGED TO ("Resolved", "Closed") AFTER -24h ORDER BY updated DESC',
    "window_hours": 24,
    "ticket_count": 5,
    "tickets": ["NAV-10335", "NAV-10344", "NAV-10327", "NAV-10339", "NAV-10285"],
    "announced": 5,
    "messages_sent": 1,
}


def _parse(response):
    """Call the real ``_parse_response``; it touches no wrapper state."""
    from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

    return TelegramAgentWrapper._parse_response(SimpleNamespace(), response)


def _markup_outside_code(text: str) -> dict:
    """Count Markdown v1 markers left outside fences and code spans."""
    bare = re.sub(r"```.*?```", "", text, flags=re.S)
    bare = re.sub(r"`[^`]*`", "", bare)
    return {char: bare.count(char) for char in "_*`[" if bare.count(char)}


class TestDictResultRendering:
    """A dict/list result is data, so it goes in a code block."""

    def test_status_dict_becomes_a_json_code_block(self) -> None:
        parsed = _parse(REPORT_RESULT)

        assert parsed.text == ""
        assert parsed.has_code
        assert parsed.code_language == "json"
        # Readable, and every key keeps its underscore.
        assert '"window_hours": 24' in parsed.code
        assert '"messages_sent": 1' in parsed.code

    def test_rendered_message_leaves_no_loose_markdown(self) -> None:
        parsed = _parse(REPORT_RESULT)
        message = "✅ `report_resolved_tickets` result:\n\n" f"```{parsed.code_language}\n{parsed.code}\n```"

        assert _markup_outside_code(message) == {}

    def test_non_serialisable_values_still_render(self) -> None:
        from datetime import datetime, timezone

        parsed = _parse({"moved_at": datetime(2026, 10, 21, 23, 47, tzinfo=timezone.utc)})

        assert parsed.has_code
        assert "2026-10-21" in parsed.code

    def test_list_result_is_also_fenced(self) -> None:
        parsed = _parse([{"key": "NAV-1"}, {"key": "NAV-2"}])

        assert parsed.has_code
        assert parsed.text == ""

    def test_string_result_stays_prose(self) -> None:
        """A method returning text must not be wrapped in a code block."""
        parsed = _parse("Nothing moved in the last 24h.")

        assert parsed.text == "Nothing moved in the last 24h."
        assert not parsed.has_code


class TestCallPrefix:
    """The method name is a code span, so its underscores survive."""

    @staticmethod
    def _wrapper(use_html: bool, result):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.logger = MagicMock()
        wrapper.config = MagicMock()
        wrapper.config.use_html = use_html
        wrapper.bot = MagicMock(send_chat_action=AsyncMock())
        wrapper.agent = SimpleNamespace(report_resolved_tickets=AsyncMock(return_value=result))
        wrapper._send_parsed_response = AsyncMock()

        async def _typing_indicator(chat_id):
            return None

        wrapper._typing_indicator = _typing_indicator
        return wrapper

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "use_html, expected",
        [
            (False, "✅ `report_resolved_tickets` result:\n\n"),
            (True, "✅ <code>report_resolved_tickets</code> result:\n\n"),
        ],
    )
    async def test_prefix_is_written_in_the_mode_it_is_sent_in(self, use_html: bool, expected: str) -> None:
        wrapper = self._wrapper(use_html, REPORT_RESULT)
        message = MagicMock(chat=MagicMock(id=-4788340010), answer=AsyncMock())

        await wrapper._execute_agent_method(message, "report_resolved_tickets", "")

        prefix = wrapper._send_parsed_response.await_args.kwargs["prefix"]
        assert prefix == expected
        # Never ``*bold*``: Markdown v1 would eat the name's underscores.
        assert "*" not in prefix
