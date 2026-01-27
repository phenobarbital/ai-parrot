from typing import Optional, Dict, Any, List
import os
import yaml
import asyncio
import importlib
import logging
from navconfig import config as nav_config
from parrot.services.mcp.simple import SimpleMCPServer
from parrot.tools.abstract import AbstractTool
from parrot.tools.toolkit import AbstractToolkit


def resolve_config_value(tool_name: str, key: str, value: Any) -> Any:
    """
    Resolve configuration value with priority:
    1. If value is provided and looks like an env var key (UPPERCASE), check env/config.
    2. If value is None, check env/config using {TOOL_NAME}_{KEY} convention.
    3. Return original value if no resolution found.
    """
    # Case 1: Value is a string, check if it's a reference to an env var
    if isinstance(value, str):
        # Check navconfig/env for the value as a key
        resolved = nav_config.get(value, os.getenv(value))
        if resolved is not None:
            return resolved

    # Case 2: Value is None/Empty, look for convention {TOOL_NAME}_{KEY}
    if value is None:
        env_key = f"{tool_name.upper()}_{key.upper()}"
        resolved = nav_config.get(env_key, os.getenv(env_key))
        if resolved is not None:
            return resolved
            
    # Return original value (or None if strictly nothing found)
    return value

def load_tool_class(tool_name: str):
    """
    Dynamic loading of tool class.
    Tries to find the tool in parrot.tools.<lower_tool_name> or parrot.tools.<lower_tool_name>.bundle
    """
    # Heuristic: try finding the module based on tool name
    module_name = tool_name.lower()
    
    # Common variations/mappings could be added here if needed
    # e.g JiraToolkit -> jiratoolkit
    
    attempts = [
        f"parrot.tools.{module_name}",
        f"parrot.tools.{module_name}.bundle",
        f"parrot.tools.{module_name}.{module_name}"
    ]
    
    for module_path in attempts:
        try:
            module = importlib.import_module(module_path)
            if hasattr(module, tool_name):
                return getattr(module, tool_name)
        except ImportError:
            continue
            
    raise ImportError(f"Could not load tool class '{tool_name}'. Tried: {attempts}")

def load_server_from_config(config_path: str) -> SimpleMCPServer:
    """
    Load a SimpleMCPServer instance from a YAML configuration file.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, 'r') as f:
        data = yaml.safe_load(f)

    if 'MCPServer' not in data:
        raise ValueError("Invalid YAML: missing 'MCPServer' root key")

    server_config = data['MCPServer']
    
    # Resolve all server configuration values
    resolved_server_config = {}
    for k, v in server_config.items():
        if k == 'tools':
            continue
        resolved_server_config[k] = resolve_config_value("MCPServer", k, v)
    
    # Server configuration
    name = resolved_server_config.get('name', 'SimpleMCPServer')
    host = resolved_server_config.get('host', '0.0.0.0')
    port = resolved_server_config.get('port', 8081)
    transport = resolved_server_config.get('transport', 'http')
    auth_method = resolved_server_config.get('auth_method', 'none')
    
    # Initialize list to hold instantiated tools
    loaded_tools = []
    
    tools_def = server_config.get('tools', [])
    
    for tool_entry in tools_def:
        # tool_entry is expected to be a dict like {ToolClassName: {config_dict}} 
        # or just a string "ToolClassName" (if no config needed)
        
        if isinstance(tool_entry, str):
            tool_class_name = tool_entry
            tool_kwargs = {}
        elif isinstance(tool_entry, dict):
            # Expecting single key dict
            tool_class_name = list(tool_entry.keys())[0]
            tool_kwargs = tool_entry[tool_class_name] or {}
        else:
            logging.warning(f"Skipping invalid tool entry: {tool_entry}")
            continue

        try:
            tool_cls = load_tool_class(tool_class_name)
            
            # Resolve arguments
            resolved_kwargs = {}
            for k, v in tool_kwargs.items():
                resolved_kwargs[k] = resolve_config_value(tool_class_name, k, v)
                
            # Instantiate tool
            # Check if we should pass kwargs or not. AbstractToolkit usually takes kwargs.
            tool_instance = tool_cls(**resolved_kwargs)
            loaded_tools.append(tool_instance)
            
        except Exception as e:
            logging.error(f"Failed to load tool '{tool_class_name}': {e}")
            raise e

    if not loaded_tools:
        logging.warning("No tools were loaded for the server.")

    # Create server
    server = SimpleMCPServer(
        tool=loaded_tools, # SimpleMCPServer accepts a list of tools
        name=name,
        host=host,
        port=port,
        transport=transport,
        auth_method=auth_method,
        **{k: v for k, v in resolved_server_config.items() if k not in ['name', 'host', 'port', 'transport', 'auth_method']}
    )
    
    return server
