from typing import Any, Optional, Union, List, Callable, Awaitable
import asyncio
import importlib
import ssl
from aiohttp import web
from ...mcp.server import MCPServerConfig, HttpMCPServer, SseMCPServer
from ...mcp.transports.unix import UnixMCPServer
from ...mcp.transports.stdio import StdioMCPServer
from ...mcp.transports.quic import QuicMCPServer, QuicMCPConfig
from ...mcp.config import AuthMethod
from ...tools.abstract import AbstractTool
from ...tools.toolkit import AbstractToolkit
from ...mcp.resources import MCPResource


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
        ssl_key: Optional[str] = None,
        socket_path: Optional[str] = None,
        **kwargs
    ):
        self.name = name
        self.host = host
        self.port = port
        self.transport = transport.lower()
        self.tools_payload = tool
        self._pending_resources: List[tuple[MCPResource, Callable[[str], Awaitable[str | bytes]]]] = []
        self.app = web.Application()
        self.server = None
        self.socket_path = socket_path
        self.extra_config = kwargs
        
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
            base_path="/",
            socket_path=self.socket_path
        )
        
        if self.transport == "sse":
            self.server = SseMCPServer(config, parent_app=self.app)
        elif self.transport == "unix":
            self.server = UnixMCPServer(config)
        elif self.transport == "stdio":
            self.server = StdioMCPServer(config)
        elif self.transport == "quic":
            # Extract QUIC config from kwargs
            quic_config = QuicMCPConfig(
                host=self.host,
                port=self.port,
                cert_path=self.extra_config.get("cert_path", "cert.pem"),
                key_path=self.extra_config.get("key_path", "key.pem"),
                insecure=self.extra_config.get("insecure", False)
            )
            # Map other kwargs to quic_config if needed
            for k, v in self.extra_config.items():
                if hasattr(quic_config, k):
                    setattr(quic_config, k, v)
                    
            self.server = QuicMCPServer(config, quic_config=quic_config)
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
        
        if self.transport in ("http", "sse"):
            async def on_startup(app):
                await self.server.start()
                
            self.app.on_startup.append(on_startup)
            
            ssl_context = None
            if self.ssl_cert and self.ssl_key:
                ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                ssl_context.load_cert_chain(certfile=self.ssl_cert, keyfile=self.ssl_key)
                
            web.run_app(self.app, host=self.host, port=self.port, ssl_context=ssl_context)
        else:
            # For asyncio-based servers
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(self.server.start())

    async def start(self):
        """Start the server asynchronously (for embedding)."""
        self.setup()
        
        if self.transport in ("http", "sse"):
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
        else:
            # For other transports (stdio, unix, quic)
            await self.server.start()
            return self.server
