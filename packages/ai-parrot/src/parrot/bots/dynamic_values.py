"""
Dynamic Value Provider Registry.

This module provides a registry for dynamic values that can be injected into system prompts
during runtime. It allows for registered functions to be called and their return values
used for template substitution in prompts.
"""
from typing import Dict, Any, Callable, Awaitable
import inspect
from datetime import datetime


class DynamicValueProvider:
    """Registry for dynamic value functions"""
    
    def __init__(self):
        self._providers: Dict[str, Callable[..., Awaitable[Any]]] = {}
    
    def register(self, name: str):
        """Decorator to register a dynamic value provider"""
        def decorator(func):
            self._providers[name] = func
            return func
        return decorator
    
    async def get_value(self, name: str, context: Dict[str, Any] = None) -> Any:
        """Get a dynamic value, passing runtime context"""
        if name not in self._providers:
            raise ValueError(f"Unknown dynamic value: {name}")
        
        provider = self._providers[name]
        context = context or {}
        
        # Call provider with context if it accepts it
        sig = inspect.signature(provider)
        if len(sig.parameters) > 0:
            # Check if it accepts **kwargs or specific context keys
            try:
                if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    return await provider(**context)
                else:
                    # Only pass what's needed? Or assume single argument 'context'?
                    # The user example showed `def get_user_name(context):` so it expects a single dict arg
                    # OR we can pass it as a named argument if the function signature matches keys in context.
                    # BUT, to be safer and follow the user's snippet design:
                    # "if len(sig.parameters) > 0: return await provider(context)"
                    # Let's stick to the simplest interpretation of the user request first:
                    return await provider(context)
            except TypeError as e:
                # Fallback or re-raise with better message
                raise RuntimeError(f"Error calling provider '{name}': {e}") from e
        else:
            return await provider()
            
    def get_all_names(self):
        """Return list of all registered value names"""
        return list(self._providers.keys())

# Global registry
dynamic_values = DynamicValueProvider()

# Register built-in providers
@dynamic_values.register("current_date")
async def get_current_date(_=None):
    return datetime.now().strftime("%Y-%m-%d")

@dynamic_values.register("local_time")
async def get_local_time(_=None):
    return datetime.now().strftime("%H:%M:%S")

@dynamic_values.register("user_name")
async def get_user_name(context):
    """This one needs context to determine the user"""
    if not context:
        return "User"
    # Try different common keys for user identifier
    # Check for user object first as it might contain the name
    user = context.get("user")
    if isinstance(user, dict):
        return user.get("name", "User")
        
    # Fallback to user_id
    user_id = context.get("user_id")
    if user_id:
        return str(user_id)
        
    return str(user or "User")
