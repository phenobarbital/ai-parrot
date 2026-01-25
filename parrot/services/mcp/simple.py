from typing import Any, Optional, Union, List
import asyncio
import importlib
import ssl
from aiohttp import web
from parrot.mcp.server import MCPServerConfig, HttpMCPServer, SseMCPServer
from parrot.mcp.transports.unix import UnixMCPServer
from parrot.mcp.transports.stdio import StdioMCPServer
from parrot.mcp.transports.quic import QuicMCPServer, QuicMCPConfig
from parrot.mcp.config import AuthMethod
from parrot.tools.abstract import AbstractTool
from parrot.tools.toolkit import AbstractToolkit

from parrot.mcp.resources import MCPResource
from typing import Callable, Awaitable

class SimpleMCPServer:
    """
    A simplified MCP Server implementation for exposing a single tool or function.
    
    This class handles the boilerplate of setting up an MCP server with a specific
    transport (HTTP or SSE) and authentication method, serving a single capability.
    
    Usage:
        # Define a tool function
        @tool()
        async def my_function(x: int) -> int:
            return x * 2
            
        # Or use a class-based tool
        my_tool = MyTool()
        
        # Start the server
        server = SimpleMCPServer(
            tool=my_function,
            transport="http",
            port=8080
        )
        server.run()
    """
    
    def __init__(
        self,
        tool: Union[AbstractTool, AbstractToolkit, str, Any, List[Union[AbstractTool, Any, str]]],
        name: str = "SimpleMCPServer",
        host: str = "localhost",
        port: int = 9090,
        transport: str = "http",
        auth_method: str = "none",
        api_key: Optional[str] = None,
        ssl_cert: Optional[str] = None,
        ssl_key: Optional[str] = None
    ):
        self.name = name
        self.host = host
        self.port = port
        self.transport = transport.lower()
        self.tools_payload = tool
        self._pending_resources: List[tuple[MCPResource, Callable[[str], Awaitable[str | bytes]]]] = []
        self.app = web.Application()
        self.server = None
        
        # Configure Authentication
        self.auth_method = self._parse_auth_method(auth_method)
        self.api_key_store = None
        
        if self.auth_method == AuthMethod.API_KEY and api_key:
            from parrot.mcp.oauth import APIKeyStore  # noqa: C0415
            self.api_key_store = APIKeyStore()
            self.api_key_store.add_key(api_key, "simple-mcp-user")
            
        self.ssl_cert = ssl_cert
        self.ssl_key = ssl_key
            
    def _parse_auth_method(self, method: str) -> AuthMethod:
        try:
            return AuthMethod(method.lower())
        except ValueError:
            return AuthMethod.NONE


    def register_resource(self, resource: MCPResource, handler: Callable[[str], Awaitable[str | bytes]]):
        """Register a resource to be served."""
        self._pending_resources.append((resource, handler))

    def setup(self):
        """Initialize the MCP server components."""
        tools_list = self._prepare_tools()
        
        config = MCPServerConfig(
            name=self.name,
            host=self.host,
            port=self.port,
            transport=self.transport,
            auth_method=self.auth_method,
            api_key_store=self.api_key_store,
            ssl_cert_path=self.ssl_cert,
            ssl_key_path=self.ssl_key,
            base_path="/"
        )
        
        if self.transport == "sse":
            self.server = SseMCPServer(config, parent_app=self.app)
        else:
            self.server = HttpMCPServer(config, parent_app=self.app)
            
        self.server.register_tools(tools_list)
        
        for res, handler in self._pending_resources:
            self.server.register_resource(res, handler)

    def _prepare_tools(self) -> List[AbstractTool]:
        """Convert input payload into a list of AbstractTool instances."""
        tools_list: List[AbstractTool] = []
        
        # Normalize to list
        items = self.tools_payload if isinstance(self.tools_payload, list) else [self.tools_payload]
        
        for item in items:
            tools_list.extend(self._resolve_single_item(item))
            
        return tools_list

    def _resolve_single_item(self, item: Any) -> List[AbstractTool]:
        """Resolve a single item (Tool, Toolkit, string, or function) to a list of tools."""
        if isinstance(item, AbstractToolkit):
            return item.get_tools()
            
        if isinstance(item, AbstractTool):
            return [item]
            
        # Handle string import "package.module.ClassName"
        if isinstance(item, str):
            try:
                module_path, class_name = item.rsplit('.', 1)
                module = importlib.import_module(module_path)
                cls_or_obj = getattr(module, class_name)
                
                # If it's a class, instantiate it
                if isinstance(cls_or_obj, type):
                    instance = cls_or_obj()
                else:
                    instance = cls_or_obj
                    
                # Check what we got
                if isinstance(instance, AbstractToolkit):
                    return instance.get_tools()
                if isinstance(instance, AbstractTool):
                    return [instance]
                    
                raise ValueError(f"Imported object '{item}' is neither AbstractTool nor AbstractToolkit")
                
            except (ValueError, ImportError, AttributeError) as e:
                raise ValueError(
                    f"Could not import tool/toolkit from string '{item}': {e}"
                ) from e

        # If it's a function decorated with @tool, it has metadata
        if hasattr(item, "_is_tool") and hasattr(item, "_tool_metadata"):
            return [self._create_wrapper_tool(item)]
            
        raise ValueError(f"Provided object {item} is not a valid AbstractTool, AbstractToolkit, import string, or @tool decorated function")

    def _create_wrapper_tool(self, func) -> AbstractTool:
        """Wrap a decorated function into an AbstractTool class."""
        metadata = func._tool_metadata
        
        class FunctionWrapperTool(AbstractTool):
            """Wrapper tool for a decorated function."""
            name = metadata['name']
            description = metadata['description']
            args_schema = None  # Schema is handled by logic if needed, or we can extract it
            
            async def _execute(self, **kwargs):
                if asyncio.iscoroutinefunction(metadata['function']):
                    return await metadata['function'](**kwargs)
                return metadata['function'](**kwargs)
                
        return FunctionWrapperTool()


    def run(self):
        """Run the server (blocking)."""
        self.setup()
        
        async def on_startup(app):
            await self.server.start()
            
        self.app.on_startup.append(on_startup)
        
        ssl_context = None
        if self.ssl_cert and self.ssl_key:
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(certfile=self.ssl_cert, keyfile=self.ssl_key)
            
        web.run_app(self.app, host=self.host, port=self.port, ssl_context=ssl_context)

    async def start(self):
        """Start the server asynchronously (for embedding)."""
        self.setup()
        
        # Start internal server to register routes
        await self.server.start()
        
        runner = web.AppRunner(self.app)
        await runner.setup()
        
        
        ssl_context = None
        if self.ssl_cert and self.ssl_key:
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(certfile=self.ssl_cert, keyfile=self.ssl_key)
            
        site = web.TCPSite(runner, self.host, self.port, ssl_context=ssl_context)
        await site.start()
        return runner
