"""Unit tests for ai_parrot_openlit_bridge.probe.validate_endpoint.

Spec: sdd/specs/unified-telemetry-bus.spec.md §3 Module 9.
Task: TASK-2477.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from ai_parrot_openlit_bridge.probe import EndpointStatus, validate_endpoint


class TestValidateEndpoint:
    async def test_reachable_endpoint(self) -> None:
        """Returns reachable=True for a responsive endpoint."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {"server": "otel-collector"}
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await validate_endpoint("http://localhost:4318")
            assert result.reachable is True
            assert result.status_code == 200
            assert result.collector_info == "otel-collector"
            assert result.error is None

    async def test_unreachable_endpoint(self) -> None:
        """Returns reachable=False for a dead endpoint."""
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            side_effect=aiohttp.ClientError("Connection refused")
        )
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await validate_endpoint("http://nonexistent:4318")
            assert result.reachable is False
            assert result.error is not None
            assert result.status_code is None

    async def test_trailing_slash_stripped(self) -> None:
        """A trailing slash on the base URL doesn't produce a double slash."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {}
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await validate_endpoint("http://localhost:4318/")
            called_url = mock_session.post.call_args.args[0]
            assert called_url == "http://localhost:4318/v1/traces"

    async def test_headers_forwarded(self) -> None:
        """Optional auth headers are forwarded to the probe request."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {}
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await validate_endpoint(
                "http://localhost:4318",
                headers={"Authorization": "Bearer tok"},
            )
            _, kwargs = mock_session.post.call_args
            assert kwargs["headers"] == {"Authorization": "Bearer tok"}

    def test_endpoint_status_is_dataclass(self) -> None:
        status = EndpointStatus(reachable=True, status_code=200)
        assert status.reachable is True
        assert status.status_code == 200
        assert status.collector_info is None
        assert status.error is None
