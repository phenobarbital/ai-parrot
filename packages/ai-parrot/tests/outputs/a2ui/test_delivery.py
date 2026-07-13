"""Unit tests for the A2UI delivery bridge (TASK-1733)."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.delivery import deliver_artifact

pytestmark = pytest.mark.asyncio


def _artifact(*, persisted=True, inline=True, path=None) -> RenderedArtifact:
    kwargs = dict(
        artifact_id="art-1",
        mime_type="application/pdf",
        filename="report.pdf",
        title="Report",
        surface="pdf",
        source_envelope_ref="env-1" if persisted else None,
    )
    if inline:
        kwargs["content"] = b"%PDF-data"
    else:
        kwargs["path"] = path
    return RenderedArtifact(**kwargs)


def _owner():
    owner = type("Owner", (), {})()
    owner.logger = logging.getLogger("test.owner")
    owner.send_notification = AsyncMock(return_value={"status": "ok"})
    return owner


class TestRenderedArtifactNotificationBridge:
    async def test_rendered_artifact_notification_bridge(self):
        owner = _owner()
        await deliver_artifact(
            owner, _artifact(), recipients=["u@x.com"], provider="email",
            message="hi",
        )
        kwargs = owner.send_notification.await_args.kwargs
        report = kwargs["report"]
        assert len(report.files) == 1  # routed via report.files PRIORITY-1
        # The delivered file PRESERVES the artifact's filename (not a random temp name).
        assert report.files[0].name == "report.pdf"
        # Temp dir was cleaned after send (mock doesn't read it).
        assert not report.files[0].exists()

    async def test_telegram_attachment_flows_as_document(self):
        owner = _owner()
        await deliver_artifact(
            owner, _artifact(), recipients="123", provider="telegram", message="hi",
        )
        kwargs = owner.send_notification.await_args.kwargs
        assert kwargs["report"].files  # routed via report.files precedence
        assert owner.send_notification.await_args.args[0] == "hi"

    async def test_slack_public_url_downgrade(self, caplog):
        owner = _owner()
        store = AsyncMock()
        store.get_public_url = AsyncMock(return_value="https://s3/artifact.html")
        with caplog.at_level(logging.WARNING):
            await deliver_artifact(
                owner, _artifact(persisted=True), recipients="#chan",
                provider="slack", message="hi",
                artifact_store=store, user_id="u", agent_id="a", session_id="s",
            )
        kwargs = owner.send_notification.await_args.kwargs
        assert kwargs["a2ui_artifact_url"] == "https://s3/artifact.html"
        assert "report" not in kwargs  # Slack does not attach files
        assert any("degraded delivery" in r.message.lower() for r in caplog.records)

    async def test_slack_unpersisted_artifact_logs_and_sends_text(self, caplog):
        owner = _owner()
        with caplog.at_level(logging.WARNING):
            await deliver_artifact(
                owner, _artifact(persisted=False), recipients="#chan",
                provider="slack", message="hi",
            )
        kwargs = owner.send_notification.await_args.kwargs
        assert "a2ui_artifact_url" not in kwargs
        assert any("text-only" in r.message.lower() for r in caplog.records)

    async def test_teams_routes_via_report_files(self):
        # Teams delivery routes the artifact through report.files; the Graph-upload
        # -vs-downgrade decision + logging now lives in _send_teams (not the bridge),
        # so the bridge emits no misleading "pending"/"filenames" warning.
        owner = _owner()
        await deliver_artifact(
            owner, _artifact(), recipients="chan", provider="teams", message="hi",
        )
        assert owner.send_notification.await_args.kwargs["report"].files

    async def test_inline_content_materialized_and_cleaned(self):
        owner = _owner()
        captured = {}

        async def capture(*args, **kwargs):
            report = kwargs["report"]
            p = report.files[0]
            captured["path"] = p
            captured["existed_during_send"] = p.exists()
            captured["bytes"] = p.read_bytes()
            return {"status": "ok"}

        owner.send_notification = capture
        await deliver_artifact(
            owner, _artifact(inline=True), recipients=["u@x.com"],
            provider="email", message="hi",
        )
        assert captured["existed_during_send"] is True
        assert captured["bytes"] == b"%PDF-data"
        assert captured["path"].name == "report.pdf"  # filename preserved
        # Temp file + its dir cleaned up after send.
        assert not captured["path"].exists()
        assert not captured["path"].parent.exists()

    async def test_existing_path_not_deleted(self, tmp_path):
        owner = _owner()
        real = tmp_path / "keep.pdf"
        real.write_bytes(b"%PDF-keep")
        await deliver_artifact(
            owner, _artifact(inline=False, path=real), recipients=["u@x.com"],
            provider="email", message="hi",
        )
        # A pre-existing artifact path must survive (only temp files are cleaned).
        assert real.exists()
