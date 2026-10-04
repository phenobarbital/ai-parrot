"""FEAT-603 TASK-3756 — SharePointFileManager."""

import sys
from types import SimpleNamespace
from unittest import mock

import pytest

# The repository-wide test bootstrap installs a non-package compatibility stub
# for this module before collection. This task verifies the real new submodule.
sys.modules.pop("parrot.interfaces.file", None)
import parrot.interfaces.file.sharepoint as sharepoint_module
from parrot.interfaces.file.graph import GraphDriveFileManager
from parrot.interfaces.file.sharepoint import SharePointFileManager
from parrot.interfaces.sharepoint import SharepointClient

from ._graph_fakes import FakeDrive, FakeGraphClient, make_sharepoint_client

# TASK-3751..3754 (parallel siblings under the same FEAT-603 feature) still owe
# GraphDriveFileManager's read/transfer implementations of navigator-api's
# FileManagerInterface in this isolated per-task worktree; they are not
# dependencies of this task and are not merged onto this branch yet. This
# task's own contract is only `_build_client` / `_resolve_drive_id` / `__init__`,
# so neutralize the abstract-method gate here (the source files are untouched)
# to exercise those hooks directly.
SharePointFileManager.__abstractmethods__ = frozenset()


def test_constructor_and_defaults():
    manager = SharePointFileManager("/TeamSite/")
    assert isinstance(manager, GraphDriveFileManager)
    assert manager.site == "TeamSite"
    assert manager.library == "Documents"
    assert manager.manager_name == "sharepointfile"
    assert manager.client_class is SharepointClient
    assert manager.tenant is None

    with pytest.raises(ValueError):
        SharePointFileManager("")
    with pytest.raises(ValueError):
        SharePointFileManager("///")


def test_sharepoint_manager_builds_client_with_site_and_tenant(monkeypatch):
    recorded = {}

    class StubSharepointClient:
        def __init__(self, *, credentials):
            recorded["credentials"] = credentials
            self._srcfiles = []

    monkeypatch.setattr(sharepoint_module, "SharepointClient", StubSharepointClient)
    manager = SharePointFileManager("TeamSite", credentials={"client_id": "abc"}, tenant="contoso")

    client = manager._build_client()

    assert isinstance(client, StubSharepointClient)
    assert recorded["credentials"] == {"client_id": "abc", "site": "TeamSite", "tenant": "contoso"}
    assert client._srcfiles == []


async def test_sharepoint_resolve_drive_uses_library():
    fake = FakeGraphClient({"drive-1": FakeDrive()})
    client = make_sharepoint_client(fake, drive_id="drive-1")
    recorded_library = {}

    async def _resolve_drive(library_name=None):
        recorded_library["library"] = library_name
        return SimpleNamespace(id="drive-1", name=library_name)

    client._resolve_drive = _resolve_drive
    manager = SharePointFileManager("TeamSite", library="Reports")
    manager.adopt_client(client)

    assert await manager._ready() == "drive-1"
    assert recorded_library["library"] == "Reports"


async def test_sharepoint_subsite_via_explicit_site_path():
    recorded = {}

    class StubSharepointClient:
        def __init__(self, *, credentials):
            recorded["credentials"] = credentials
            self._srcfiles = []

    manager = SharePointFileManager("hr/benefits")
    assert manager.site == "hr/benefits"

    with mock.patch.object(sharepoint_module, "SharepointClient", StubSharepointClient):
        client = manager._build_client()

    assert isinstance(client, StubSharepointClient)
    assert recorded["credentials"]["site"] == "hr/benefits"
    assert client._srcfiles == []


async def test_sharepoint_manager_never_populates_srcfiles():
    fake = FakeGraphClient({"drive-1": FakeDrive()})
    client = make_sharepoint_client(fake, drive_id="drive-1")
    manager = SharePointFileManager("TeamSite")
    manager.adopt_client(client)

    await manager._ready()

    assert client._srcfiles == []


def test_subclass_overrides_only_allowed_members():
    # __annotations__ is CPython's own bookkeeping for the annotated class-level
    # assignments the blueprint fixes (`manager_name: str = ...`, `client_class: type
    # = ...`); it carries no additional override surface beyond those two allowed names.
    allowed = {
        "manager_name",
        "client_class",
        "__init__",
        "_build_client",
        "_resolve_drive_id",
        "__doc__",
        "__module__",
        "__qualname__",
        "__abstractmethods__",
        "_abc_impl",
        "__firstlineno__",
        "__static_attributes__",
        "__annotations__",
    }
    assert set(vars(SharePointFileManager)) - allowed == set()
