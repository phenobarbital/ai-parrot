"""Unit tests for parrot.interfaces.zammad.ZammadInterface."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from parrot.interfaces.zammad import (
    TicketCreatePayload,
    TicketUpdatePayload,
    UserCreatePayload,
    ZammadAuthError,
    ZammadConfig,
    ZammadConnectionError,
    ZammadError,
    ZammadInterface,
    _extract_filename,
)


@pytest.fixture
def zammad():
    """Return a ZammadInterface configured with explicit kwargs."""
    return ZammadInterface(
        instance_url="https://zammad.example.com",
        token="test-token",
        default_group="Support",
    )


def _mock_response(status: int = 200, json_data=None, headers=None):
    """Build a mock aiohttp response usable as an async context manager."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data if json_data is not None else {})
    resp.text = AsyncMock(return_value="error body")
    resp.read = AsyncMock(return_value=b"binary-data")
    resp.headers = headers or {}

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


class TestZammadConfig:
    """Tests for the ZammadConfig Pydantic model."""

    def test_config_from_kwargs(self):
        cfg = ZammadConfig(instance_url="https://z.example.com", token="tok")
        assert cfg.on_behalf_of_header == "From"

    def test_config_custom_header(self):
        cfg = ZammadConfig(
            instance_url="https://z.example.com",
            token="tok",
            on_behalf_of_header="X-On-Behalf-Of",
        )
        assert cfg.on_behalf_of_header == "X-On-Behalf-Of"


class TestZammadInterfaceInit:
    """Tests for ZammadInterface instantiation."""

    def test_init_from_kwargs(self, zammad):
        assert zammad.config.instance_url == "https://zammad.example.com"
        assert zammad.config.token == "test-token"
        assert zammad.config.default_group == "Support"

    def test_init_from_env(self, monkeypatch):
        monkeypatch.setattr("parrot.interfaces.zammad.ZAMMAD_INSTANCE", "https://env.example.com")
        monkeypatch.setattr("parrot.interfaces.zammad.ZAMMAD_TOKEN", "env-token")
        z = ZammadInterface()
        assert z.config.instance_url == "https://env.example.com"
        assert z.config.token == "env-token"

    def test_init_missing_url_raises(self, monkeypatch):
        monkeypatch.setattr("parrot.interfaces.zammad.ZAMMAD_INSTANCE", None)
        monkeypatch.setattr("parrot.interfaces.zammad.ZAMMAD_TOKEN", "env-token")
        with pytest.raises(ZammadError, match="instance URL is required"):
            ZammadInterface(token="tok")

    def test_init_missing_token_raises(self, monkeypatch):
        monkeypatch.setattr("parrot.interfaces.zammad.ZAMMAD_INSTANCE", None)
        monkeypatch.setattr("parrot.interfaces.zammad.ZAMMAD_TOKEN", None)
        with pytest.raises(ZammadError, match="API token is required"):
            ZammadInterface(instance_url="https://z.example.com")

    def test_attachment_dir_not_created_eagerly(self, zammad):
        """A temp dir is only created on first attachment download."""
        assert zammad.config.attachment_dir is None


class TestZammadInterfaceContextManager:
    """Tests for the async context manager and session lifecycle."""

    @pytest.mark.asyncio
    async def test_context_manager(self, zammad):
        async with zammad:
            assert zammad._session is not None
            assert not zammad._session.closed
        assert zammad._session is None or zammad._session.closed


class TestZammadRequest:
    """Tests for the core _request() method."""

    @pytest.mark.asyncio
    async def test_request_auth_header(self, zammad):
        session = await zammad._get_session()
        assert session.headers["Authorization"] == "Bearer test-token"
        await zammad.close()

    @pytest.mark.asyncio
    async def test_request_on_behalf_of_from(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(
            return_value=_mock_response(200, {"id": 1})
        )
        zammad._session = mock_session

        await zammad._request("GET", "/api/v1/tickets/1", on_behalf_of="jane@example.com")

        _, kwargs = mock_session.request.call_args
        assert kwargs["headers"]["From"] == "jane@example.com"

    @pytest.mark.asyncio
    async def test_request_on_behalf_of_custom_header(self):
        z = ZammadInterface(
            instance_url="https://zammad.example.com",
            token="tok",
            on_behalf_of_header="X-On-Behalf-Of",
        )
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(return_value=_mock_response(200, {"id": 1}))
        z._session = mock_session

        await z._request("GET", "/api/v1/tickets/1", on_behalf_of="42")

        _, kwargs = mock_session.request.call_args
        assert kwargs["headers"]["X-On-Behalf-Of"] == "42"
        assert "From" not in kwargs["headers"]

    @pytest.mark.asyncio
    async def test_request_no_on_behalf_of(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(return_value=_mock_response(200, {"id": 1}))
        zammad._session = mock_session

        await zammad._request("GET", "/api/v1/tickets/1")

        _, kwargs = mock_session.request.call_args
        assert kwargs["headers"] == {}

    @pytest.mark.asyncio
    async def test_error_handling_4xx(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(return_value=_mock_response(400))
        zammad._session = mock_session

        with pytest.raises(ZammadError) as exc_info:
            await zammad._request("GET", "/api/v1/tickets/1")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_error_handling_401(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(return_value=_mock_response(401))
        zammad._session = mock_session

        with pytest.raises(ZammadAuthError):
            await zammad._request("GET", "/api/v1/tickets/1")

    @pytest.mark.asyncio
    async def test_error_handling_network(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(side_effect=aiohttp.ClientError("boom"))
        zammad._session = mock_session

        with pytest.raises(ZammadConnectionError):
            await zammad._request("GET", "/api/v1/tickets/1")


class TestTicketOperations:
    """Tests for ticket CRUD and search."""

    @pytest.mark.asyncio
    async def test_create_ticket_payload(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(
            return_value=_mock_response(200, {"id": 42, "title": "Test Ticket"})
        )
        zammad._session = mock_session

        payload = TicketCreatePayload(
            title="Test Ticket",
            group="Support",
            customer="customer@example.com",
            article_body="Please help",
        )
        result = await zammad.create_ticket(payload)

        assert result["id"] == 42
        _, kwargs = mock_session.request.call_args
        assert kwargs["json"]["title"] == "Test Ticket"
        assert kwargs["json"]["article"]["body"] == "Please help"

    @pytest.mark.asyncio
    async def test_create_ticket_with_attachments(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(return_value=_mock_response(200, {"id": 43}))
        zammad._session = mock_session

        payload = TicketCreatePayload(
            title="With Attachment",
            group="Support",
            customer="customer@example.com",
            article_body="See attached",
            attachments=[
                {"filename": "report.txt", "data": "aGVsbG8=", "mime-type": "text/plain"}
            ],
        )
        await zammad.create_ticket(payload)

        _, kwargs = mock_session.request.call_args
        sent_attachments = kwargs["json"]["article"]["attachments"]
        assert sent_attachments[0]["filename"] == "report.txt"
        assert sent_attachments[0]["data"] == "aGVsbG8="

    @pytest.mark.asyncio
    async def test_update_ticket(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(
            return_value=_mock_response(200, {"id": 42, "title": "Updated"})
        )
        zammad._session = mock_session

        payload = TicketUpdatePayload(ticket_id=42, title="Updated", article_body="Follow-up")
        result = await zammad.update_ticket(payload)

        assert result["title"] == "Updated"
        args, kwargs = mock_session.request.call_args
        assert args[0] == "PUT"
        assert kwargs["json"]["title"] == "Updated"

    @pytest.mark.asyncio
    async def test_get_ticket(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(return_value=_mock_response(200, {"id": 42}))
        zammad._session = mock_session

        result = await zammad.get_ticket(42)
        assert result["id"] == 42

    @pytest.mark.asyncio
    async def test_search_tickets_pagination(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(
            side_effect=[
                _mock_response(200, {"tickets": [{"id": 1}]}),
                _mock_response(200, {"tickets": [{"id": 2}]}),
            ]
        )
        zammad._session = mock_session

        page1 = await zammad.search_tickets("foo", page=1, per_page=1)
        page2 = await zammad.search_tickets("foo", page=2, per_page=1)
        aggregated = page1["tickets"] + page2["tickets"]

        assert aggregated == [{"id": 1}, {"id": 2}]
        first_call_kwargs = mock_session.request.call_args_list[0][1]
        assert first_call_kwargs["params"]["limit"] == 1
        assert first_call_kwargs["params"]["page"] == 1

    @pytest.mark.asyncio
    async def test_list_tickets_state_filter(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(
            return_value=_mock_response(200, {"tickets": [{"id": 1, "state_id": 2}]})
        )
        zammad._session = mock_session

        result = await zammad.list_tickets(state_ids=[1, 2])

        assert result["tickets"] == [{"id": 1, "state_id": 2}]
        _, kwargs = mock_session.request.call_args
        assert kwargs["params"]["state_ids"] == "1,2"


class TestArticleAndAttachmentOperations:
    """Tests for article listing and attachment download."""

    @pytest.mark.asyncio
    async def test_get_articles(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(
            return_value=_mock_response(200, [{"id": 1, "body": "hi"}])
        )
        zammad._session = mock_session

        articles = await zammad.get_articles(42)
        assert articles == [{"id": 1, "body": "hi"}]

    @pytest.mark.asyncio
    async def test_get_attachment_saves_file(self, zammad, tmp_path):
        zammad.config.attachment_dir = str(tmp_path)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.get = MagicMock(
            return_value=_mock_response(
                200,
                headers={"Content-Disposition": 'attachment; filename="report.pdf"'},
            )
        )
        zammad._session = mock_session

        data, file_path = await zammad.get_attachment(1, 2, 3)

        assert data == b"binary-data"
        assert os.path.exists(file_path)
        with open(file_path, "rb") as fh:
            assert fh.read() == b"binary-data"


class TestUserOperations:
    """Tests for user CRUD and search."""

    @pytest.mark.asyncio
    async def test_create_user(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(
            return_value=_mock_response(200, {"id": 5, "email": "jane@example.com"})
        )
        zammad._session = mock_session

        payload = UserCreatePayload(firstname="Jane", lastname="Doe", email="jane@example.com")
        result = await zammad.create_user(payload)

        assert result["email"] == "jane@example.com"
        _, kwargs = mock_session.request.call_args
        assert kwargs["json"]["firstname"] == "Jane"
        assert kwargs["json"]["roles"] == ["Customer"]

    @pytest.mark.asyncio
    async def test_search_users(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(
            return_value=_mock_response(200, [{"id": 5, "login": "jane@example.com"}])
        )
        zammad._session = mock_session

        users = await zammad.search_users("jane")
        assert users == [{"id": 5, "login": "jane@example.com"}]
        _, kwargs = mock_session.request.call_args
        assert kwargs["params"]["query"] == "jane"

    @pytest.mark.asyncio
    async def test_get_current_user(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(
            return_value=_mock_response(200, {"id": 1, "login": "svc@example.com"})
        )
        zammad._session = mock_session

        result = await zammad.get_current_user()
        assert result["login"] == "svc@example.com"
        args, _ = mock_session.request.call_args
        assert args == ("GET", "https://zammad.example.com/api/v1/users/me")

    @pytest.mark.asyncio
    async def test_update_user(self, zammad):
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.request = MagicMock(
            return_value=_mock_response(200, {"id": 5, "active": False})
        )
        zammad._session = mock_session

        result = await zammad.update_user(5, {"active": False})
        assert result["active"] is False
        args, kwargs = mock_session.request.call_args
        assert args[0] == "PUT"
        assert kwargs["json"] == {"active": False}


class TestFilenameSanitization:
    """Tests for _extract_filename path-traversal hardening."""

    def test_extract_plain_filename(self):
        assert (
            _extract_filename('attachment; filename="report.pdf"', "fallback")
            == "report.pdf"
        )

    def test_extract_strips_path_traversal(self):
        assert (
            _extract_filename('attachment; filename="../../etc/passwd"', "fallback")
            == "passwd"
        )

    def test_extract_uses_fallback_when_absent(self):
        assert _extract_filename("", "fallback.bin") == "fallback.bin"
