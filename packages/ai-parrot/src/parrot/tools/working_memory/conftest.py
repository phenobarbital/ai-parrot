"""
Conftest for working_memory package tests.

Patches parrot.tools.__getattr__ to raise AttributeError instead of ImportError
for unknown names. This is necessary because parrot.tools.__getattr__ raises
ImportError (not AttributeError) for unrecognised tool names, which breaks pytest's
getattr(mod, name, default) calls for names like 'pytest_plugins', 'setUpModule',
'tearDownModule', etc. — causing the default value to be bypassed and ImportError
to propagate.
"""
import sys


def _patch_parrot_tools_for_pytest() -> None:
    """Wrap parrot.tools.__getattr__ to raise AttributeError instead of ImportError."""
    if "parrot.tools" not in sys.modules:
        return
    mod = sys.modules["parrot.tools"]
    original_getattr = mod.__dict__.get("__getattr__")
    if original_getattr is None:
        return
    # Avoid double-patching
    if getattr(original_getattr, "_pytest_patched", False):
        return

    def _patched_getattr(name: str) -> object:
        try:
            return original_getattr(name)
        except ImportError as exc:
            raise AttributeError(name) from exc

    _patched_getattr._pytest_patched = True  # type: ignore[attr-defined]
    mod.__dict__["__getattr__"] = _patched_getattr


_patch_parrot_tools_for_pytest()
