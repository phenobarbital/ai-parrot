from typing import Callable, Optional, Dict, Any, Type, Union, get_args, get_origin, get_type_hints
from functools import wraps
import inspect
import re
from enum import Enum
from pydantic import BaseModel


# Decorator for custom argument schemas
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None):
    """
    Decorator to specify a custom argument schema for a toolkit method.

    Usage:
        @tool_schema(MyCustomSchema)
        async def my_tool(self, arg1: str, arg2: int) -> str:
            '''My custom tool.'''
            return result
    """
    def decorator(func):
        func._args_schema = schema
        func._tool_description = description or func.__doc__ or f"Tool: {func.__name__}"
        return func
    return decorator


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    schema: Optional[Dict[str, Any]] = None,
    auto_register: bool = False
):
    """
    Decorator to mark a function as a tool with automatic schema generation.

    Automatically extracts:
    - Name from function name (or use custom name)
    - Description from docstring (or use custom description)
    - Input schema from type hints (or use custom schema)

    Args:
        name: Optional custom tool name (defaults to function name)
        description: Optional custom description (defaults to docstring)
        schema: Optional custom input schema (auto-generated from type hints if not provided)
        auto_register: If True, automatically register with active client/bot

    Usage:
        @tool()
        def get_weather(location: str) -> str:
            '''Get weather for a location.'''
            return f"Weather in {location}"

        @tool(name="custom_name", description="Custom description")
        def my_function(param: int) -> str:
            return str(param)
    """
    def decorator(func: Callable) -> Callable:
        # Extract metadata
        tool_name = name or func.__name__
        tool_description = description or _extract_description(func)

        # Generate schema from type hints if not provided
        if schema is None:
            tool_schema = _generate_schema_from_function(func)
        else:
            tool_schema = schema

        # Store metadata on the function
        func._tool_metadata = {
            'name': tool_name,
            'description': tool_description,
            'schema': tool_schema,
            'function': func,
            'auto_register': auto_register
        }

        # Mark as a tool
        func._is_tool = True

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # Preserve metadata on wrapper
        wrapper._tool_metadata = func._tool_metadata
        wrapper._is_tool = True

        return wrapper

    return decorator

def _extract_description(func: Callable) -> str:
    """
    Extract description from function docstring.
    Takes the first line or paragraph of the docstring.
    """
    if not func.__doc__:
        return f"Tool: {func.__name__}"

    # Get first line or first paragraph
    docstring = func.__doc__.strip()

    # Split by newlines and get first non-empty line
    lines = [line.strip() for line in docstring.split('\n')]
    non_empty = [line for line in lines if line]

    if non_empty:
        return non_empty[0]

    return f"Tool: {func.__name__}"


def _generate_schema_from_function(func: Callable) -> Dict[str, Any]:
    """
    Generate JSON schema from function signature and type hints.

    Args:
        func: The function to generate schema for

    Returns:
        JSON schema dictionary
    """
    sig = inspect.signature(func)

    # Get type hints
    try:
        type_hints = get_type_hints(func)
    except Exception:
        # If get_type_hints fails, fall back to annotations
        type_hints = func.__annotations__ or {}

    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        # Skip self and cls
        if param_name in ('self', 'cls'):
            continue

        # Get type hint (default to string if not specified)
        param_type = type_hints.get(param_name, str)

        # Convert Python types to JSON schema types
        json_type = _python_type_to_json_type(param_type)

        # Get description from docstring if available
        param_description = _extract_param_description(func, param_name)

        # Build property definition
        if isinstance(json_type, dict):
            # Complex type (List, Optional, Union, etc.)
            prop_def = json_type.copy()
            if param_description:
                prop_def['description'] = param_description
            else:
                prop_def['description'] = f"The {param_name} parameter"
        else:
            # Simple type
            prop_def = {
                'type': json_type,
                'description': param_description or f"The {param_name} parameter"
            }

        properties[param_name] = prop_def

        # Check if parameter is required (no default value)
        if param.default == inspect.Parameter.empty:
            required.append(param_name)

    return {
        'type': 'object',
        'properties': properties,
        'required': required
    }

def _extract_param_description(func: Callable, param_name: str) -> Optional[str]:
    """
    Extract parameter description from docstring.
    Looks for Google, NumPy, or Sphinx style docstrings.
    """
    if not func.__doc__:
        return None

    docstring = func.__doc__

    # Google style: Args: section
    google_pattern = rf'{param_name}\s*:\s*(.+?)(?:\n|$)'
    match = re.search(google_pattern, docstring)
    if match:
        return match.group(1).strip()

    # Sphinx style: :param name: description
    sphinx_pattern = rf':param\s+{param_name}\s*:\s*(.+?)(?:\n|$)'
    match = re.search(sphinx_pattern, docstring)
    if match:
        return match.group(1).strip()

    return None


def _python_type_to_json_type(python_type: Any) -> Union[str, Dict[str, Any]]:
    """
    Convert Python type hints to JSON schema types.

    Handles:
    - Basic types (str, int, float, bool)
    - Optional types
    - List types
    - Dict types
    - Union types
    - Enum types
    """
    # Handle None type
    if python_type is type(None):
        return "null"

    # Get origin for generic types (List, Dict, Optional, etc.)
    origin = get_origin(python_type)

    # Handle Optional[T] -> Union[T, None]
    if origin is Union:
        args = get_args(python_type)
        # Check if it's Optional (Union with None)
        if type(None) in args:
            # It's Optional, get the non-None type
            non_none_types = [t for t in args if t is not type(None)]
            if len(non_none_types) == 1:
                # Optional[T] - return the type with nullable
                base_type = _python_type_to_json_type(non_none_types[0])
                if isinstance(base_type, dict):
                    return base_type
                return {"type": [base_type, "null"]}
        # Regular Union - return anyOf
        return {
            "anyOf": [_python_type_to_json_type(t) for t in args]
        }

    # Handle List[T]
    if origin is list or python_type is list:
        args = get_args(python_type)
        if args:
            item_type = _python_type_to_json_type(args[0])
            return {
                "type": "array",
                "items": {"type": item_type} if isinstance(item_type, str) else item_type
            }
        return "array"

    # Handle Dict[K, V]
    if origin is dict or python_type is dict:
        return "object"

    # Handle Enum
    if inspect.isclass(python_type) and issubclass(python_type, Enum):
        return {
            "type": "string",
            "enum": [e.value for e in python_type]
        }

    # Basic types
    type_mapping = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    return type_mapping.get(python_type, "string")
