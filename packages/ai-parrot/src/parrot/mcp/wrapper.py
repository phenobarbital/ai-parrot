from typing import Any
import os
import importlib
import logging
import yaml
from navconfig import config as nav_config
from parrot.services.mcp.simple import SimpleMCPServer, _resolve_env_value


def resolve_config_value(tool_name: str, key: str, value: Any) -> Any:
    """Resolve a configuration value against navconfig / os.environ.

    Resolution priority:

    1. If *value* is a string that looks like an env-var name (all-uppercase +
       underscores), resolve it via :func:`_resolve_env_value`.
    2. If *value* is ``None``, attempt the ``{TOOL_NAME}_{KEY}`` convention.
    3. Return the original value unchanged otherwise.

    Args:
        tool_name: Logical name of the tool/server (used for convention fallback).
        key: Configuration key name (used for convention fallback).
        value: Raw value from YAML.

    Returns:
        Resolved value, or the original value when no resolution is found.
    """
    # Case 1: non-None string — attempt env-var resolution
    if isinstance(value, str):
        resolved = _resolve_env_value(value)
        if resolved != value:
            return resolved

    # Case 2: missing value — try {TOOL_NAME}_{KEY} convention
    if value is None:
        env_key = f"{tool_name.upper()}_{key.upper()}"
        resolved = nav_config.get(env_key) or os.getenv(env_key)
        if resolved is not None:
            return resolved

    # No resolution found — return original
    return value

_TOOL_SUBPACKAGES = (
    "aws",
    "google",
    "o365",
    "workday",
    "calculator",
    "database",
    "file",
    "scraping",
    "messaging",
)


def load_tool_class(tool_name: str):
    """Dynamic loading of a tool class by its class name.

    Resolution order:
    1. parrot.tools.<lowercase_name>           (top-level module)
    2. parrot.tools.<lowercase_name>.bundle     (bundle convention)
    3. parrot.tools.<lowercase_name>.<lowercase_name>
    4. parrot.tools.<subpackage>                (sub-package __init__ re-exports)
    5. parrot.tools  (top-level __getattr__ / re-exports)
    """
    module_name = tool_name.lower()

    attempts = [
        f"parrot.tools.{module_name}",
        f"parrot.tools.{module_name}.bundle",
        f"parrot.tools.{module_name}.{module_name}",
    ]
    # Also try each known sub-package (e.g. parrot.tools.aws)
    for subpkg in _TOOL_SUBPACKAGES:
        attempts.append(f"parrot.tools.{subpkg}")

    for module_path in attempts:
        try:
            module = importlib.import_module(module_path)
            if hasattr(module, tool_name):
                return getattr(module, tool_name)
        except ImportError:
            continue

    # Last resort: try the parrot.tools package itself (__getattr__)
    try:
        tools_pkg = importlib.import_module("parrot.tools")
        if hasattr(tools_pkg, tool_name):
            return getattr(tools_pkg, tool_name)
    except (ImportError, AttributeError):
        pass

    raise ImportError(
        f"Could not load tool class '{tool_name}'. "
        f"Tried: {attempts} + parrot.tools"
    )

def load_server_from_config(config_path: str) -> SimpleMCPServer:
    """
    Load a SimpleMCPServer instance from a YAML configuration file.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, 'r') as f:
        data = yaml.safe_load(f)

    if 'MCPServer' not in data:
        raise ValueError(
            "Invalid YAML: missing 'MCPServer' root key"
        )

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
            logging.warning(
                f"Skipping invalid tool entry: {tool_entry}"
            )
            continue

        try:
            tool_cls = load_tool_class(tool_class_name)
            
            # Resolve arguments
            resolved_kwargs = {}
            for k, v in tool_kwargs.items():
                resolved_kwargs[k] = resolve_config_value(tool_class_name, k, v)
                
            # Check if it's a function decorated with @tool
            if hasattr(tool_cls, "_is_tool") and hasattr(tool_cls, "_tool_metadata"):
                # Pass directly to SimpleMCPServer which will wrap it
                loaded_tools.append(tool_cls)
            else:
                # Instantiate tool (AbstractTool or AbstractToolkit)
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
