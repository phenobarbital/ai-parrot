"""FEAT-603 TASK-3757 — OneDriveFileManager."""
import sys

import pytest

# The repository-wide test bootstrap installs a non-package compatibility stub
# for this module before collection. This task verifies the real new submodule.
sys.modules.pop("parrot.interfaces.file", None)

from parrot.interfaces.file.onedrive import OneDriveFileManager

from ._graph_fakes import FakeDrive, FakeGraphClient, make_onedrive_client


# TASK-3751..3754 supply GraphDriveFileManager's remaining FileManagerInterface
# methods after this task's dependency boundary. Exercise this subclass's own
# hooks without changing that shared base in this task.
OneDriveFileManager.__abstractmethods__ = frozenset()


@pytest.fixture
def fake():
    """Create two independently resolvable OneDrive fakes."""
    return FakeGraphClient(
        {"drive-me": FakeDrive("drive-me"), "drive-u": FakeDrive("drive-u")},
        me_drive_id="drive-me",
        user_drives={"u@t.com": "drive-u"},
    )


async def test_onedrive_manager_me_requires_delegated(fake):
    """Reject app-only ``me`` and resolve it under delegated authentication."""
    app_only = OneDriveFileManager(user="me")
    app_only.adopt_client(make_onedrive_client(fake, app_only=True))

    with pytest.raises(RuntimeError, match="requires delegated, cached or on_behalf_of authentication"):
        await app_only._ready()

    delegated = OneDriveFileManager(user="me")
    delegated.adopt_client(make_onedrive_client(fake, app_only=False))

    assert await delegated._ready() == "drive-me"


async def test_onedrive_manager_user_drive(fake):
    """Resolve a UPN through the user-drive client hook under app-only auth."""
    manager = OneDriveFileManager(user="u@t.com")
    manager.adopt_client(make_onedrive_client(fake, app_only=True))

    assert await manager._ready() == "drive-u"


async def test_two_managers_one_client_different_users(fake):
    """Keep cached drive resolution isolated by user when clients are shared."""
    client = make_onedrive_client(fake, app_only=False)
    me_manager = OneDriveFileManager(user="me")
    user_manager = OneDriveFileManager(user="u@t.com")
    me_manager.adopt_client(client)
    user_manager.adopt_client(client)

    assert await me_manager._ready() == "drive-me"
    assert await user_manager._ready() == "drive-u"


def test_constructor_rejects_empty_user():
    """Require an explicit, non-whitespace OneDrive user target."""
    with pytest.raises(ValueError):
        OneDriveFileManager(user="  ")


def test_subclass_overrides_only_allowed_members():
    """Keep OneDrive targeting limited to its permitted subclass hooks."""
    allowed = {
        "manager_name", "client_class", "__init__", "_build_client", "_resolve_drive_id", "__doc__", "__module__",
        "__qualname__", "__abstractmethods__", "_abc_impl", "__firstlineno__", "__static_attributes__", "__annotations__",
    }
    assert set(vars(OneDriveFileManager)) - allowed == set()
