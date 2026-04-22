"""Manager-specific test configuration — FEAT-114.

Minimal stub patches that allow BotManager to be imported without a full
runtime environment, while not interfering with existing manager tests.
"""
from __future__ import annotations

import sys
import types


def _install_minimal_stubs() -> None:
    """Install only the stubs that BotManager's import chain is missing.

    The root conftest handles most parrot/navigator stubs.  This adds the
    few extras that block BotManager collection in this directory's tests.
    """
    # navconfig.DEBUG — imported by notify.providers.base
    try:
        import navconfig as _nc
        if not hasattr(_nc, "DEBUG"):
            _nc.DEBUG = False
    except ImportError:
        pass

    # navconfig._Config.getlist — used by parrot/conf.py at line ~570
    if "navconfig" in sys.modules:
        _nc2 = sys.modules["navconfig"]
        if hasattr(_nc2, "config") and not hasattr(type(_nc2.config), "getlist"):
            import os as _os

            def _getlist(self, key, fallback=None):  # type: ignore[misc]
                val = _os.environ.get(key)
                return [v.strip() for v in val.split(",")] if val else (fallback or [])

            type(_nc2.config).getlist = _getlist

    # notify hierarchy — parrot.handlers.agents.abstract imports notify
    for _mod in ("notify", "notify.models", "notify.providers", "notify.providers.base"):
        if _mod not in sys.modules:
            stub = types.ModuleType(_mod)
            stub.__path__ = []  # type: ignore[attr-defined]
            sys.modules[_mod] = stub

    # Seed class names that abstract.py imports by name
    _m = sys.modules
    for _cls in ("Actor", "Chat", "TeamsCard", "TeamsChannel"):
        if not hasattr(_m.get("notify.models", types.ModuleType("x")), _cls):
            setattr(_m["notify.models"], _cls, type(_cls, (), {}))
    if not hasattr(_m.get("notify.providers.base", types.ModuleType("x")), "ProviderType"):
        setattr(_m["notify.providers.base"], "ProviderType", type("ProviderType", (), {}))
    if not hasattr(_m.get("notify", types.ModuleType("x")), "Notify"):
        setattr(_m["notify"], "Notify", type("Notify", (), {}))

    # navigator.background — parrot.handlers.agents.abstract imports it
    for _mod in ("navigator.background", "navigator.background.tasks"):
        if _mod not in sys.modules:
            stub = types.ModuleType(_mod)
            stub.__path__ = []  # type: ignore[attr-defined]
            sys.modules[_mod] = stub

    # navigator.services — parrot.handlers.agents.abstract imports it
    for _mod in ("navigator.services", "navigator.services.ws"):
        if _mod not in sys.modules:
            stub = types.ModuleType(_mod)
            stub.__path__ = []  # type: ignore[attr-defined]
            sys.modules[_mod] = stub
            setattr(stub, "WebSocketManager", type("WebSocketManager", (), {}))

    # navigator.responses — used deeper in the handler chain
    if "navigator.responses" not in sys.modules:
        stub = types.ModuleType("navigator.responses")
        stub.__path__ = []  # type: ignore[attr-defined]
        sys.modules["navigator.responses"] = stub


_install_minimal_stubs()
