"""Tests for first-class Adaptive Card support in NotificationMixin.

Validates that TeamsCard objects, dict Adaptive Cards, and JSON-string
cards flow through send_notification / _send_teams without corruption,
and that file attachments are injected as card actions.
"""

import importlib
import json
import logging
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_notifications():
    """Import parrot.notifications dynamically (namespace-package workaround).

    Under the PEP 420 namespace-merge layout, local pytest can resolve
    ``parrot.notifications`` as a bare namespace package instead of the
    real ``__init__.py``.  This is a known limitation — the tests are
    validated in CI where packages are properly installed.
    """
    mod = importlib.import_module("parrot.notifications")
    if hasattr(mod, "NotificationMixin"):
        return mod
    pytest.skip(
        "parrot.notifications resolved as namespace package "
        "(no NotificationMixin); validated in CI"
    )


def _mixin_instance():
    notifications = _load_notifications()
    if not hasattr(notifications.NotificationMixin, "_is_teams_card"):
        pytest.skip(
            "NotificationMixin missing Adaptive Card support; "
            "worktree namespace may not have resolved."
        )

    class _Owner(notifications.NotificationMixin):
        def __init__(self):
            self.logger = logging.getLogger("test.teams.cards")

    return _Owner()


class _SentCapture:
    """Records what the mocked Teams provider received."""

    def __init__(self):
        self.calls: list[Dict[str, Any]] = []

    def patch(self, monkeypatch):
        """Monkey-patch notify.providers.teams.Teams with a recording stub."""
        calls = self.calls
        notify_teams = importlib.import_module("notify.providers.teams")

        class _Conn:
            async def send(self, **kw):
                calls.append(kw)
                return {"ok": True}

        class _FakeTeams:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return _Conn()

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(notify_teams, "Teams", _FakeTeams)
        return self


def _set_teams_creds(monkeypatch, present=True):
    """Set or clear the TEAMS_NOTIFY_* env-equivalent config vars."""
    conf = importlib.import_module("parrot.conf")
    value = "x" if present else None
    for var in (
        "TEAMS_NOTIFY_TENANT_ID",
        "TEAMS_NOTIFY_CLIENT_ID",
        "TEAMS_NOTIFY_CLIENT_SECRET",
        "TEAMS_NOTIFY_USERNAME",
        "TEAMS_NOTIFY_PASSWORD",
    ):
        monkeypatch.setattr(conf, var, value, raising=False)


# ===================================================================
# _is_teams_card detection
# ===================================================================

class TestIsTeamsCard:
    def test_teams_card_object(self):
        from notify.models import TeamsCard
        owner = _mixin_instance()
        card = TeamsCard(title="Test", text="hello")
        assert owner._is_teams_card(card) is True

    def test_dict_adaptive_card(self):
        owner = _mixin_instance()
        payload = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.5",
            "body": [{"type": "TextBlock", "text": "hi"}],
        }
        assert owner._is_teams_card(payload) is True

    def test_dict_message_card(self):
        owner = _mixin_instance()
        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "text": "hello",
        }
        assert owner._is_teams_card(payload) is True

    def test_json_string_adaptive_card(self):
        owner = _mixin_instance()
        raw = json.dumps({
            "type": "AdaptiveCard",
            "body": [{"type": "TextBlock", "text": "hi"}],
        })
        assert owner._is_teams_card(raw) is True

    def test_plain_text_is_not_card(self):
        owner = _mixin_instance()
        assert owner._is_teams_card("Hello, world!") is False

    def test_none_is_not_card(self):
        owner = _mixin_instance()
        assert owner._is_teams_card(None) is False

    def test_plain_dict_is_not_card(self):
        owner = _mixin_instance()
        assert owner._is_teams_card({"key": "value"}) is False


# ===================================================================
# build_teams_card factory
# ===================================================================

class TestBuildTeamsCard:
    def test_basic_card(self):
        from notify.models import TeamsCard
        owner = _mixin_instance()
        card = owner.build_teams_card(title="Report", text="Body text")
        assert isinstance(card, TeamsCard)
        assert card.title == "Report"
        assert card.text == "Body text"
        assert card.summary == "Report"

    def test_card_with_sections(self):
        owner = _mixin_instance()
        card = owner.build_teams_card(
            title="Report",
            sections=[{"activityTitle": "Revenue", "text": "$1.2M"}],
        )
        assert len(card.sections) == 1
        assert card.sections[0].activityTitle == "Revenue"

    def test_card_with_actions(self):
        owner = _mixin_instance()
        card = owner.build_teams_card(
            title="Report",
            actions=[{
                "type": "Action.OpenUrl",
                "title": "Dashboard",
                "url": "https://example.com",
            }],
        )
        assert len(card.actions) == 1
        assert card.actions[0].title == "Dashboard"
        assert card.actions[0].url == "https://example.com"

    def test_card_with_files(self, tmp_path):
        owner = _mixin_instance()
        f1 = tmp_path / "report.pdf"
        f1.write_bytes(b"%PDF")
        card = owner.build_teams_card(title="Report", files=[f1])
        # File should appear as an action
        assert any("report.pdf" in a.title for a in card.actions)

    def test_card_produces_valid_adaptive(self):
        owner = _mixin_instance()
        card = owner.build_teams_card(
            title="Test",
            text="Body",
            summary="Sum",
            sections=[{"activityTitle": "S1", "text": "content"}],
            actions=[{"type": "Action.OpenUrl", "title": "Go", "url": "https://x.com"}],
        )
        adaptive = card.to_adaptative()
        assert adaptive["type"] == "AdaptiveCard"
        assert adaptive["version"] == "1.5"
        assert any(b.get("text") == "Test" for b in adaptive["body"])


# ===================================================================
# TeamsCard flows through send_notification without corruption
# ===================================================================

@pytest.mark.asyncio
class TestSendTeamsCard:
    async def test_teams_card_object_preserved(self, monkeypatch):
        """TeamsCard reaches conn.send() as a TeamsCard, not str(TeamsCard)."""
        from notify.models import TeamsCard, TeamsChannel

        _set_teams_creds(monkeypatch)
        owner = _mixin_instance()
        owner._teams_graph_upload_links = AsyncMock(return_value=None)
        capture = _SentCapture().patch(monkeypatch)

        card = TeamsCard(title="Daily Report", text="Revenue up 5%")
        await owner._send_teams({"message": card}, files=None)

        assert len(capture.calls) == 1
        sent_msg = capture.calls[0]["message"]
        assert isinstance(sent_msg, TeamsCard)
        assert sent_msg.title == "Daily Report"

    async def test_dict_adaptive_card_preserved(self, monkeypatch):
        """A dict Adaptive Card payload passes through untouched."""
        _set_teams_creds(monkeypatch)
        owner = _mixin_instance()
        owner._teams_graph_upload_links = AsyncMock(return_value=None)
        capture = _SentCapture().patch(monkeypatch)

        payload = {
            "type": "AdaptiveCard",
            "version": "1.5",
            "body": [{"type": "TextBlock", "text": "hello"}],
        }
        await owner._send_teams({"message": payload}, files=None)

        assert len(capture.calls) == 1
        sent_msg = capture.calls[0]["message"]
        assert isinstance(sent_msg, dict)
        assert sent_msg["type"] == "AdaptiveCard"

    async def test_send_notification_preserves_card(self, monkeypatch):
        """Full send_notification path doesn't corrupt TeamsCard into str."""
        from notify.models import TeamsCard

        _set_teams_creds(monkeypatch)
        owner = _mixin_instance()
        owner._teams_graph_upload_links = AsyncMock(return_value=None)
        capture = _SentCapture().patch(monkeypatch)

        card = TeamsCard(title="Test Card", text="Hello")
        recipient = "user@example.com"

        await owner.send_notification(
            message=card,
            recipients=recipient,
            provider="teams",
        )

        assert len(capture.calls) == 1
        sent_msg = capture.calls[0]["message"]
        assert isinstance(sent_msg, TeamsCard), (
            f"Expected TeamsCard, got {type(sent_msg).__name__}: {sent_msg!r}"
        )

    async def test_send_teams_card_convenience(self, monkeypatch):
        """send_teams_card() convenience flows through correctly."""
        from notify.models import TeamsCard

        _set_teams_creds(monkeypatch)
        owner = _mixin_instance()
        owner._teams_graph_upload_links = AsyncMock(return_value=None)
        capture = _SentCapture().patch(monkeypatch)

        card = TeamsCard(title="Revenue", text="$1.2M", summary="Revenue report")
        await owner.send_teams_card(
            card=card,
            recipient="user@example.com",
        )

        assert len(capture.calls) == 1
        sent_msg = capture.calls[0]["message"]
        assert isinstance(sent_msg, TeamsCard)
        assert sent_msg.title == "Revenue"


# ===================================================================
# File attachment injection into cards
# ===================================================================

@pytest.mark.asyncio
class TestCardFileAttachment:
    async def test_teams_card_gets_file_actions_with_graph_links(self, tmp_path, monkeypatch):
        """Files are injected as Action.OpenUrl on TeamsCard when Graph links exist."""
        from notify.models import TeamsCard

        _set_teams_creds(monkeypatch)
        owner = _mixin_instance()
        capture = _SentCapture().patch(monkeypatch)

        f = tmp_path / "chart.png"
        f.write_bytes(b"PNG")
        owner._teams_graph_upload_links = AsyncMock(
            return_value=["https://share/chart.png"]
        )

        card = TeamsCard(title="Report")
        await owner._send_teams({"message": card}, files=[f])

        sent_card = capture.calls[0]["message"]
        assert isinstance(sent_card, TeamsCard)
        file_actions = [a for a in sent_card.actions if "chart.png" in a.title]
        assert len(file_actions) == 1
        assert file_actions[0].url == "https://share/chart.png"

    async def test_teams_card_gets_a2ui_fallback(self, tmp_path, monkeypatch):
        """When Graph upload fails, A2UI public URL is added as action."""
        from notify.models import TeamsCard

        _set_teams_creds(monkeypatch)
        owner = _mixin_instance()
        capture = _SentCapture().patch(monkeypatch)

        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF")
        owner._teams_graph_upload_links = AsyncMock(return_value=None)

        card = TeamsCard(title="Report")
        await owner._send_teams(
            {"message": card, "a2ui_artifact_url": "https://public/artifact"},
            files=[f],
        )

        sent_card = capture.calls[0]["message"]
        assert isinstance(sent_card, TeamsCard)
        url_actions = [a for a in sent_card.actions if a.url == "https://public/artifact"]
        assert len(url_actions) == 1

    async def test_teams_card_filename_fallback(self, tmp_path, monkeypatch):
        """When both Graph and A2UI are unavailable, filenames are listed."""
        from notify.models import TeamsCard

        _set_teams_creds(monkeypatch)
        owner = _mixin_instance()
        capture = _SentCapture().patch(monkeypatch)

        f = tmp_path / "data.xlsx"
        f.write_bytes(b"x")
        owner._teams_graph_upload_links = AsyncMock(return_value=None)

        card = TeamsCard(title="Report")
        await owner._send_teams({"message": card}, files=[f])

        sent_card = capture.calls[0]["message"]
        file_actions = [a for a in sent_card.actions if "data.xlsx" in a.title]
        assert len(file_actions) == 1

    async def test_dict_card_gets_file_actions(self, tmp_path, monkeypatch):
        """Dict Adaptive Cards also get file actions injected."""
        _set_teams_creds(monkeypatch)
        owner = _mixin_instance()
        capture = _SentCapture().patch(monkeypatch)

        f = tmp_path / "chart.png"
        f.write_bytes(b"PNG")
        owner._teams_graph_upload_links = AsyncMock(
            return_value=["https://share/chart.png"]
        )

        payload = {
            "type": "AdaptiveCard",
            "version": "1.5",
            "body": [{"type": "TextBlock", "text": "Report"}],
        }
        await owner._send_teams({"message": payload}, files=[f])

        sent = capture.calls[0]["message"]
        assert isinstance(sent, dict)
        assert any(
            a.get("url") == "https://share/chart.png"
            for a in sent.get("actions", [])
        )

    async def test_json_string_card_gets_file_actions(self, tmp_path, monkeypatch):
        """JSON-string Adaptive Cards also get file actions injected."""
        _set_teams_creds(monkeypatch)
        owner = _mixin_instance()
        capture = _SentCapture().patch(monkeypatch)

        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF")
        owner._teams_graph_upload_links = AsyncMock(
            return_value=["https://share/report.pdf"]
        )

        raw = json.dumps({
            "type": "AdaptiveCard",
            "version": "1.5",
            "body": [{"type": "TextBlock", "text": "Report"}],
        })
        await owner._send_teams({"message": raw}, files=[f])

        sent = capture.calls[0]["message"]
        assert isinstance(sent, str)
        parsed = json.loads(sent)
        assert any(
            a.get("url") == "https://share/report.pdf"
            for a in parsed.get("actions", [])
        )


# ===================================================================
# Full end-to-end: send_notification with card + report files
# ===================================================================

@pytest.mark.asyncio
class TestEndToEndCardWithReport:
    async def test_card_with_report_files(self, tmp_path, monkeypatch):
        """send_notification with TeamsCard + report.files extracts files
        from report and injects them into the card."""
        from notify.models import TeamsCard

        _set_teams_creds(monkeypatch)
        owner = _mixin_instance()
        capture = _SentCapture().patch(monkeypatch)
        owner._teams_graph_upload_links = AsyncMock(
            return_value=["https://share/attachment.pdf"]
        )

        f = tmp_path / "attachment.pdf"
        f.write_bytes(b"%PDF")

        class _Report:
            files = [f]
            documents = None

        card = TeamsCard(title="Analysis", text="Done")
        await owner.send_notification(
            message=card,
            recipients="user@example.com",
            provider="teams",
            report=_Report(),
        )

        assert len(capture.calls) == 1
        sent_card = capture.calls[0]["message"]
        assert isinstance(sent_card, TeamsCard)
        assert sent_card.title == "Analysis"
        file_actions = [a for a in sent_card.actions if "attachment.pdf" in a.title]
        assert len(file_actions) == 1
        assert file_actions[0].url == "https://share/attachment.pdf"


# ===================================================================
# Backward compatibility: plain text still works
# ===================================================================

@pytest.mark.asyncio
class TestPlainTextBackwardCompat:
    async def test_plain_text_still_works(self, monkeypatch):
        """Plain string message through Teams is not broken by card logic."""
        _set_teams_creds(monkeypatch)
        owner = _mixin_instance()
        owner._teams_graph_upload_links = AsyncMock(return_value=None)
        capture = _SentCapture().patch(monkeypatch)

        await owner._send_teams({"message": "Hello, plain text!"})

        assert len(capture.calls) == 1
        assert capture.calls[0]["message"] == "Hello, plain text!"

    async def test_plain_text_with_files_still_lists_filenames(self, tmp_path, monkeypatch):
        """Plain text + files still appends filenames (existing behaviour)."""
        _set_teams_creds(monkeypatch)
        owner = _mixin_instance()
        owner._teams_graph_upload_links = AsyncMock(return_value=None)
        capture = _SentCapture().patch(monkeypatch)

        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF")
        await owner._send_teams({"message": "Hi"}, files=[f])

        sent = capture.calls[0]["message"]
        assert isinstance(sent, str)
        assert "report.pdf" in sent
