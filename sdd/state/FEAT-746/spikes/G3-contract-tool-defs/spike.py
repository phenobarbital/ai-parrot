"""G3 — one Squawk contract, four provider tool formats (FEAT-746)."""

from __future__ import annotations

import asyncio
import copy
import importlib
import json
import os
import sys
from collections.abc import Iterator
from typing import Any

from parrot.clients.base import AbstractClient
from parrot.interagent import MediaType, PolicyAnnotations, ReturnsSpec, SquawkCapability, compile_capability
from parrot.tools.manager import ToolFormat, ToolManager

FORMATS = (ToolFormat.OPENAI, ToolFormat.ANTHROPIC, ToolFormat.GOOGLE, ToolFormat.GROQ)
_PROVIDER_CLIENTS = (
    ("openai", "parrot.clients.openai", "OpenAIClient"),
    ("anthropic", "parrot.clients.anthropic", "AnthropicClient"),
    ("google", "parrot.clients.google", "GoogleGenAIClient"),
    ("groq", "parrot.clients.groq", "GroqClient"),
)
_GROQ_UNSUPPORTED = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
}


def hr_capabilities() -> list[SquawkCapability]:
    """Return the spec §4 HR fixture with artifact, inline, and LLM-backed capabilities."""
    return [
        SquawkCapability(
            cap_id="hr.reports.headcount_by_dept",
            category="hr.reports",
            description="Headcount grouped by department.",
            input_schema={
                "type": "object",
                "properties": {"as_of": {"type": "string", "format": "date"}},
                "required": [],
            },
            returns=ReturnsSpec(kind="artifact", media_type=MediaType.ARROW),
            backing="deterministic",
            policy=PolicyAnnotations(data_class="hr", aggregation_min=5),
        ),
        SquawkCapability(
            cap_id="hr.reports.manager_of",
            category="hr.reports",
            description="Manager of an employee id.",
            input_schema={
                "type": "object",
                "properties": {"employee_id": {"type": "string"}},
                "required": ["employee_id"],
            },
            returns=ReturnsSpec(
                kind="inline",
                schema={"type": "object", "properties": {"manager_id": {"type": "string"}}},
            ),
            backing="deterministic",
            policy=PolicyAnnotations(data_class="hr"),
        ),
        SquawkCapability(
            cap_id="hr.people.lookup",
            category="hr.people",
            description="Free-text lookup of a person (LLM-backed, structured output).",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            returns=ReturnsSpec(
                kind="inline",
                schema={"type": "object", "properties": {"matches": {"type": "array"}}},
            ),
            backing="llm_backed",
            policy=PolicyAnnotations(data_class="pii", token_budget=2000),
        ),
    ]


async def _noop(**kwargs: Any) -> dict[str, Any]:
    """Return invocation arguments without an external side effect."""
    return {"ok": True, "args": kwargs}


def tool_manager() -> ToolManager:
    """Build a fresh manager containing the three compiled HR capabilities."""
    manager = ToolManager()
    for capability in hr_capabilities():
        manager.register_tool(tool=compile_capability(capability, function=_noop))
    return manager


def schemas_per_format() -> dict[str, list[dict[str, Any]]]:
    """Return provider-cleaned schemas without the manager-only tool reference."""
    manager = tool_manager()
    result: dict[str, list[dict[str, Any]]] = {}
    for tool_format in FORMATS:
        # The adapter shallow-copies the outer schema but mutates nested
        # parameters while cleaning. Snapshot each provider response before
        # preparing the next format so a later adapter cannot alter evidence
        # already recorded for an earlier provider.
        schemas = copy.deepcopy(manager.get_tool_schemas(tool_format))
        for schema in schemas:
            schema.pop("_tool_instance", None)
        result[tool_format.value] = schemas
    return result


def _walk(value: Any, path: str = "$") -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield every dictionary in a JSON-schema-shaped value with its path."""
    if isinstance(value, dict):
        yield path, value
        for key, nested in value.items():
            yield from _walk(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _walk(nested, f"{path}[{index}]")


def validate(fmt: str, schema: dict[str, Any]) -> list[str]:
    """Return reject-only violations for a provider-cleaned tool schema.

    The checks mirror the current ``ToolSchemaAdapter`` output: Google removes
    unsupported metadata, Groq fixes object schemas to closed objects and
    removes unsupported constraints, and OpenAI/Anthropic close objects while
    requiring all declared properties.
    """
    problems: list[str] = []
    if not isinstance(schema.get("name"), str) or not schema["name"]:
        problems.append("name must be a non-empty string")
    if not isinstance(schema.get("description"), str):
        problems.append("description must be a string")
    parameters = schema.get("parameters")
    if not isinstance(parameters, dict):
        return [*problems, "parameters must be an object"]

    for path, node in _walk(parameters):
        if node.get("type") != "object":
            continue
        properties = node.get("properties", {})
        required = node.get("required", [])
        if not isinstance(properties, dict):
            problems.append(f"{path}.properties must be an object")
            continue
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            problems.append(f"{path}.required must be a list of strings")
        elif not set(required).issubset(properties):
            problems.append(f"{path}.required must be a subset of properties")

        if fmt in {ToolFormat.OPENAI.value, ToolFormat.ANTHROPIC.value}:
            if node.get("additionalProperties") is not False:
                problems.append(f"{path}.additionalProperties must be false")
            if set(required) != set(properties):
                problems.append(f"{path}.required must include every property")
        elif fmt == ToolFormat.GROQ.value:
            if node.get("additionalProperties") is not False:
                problems.append(f"{path}.additionalProperties must be false")

    if fmt == ToolFormat.GOOGLE.value:
        for path, node in _walk(parameters):
            for forbidden in ("$ref", "anyOf", "additionalProperties", "title"):
                if forbidden in node:
                    problems.append(f"{path} contains unsupported {forbidden}")
    elif fmt == ToolFormat.GROQ.value:
        for path, node in _walk(parameters):
            for forbidden in _GROQ_UNSUPPORTED:
                if forbidden in node:
                    problems.append(f"{path} contains unsupported {forbidden}")
    return problems


def _configured_clients(manager: ToolManager) -> list[tuple[str, AbstractClient]]:
    """Instantiate installed target providers that expose server credentials."""
    clients: list[tuple[str, AbstractClient]] = []
    for label, module_name, class_name in _PROVIDER_CLIENTS:
        try:
            client_class = getattr(importlib.import_module(module_name), class_name)
        except ImportError:
            continue
        if client_class.has_server_credentials():
            clients.append((label, client_class(tool_manager=manager)))
    return clients


async def real_call_results() -> list[dict[str, Any]]:
    """Make one tool-forcing call per configured target provider."""
    manager = tool_manager()
    results: list[dict[str, Any]] = []
    configured = dict(_configured_clients(manager))
    for label, _module_name, _class_name in _PROVIDER_CLIENTS:
        client = configured.get(label)
        if client is None:
            results.append({"provider": label, "status": "skipped", "reason": "not configured"})
            continue
        try:
            # Clients are lazy: the provider SDK handle only exists inside the async context.
            async with client:
                schemas = manager.get_tool_schemas(client._resolve_tool_format())
                message = await client.ask(
                    prompt="Use hr__reports__manager_of for employee_id E-001. Call the tool.",
                    model=client.model,
                    tools=schemas,
                    use_tools=True,
                )
        except Exception as exc:  # noqa: BLE001 — one provider's failure is a recorded verdict, not a crash
            results.append({"provider": label, "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]})
            continue
        calls = list(getattr(message, "tool_calls", None) or [])
        valid = bool(calls) and all(
            getattr(call, "name", None) in manager.list_tools()
            and isinstance(getattr(call, "arguments", None), dict)
            and "_error" not in getattr(call, "arguments", {})
            for call in calls
        )
        results.append({"provider": label, "status": "passed" if valid else "failed", "tool_calls": len(calls)})
    return results


def main() -> int:
    """Print offline schema results and, when opted in, live provider results."""
    offline = {
        fmt: [
            {"name": schema.get("name") or schema.get("function", {}).get("name"), "problems": validate(fmt, schema)}
            for schema in schemas
        ]
        for fmt, schemas in schemas_per_format().items()
    }
    report: dict[str, Any] = {"offline": offline}
    if os.environ.get("PARROT_TEST_REAL_LLM") == "1":
        report["real_calls"] = asyncio.run(real_call_results())
    else:
        report["real_calls"] = "skipped: set PARROT_TEST_REAL_LLM=1"
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
