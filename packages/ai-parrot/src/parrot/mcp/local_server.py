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

# How long handlers still in flight may keep running once the read loop has
# ended (stdin EOF / stop()) before they are cancelled.
_INFLIGHT_DRAIN_SECONDS = 5.0


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
        # Every request that has been read but whose handler has not finished.
        # Handlers run as independent tasks so one slow (or wedged) tool call
        # never stops the transport from reading and answering later requests.
        self._inflight: set[asyncio.Task[None]] = set()

    async def start(self):
        """Start the stdio MCP server.

        Reads one JSON-RPC message per line from stdin and dispatches each one
        as its own task, writing responses as they complete (so they may be
        answered out of order, which JSON-RPC permits via ``id``). The loop
        ends on stdin EOF or :meth:`stop`; handlers still in flight are then
        given ``_INFLIGHT_DRAIN_SECONDS`` to finish before being cancelled.
        """
        self.logger.info("Starting stdio MCP server with %s tools...", len(self.tools))
        self._running = True
        loop = asyncio.get_running_loop()

        try:
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
                    except json.JSONDecodeError as e:
                        self.logger.warning("Invalid JSON received: %s", e)
                        continue

                    task = loop.create_task(self._dispatch(request))
                    self._inflight.add(task)
                    task.add_done_callback(self._inflight.discard)

                except KeyboardInterrupt:
                    break
                except Exception as e:  # noqa: BLE001
                    self.logger.error("Error in main loop: %s", e)
                    continue
        finally:
            await self._drain_inflight()

        self.logger.info("Stdio MCP server stopped")

    async def _dispatch(self, request: dict[str, Any]) -> None:
        """Handle one request to completion and write its response, if any."""
        try:
            response = await self._handle_request(request)
        except Exception as e:  # noqa: BLE001 -- _handle_request already maps errors; this is the last resort
            self.logger.error("Unhandled error dispatching %s: %s", request.get("method"), e)
            return
        if response:
            self._write_response(response)

    def _write_response(self, response: dict[str, Any]) -> None:
        """Write one JSON-RPC message as a single line on stdout."""
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    async def _drain_inflight(self) -> None:
        """Wait briefly for in-flight handlers, then cancel whatever is left.

        Called once the read loop has ended (client closed stdin or
        :meth:`stop` ran): nobody is left to read late responses, so a handler
        that cannot finish within ``_INFLIGHT_DRAIN_SECONDS`` is cancelled
        rather than allowed to keep the process alive.
        """
        pending = {task for task in self._inflight if not task.done()}
        if not pending:
            return
        _done, still_pending = await asyncio.wait(pending, timeout=_INFLIGHT_DRAIN_SECONDS)
        for task in still_pending:
            task.cancel()
        if still_pending:
            self.logger.warning("Cancelled %s request handler(s) still running at shutdown", len(still_pending))
            await asyncio.gather(*still_pending, return_exceptions=True)

    async def stop(self):
        """Stop the stdio server.

        Clears the running flag so the read loop exits after its current
        ``readline`` returns; the loop's own shutdown path then drains and
        cancels in-flight handlers.
        """
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
