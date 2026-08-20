"""Bridges a live `ToolManager` into an in-process Claude Agent SDK MCP server
(FEAT-434 — Claude Agent Tool Bridge, spec §3 Module 1).

`ClaudeAgentToolBridge` converts an agent's registered tools into
`claude_agent_sdk.SdkMcpTool` objects grouped into a single
`McpSdkServerConfig`, so a delegated Claude Code sub-agent (via
`ClaudeAgentClient`) can call the agent's OWN tools — not just Claude
Code's native Read/Write/Bash/Edit/Glob/Grep — while those tools keep
their open connections, auth context, `working_memory` and toolkit
lifecycle (they run **inside the daemon's own event loop**, never in a
separate process).

The single rule that makes the security model work: every bridged call
dispatches through `ToolManager.execute_tool()`, never `tool.execute()`
directly. That inherits the TOOL_CALL guardrail pipeline (FEAT-406) ->
`GrantGuard` (FEAT-211) -> `ConfirmationGuard` (FEAT-235) ->
`tool.execute()` -> the tool-result compression pipeline (FEAT-380) for
free — this module adds no guardrail logic of its own.

`claude_agent_sdk` is an optional extra (`ai-parrot[claude-agent]`) and is
imported strictly lazily (inside `build_server()`, never at module scope)
so `import parrot.clients.claude_agent_bridge` always succeeds.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import TYPE_CHECKING, Any

from parrot.mcp.adapter import MCPToolAdapter
from parrot.tools.abstract import ToolResult

if TYPE_CHECKING:
    from parrot.auth.permission import PermissionContext
    from parrot.tools.abstract import AbstractTool
    from parrot.tools.manager import ToolManager

_INSTALL_HINT = (
    "claude_agent_sdk is not installed. "
    "Install with: pip install ai-parrot[claude-agent]"
)


def _import_sdk():
    """Lazy-import the `claude_agent_sdk` symbols this module uses.

    Returns:
        A tuple `(create_sdk_mcp_server, SdkMcpTool)`.

    Raises:
        ImportError: With a clear pip install hint when the optional
            `[claude-agent]` extra is not installed.
    """
    try:  # pragma: no cover - import side effect varies by env
        from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server
    except ImportError as exc:  # pragma: no cover
        raise ImportError(_INSTALL_HINT) from exc
    return create_sdk_mcp_server, SdkMcpTool


class ClaudeAgentToolBridge:
    """Builds an in-process SDK-MCP server from a live `ToolManager`.

    Attributes:
        tool_manager: The live `ToolManager` whose registered tools are
            bridged. Every dispatched call goes through
            `tool_manager.execute_tool()`.
        namespace: MCP server name; also the prefix of every exposed tool
            name (`mcp__<namespace>__<tool>`).
        tool_timeout: Optional per-call timeout in seconds. On expiry, a
            recoverable MCP error result is returned — the turn is never
            aborted. `None` means no per-call cap.
    """

    def __init__(
        self,
        tool_manager: ToolManager,
        *,
        namespace: str = "parrot",
        tool_timeout: float | None = None,
    ) -> None:
        self.tool_manager = tool_manager
        self.namespace = namespace
        self.tool_timeout = tool_timeout
        self.logger = logging.getLogger(__name__)
        self._exposed_names: list[str] = []

    def build_server(
        self,
        tools: list[AbstractTool],
        permission_context: PermissionContext | None = None,
    ) -> Any:
        """Build an `McpSdkServerConfig` exposing `tools`.

        A tool whose schema cannot be converted is skipped (with a
        warning) rather than failing the whole assembly — the rest of
        `tools` is still exposed.

        Args:
            tools: The tools to expose this turn (already ranked/bounded
                by the caller — narrowing is not this method's job).
            permission_context: The caller's identity (FEAT-434 —
                resolved by agentd from `SO_PEERCRED` or the service-
                identity fallback), forwarded to every
                `tool_manager.execute_tool()` call made through this
                server. `None` preserves today's unguarded default.

        Returns:
            An `McpSdkServerConfig`, ready for
            `ClaudeAgentOptions.mcp_servers`.
        """
        create_sdk_mcp_server, SdkMcpTool = _import_sdk()

        sdk_tools = []
        exposed_names: list[str] = []
        for tool in tools:
            tool_name = getattr(tool, "name", None) or "unknown_tool"
            try:
                sdk_tool = self._build_sdk_tool(tool, SdkMcpTool, permission_context)
            except Exception as exc:  # noqa: BLE001 - never fail the whole run
                self.logger.warning(
                    "Skipping tool %r — schema conversion failed: %s",
                    tool_name,
                    exc,
                )
                continue
            sdk_tools.append(sdk_tool)
            exposed_names.append(f"mcp__{self.namespace}__{tool_name}")

        self._exposed_names = exposed_names
        return create_sdk_mcp_server(name=self.namespace, tools=sdk_tools)

    def _build_sdk_tool(
        self,
        tool: AbstractTool,
        sdk_mcp_tool_cls: Any,
        permission_context: PermissionContext | None,
    ) -> Any:
        """Convert one tool into an `SdkMcpTool`.

        Args:
            tool: The tool to convert.
            sdk_mcp_tool_cls: The `SdkMcpTool` class (passed in so the
                lazy import happens exactly once per `build_server()`
                call).
            permission_context: Forwarded to this tool's handler closure.

        Returns:
            An `SdkMcpTool` ready for `create_sdk_mcp_server()`.
        """
        adapter = MCPToolAdapter(tool)
        definition = adapter.to_mcp_tool_definition()
        input_schema = self._strip_confirm(definition["inputSchema"])

        handler = self._make_handler(tool, adapter, permission_context)

        return sdk_mcp_tool_cls(
            name=definition["name"],
            description=definition["description"],
            input_schema=input_schema,
            handler=handler,
        )

    @staticmethod
    def _strip_confirm(schema: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of `schema` with the `confirm` property removed.

        `MCPToolAdapter.to_mcp_tool_definition()` injects a required
        `confirm: boolean` for confirming tools because the stdio
        transport has no interactive HITL channel. In-process, the real
        `ConfirmationGuard` runs instead (via `execute_tool()`), so the
        sub-agent must never be handed a switch it can flip itself. The
        adapter itself is never mutated — this is post-processing on a
        deep copy, applied only on the SDK-MCP path.

        Args:
            schema: The adapter's `inputSchema` dict.

        Returns:
            A deep copy of `schema` with `confirm` removed from both
            `properties` and `required`.
        """
        schema_copy = copy.deepcopy(schema)
        properties = schema_copy.get("properties")
        if isinstance(properties, dict):
            properties.pop("confirm", None)
        required = schema_copy.get("required")
        if isinstance(required, list) and "confirm" in required:
            required.remove("confirm")
        return schema_copy

    def _make_handler(
        self,
        tool: AbstractTool,
        adapter: MCPToolAdapter,
        permission_context: PermissionContext | None,
    ):
        """Build the in-process handler closure for one tool.

        Dispatches exclusively through `self.tool_manager.execute_tool()`
        — never `tool.execute()` — so the TOOL_CALL guardrail pipeline,
        `GrantGuard`, `ConfirmationGuard` and the compression pipeline all
        apply. Every failure mode (tool exception, timeout, HITL denial,
        HITL timeout) is mapped to a recoverable MCP error result; the
        handler never raises.

        `execute_tool()`'s own contract: on success it returns the
        unwrapped result (not a `ToolResult`); on several guard-denial
        statuses (`not_found`, `forbidden`, a HITL `cancelled`/`timeout`,
        `authorization_required`) it returns a `ToolResult` directly
        without raising; on a genuine tool execution error it *raises*
        (typically `ValueError`). This handler normalizes all three shapes
        through `MCPToolAdapter._toolresult_to_mcp()`.

        Args:
            tool: The tool this handler dispatches for.
            adapter: This tool's `MCPToolAdapter` (reused for result
                conversion — never forked).
            permission_context: Forwarded to `execute_tool()` on every
                call.

        Returns:
            An async callable suitable for `SdkMcpTool.handler`.
        """
        tool_name = tool.name

        async def handler(args: dict[str, Any]) -> dict[str, Any]:
            call = self.tool_manager.execute_tool(
                tool_name, args, permission_context
            )
            try:
                if self.tool_timeout is not None:
                    raw = await asyncio.wait_for(call, timeout=self.tool_timeout)
                else:
                    raw = await call
            except TimeoutError:
                self.logger.warning(
                    "Bridged tool %r timed out after %ss", tool_name, self.tool_timeout
                )
                result = ToolResult(
                    success=False,
                    status="timeout",
                    error=f"Tool '{tool_name}' timed out after {self.tool_timeout}s",
                    result=None,
                )
                return adapter._toolresult_to_mcp(result)
            except Exception as exc:  # noqa: BLE001 - never raise out of a handler
                self.logger.warning("Bridged tool %r raised: %s", tool_name, exc)
                result = ToolResult(
                    success=False,
                    status="error",
                    error=str(exc),
                    result=None,
                )
                return adapter._toolresult_to_mcp(result)

            if isinstance(raw, ToolResult):
                return adapter._toolresult_to_mcp(raw)

            success_result = ToolResult(success=True, status="success", result=raw)
            return adapter._toolresult_to_mcp(success_result)

        return handler

    def exposed_names(self) -> list[str]:
        """Names of the tools exposed by the most recent `build_server()` call.

        Returns:
            `mcp__<namespace>__<tool>` strings, for `allowed_tools`
            reconciliation. Empty until `build_server()` has run at least
            once.
        """
        return list(self._exposed_names)
