from typing import Any, Dict, Optional, Union, List
import asyncio
import importlib
from aiohttp import web
from parrot.mcp.server import MCPServerConfig, HttpMCPServer, SseMCPServer
from parrot.mcp.config import AuthMethod
from parrot.tools.decorators import tool
from parrot.tools.abstract import AbstractTool
from parrot.tools.toolkit import AbstractToolkit
from .config import TransportConfig

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
        api_key: Optional[str] = None
    ):
        self.name = name
        self.host = host
        self.port = port
        self.transport = transport.lower()
        self.tools_payload = tool
        self.app = web.Application()
        self.server = None
        
        # Configure Authentication
        self.auth_method = self._parse_auth_method(auth_method)
        self.api_key_store = None
        
        if self.auth_method == AuthMethod.API_KEY and api_key:
            from parrot.mcp.oauth import APIKeyStore
            self.api_key_store = APIKeyStore()
            self.api_key_store.add_key(api_key, "simple-mcp-user")
            
    def _parse_auth_method(self, method: str) -> AuthMethod:
        try:
            return AuthMethod(method.lower())
        except ValueError:
            return AuthMethod.NONE

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
                raise ValueError(f"Could not import tool/toolkit from string '{item}': {e}")

        # If it's a function decorated with @tool, it has metadata
        if hasattr(item, "_is_tool") and hasattr(item, "_tool_metadata"):
            return [self._create_wrapper_tool(item)]
            
        raise ValueError(f"Provided object {item} is not a valid AbstractTool, AbstractToolkit, import string, or @tool decorated function")

    def _create_wrapper_tool(self, func) -> AbstractTool:
        """Wrap a decorated function into an AbstractTool class."""
        metadata = func._tool_metadata
        
        class FunctionWrapperTool(AbstractTool):
            name = metadata['name']
            description = metadata['description']
            args_schema = None  # Schema is handled by logic if needed, or we can extract it
            
            async def _execute(self, **kwargs):
                if asyncio.iscoroutinefunction(metadata['function']):
                    return await metadata['function'](**kwargs)
                return metadata['function'](**kwargs)
                
        return FunctionWrapperTool()

    def setup(self):
        """Initialize the MCP server components."""
        tools_list = self._prepare_tools()
        
        config = MCPServerConfig(
            name=self.name,
            host=self.host,
            port=self.port,
            transport=self.transport,
            auth_method=self.auth_method,
            api_key_store=self.api_key_store
        )
        
        if self.transport == "sse":
            self.server = SseMCPServer(config, parent_app=self.app)
        else:
            self.server = HttpMCPServer(config, parent_app=self.app)
            
        self.server.register_tools(tools_list)

    def run(self):
        """Run the server (blocking)."""
        self.setup()
        web.run_app(self.app, host=self.host, port=self.port)

    async def start(self):
        """Start the server asynchronously (for embedding)."""
        self.setup()
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        return runner
