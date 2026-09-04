"""TASK-2855: proves `parrot/clients/__init__.py`'s `extend_path()` call
genuinely merges a namespace-package directory on `sys.path` at runtime —
not just that the 15 real satellites happen to work (they're regular
installed packages; this test simulates a *brand new* satellite that was
never `pip install`-ed, only added to `sys.path`, the way an editable
install's `.pth` entry effectively does).
"""
from __future__ import annotations

import importlib
import sys

FAKEPROV_INIT = '''\
from .client import FakeProvClient
from .models import FakeProvModel

__all__ = ["FakeProvClient", "FakeProvModel"]
'''

FAKEPROV_CLIENT = '''\
from enum import Enum
from ..base import AbstractClient


class FakeProvModel(str, Enum):
    FAKE_MODEL = "fakeprov-model"


class FakeProvClient(AbstractClient):
    client_type = "fakeprov"
    client_name = "fakeprov"
    provider_keys = ("fakeprov",)
    models = FakeProvModel
'''

FAKEPROV_MODELS = '''\
from enum import Enum


class FakeProvModel(str, Enum):
    FAKE_MODEL = "fakeprov-model"
'''


def test_extend_path_merges_satellite(tmp_path):
    """A directory that looks like a satellite (`<tmp>/parrot/clients/
    fakeprov/{__init__,client,models}.py`), added to `sys.path` after
    `parrot.clients` is already imported, must become importable as
    `parrot.clients.fakeprov` once `parrot.clients` is reloaded — proving
    `extend_path()` re-scans `sys.path` rather than caching `__path__`
    once at first import.
    """
    fakeprov_dir = tmp_path / "parrot" / "clients" / "fakeprov"
    fakeprov_dir.mkdir(parents=True)
    (fakeprov_dir / "__init__.py").write_text(FAKEPROV_INIT)
    (fakeprov_dir / "client.py").write_text(FAKEPROV_CLIENT)
    (fakeprov_dir / "models.py").write_text(FAKEPROV_MODELS)
    # No __init__.py at <tmp>/parrot/ or <tmp>/parrot/clients/ — PEP 420
    # namespace package levels, matching every real satellite's layout
    # (only .gitkeep markers, never __init__.py, at those two levels).

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()

        # `parrot.clients`'s own extend_path() call walks
        # `sys.modules["parrot"].__path__`, not sys.path directly (see
        # pkgutil.extend_path's source: for a dotted name it resolves the
        # *parent* package's __path__ and searches that). Core's own
        # top-level `parrot` package is a REGULAR package (has
        # __init__.py, unlike the satellites' bare namespace dirs) whose
        # own extend_path() call computed __path__ once, at its own
        # import time — so the parent must be reloaded first, or its
        # __path__ stays stale and parrot.clients's own extend_path()
        # never sees tmp_path at all.
        import parrot

        importlib.reload(parrot)
        import parrot.clients as parrot_clients

        importlib.reload(parrot_clients)

        fakeprov = importlib.import_module("parrot.clients.fakeprov")
        assert fakeprov.FakeProvClient.provider_keys == ("fakeprov",)
        assert fakeprov.FakeProvClient.models.FAKE_MODEL.value == "fakeprov-model"
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("parrot.clients.fakeprov", None)
        sys.modules.pop("parrot.clients.fakeprov.client", None)
        sys.modules.pop("parrot.clients.fakeprov.models", None)
        importlib.invalidate_caches()
        # Reload both once more so __path__ drops the removed tmp_path
        # entry — leaves no residue for later tests.
        import parrot

        importlib.reload(parrot)
        import parrot.clients as parrot_clients

        importlib.reload(parrot_clients)
