"""
AI-Parrot SkillRegistry Module — Deprecated re-export shim.

This module has been promoted to the top-level ``parrot.skills`` namespace.
Importing from ``parrot.memory.skills`` will issue a ``DeprecationWarning``.

Migrate to:
    from parrot.skills import <name>
"""
import importlib
import warnings

_NEW_MODULE = "parrot.skills"


def __getattr__(name: str):
    """Lazy re-export with DeprecationWarning."""
    new_mod = importlib.import_module(_NEW_MODULE)
    if hasattr(new_mod, name):
        warnings.warn(
            f"Importing '{name}' from 'parrot.memory.skills' is deprecated. "
            f"Use 'parrot.skills' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(new_mod, name)
    raise AttributeError(f"module 'parrot.memory.skills' has no attribute '{name}'")


# Preserve __all__ for star imports
from parrot.skills import __all__  # noqa: F401, E402
