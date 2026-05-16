"""Specialist that designs tool-using agents backed by toolkits / MCP servers."""
from __future__ import annotations

from typing import Any, ClassVar, List

from parrot.bots.factory.builders.base import COMMON_SCHEMA_NOTES, BaseFactoryBuilder
from parrot.bots.factory.contracts import BuilderType


_TOOL_AGENT_PROMPT = f"""\
You are ToolAgentBuilderAgent, a specialist that designs tool-using agents
inside ai-parrot.

Your single responsibility is to produce a BuilderOutput whose `definition`
configures a BasicAgent with the right mix of toolkits and standalone
tools to satisfy the user's request.

Decision flow:
1. Call `list_available_toolkits` and `list_available_tools` to see what is
   already shipped. ONLY reference these names in the definition.
2. If the user needs an integration with NO matching toolkit (LinkedIn,
   Notion, custom REST API, …), call `register_openapi_toolkit` with a
   public OpenAPI spec URL. Use the returned `toolkit_name` in
   `definition.toolkits`. Add a ProvisioningRecord(kind="openapi_toolkit").
3. If the agent will write to / publish on an external service, set the
   definition tag `requires_approval` and mention in `system_prompt` that
   destructive actions need explicit user confirmation. Never silently
   enable autonomous posting/sending.
4. Pick `class_name = "BasicAgent"` and `module = "parrot.bots.agent"`
   unless the user explicitly wants another bot class.
5. Default model: provider=`google`, model=`gemini-2.5-flash`,
   temperature=0.4, max_tokens=4096 — override only if the user said so.
6. `vector_store` stays null. If the user asked for retrieval, switch to
   RAGBuilderAgent territory (note it and refuse).

{COMMON_SCHEMA_NOTES}
"""


class ToolAgentBuilderAgent(BaseFactoryBuilder):
    """Specialist that produces tool-using agent definitions."""

    builder_type: ClassVar[BuilderType] = BuilderType.TOOL_AGENT
    system_prompt: ClassVar[str] = _TOOL_AGENT_PROMPT

    def _tools(self) -> List[Any]:
        from parrot.bots.factory.tools.openapi_register import (
            _register_openapi_toolkit_tool,
        )

        return [*super()._tools(), _register_openapi_toolkit_tool]
