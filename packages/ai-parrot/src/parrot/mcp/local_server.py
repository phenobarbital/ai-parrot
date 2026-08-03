"""Core local MCP transports — stdio JSON-RPC server.

``LocalMCPServerBase`` is the extension point for any local (in-process)
MCP transport; ``StdioMCPServer`` is the concrete stdin/stdout JSON-RPC
implementation. Neither depends on aiohttp, auth, or resources — those
remain server-only concerns handled by ``RemoteMCPServerBase`` in
``ai-parrot-server`` (FEAT-403).
"""
import asyncio
import json
import logging
import sys
from typing import Any

from parrot.mcp.server_base import LocalServerConfig, MCPServerBase


class LocalMCPServerBase(MCPServerBase):
    """Extension point for local (in-process) MCP transports.

    Local transports (e.g. stdio) may reserve stdout as the JSON-RPC
    channel, so all logging must go to stderr instead of a default handler
    that could write to stdout.
    """

    def __init__(self, config: LocalServerConfig):
        super().__init__(config)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
        self.logger.addHandler(handler)
        self.logger.propagate = False


class StdioMCPServer(LocalMCPServerBase):
    """MCP server using stdio transport (core, local-only)."""

    def __init__(self, config: LocalServerConfig):
        super().__init__(config)
        self._request_id = 0
        self._running = False

    async def start(self):
        """Start the stdio MCP server."""
        self.logger.info("Starting stdio MCP server with %s tools...", len(self.tools))
        self._running = True
        loop = asyncio.get_running_loop()

        while self._running:
            try:
                # sys.stdin.readline() is blocking — run it off the event loop.
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    request = json.loads(line)
                    response = await self._handle_request(request)

                    if response:
                        print(json.dumps(response), flush=True)

                except json.JSONDecodeError as e:
                    self.logger.warning("Invalid JSON received: %s", e)
                    continue

            except KeyboardInterrupt:
                break
            except Exception as e:  # noqa: BLE001
                self.logger.error("Error in main loop: %s", e)
                continue

        self.logger.info("Stdio MCP server stopped")

    async def stop(self):
        """Stop the stdio server."""
        self._running = False

    async def _handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a JSON-RPC request."""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        try:
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list(params)
            elif method == "tools/call":
                result = await self.handle_tools_call(params)
            elif method == "notifications/initialized":
                # This is a notification, no response needed
                self.logger.info("Client initialization complete")
                return None
            else:
                raise RuntimeError(f"Unknown method: {method}")

            # Return success response
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }

        except Exception as e:  # noqa: BLE001
            self.logger.error("Error handling %s: %s", method, e)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
