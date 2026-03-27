from pathlib import Path

from parrot.integrations.parser import ParsedResponse
from parrot.integrations.slack.wrapper import SlackAgentWrapper
from parrot.integrations.models import IntegrationBotConfig


def test_build_blocks_supports_markdown_code_table_and_images():
    parsed = ParsedResponse(
        text="*hello*",
        code="print('x')",
        code_language="python",
        table_markdown="|A|\n|---|\n|1|",
        images=[Path("https://example.com/img.png"), Path("/tmp/local.png")],
    )

    blocks = SlackAgentWrapper._build_blocks(parsed)

    assert any(b.get("type") == "section" and b["text"]["type"] == "mrkdwn" for b in blocks)
    assert any(b.get("type") == "image" for b in blocks)
    assert any(b.get("type") == "context" for b in blocks)


def test_integration_config_parses_slack_kind():
    cfg = IntegrationBotConfig.from_dict(
        {
            "agents": {
                "sales": {
                    "kind": "slack",
                    "chatbot_id": "sales_bot",
                    "bot_token": "xoxb-123",
                }
            }
        }
    )

    assert "sales" in cfg.agents
    assert cfg.validate() == []
