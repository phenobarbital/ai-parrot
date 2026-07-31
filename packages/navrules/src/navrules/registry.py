"""Registry of computed-value functions addressable by string path.

Port of nav-rewards ``AchievementRegistry`` with the ``register()`` bug fixed
(the original wrote to a ``self._functions`` attribute that was never
initialized) and an optional import-path allowlist for safety.
"""
from __future__ import annotations

import importlib
import inspect
import logging
from typing import Callable, Optional


class FunctionRegistry:
    """Dynamically loads and caches async functions from string paths.

    Registered/loaded functions must be ``async`` and accept at least
    ``(subject, env, conn, **kwargs)``.

    Args:
        allowed_prefixes: If non-empty, only function paths starting with one
            of these prefixes may be imported (defense against arbitrary
            imports from untrusted rule definitions).
    """

    def __init__(self, allowed_prefixes: tuple[str, ...] = ()) -> None:
        self._functions: dict[str, Callable] = {}
        self._cache: dict[str, Callable] = {}
        self._allowed_prefixes = allowed_prefixes
        self.logger = logging.getLogger("navrules.FunctionRegistry")

    def register(self, name: str, func: Callable) -> None:
        """Register a computed-value function under an explicit name."""
        self._validate_function_signature(func, name)
        self._functions[name] = func
        self._cache[name] = func
        self.logger.info("Registered function: %s", name)

    def load_function(self, function_path: str) -> Optional[Callable]:
        """Load a function from a dotted path, caching the result.

        Returns None (and logs) when the path cannot be resolved.
        """
        if function_path in self._cache:
            return self._cache[function_path]
        if self._allowed_prefixes and not function_path.startswith(
            self._allowed_prefixes
        ):
            self.logger.error(
                "Function path %r not allowed (prefixes: %s)",
                function_path,
                self._allowed_prefixes,
            )
            return None
        try:
            module_path, function_name = function_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            func = getattr(module, function_name)
            self._validate_function_signature(func, function_path)
            self._cache[function_path] = func
            self.logger.info("Loaded function: %s", function_path)
            return func
        except (ImportError, AttributeError, ValueError) as err:
            self.logger.error(
                "Failed to load function %r: %s", function_path, err
            )
            return None

    def get_function(self, function_path: str) -> Optional[Callable]:
        """Get a function by path or registered name, loading if necessary."""
        if function_path in self._functions:
            return self._functions[function_path]
        return self.load_function(function_path)

    resolve = get_function

    def _validate_function_signature(self, func: Callable, path: str) -> None:
        """Validate the (subject, env, conn, **kwargs) async contract."""
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        if len(params) < 3:
            raise ValueError(
                f"Function {path} must accept at least (subject, env, conn) args"
            )
        if not inspect.iscoroutinefunction(func):
            raise ValueError(f"Function {path} must be async")

    def clear_cache(self) -> None:
        """Clear the loaded-function cache (registered names persist)."""
        self._cache.clear()
        self._cache.update(self._functions)

    def list_functions(self) -> list[str]:
        """List all cached function paths/names."""
        return list(self._cache.keys())


# Shared default instance used by EvalContext.get_computed when no registry
# is supplied explicitly.
default_registry = FunctionRegistry()


def register_function(name: str) -> Callable:
    """Decorator: register an async function in the default registry."""

    def decorator(func: Callable) -> Callable:
        default_registry.register(name, func)
        return func

    return decorator
