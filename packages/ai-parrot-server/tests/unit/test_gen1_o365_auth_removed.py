"""TASK-1686: Gen 1 legacy O365 interactive-auth is fully removed (FEAT-266)."""
import importlib

import pytest


def test_gen1_modules_removed():
    for mod in ("parrot.services.o365_remote_auth", "parrot.handlers.o365_auth"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(mod)
