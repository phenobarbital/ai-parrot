"""Slack output renderer.

Lightweight renderer that extracts plain text for Slack delivery.
Slack-specific mrkdwn formatting is handled downstream by the
SlackAgentWrapper._build_blocks() method via the ParsedResponse parser.
"""
from typing import Any, Tuple
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode


SLACK_SYSTEM_PROMPT = (
    "SLACK OUTPUT MODE: Format your response as clean, concise text suitable "
    "for Slack messaging. You may use markdown bold (**text**), italic (*text*), "
    "inline code (`code`), and fenced code blocks (```lang\ncode\n```) — these "
    "will be converted to Slack mrkdwn automatically. "
    "Avoid HTML or complex formatting. Keep responses brief and conversational. "
    "Use bullet lists where appropriate."
)


@register_renderer(OutputMode.SLACK, system_prompt=SLACK_SYSTEM_PROMPT)
class SlackRenderer(BaseRenderer):
    """Renderer for Slack output — returns plain text / markdown."""

    def _extract_content(self, response: Any) -> str:
        """Extract text content from the agent response."""
        output = getattr(response, 'output', None)
        if output is not None:
            if hasattr(output, 'explanation') and output.explanation:
                return str(output.explanation)
            if hasattr(output, 'response') and output.response:
                return str(output.response)

        if hasattr(response, 'response') and response.response:
            return str(response.response)

        if output is not None:
            return output if isinstance(output, str) else str(output)

        return str(response)

    async def render(
        self,
        response: Any,
        environment: str = 'default',
        export_format: str = 'html',
        include_code: bool = False,
        **kwargs,
    ) -> Tuple[str, Any]:
        """Render response as plain text for Slack."""
        content = self._extract_content(response)
        return content, content
