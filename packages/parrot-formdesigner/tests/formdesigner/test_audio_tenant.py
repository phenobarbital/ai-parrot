"""Tests for the inline tenant check in AudioFormWSHandler (FEAT-421 TASK-2204).

The audio WS route is not `_wrap_auth`-ed (navigator-auth's decorators
return HTTP 401, incompatible with the WS upgrade handshake), so its
tenant check is inline, after JWT validation and before the form is
resolved. These tests patch ``web.WebSocketResponse.prepare``/``close`` at
the class level to exercise ``handle_websocket`` without a real network
transport — the same technique the WS upgrade itself would need a live
server for, which unit tests avoid throughout this test suite.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType


def _make_form(tenant: str) -> FormSchema:
    return FormSchema(
        form_id="audio-form",
        title="Audio Form",
        tenant=tenant,
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name?"),
                ],
            )
        ],
    )


@pytest.fixture
def mock_token_validator() -> AsyncMock:
    from parrot.voice.handler import AuthenticatedUser  # type: ignore[import-untyped]

    validator = AsyncMock()
    validator.validate.return_value = AuthenticatedUser(
        user_id="test-user-1", username="testuser"
    )
    return validator


def _request(*, match_info=None, token="valid-jwt"):
    headers = {"Sec-WebSocket-Protocol": f"{token}, json"} if token else {}
    return make_mocked_request(
        "GET",
        "/api/v1/x/forms/f1/audio/ws",
        headers=headers,
        match_info=match_info or {},
    )


class TestAudioWSTenant:
    async def test_missing_tenant_closes_socket(self, mock_token_validator):
        """Already upgraded — must close(1008), not return HTTP 400."""
        registry = AsyncMock()
        handler = AudioFormWSHandler(
            registry=registry,
            synthesizer=None,
            transcriber=None,
            validator=MagicMock(),
            token_validator=mock_token_validator,
        )
        request = _request(match_info={"form_uid": "f1"})  # no "tenant" key

        with (
            patch.object(web.WebSocketResponse, "prepare", new=AsyncMock()),
            patch.object(web.WebSocketResponse, "close", new=AsyncMock()) as mock_close,
            patch.object(web.WebSocketResponse, "send_json", new=AsyncMock()),
        ):
            await handler.handle_websocket(request)

        mock_close.assert_awaited_once()
        assert mock_close.call_args.kwargs.get("code") == 1008
        registry.get.assert_not_called()

    async def test_empty_tenant_closes_socket(self, mock_token_validator):
        """An empty (not just absent) tenant segment must also close(1008)."""
        registry = AsyncMock()
        handler = AudioFormWSHandler(
            registry=registry,
            synthesizer=None,
            transcriber=None,
            validator=MagicMock(),
            token_validator=mock_token_validator,
        )
        request = _request(match_info={"form_uid": "f1", "tenant": ""})

        with (
            patch.object(web.WebSocketResponse, "prepare", new=AsyncMock()),
            patch.object(web.WebSocketResponse, "close", new=AsyncMock()) as mock_close,
            patch.object(web.WebSocketResponse, "send_json", new=AsyncMock()),
        ):
            await handler.handle_websocket(request)

        mock_close.assert_awaited_once()
        assert mock_close.call_args.kwargs.get("code") == 1008

    async def test_cross_tenant_form_closes_socket(self, mock_token_validator):
        """Form belongs to navigator, socket declared flexroc — must close,
        never serve the form."""
        registry = AsyncMock()
        registry.get.return_value = _make_form(tenant="navigator")
        handler = AudioFormWSHandler(
            registry=registry,
            synthesizer=None,
            transcriber=None,
            validator=MagicMock(),
            token_validator=mock_token_validator,
        )

        with (
            patch.object(web.WebSocketResponse, "prepare", new=AsyncMock()),
            patch.object(web.WebSocketResponse, "close", new=AsyncMock()) as mock_close,
            patch.object(web.WebSocketResponse, "send_json", new=AsyncMock()),
        ):
            await handler._handle_start_session(
                ws=web.WebSocketResponse(),
                data={"form_uid": "f1"},
                session=_session(),
                request=_request(match_info={"form_uid": "f1", "tenant": "flexroc"}),
                audio_cache={},
            )
            mock_close.assert_awaited_once()
            assert mock_close.call_args.kwargs.get("code") == 1008

    async def test_happy_path_resolves_form_with_declared_tenant(
        self, mock_token_validator
    ):
        """A correctly declared tenant resolves the matching form and does
        not close the socket."""
        registry = AsyncMock()
        registry.get.return_value = _make_form(tenant="flexroc")
        handler = AudioFormWSHandler(
            registry=registry,
            synthesizer=None,
            transcriber=None,
            validator=MagicMock(),
            token_validator=mock_token_validator,
        )

        with (
            patch.object(web.WebSocketResponse, "prepare", new=AsyncMock()),
            patch.object(web.WebSocketResponse, "close", new=AsyncMock()) as mock_close,
            patch.object(web.WebSocketResponse, "send_json", new=AsyncMock()),
        ):
            await handler._handle_start_session(
                ws=web.WebSocketResponse(),
                data={"form_uid": "f1"},
                session=_session(),
                request=_request(match_info={"form_uid": "f1", "tenant": "flexroc"}),
                audio_cache={},
            )

        registry.get.assert_awaited_once_with("f1", tenant="flexroc")
        mock_close.assert_not_called()


def _session():
    from parrot_formdesigner.audio.models import AudioSessionState

    return AudioSessionState(session_id="s1", form_uid="f1", user_id="u1")
