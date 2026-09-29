"""Keep the notification backend outside the Agent startup import graph."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("statement", ["import parrot.notifications", "from parrot.bots import Agent"])
def test_startup_does_not_import_notify(statement: str) -> None:
    """Fail even on attempted notify imports, in an uncontaminated interpreter."""
    code = f"""
import importlib.abc
import sys

class BlockNotify(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "notify" or fullname.startswith("notify."):
            raise AssertionError(f"Startup attempted to import {{fullname}}")
        return None

sys.meta_path.insert(0, BlockNotify())
{statement}
from parrot.notifications import NotificationConfig, NotificationMixin, NotificationProvider
assert NotificationConfig().provider is NotificationProvider.EMAIL
assert NotificationMixin.notification_succeeded({{"status": "success"}})
assert not any(name == "notify" or name.startswith("notify.") for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "VAULT_ENABLED": "false"},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_legacy_exports_resolve_real_classes() -> None:
    """Explicit callers still receive the original backend classes, cached."""
    import notify
    import notify.models
    import parrot.notifications as notifications

    for name in (
        "Notify",
        "Actor",
        "Channel",
        "Chat",
        "TeamsChannel",
        "TeamsWebhook",
        "TeamsCard",
        "CardAction",
        "TeamsSection",
    ):
        backend = notify if name == "Notify" else notify.models
        assert name in dir(notifications)
        assert getattr(notifications, name) is getattr(backend, name)
        assert vars(notifications)[name] is getattr(backend, name)

    with pytest.raises(AttributeError, match="has no attribute"):
        _ = notifications.unknown_notification_export
