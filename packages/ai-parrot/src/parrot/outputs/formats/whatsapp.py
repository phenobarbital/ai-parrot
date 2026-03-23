"""WhatsApp output renderer.

Lightweight renderer that extracts plain text for WhatsApp delivery.
WhatsApp-specific formatting (bold, italic, monospace) is handled
downstream by `convert_markdown_to_whatsapp` in the bridge wrapper.
"""
from typing import Any, Tuple
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode


WHATSAPP_SYSTEM_PROMPT = (
    "WHATSAPP OUTPUT MODE: Format your response as clean, concise text "
    "suitable for WhatsApp messaging. Use short paragraphs. "
    "You may use markdown bold (**text**), italic (*text*), "
    "and code blocks (```code```) which will be converted to WhatsApp "
    "formatting. Avoid tables, HTML, or complex formatting. "
    "Keep responses brief and conversational."
)


@register_renderer(OutputMode.WHATSAPP, system_prompt=WHATSAPP_SYSTEM_PROMPT)
class WhatsAppRenderer(BaseRenderer):
    """Renderer for WhatsApp output — returns plain text."""

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
        """Render response as plain text for WhatsApp."""
        content = self._extract_content(response)
        return content, content
