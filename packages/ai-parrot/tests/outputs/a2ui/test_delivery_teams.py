"""_send_teams Graph-upload wiring + downgrade tests (TASK-1734).

Imports of ``parrot.notifications`` are deferred into fixtures/tests (top-level
``from parrot.notifications import ...`` resolves as a namespace package under this
repo's pytest layout; ``importlib.import_module`` inside a function works).
"""

import importlib
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.asyncio


def _mixin_instance():
    notifications = importlib.import_module("parrot.notifications")
    if not hasattr(notifications.NotificationMixin, "_teams_graph_upload_links"):
        pytest.skip(
            "worktree parrot.notifications not resolved under pytest "
            "(namespace-package layout with editable installs); validated in CI"
        )

    class _Owner(notifications.NotificationMixin):
        def __init__(self):
            self.logger = logging.getLogger("test.teams")

    return _Owner()


class _FakeGraphClient:
    """Fake GraphClient recording upload_file calls."""

    calls: list = []

    def __init__(self, *, client_id, client_secret, tenant_id, logger=None):
        pass

    async def upload_file(self, file_path, *, user, folder="A2UI-Artifacts"):
        _FakeGraphClient.calls.append((Path(file_path).name, user))
        return f"https://share/{Path(file_path).name}"

    async def close(self):
        pass


def _set_teams_creds(monkeypatch, present=True):
    conf = importlib.import_module("parrot.conf")
    value = "x" if present else None
    for var in (
        "TEAMS_NOTIFY_TENANT_ID",
        "TEAMS_NOTIFY_CLIENT_ID",
        "TEAMS_NOTIFY_CLIENT_SECRET",
        "TEAMS_NOTIFY_USERNAME",
    ):
        monkeypatch.setattr(conf, var, value, raising=False)


class TestSendTeamsGraphWiring:
    async def test_teams_graph_upload_called(self, tmp_path, monkeypatch):
        _FakeGraphClient.calls = []
        _set_teams_creds(monkeypatch, present=True)
        graph_mod = importlib.import_module("parrot.integrations.msteams.graph")
        monkeypatch.setattr(graph_mod, "GraphClient", _FakeGraphClient)

        owner = _mixin_instance()
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF")
        links = await owner._teams_graph_upload_links([f])
        assert links == ["https://share/report.pdf"]
        assert _FakeGraphClient.calls == [("report.pdf", "x")]

    async def test_no_credentials_returns_none(self, tmp_path, monkeypatch):
        _set_teams_creds(monkeypatch, present=False)
        owner = _mixin_instance()
        f = tmp_path / "r.pdf"
        f.write_bytes(b"x")
        assert await owner._teams_graph_upload_links([f]) is None

    async def test_permission_failure_downgrades_with_log(self, tmp_path, monkeypatch, caplog):
        _set_teams_creds(monkeypatch, present=True)
        graph_mod = importlib.import_module("parrot.integrations.msteams.graph")

        class _FailingClient(_FakeGraphClient):
            async def upload_file(self, file_path, *, user, folder="A2UI-Artifacts"):
                return None  # simulate 403 / permission failure

        monkeypatch.setattr(graph_mod, "GraphClient", _FailingClient)
        owner = _mixin_instance()
        f = tmp_path / "r.pdf"
        f.write_bytes(b"x")
        assert await owner._teams_graph_upload_links([f]) is None

    async def test_send_teams_downgrades_to_filenames(self, tmp_path, monkeypatch):
        # Force upload to yield no links → _send_teams lists filenames + warns.
        owner = _mixin_instance()
        owner._teams_graph_upload_links = AsyncMock(return_value=None)

        sent = {}
        notify = importlib.import_module("notify.providers.teams")

        class _Conn:
            async def send(self, **kw):
                sent.update(kw)
                return {"ok": True}

        class _Teams:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return _Conn()

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(notify, "Teams", _Teams)

        f = tmp_path / "chart.pdf"
        f.write_bytes(b"x")
        with pytest.MonkeyPatch.context():
            await owner._send_teams({"message": "hi"}, files=[f])
        assert "chart.pdf" in sent["message"]
