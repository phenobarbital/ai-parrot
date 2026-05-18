"""Shared base class for specialist builders.

A builder is a thin wrapper over a ``BasicAgent`` with:

- a specialist system prompt embedding the YAML schema and conventions
- a curated toolset (introspection + builder-specific deterministic tools)
- a single ``build`` entry point that emits a ``BuilderOutput`` via the
  LLM's structured-output channel

The orchestrator never speaks to ``BasicAgent`` directly — it only calls
``builder.build(request, decision)`` and consumes the typed result.
"""
from __future__ import annotations

import json
import logging
from typing import Any, ClassVar, Dict, List, Optional

from parrot.bots.agent import BasicAgent
from parrot.bots.factory.contracts import (
    AgentDefinition,
    BuilderOutput,
    BuilderType,
    FactoryRequest,
    RouterDecision,
)


COMMON_SCHEMA_NOTES = """\
The YAML AgentDefinition follows this shape (Pydantic: BotConfig):

  name: str               # PascalCase, unique
  class_name: str         # implementing class, default "BasicAgent"
  module: str             # default "parrot.bots.agent"
  enabled: bool           # default true
  description: str        # short purpose
  system_prompt: str|dict # the agent persona / instructions
  model:
    provider: str         # openai | anthropic | google | groq | vertex
    model: str            # provider-specific id
    temperature: float
    max_tokens: int
  tools:
    tools: list[dict]     # standalone @tool function names
    toolkits: list[str]   # ToolkitRegistry names (lower-case)
    mcp_servers: list[dict]
  vector_store:           # only for RAG agents
    provider: pgvector
    table: str
    schema: str
    dimension: int
    embedding_model: str
  tags: list[str]

Toolkits must match names returned by list_available_toolkits. Do not invent
toolkit names. If the user needs an integration with no native toolkit, call
register_openapi_toolkit FIRST and use the returned name."""


class BaseFactoryBuilder:
    """Common machinery for the three specialists."""

    builder_type: ClassVar[BuilderType]
    system_prompt: ClassVar[str]

    def __init__(
        self,
        *,
        llm: Optional[str] = None,
        use_llm: str = "google",
        agent_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.logger = logging.getLogger(f"Parrot.Factory.{self.__class__.__name__}")
        self._llm = llm
        self._use_llm = use_llm
        self._agent_kwargs = agent_kwargs or {}

    # ---- tool wiring --------------------------------------------------------

    def _tools(self) -> List[Any]:
        """Tools available to this specialist. Override to add more."""
        from parrot.bots.factory.tools.introspection import (
            _list_available_toolkits_tool,
            _list_available_tools_tool,
        )

        return [_list_available_toolkits_tool, _list_available_tools_tool]

    def _make_agent(self) -> BasicAgent:
        return BasicAgent(
            name=f"{self.builder_type.value}_builder",
            agent_id=f"factory_{self.builder_type.value}_builder",
            use_llm=self._use_llm,
            llm=self._llm,
            tools=self._tools(),
            system_prompt=self.system_prompt,
            **self._agent_kwargs,
        )

    # ---- prompt rendering ---------------------------------------------------

    def _render_user_prompt(
        self,
        request: FactoryRequest,
        decision: RouterDecision,
    ) -> str:
        return (
            f"User request:\n{request.description}\n\n"
            f"Router reasoning: {decision.reasoning}\n"
            f"Detected integrations: {decision.detected_integrations or 'none'}\n\n"
            "Produce a BuilderOutput. The 'definition' field MUST be a valid "
            "AgentDefinition with all required keys filled in. Use the tools "
            "to discover capabilities; do not invent toolkit names."
        )

    # ---- main entry point ---------------------------------------------------

    async def build(
        self,
        request: FactoryRequest,
        decision: RouterDecision,
    ) -> BuilderOutput:
        agent = self._make_agent()
        prompt = self._render_user_prompt(request, decision)

        self.logger.info("Building %s agent for: %s",
                         self.builder_type.value, request.description[:80])

        try:
            result = await agent.invoke(prompt, response_model=BuilderOutput)
            return self._coerce_output(result)
        finally:
            await agent.shutdown()

    # ---- result normalisation ----------------------------------------------

    def _coerce_output(self, result: Any) -> BuilderOutput:
        """Normalise ``BasicAgent.ask`` return shape to a ``BuilderOutput``.

        ``ask`` returns either a ``ChatResponse``-ish object whose ``output``
        is the parsed Pydantic model, or the model itself depending on the
        client. Accept both, plus the JSON-string fallback when the client
        cannot natively bind structured output.
        """
        candidate = getattr(result, "output", result)
        if isinstance(candidate, BuilderOutput):
            return candidate
        if isinstance(candidate, AgentDefinition):
            return BuilderOutput(
                builder=self.builder_type, definition=candidate, provisioning=[]
            )
        if isinstance(candidate, dict):
            if "definition" in candidate:
                return BuilderOutput(**candidate)
            return BuilderOutput(
                builder=self.builder_type,
                definition=AgentDefinition(**candidate),
            )
        if isinstance(candidate, str):
            data = json.loads(candidate)
            if "definition" in data:
                return BuilderOutput(**data)
            return BuilderOutput(
                builder=self.builder_type,
                definition=AgentDefinition(**data),
            )
        raise TypeError(
            f"Specialist {self.builder_type.value} returned unsupported "
            f"output type: {type(result).__name__}"
        )
