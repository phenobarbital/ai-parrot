"""Agent metadata as MCP resources (FEAT-477, Module 2, OQ8).

Publishes exactly **three** read-only MCP resources per exposed agent:

- an **identity card** — ``name``, ``role``, ``goal``, ``capabilities``,
  ``description`` (the same fields A2A's ``AgentCard`` already publishes,
  ``a2a/server.py:334``)
- a **tool catalog** — a browsable manifest of the tools *this principal*
  may call, filtered by the same policy as ``tools/list``
- **KB descriptors** — which knowledge bases the agent consults
  (``AbstractBot.knowledge_bases``, ``bots/abstract.py:554``)

**OQ8 — hard exclusion (merge blocker).** The agent's system prompt,
``backstory`` and ``rationale`` are never served here — not policy-gated,
excluded outright. Each resource is built from an explicit **allowlist**
of fields, never a denylist, so a future agent attribute cannot leak in by
default. Publishing guardrail wording hands an attacker the bypass design.
"""

import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from parrot.mcp.resources import MCPResource

logger = logging.getLogger("Parrot.MCP.AgentResources")

#: Policy filter hook: `(agent_name, tool_name) -> bool` (sync or async),
#: `True` meaning the calling principal may see/call the tool. Same
#: decision path as `tools/list`. TASK-2605 supplies the real PBAC-backed
#: implementation; `None` means "everything visible" (pre-guard default).
ToolPolicyFilter = Callable[[str, str], "bool | Awaitable[bool]"]


def _identity_card(agent_name: str, agent: Any) -> dict[str, Any]:
    """Build the identity-card payload for `agent` (allowlist only).

    Args:
        agent_name: Configured agent name (fallback if `agent.name` is unset).
        agent: The agent instance to introspect.

    Returns:
        A dict with exactly `name`, `role`, `goal`, `capabilities`,
        `description` — never any other agent attribute.
    """
    return {
        "name": getattr(agent, "name", None) or agent_name,
        "role": getattr(agent, "role", None),
        "goal": getattr(agent, "goal", None),
        "capabilities": list(getattr(agent, "capabilities", None) or []),
        "description": getattr(agent, "description", None),
    }


async def _resolve_filter(policy_filter: ToolPolicyFilter | None, agent_name: str, tool_name: str) -> bool:
    """Evaluate `policy_filter` for one tool, awaiting it if needed.

    Args:
        policy_filter: The filter hook, or `None` (everything visible).
        agent_name: Configured agent name.
        tool_name: Candidate tool name.

    Returns:
        Whether the calling principal may see `tool_name`.
    """
    if policy_filter is None:
        return True
    result = policy_filter(agent_name, tool_name)
    if inspect.isawaitable(result):
        return bool(await result)
    return bool(result)


async def _tool_catalog(
    agent_name: str,
    agent: Any,
    exposure_names: list[str],
    policy_filter: ToolPolicyFilter | None,
) -> dict[str, Any]:
    """Build the caller-visible tool catalog.

    Args:
        agent_name: Configured agent name.
        agent: The agent instance to introspect.
        exposure_names: Names already known to be in the agent's MCP
            exposure set (TASK-2600's `build_exposure_set`).
        policy_filter: Optional `(agent_name, tool_name) -> bool` policy
            hook — same decision path as `tools/list` (TASK-2605).

    Returns:
        `{"tools": [...]}`, restricted to names `policy_filter` allows.
    """
    tool_manager = getattr(agent, "tool_manager", None)
    own_names = list(tool_manager.list_tools()) if tool_manager is not None else []
    # De-duplicate while preserving order (exposure set first).
    all_names = list(dict.fromkeys([*exposure_names, *own_names]))
    visible = [tool_name for tool_name in all_names if await _resolve_filter(policy_filter, agent_name, tool_name)]
    return {"tools": visible}


def _kb_descriptors(agent: Any) -> dict[str, Any]:
    """Build the KB-descriptor payload from `AbstractBot.knowledge_bases`.

    Args:
        agent: The agent instance to introspect.

    Returns:
        `{"knowledge_bases": [{"name": ..., "description": ...}, ...]}`.
    """
    knowledge_bases = getattr(agent, "knowledge_bases", None) or []
    return {
        "knowledge_bases": [
            {
                "name": getattr(kb, "name", None) or getattr(kb, "id", None) or str(kb),
                "description": getattr(kb, "description", None),
            }
            for kb in knowledge_bases
        ]
    }


def register_agent_resources(
    server: Any,
    agent_name: str,
    agent: Any,
    exposure_names: list[str],
    policy_filter: ToolPolicyFilter | None = None,
) -> None:
    """Register the three agent metadata resources on `server`.

    Re-registering (e.g. after an OQ5 rebuild following `reload_agent()`)
    simply overwrites the same three URIs with handlers closing over the
    new `agent` instance — `RemoteMCPServerBase.register_resource` keys its
    resource/handler dicts by URI.

    Args:
        server: The per-agent `RemoteMCPServerBase` (a
            `StreamableHttpMCPServer`) to register resources on.
        agent_name: Configured agent name (used to build resource URIs).
        agent: The agent instance to introspect. Resolved fresh by the
            caller — never cached beyond this call (OQ5).
        exposure_names: Names already known to be in the agent's MCP
            exposure set (TASK-2600), included in the tool catalog
            alongside `agent.tool_manager`'s own tools.
        policy_filter: Optional `(agent_name, tool_name) -> bool` (or
            awaitable) hook filtering the tool catalog by the calling
            principal's policy. `None` (default) means everything is
            visible — the stub until TASK-2605's PBAC guard is wired in.
    """
    identity_uri = f"agent://{agent_name}/identity"
    tools_uri = f"agent://{agent_name}/tools"
    kbs_uri = f"agent://{agent_name}/kbs"

    async def _read_identity(uri: str) -> str:
        return json.dumps(_identity_card(agent_name, agent))

    async def _read_tools(uri: str) -> str:
        catalog = await _tool_catalog(agent_name, agent, exposure_names, policy_filter)
        return json.dumps(catalog)

    async def _read_kbs(uri: str) -> str:
        return json.dumps(_kb_descriptors(agent))

    server.register_resource(
        MCPResource(
            uri=identity_uri,
            name=f"{agent_name} identity",
            description=f"Identity card for agent {agent_name!r}",
            mime_type="application/json",
        ),
        _read_identity,
    )
    server.register_resource(
        MCPResource(
            uri=tools_uri,
            name=f"{agent_name} tool catalog",
            description=f"Policy-filtered tool catalog for agent {agent_name!r}",
            mime_type="application/json",
        ),
        _read_tools,
    )
    server.register_resource(
        MCPResource(
            uri=kbs_uri,
            name=f"{agent_name} knowledge bases",
            description=f"Knowledge bases consulted by agent {agent_name!r}",
            mime_type="application/json",
        ),
        _read_kbs,
    )


__all__ = ["ToolPolicyFilter", "register_agent_resources"]
