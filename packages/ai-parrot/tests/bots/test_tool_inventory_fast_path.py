from types import SimpleNamespace

from parrot.bots.base import BaseBot


class _ToolManagerStub:
    def get_tools_summary(self):
        return {
            "count": 2,
            "tools": [
                {
                    "name": "run_scan",
                    "description": "Run a security scan",
                    "parameters_count": 1,
                },
                {
                    "name": "aws_securityhub_get_findings",
                    "description": "Get Security Hub findings",
                    "parameters_count": 2,
                },
            ],
        }


def _bot():
    bot = BaseBot.__new__(BaseBot)
    bot.tool_manager = _ToolManagerStub()
    bot._llm = SimpleNamespace(model="test-model", client_type="test-provider")
    return bot


def test_tool_inventory_request_matches_short_meta_prompts():
    bot = _bot()

    assert bot._is_tool_inventory_request("tools list")
    assert bot._is_tool_inventory_request("list tools")
    assert bot._is_tool_inventory_request("what tools do you have?")


def test_tool_inventory_request_does_not_match_operational_prompts():
    bot = _bot()

    assert not bot._is_tool_inventory_request("run a security scan with the tools")
    assert not bot._is_tool_inventory_request("use aws tools to check findings")


def test_build_tool_inventory_message_uses_registered_tools():
    bot = _bot()

    message = bot._build_tool_inventory_message(
        question="tools list",
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
    )

    assert message.input == "tools list"
    assert message.finish_reason == "tool_inventory_fast_path"
    assert message.model == "test-model"
    assert message.provider == "test-provider"
    assert message.data["count"] == 2
    assert "`run_scan`" in message.response
    assert "`aws_securityhub_get_findings`" in message.response
