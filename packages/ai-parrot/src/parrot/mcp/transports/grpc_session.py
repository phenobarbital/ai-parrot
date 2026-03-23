import grpc
import asyncio
from typing import Dict, Any, Optional
from dataclasses import dataclass
# from .proto import mcp_pb2, mcp_pb2_grpc


@dataclass
class GrpcMCPConfig:
    """Configuration for gRPC MCP transport."""
    host: str = "localhost"
    port: int = 50051
    use_tls: bool = True
    cert_path: Optional[str] = None
    # For protobuf message format instead of JSON-RPC
    use_protobuf_messages: bool = False


class GrpcMCPSession:
    """MCP session for gRPC transport with optional protobuf messages."""
    
    def __init__(self, config: 'MCPServerConfig', logger):
        self.config = config
        self.logger = logger
        self._request_id = 0
        self._channel: Optional[grpc.aio.Channel] = None
        self._stub = None
        self._initialized = False
        self._response_queue: asyncio.Queue = asyncio.Queue()
        self._stream_task: Optional[asyncio.Task] = None
        
    async def connect(self):
        """Connect to MCP server via gRPC."""
        try:
            grpc_config = self.config.grpc_config or GrpcMCPConfig()
            
            # Create channel
            target = f"{grpc_config.host}:{grpc_config.port}"
            
            if grpc_config.use_tls:
                if grpc_config.cert_path:
                    with open(grpc_config.cert_path, 'rb') as f:
                        creds = grpc.ssl_channel_credentials(f.read())
                else:
                    creds = grpc.ssl_channel_credentials()
                self._channel = grpc.aio.secure_channel(target, creds)
            else:
                self._channel = grpc.aio.insecure_channel(target)
            
            # Create stub
            self._stub = mcp_pb2_grpc.MCPServiceStub(self._channel)
            
            # Start bidirectional stream
            self._stream = self._stub.BiDirectionalStream()
            self._stream_task = asyncio.create_task(self._read_responses())
            
            # Initialize MCP session
            await self._initialize_session()
            self._initialized = True
            
            self.logger.info(f"gRPC connection established to {self.config.name}")
            
        except Exception as e:
            await self.disconnect()
            raise MCPConnectionError(f"gRPC connection failed: {e}") from e
    
    async def _read_responses(self):
        """Background task to read responses from gRPC stream."""
        try:
            async for response in self._stream:
                # Convert protobuf to dict if needed
                if hasattr(response, 'json_rpc_message'):
                    msg = json.loads(response.json_rpc_message)
                else:
                    msg = self._protobuf_to_dict(response)
                
                await self._response_queue.put(msg)
        except grpc.aio.AioRpcError as e:
            self.logger.error(f"gRPC stream error: {e}")
        except asyncio.CancelledError:
            pass
    
    async def send_request(self, method: str, params: Dict = None) -> Dict[str, Any]:
        """Send JSON-RPC request over gRPC."""
        self._request_id += 1
        
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {}
        }
        
        # Option 1: Send JSON-RPC as string in protobuf wrapper
        grpc_request = mcp_pb2.MCPRequest(
            json_rpc_message=json.dumps(request)
        )
        
        # Option 2: Use native protobuf messages (more efficient)
        # grpc_request = self._dict_to_protobuf(request)
        
        await self._stream.write(grpc_request)
        
        # Wait for response with matching ID
        while True:
            response = await asyncio.wait_for(
                self._response_queue.get(),
                timeout=self.config.timeout
            )
            if response.get("id") == self._request_id:
                return response
            # Put back if not matching (notifications, etc.)
            await self._response_queue.put(response)
    
    async def _initialize_session(self):
        """Initialize MCP session."""
        response = await self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "ai-parrot",
                "version": "1.0.0"
            }
        })
        
        if "error" in response:
            raise MCPConnectionError(f"Initialize failed: {response['error']}")
        
        # Send initialized notification
        await self._stream.write(mcp_pb2.MCPRequest(
            json_rpc_message=json.dumps({
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            })
        ))
    
    async def list_tools(self) -> list:
        """List available tools."""
        response = await self.send_request("tools/list")
        return response.get("result", {}).get("tools", [])
    
    async def call_tool(self, name: str, arguments: Dict) -> Dict:
        """Call a tool."""
        response = await self.send_request("tools/call", {
            "name": name,
            "arguments": arguments
        })
        return response.get("result", {})
    
    async def disconnect(self):
        """Disconnect from gRPC server."""
        self._initialized = False
        
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stream_task
        
        if self._channel:
            await self._channel.close()
            self._channel = None
        
        self.logger.info("gRPC disconnected")