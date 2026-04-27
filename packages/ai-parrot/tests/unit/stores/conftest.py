"""Conftest for stores unit tests.

Stubs out parrot.utils.types so the parent conftest's _crud import chain
does not fail when parrot.utils.types is missing from the installed package.
"""
from __future__ import annotations

import sys
from types import ModuleType

# Stub missing modules before the parent conftest tries to import _crud.
for _mod_name in (
    "parrot.utils.types",
    "parrot.utils",
):
    if _mod_name not in sys.modules:
        _stub = ModuleType(_mod_name)
        # Add minimal stubs used by the chain
        if _mod_name == "parrot.utils.types":
            _stub.SafeDict = dict  # type: ignore[attr-defined]
        sys.modules[_mod_name] = _stub
