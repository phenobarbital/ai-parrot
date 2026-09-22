"""Shared fakes for FEAT-590 delegate tests (mirror test_node.py's fakes)."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import BaseModel

from parrot.bots.flows.plan.delegate.protocol import ToolCallProposal, ToolSpec


class FakeTool:
    """AbstractTool-shaped fake with schema and delegate metadata."""

    def __init__(
        self,
        name: str,
        args_schema: type[BaseModel],
        *,
        delegate_safe: bool = True,
        delegate_description: Optional[str] = None,
    ) -> None:
        self.name = name
        self.args_schema = args_schema
        self.description = f"{name} tool"
        self.delegate_safe = delegate_safe
        self.delegate_description = delegate_description

    def get_schema(self) -> Dict[str, Any]:
        """Return the tool registration schema."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.args_schema.model_json_schema(),
        }

    def validate_args(self, **kwargs: Any) -> BaseModel:
        """Validate proposed arguments through the supplied model."""
        return self.args_schema(**kwargs)


class FakeToolManager:
    """get_tool/list_tools/execute_tool; records dispatches like test_node._ToolManager."""

    def __init__(self, tools: Sequence[FakeTool], payloads: Dict[str, Any]) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._payloads = payloads
        self.calls: List[tuple[str, Dict[str, Any]]] = []

    def get_tool(self, tool_name: str) -> Optional[FakeTool]:
        """Return a registered fake tool, if any."""
        return self._tools.get(tool_name)

    def list_tools(self) -> List[str]:
        """Return registered tool names in stable order."""
        return sorted(self._tools)

    async def execute_tool(
        self, tool_name: str, parameters: Dict[str, Any], permission_context: Optional[Any] = None
    ) -> Any:
        """Record and execute the scripted payload."""
        self.calls.append((tool_name, dict(parameters)))
        await asyncio.sleep(0)
        payload = self._payloads[tool_name]
        return payload(parameters) if callable(payload) else payload


class FakeDelegate:
    """Scripted ToolCallDelegate: returns queued proposals (or raises queued exceptions)."""

    def __init__(
        self,
        script: Sequence[Any],
        *,
        backend_name: str = "fake",
        max_tools: int = 5,
        max_input_chars: int = 1000,
    ) -> None:
        self.backend_name = backend_name
        self.max_tools = max_tools
        self.max_input_chars = max_input_chars
        self._script = list(script)
        self.seen: List[tuple[str, List[str], Dict[str, str]]] = []
        self.closed = False

    async def propose_call(
        self, instruction: str, tools: Sequence[ToolSpec], facts: Optional[Mapping[str, str]] = None
    ) -> ToolCallProposal:
        """Return the next proposal or produce its scripted failure."""
        self.seen.append((instruction, [tool.name for tool in tools], dict(facts or {})))
        outcome = self._script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return outcome(instruction)
        return outcome

    async def extract(self, text: str, schema: Any) -> Optional[Dict[str, Any]]:
        """Return no extraction for the generic fake."""
        return None

    async def aclose(self) -> None:
        """Mark this fake delegate closed."""
        self.closed = True
