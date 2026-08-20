"""Shared fixtures for the authoring tests.

No test in this package talks to a real model. ``FakePlannerClient`` replays
a scripted list of responses, which lets the suite assert on the *prompts*
the loop builds — in particular that a per-node prompt does not carry the
other nodes' definitions, the property the node-by-node design exists to
provide.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

import pytest

from parrot.bots.flows.authoring.catalog import (
    AgentEntry,
    ComponentCatalog,
    NodeTypeEntry,
    ToolEntry,
)


class _Response:
    """Minimal stand-in for an ``AIMessage``."""

    def __init__(self, output: str) -> None:
        self.output = output


class FakePlannerClient:
    """Replays scripted responses and records every prompt it was given.

    Attributes:
        prompts: Every prompt received, in call order.
        model: Present because the author passes ``model=`` through.
    """

    def __init__(self, responses: Sequence[Any]) -> None:
        """Bind the script.

        Args:
            responses: Each entry is returned for one call, in order. A
                non-string is JSON-encoded; a ``BaseException`` is raised.
        """
        self._responses: List[Any] = list(responses)
        self.prompts: List[str] = []
        self.model = "fake:model"

    async def __aenter__(self) -> "FakePlannerClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def ask(self, prompt: str, **kwargs: Any) -> _Response:
        """Return the next scripted response.

        Args:
            prompt: The prompt, recorded for assertions.
            **kwargs: Ignored.

        Returns:
            The next response.

        Raises:
            AssertionError: If the script is exhausted — an unexpected extra
                call is a bug worth failing on, not something to paper over.
            BaseException: If the scripted entry is an exception.
        """
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError(
                f"FakePlannerClient ran out of scripted responses "
                f"(call #{len(self.prompts)})"
            )
        nxt = self._responses.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return _Response(nxt if isinstance(nxt, str) else json.dumps(nxt))


@pytest.fixture
def catalog() -> ComponentCatalog:
    """A small, fixed catalog — independent of what is installed."""
    return ComponentCatalog(
        node_types=[
            NodeTypeEntry(
                type="agent",
                class_name="AgentNode",
                module="parrot.bots.flows.core.node",
                summary="Wraps a registered agent.",
                requires_agent_ref=True,
                engines=["crew", "flow"],
            ),
            NodeTypeEntry(
                type="tool",
                class_name="ToolNode",
                module="parrot.bots.flows.crew.tool_node",
                summary="Executes a tool directly.",
                engines=["crew", "flow"],
            ),
            NodeTypeEntry(
                type="decision",
                class_name="DecisionNode",
                module="parrot.bots.flows.flow.flow",
                summary="Multi-agent voting.",
                config_schema={
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string"},
                        "decision_type": {"type": "string"},
                    },
                    "required": ["mode", "decision_type"],
                },
                engines=["flow"],
            ),
            NodeTypeEntry(
                type="synthesis",
                class_name="SynthesisNode",
                module="parrot.bots.flows.flow.flow",
                summary="Synthesises results.",
                engines=["flow"],
            ),
            NodeTypeEntry(
                type="start",
                class_name="StartNode",
                module="parrot.bots.flows.core.node",
                engines=["flow"],
            ),
            NodeTypeEntry(
                type="end",
                class_name="EndNode",
                module="parrot.bots.flows.core.node",
                engines=["flow"],
            ),
        ],
        agents=[
            AgentEntry(name="researcher_agent", class_name="BasicAgent"),
            AgentEntry(name="writer_agent", class_name="BasicAgent"),
        ],
        tools=[
            ToolEntry(name="google_search", description="Search the web."),
            ToolEntry(name="web_scraping", description="Fetch a page."),
            ToolEntry(name="rest_api", description="Call an HTTP endpoint."),
        ],
    )


@pytest.fixture
def crew_catalog(catalog: ComponentCatalog) -> ComponentCatalog:
    """The same catalog with no registered agents, forcing engine='crew'."""
    return catalog.model_copy(update={"agents": []})
