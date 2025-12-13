import asyncio
import json
import logging
import uuid
import contextlib
from typing import Dict, Any, Optional
from dataclasses import dataclass
from aiohttp import web, WSMsgType, ClientSession, ClientWebSocketResponse
import aiohttp

from parrot.mcp.config import MCPServerConfig
from parrot.mcp.transports.base import MCPServerBase
from parrot.mcp.oauth import OAuthRoutesMixin
from parrot.mcp.client import MCPClientConfig, MCPConnectionError


@dataclass
class WebSocketConnection:
    """Represents an active WebSocket connection with session info."""
    websocket: web.WebSocketResponse
    session_id: str
    message_queue: asyncio.Queue
    last_ping: float = 0.0


class WebSocketMCPServer(OAuthRoutesMixin, MCPServerBase):
    """MCP server using WebSocket transport for bidirectional communication.
    
    Implements the WebSocket transport as proposed in SEP-1288:
    - Session-based connection management (single connection per session)
    - Bidirectional JSON-RPC communication
    - Server-initiated notifications support
    - OAuth authentication via query params or websocket subprotocol
    - Automatic ping/pong keep-alive
    """

    def __init__(self, config: MCPServerConfig, parent_app: Optional[web.Application] = None):
        super().__init__(config)
        self.app = parent_app or web.Application()
        self.base_path = config.base_path or "/mcp"
        # WebSocket endpoint is at /mcp/ws (base_path + /ws)
        self.ws_path = f"{self.base_path.rstrip('/')}/ws"
        self._init_oauth_support()
        self.runner = None
        self.site = None
        self.sessions: Dict[str, WebSocketConnection] = {}
        self._external_setup = parent_app is not None
        
        # Register routes
        self.app.router.add_get(self.ws_path, self._handle_websocket)
        self.app.router.add_get("/", self._handle_info, allow_head=True)
        
        if self.oauth_server:
            self.oauth_server.register_routes(self.app)

    async def start(self):
        """Start the WebSocket MCP server."""
        if self._external_setup:
            self.logger.info("WebSocket MCP server using existing aiohttp application")
            return

        self.logger.info(
            f"Starting WebSocket MCP server on {self.config.host}:{self.config.port}"
        )

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        self.site = web.TCPSite(
            self.runner,
            self.config.host,
            self.config.port
        )
        await self.site.start()

        self.logger.info(
            f"WebSocket MCP server started at ws://{self.config.host}:{self.config.port}{self.ws_path}"
        )

    async def stop(self):
        """Stop the WebSocket server."""
        # Close all active WebSocket connections
        for session_id, conn in list(self.sessions.items()):
            try:
                await conn.websocket.close()
            except Exception as e:
                self.logger.warning(f"Error closing WebSocket for session {session_id}: {e}")
            self.sessions.pop(session_id, None)

        if not self._external_setup:
            if self.site:
                await self.site.stop()
            if self.runner:
                await self.runner.cleanup()

        self.logger.info("WebSocket MCP server stopped")

    async def _handle_info(self, request: web.Request) -> web.Response:
        """Return server info endpoint."""
        auth_response = self._authenticate_request(request)
        if auth_response:
            return auth_response

        info = {
            "name": self.config.name,
            "version": self.config.version,
            "description": self.config.description,
            "transport": "websocket",
            "endpoint": self.ws_path,
            "tools": list(self.tools.keys()),
            "tool_count": len(self.tools)
        }
        return web.json_response(info)

    def _get_session_id(self, request: web.Request) -> str:
        """Extract session ID from request headers or query params, or generate new one."""
        session_id = (
            request.headers.get("X-MCP-Session-Id") or
            request.query.get("session_id") or
            str(uuid.uuid4())
        )
        return session_id

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connection upgrade and message loop."""
        # OAuth authentication check
        auth_response = self._authenticate_request(request)
        if auth_response:
            return auth_response

        session_id = self._get_session_id(request)
        
        # Close existing connection for this session (SEP-1288: single connection per session)
        if session_id in self.sessions:
            old_conn = self.sessions[session_id]
            self.logger.info(f"Closing previous WebSocket connection for session {session_id}")
            try:
                await old_conn.websocket.close(code=1000, message=b"New connection established")
            except Exception:
                pass

        # Upgrade to WebSocket
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)

        # Create connection object
        connection = WebSocketConnection(
            websocket=ws,
            session_id=session_id,
            message_queue=asyncio.Queue()
        )
        self.sessions[session_id] = connection

        self.logger.info(f"WebSocket client connected: {session_id}")

        # Send connection established message
        await self._send_message(ws, {
            "jsonrpc": "2.0",
            "method": "notifications/connection",
            "params": {
                "type": "connected",
                "sessionId": session_id
            }
        })

        try:
            # Message handling loop
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_message(session_id, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    self.logger.error(f"WebSocket error for {session_id}: {ws.exception()}")
                    break
                elif msg.type == WSMsgType.CLOSE:
                    self.logger.info(f"WebSocket closed by client: {session_id}")
                    break

        except asyncio.CancelledError:
            self.logger.info(f"WebSocket connection cancelled: {session_id}")
        except Exception as e:
            self.logger.error(f"Error in WebSocket handler for {session_id}: {e}")
        finally:
            # Cleanup
            self.sessions.pop(session_id, None)
            if not ws.closed:
                await ws.close()
            self.logger.info(f"WebSocket client disconnected: {session_id}")

        return ws

    async def _handle_message(self, session_id: str, message_data: str):
        """Handle incoming JSON-RPC message from WebSocket client."""
        try:
            data = json.loads(message_data)
            method = data.get("method")
            params = data.get("params", {})
            request_id = data.get("id")

            self.logger.debug(f"WebSocket message from {session_id}: {method}")

            # Handle JSON-RPC request
            try:
                if method == "initialize":
                    result = await self.handle_initialize(params)
                elif method == "tools/list":
                    result = await self.handle_tools_list(params)
                elif method == "tools/call":
                    result = await self.handle_tools_call(params)
                elif method == "notifications/initialized":
                    # Client initialization complete notification (no response needed)
                    self.logger.info(f"Client {session_id} initialization complete")
                    return
                else:
                    raise RuntimeError(f"Unknown method: {method}")

                # Send success response
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }

            except Exception as e:
                self.logger.error(f"Error handling {method} for {session_id}: {e}")
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": str(e)
                    }
                }

            # Send response back to client
            connection = self.sessions.get(session_id)
            if connection:
                await self._send_message(connection.websocket, response)

        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON from {session_id}: {e}")
            # Send parse error
            connection = self.sessions.get(session_id)
            if connection:
                await self._send_message(connection.websocket, {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error"
                    }
                })

    async def _send_message(self, ws: web.WebSocketResponse, message: Dict[str, Any]):
        """Send JSON-RPC message to WebSocket client."""
        try:
            await ws.send_str(json.dumps(message))
        except Exception as e:
            self.logger.error(f"Failed to send WebSocket message: {e}")

    async def send_notification(self, session_id: str, method: str, params: Dict[str, Any]):
        """Send server-initiated notification to client.
        
        This enables server-to-client notifications like:
        - notifications/resources/updated
        - notifications/tools/list_changed
        """
        connection = self.sessions.get(session_id)
        if not connection:
            self.logger.warning(f"Cannot send notification: session {session_id} not found")
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        await self._send_message(connection.websocket, notification)


class WebSocketMCPSession:
    """MCP client session for WebSocket transport.
    
    Implements the client side of SEP-1288 WebSocket transport:
    - Connects to WebSocket MCP server
    - Manages session ID persistence
    - Handles request/response matching
    - Supports automatic reconnection
    - Receives server-initiated notifications
    """

    def __init__(self, config: MCPClientConfig, logger):
        self.config = config
        self.logger = logger
        self._request_id = 0
        self._session: Optional[ClientSession] = None
        self._websocket: Optional[ClientWebSocketResponse] = None
        self._response_futures: Dict[int, asyncio.Future] = {}
        self._session_id: Optional[str] = None
        self._connected = False
        self._receiver_task: Optional[asyncio.Task] = None
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5

    async def connect(self):
        """Connect to WebSocket MCP server."""
        if self._connected:
            return

        try:
            # Create aiohttp session
            self._session = ClientSession()

            # Build WebSocket URL
            url = self.config.url
            if not url.startswith("ws://") and not url.startswith("wss://"):
                # Convert http(s) to ws(s)
                url = url.replace("http://", "ws://").replace("https://", "wss://")

            # Add session ID if we have one (for reconnection)
            params = {}
            if self._session_id:
                params["session_id"] = self._session_id

            # Prepare headers
            headers = dict(self.config.headers or {})
            
            # Add authentication
            if self.config.auth_type == "bearer" and self.config.auth_config:
                token = self.config.auth_config.get("token")
                if token:
                    headers["Authorization"] = f"Bearer {token}"
            elif self.config.auth_type == "api_key" and self.config.auth_config:
                api_key = self.config.auth_config.get("api_key")
                header_name = self.config.auth_config.get("header_name", "X-API-Key")
                if api_key:
                    headers[header_name] = api_key

            # Connect to WebSocket
            self._websocket = await self._session.ws_connect(
                url,
                params=params,
                headers=headers
            )

            self.logger.info(f"Connected to WebSocket MCP server: {url}")

            # Mark as connected BEFORE starting receiver and initialization
            self._connected = True

            # Start background receiver task
            self._receiver_task = asyncio.create_task(self._receive_messages())

            # Wait a moment for receiver to be ready
            await asyncio.sleep(0.1)

            # Initialize MCP session
            await self._initialize_session()

            self._reconnect_attempts = 0

        except Exception as e:
            self.logger.error(f"Failed to connect to WebSocket MCP server: {e}")
            self._connected = False
            await self.disconnect()
            raise MCPConnectionError(f"WebSocket connection failed: {e}")

    async def _receive_messages(self):
        """Background task to receive messages from server."""
        try:
            async for msg in self._websocket:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type == WSMsgType.ERROR:
                    self.logger.error(f"WebSocket error: {self._websocket.exception()}")
                    break
                elif msg.type == WSMsgType.CLOSE:
                    self.logger.info("WebSocket closed by server")
                    break
        except asyncio.CancelledError:
            self.logger.debug("Message receiver task cancelled")
        except Exception as e:
            self.logger.error(f"Error in message receiver: {e}")
        finally:
            self._connected = False

    async def _handle_message(self, message_data: str):
        """Handle incoming message from server."""
        try:
            data = json.loads(message_data)

            # Check if this is a response to a request
            if "id" in data and data["id"] is not None:
                request_id = data["id"]
                if request_id in self._response_futures:
                    future = self._response_futures.pop(request_id)
                    if "error" in data:
                        future.set_exception(
                            RuntimeError(f"MCP error: {data['error']['message']}")
                        )
                    else:
                        future.set_result(data.get("result"))
            
            # Handle notifications from server
            elif "method" in data:
                method = data["method"]
                params = data.get("params", {})
                
                if method == "notifications/connection":
                    # Extract session ID from connection notification
                    self._session_id = params.get("sessionId")
                    self.logger.info(f"Session ID: {self._session_id}")
                else:
                    self.logger.info(f"Server notification: {method}")
                    # Could add notification handlers here

        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON from server: {e}")
        except Exception as e:
            self.logger.error(f"Error handling message: {e}")

    async def _initialize_session(self):
        """Initialize MCP session over WebSocket."""
        init_result = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "ai-parrot-websocket-client",
                "version": "1.0"
            }
        })

        self.logger.info(f"MCP session initialized: {init_result.get('serverInfo', {}).get('name', 'unknown')}")

        # Send initialized notification
        await self._send_notification("notifications/initialized", {})

    async def _send_request(self, method: str, params: dict = None) -> Any:
        """Send JSON-RPC request and wait for response."""
        if not self._connected or not self._websocket:
            raise MCPConnectionError("Not connected to WebSocket server")

        request_id = self._get_next_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {}
        }

        # Create future for response
        future = asyncio.Future()
        self._response_futures[request_id] = future

        try:
            # Send request
            await self._websocket.send_str(json.dumps(request))
            
            # Wait for response (with timeout)
            result = await asyncio.wait_for(future, timeout=30.0)
            return result

        except asyncio.TimeoutError:
            self._response_futures.pop(request_id, None)
            raise MCPConnectionError(f"Request timeout for method: {method}")
        except Exception as e:
            self._response_futures.pop(request_id, None)
            raise

    async def _send_notification(self, method: str, params: dict = None):
        """Send JSON-RPC notification (no response expected)."""
        if not self._connected or not self._websocket:
            raise MCPConnectionError("Not connected to WebSocket server")

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {}
        }

        await self._websocket.send_str(json.dumps(notification))

    def _get_next_id(self) -> int:
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    async def list_tools(self):
        """List available tools from MCP server."""
        result = await self._send_request("tools/list", {})
        
        # Convert to compatible format
        tools = []
        for tool_dict in result.get("tools", []):
            # Create simple object with attributes
            tool_obj = type('Tool', (), tool_dict)()
            tools.append(tool_obj)
        
        return tools

    async def call_tool(self, tool_name: str, arguments: dict):
        """Call a tool on the MCP server."""
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
        
        # Convert result to compatible format matching other transports
        # MCP returns: {"content": [{"type": "text", "text": "..."}], "isError": false}
        if isinstance(result, dict):
            content_list = result.get("content", [])
            # Convert to object with content attribute containing text items
            result_obj = type('ToolResult', (), {
                'content': [
                    type('ContentItem', (), item)() 
                    for item in content_list
                ],
                'isError': result.get("isError", False)
            })()
            return result_obj
        
        return result

    async def disconnect(self):
        """Disconnect from WebSocket server."""
        self._connected = False

        # Cancel receiver task
        if self._receiver_task and not self._receiver_task.done():
            self._receiver_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._receiver_task

        # Close WebSocket
        if self._websocket and not self._websocket.closed:
            await self._websocket.close()

        # Close session
        if self._session and not self._session.closed:
            await self._session.close()

        # Clear futures
        for future in self._response_futures.values():
            if not future.done():
                future.cancel()
        self._response_futures.clear()

        self.logger.info("Disconnected from WebSocket MCP server")
