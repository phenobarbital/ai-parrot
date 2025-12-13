import asyncio
import json
import logging
import uuid
import contextlib
from typing import Dict, Any, Optional
from aiohttp import web
import aiohttp

from parrot.mcp.config import MCPServerConfig
from parrot.mcp.transports.base import MCPServerBase
from parrot.mcp.oauth import OAuthRoutesMixin
from parrot.mcp.client import MCPClientConfig, MCPConnectionError
from parrot.mcp.transports.http import HttpMCPSession
from aiohttp_sse_client import client as sse_client

class SseMCPServer(OAuthRoutesMixin, MCPServerBase):
    """MCP server using SSE transport compatible with ChatGPT and OpenAI MCP clients."""

    def __init__(self, config: MCPServerConfig, parent_app: Optional[web.Application] = None):
        super().__init__(config)
        self.app = parent_app or web.Application()
        self.base_path = config.base_path or "/mcp"
        self.events_path = config.events_path or f"{self.base_path.rstrip('/')}/events"
        self._init_oauth_support()
        self.runner = None
        self.site = None
        self.sessions: Dict[str, asyncio.Queue] = {}
        self._external_setup = parent_app is not None
        self.app.router.add_post(self.base_path, self._handle_http_request)
        # Alias GET on base path to the SSE stream for clients that connect at /mcp
        self.app.router.add_get(self.base_path, self._handle_sse, allow_head=True)
        self.app.router.add_get(self.events_path, self._handle_sse, allow_head=True)
        self.app.router.add_get("/", self._handle_info, allow_head=True)
        if self.oauth_server:
            self.oauth_server.register_routes(self.app)

    async def start(self):
        """Start the SSE MCP server."""
        if self._external_setup:
            self.logger.info("SSE MCP server using existing aiohttp application")
            return

        self.logger.info(
            f"Starting SSE MCP server on {self.config.host}:{self.config.port}"
        )

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        self.site = web.TCPSite(
            self.runner,
            self.config.host,
            self.config.port
        )
        await self.site.start()

        self.logger.info(f"SSE MCP server started at http://{self.config.host}:{self.config.port}")
        self.logger.info(
            "MCP endpoints: "
            f"events at http://{self.config.host}:{self.config.port}{self.events_path}, "
            f"requests at http://{self.config.host}:{self.config.port}{self.base_path}"
        )

    async def stop(self):
        """Stop the SSE server."""
        if not self._external_setup:
            if self.site:
                await self.site.stop()
            if self.runner:
                await self.runner.cleanup()

        # Clear any pending sessions
        for session_id, queue in list(self.sessions.items()):
            with contextlib.suppress(Exception):
                queue.put_nowait(None)
            self.sessions.pop(session_id, None)

        self.logger.info("SSE MCP server stopped")

    async def _handle_info(self, request: web.Request) -> web.Response:
        auth_response = self._authenticate_request(request)
        if auth_response:
            return auth_response

        info = {
            "name": self.config.name,
            "version": self.config.version,
            "description": self.config.description,
            "transport": "sse",
            "endpoint": self.events_path,
            "tools": list(self.tools.keys()),
            "tool_count": len(self.tools)
        }
        return web.json_response(info)

    def _get_session_id(self, request: web.Request) -> str:
        return request.headers.get("X-Session-Id") or request.query.get("session") or str(uuid.uuid4())

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        auth_response = self._authenticate_request(request)
        if auth_response:
            return auth_response

        session_id = self._get_session_id(request)
        queue: asyncio.Queue = asyncio.Queue()
        self.sessions[session_id] = queue
        self.logger.info(f"SSE client connected: {session_id}")

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Session-Id": session_id,
            },
        )

        await response.prepare(request)
        await response.write(self._format_sse_event({"type": "connected", "session": session_id}, event="connection"))

        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                    if message is None:
                        break
                    await response.write(self._format_sse_event(message))
                except asyncio.TimeoutError:
                    await response.write(b": keep-alive\n\n")
        except asyncio.CancelledError:
            self.logger.info(f"SSE client disconnected: {session_id}")
        finally:
            self.sessions.pop(session_id, None)
            with contextlib.suppress(Exception):
                await response.write_eof()

        return response

    def _format_sse_event(self, payload: Any, event: str = "message") -> bytes:
        data = json.dumps(payload)
        return f"event: {event}\ndata: {data}\n\n".encode("utf-8")

    async def _push_to_session(self, session_id: Optional[str], message: Dict[str, Any]):
        if not session_id:
            return
        if queue := self.sessions.get(session_id):
            try:
                queue.put_nowait(message)
            except Exception as e:
                self.logger.warning(f"Failed to enqueue SSE message for {session_id}: {e}")

    async def _handle_http_request(self, request: web.Request) -> web.Response:
        try:
            auth_response = self._authenticate_request(request)
            if auth_response:
                return auth_response

            data = await request.json()
            method = data.get("method")
            params = data.get("params", {})
            request_id = data.get("id")
            session_id = request.headers.get("X-Session-Id") or request.query.get("session")

            self.logger.info(f"SSE HTTP request: {method} (session {session_id or 'none'})")

            try:
                if method == "initialize":
                    result = await self.handle_initialize(params)
                elif method == "tools/list":
                    result = await self.handle_tools_list(params)
                elif method == "notifications/initialized":
                    # This is a notification, no response needed
                    self.logger.info("Client initialization complete")
                    return web.Response(status=204)  # No Content
                elif method == "tools/call":
                    result = await self.handle_tools_call(params)
                else:
                    raise RuntimeError(
                        f"Unknown method: {method}"
                    )

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }

            except Exception as e:
                self.logger.error(f"Error handling {method}: {e}")
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": str(e)
                    }
                }

            await self._push_to_session(session_id, response)
            return web.json_response(response)

        except Exception as e:
            self.logger.error(f"SSE HTTP request error: {e}")
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error",
                    }
                },
            )


class SseMCPSession(HttpMCPSession):
    """MCP session using SSE (Server-Sent Events) for transport."""

    def __init__(self, config: MCPClientConfig, logger):
        super().__init__(config, logger)
        self._sse_task = None
        self._session_id = str(uuid.uuid4())
        self._sse_ready = asyncio.Event()

    async def connect(self):
        """Connect to MCP server via SSE + HTTP."""
        try:
            # 1. Setup headers (auth etc) - reusing logic from HttpMCPSession
            # We need to manually trigger auth setup if we want headers for SSE connection
            if self.config.auth_type:
                from parrot.mcp.client import MCPAuthHandler
                self._auth_handler = MCPAuthHandler(
                    self.config.auth_type,
                    self.config.auth_config
                )
                auth_headers = await self._auth_handler.get_auth_headers()
                self._base_headers.update(auth_headers)

            self._base_headers.update(self.config.headers)
            
            # Add Session ID to headers for correlation
            self._base_headers["X-Session-Id"] = self._session_id

            # 2. Start SSE Listener
            self._sse_task = asyncio.create_task(self._listen_sse())
            
            # Wait for connection to be ready
            try:
                await asyncio.wait_for(self._sse_ready.wait(), timeout=self.config.timeout)
            except asyncio.TimeoutError:
                self.logger.warning("Timeout waiting for SSE connection ready, proceeding anyway")

            # 3. Create HTTP session for POST requests
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers=self._base_headers
            )

            # 4. Initialize MCP
            await self._initialize_session()
            self._initialized = True
            self.logger.info(f"SSE connection established to {self.config.name} (session {self._session_id})")

        except Exception as e:
            await self.disconnect()
            raise MCPConnectionError(f"SSE connection failed: {e}") from e

    async def _listen_sse(self):
        """Listen for SSE events."""
        events_url = self.config.events_path
        if not events_url:
            events_url = self.config.url
        
        self.logger.debug(f"Connecting to SSE endpoint: {events_url}")

        try:
            async with sse_client.EventSource(
                events_url,
                headers=self._base_headers
            ) as event_source:
                self._sse_ready.set()
                
                async for event in event_source:
                    try:
                        if event.type == 'error':
                            self.logger.error(f"SSE Error: {event.data}")
                            continue
                            
                        if event.type == 'connection':
                            self.logger.debug(f"SSE Connection event: {event.data}")
                            continue

                        if event.type == 'message':
                            await self._handle_sse_message(event.data)
                            
                    except Exception as e:
                        self.logger.error(f"Error processing SSE event: {e}")

        except asyncio.CancelledError:
            self.logger.debug("SSE listener cancelled")
        except Exception as e:
            self.logger.error(f"SSE connection error: {e}")

    async def _handle_sse_message(self, data: str):
        """Handle incoming JSON-RPC message from SSE."""
        try:
            message = json.loads(data)
            
            if "method" in message and "id" not in message:
                self.logger.info(f"Received notification: {message['method']}")
            elif "method" in message and "id" in message:
                 self.logger.info(f"Received server request: {message['method']}")
            
        except json.JSONDecodeError:
            self.logger.error("Failed to decode SSE message")

    async def disconnect(self):
        """Disconnect SSE session."""
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
            self._sse_task = None
            
        await super().disconnect()
