# calculator/operations/__init__.py
"""
Calculator operations module.

Each operation should be a function that:
1. Has clear type hints
2. Includes a docstring
3. Is decorated with @operation (optional, for metadata)
"""

from functools import wraps
from typing import Callable


def operation(name: str = None, description: str = None):
    """
    Decorator to mark a function as a calculator operation.

    Args:
        name: Operation name (defaults to function name)
        description: Operation description (defaults to docstring)
    """
    def decorator(func: Callable) -> Callable:
        func._is_operation = True
        func._operation_name = name or func.__name__
        func._operation_description = description or func.__doc__

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # Preserve operation metadata
        wrapper._is_operation = True
        wrapper._operation_name = func._operation_name
        wrapper._operation_description = func._operation_description

        return wrapper
    return decorator
