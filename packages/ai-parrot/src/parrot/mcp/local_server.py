"""Core local MCP transports — stdio JSON-RPC server.

``LocalMCPServerBase`` is the extension point for any local (in-process)
MCP transport; ``StdioMCPServer`` is the concrete stdin/stdout JSON-RPC
implementation. Neither depends on aiohttp, auth, or resources — those
remain server-only concerns handled by ``RemoteMCPServerBase`` in
``ai-parrot-server`` (FEAT-403).

Concurrency model
-----------------
``tools/call`` requests run as independent asyncio tasks, so a slow tool
(a merge, a 300 s ``coder_wait``) never delays a read-only call queued
behind it. Responses are written whenever their task finishes — JSON-RPC
matches them by ``id``, so ordering is free. The lifecycle methods
(``initialize``, ``tools/list``, ``ping``) stay inline: they are cheap and
the host serialises them anyway. A ``notifications/cancelled`` from the
host cancels the matching in-flight task, which is what frees a handler
the host has given up on (the MCP host aborts a stdio call after its idle
timeout, 30 minutes by default) instead of leaving it pinned forever.
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

    #: How long `start()` waits for in-flight tool calls once stdin hits EOF
    #: before cancelling them. The host is gone by then; this only lets a
    #: call that is about to finish flush its last write.
    drain_timeout_s: float = 5.0

    def __init__(self, config: LocalServerConfig):
        super().__init__(config)
        self._request_id = 0
        self._running = False
        self._inflight: set["asyncio.Task[None]"] = set()
        self._by_request_id: dict[Any, "asyncio.Task[None]"] = {}

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
                except json.JSONDecodeError as e:
                    self.logger.warning("Invalid JSON received: %s", e)
                    continue

                await self._admit(request)

            except KeyboardInterrupt:
                break
            except Exception as e:  # noqa: BLE001
                self.logger.error("Error in main loop: %s", e)
                continue

        await self._drain()
        self.logger.info("Stdio MCP server stopped")

    async def stop(self):
        """Stop the stdio server, cancelling any in-flight tool calls."""
        self._running = False
        await self._cancel_inflight()

    # ------------------------------------------------------------------ dispatch

    async def _admit(self, request: dict[str, Any]) -> None:
        """Route one decoded JSON-RPC message: cancel, spawn a task, or answer inline."""
        method = request.get("method")
        if method == "notifications/cancelled":
            self._cancel_request((request.get("params") or {}).get("requestId"))
            return
        if method == "tools/call":
            task = asyncio.create_task(self._dispatch(request))
            self._track(request.get("id"), task)
            return
        response = await self._handle_request(request)
        if response is not None:
            self._send(response)

    async def _dispatch(self, request: dict[str, Any]) -> None:
        """Run one ``tools/call`` to completion and write its response."""
        try:
            response = await self._handle_request(request)
        except asyncio.CancelledError:
            self.logger.info("Request %s cancelled", request.get("id"))
            return
        if response is None:
            return
        try:
            self._send(response)
        except Exception as e:  # noqa: BLE001 -- non-serialisable result, closed stdout: log, never lose it silently
            self.logger.error("Failed to write response for request %s: %s", request.get("id"), e)

    def _track(self, request_id: Any, task: "asyncio.Task[None]") -> None:
        self._inflight.add(task)
        if request_id is not None:
            self._by_request_id[request_id] = task

        def _done(t: "asyncio.Task[None]") -> None:
            self._inflight.discard(t)
            if request_id is not None and self._by_request_id.get(request_id) is t:
                del self._by_request_id[request_id]

        task.add_done_callback(_done)

    def _cancel_request(self, request_id: Any) -> None:
        task = self._by_request_id.get(request_id)
        if task is None or task.done():
            self.logger.debug("Cancellation for unknown/finished request %s ignored", request_id)
            return
        self.logger.info("Host cancelled request %s; cancelling its handler", request_id)
        task.cancel()

    async def _cancel_inflight(self) -> None:
        pending = [t for t in self._inflight if not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _drain(self) -> None:
        """Give in-flight calls `drain_timeout_s` to finish, then cancel the rest."""
        pending = {t for t in self._inflight if not t.done()}
        if not pending:
            return
        _, still_pending = await asyncio.wait(pending, timeout=self.drain_timeout_s)
        for t in still_pending:
            t.cancel()
        if still_pending:
            await asyncio.gather(*still_pending, return_exceptions=True)

    def _send(self, response: dict[str, Any]) -> None:
        """Write one JSON-RPC message.

        A single synchronous write on the event-loop thread cannot interleave
        with another task's write, so no lock is needed.
        """
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    # ------------------------------------------------------------------ handling

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
            elif method == "ping":
                result = {}
            elif method == "notifications/initialized":
                # This is a notification, no response needed
                self.logger.info("Client initialization complete")
                return None
            elif isinstance(method, str) and method.startswith("notifications/"):
                # Any other notification: acknowledge silently (no id, no response).
                self.logger.debug("Ignoring notification %s", method)
                return None
            else:
                raise RuntimeError(f"Unknown method: {method}")

            # Return success response
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }

        except asyncio.CancelledError:
            raise
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


__all__ = ["LocalMCPServerBase", "StdioMCPServer"]
