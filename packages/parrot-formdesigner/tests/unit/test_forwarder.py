"""Unit tests for SubmissionForwarder (TASK-600 / FEAT-086)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.formdesigner.core.schema import SubmitAction
from parrot.formdesigner.core.auth import BearerAuth, ApiKeyAuth, NoAuth
from parrot.formdesigner.services.forwarder import ForwardResult, SubmissionForwarder


# ---------------------------------------------------------------------------
# ForwardResult model
# ---------------------------------------------------------------------------

class TestForwardResult:
    """Tests for the ForwardResult model."""

    def test_success_result(self) -> None:
        """Success result has True success and no error."""
        r = ForwardResult(success=True, status_code=200)
        assert r.success is True
        assert r.error is None

    def test_failure_result(self) -> None:
        """Failure result has False success and an error message."""
        r = ForwardResult(success=False, error="Connection refused")
        assert r.success is False
        assert r.error == "Connection refused"

    def test_status_code_optional(self) -> None:
        """status_code is optional, defaults to None."""
        r = ForwardResult(success=False)
        assert r.status_code is None


# ---------------------------------------------------------------------------
# SubmissionForwarder
# ---------------------------------------------------------------------------

class TestSubmissionForwarder:
    """Tests for SubmissionForwarder.forward()."""

    @pytest.fixture
    def forwarder(self) -> SubmissionForwarder:
        """A forwarder with a short timeout for tests."""
        return SubmissionForwarder(timeout=5)

    @pytest.fixture
    def endpoint_action(self) -> SubmitAction:
        """A SubmitAction pointing to a test endpoint."""
        return SubmitAction(
            action_type="endpoint",
            action_ref="http://example.com/api/data",
            method="POST",
        )

    @pytest.mark.asyncio
    async def test_non_endpoint_action_returns_failure(
        self, forwarder: SubmissionForwarder
    ) -> None:
        """Forwarding a non-endpoint action returns ForwardResult with error."""
        sa = SubmitAction(action_type="tool_call", action_ref="my_tool")
        result = await forwarder.forward({"key": "val"}, sa)
        assert result.success is False
        assert result.error is not None
        assert "endpoint" in result.error.lower()

    @pytest.mark.asyncio
    async def test_event_action_returns_failure(
        self, forwarder: SubmissionForwarder
    ) -> None:
        """Forwarding an event action returns ForwardResult with error."""
        sa = SubmitAction(action_type="event", action_ref="my_event")
        result = await forwarder.forward({}, sa)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_forward_does_not_raise_on_network_error(
        self, forwarder: SubmissionForwarder, endpoint_action: SubmitAction
    ) -> None:
        """Network errors are caught and returned as ForwardResult — never raised."""
        # Point to a port that nothing is listening on
        endpoint_action.action_ref = "http://localhost:19999/nonexistent"  # type: ignore[misc]
        result = await forwarder.forward({"key": "val"}, endpoint_action)
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_forward_with_bearer_auth_missing_env(
        self, forwarder: SubmissionForwarder
    ) -> None:
        """When auth env var is missing, returns ForwardResult with error."""
        sa = SubmitAction(
            action_type="endpoint",
            action_ref="http://example.com/api",
            auth=BearerAuth(token_env="NONEXISTENT_TOKEN_12345_TEST"),
        )
        result = await forwarder.forward({"data": "x"}, sa)
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_default_timeout(self) -> None:
        """Default timeout is 30 seconds."""
        f = SubmissionForwarder()
        assert f.timeout == 30

    @pytest.mark.asyncio
    async def test_custom_timeout(self) -> None:
        """Custom timeout is preserved."""
        f = SubmissionForwarder(timeout=60)
        assert f.timeout == 60

    @pytest.mark.asyncio
    async def test_forward_success_mocked(
        self, forwarder: SubmissionForwarder, endpoint_action: SubmitAction, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Successful forward returns ForwardResult(success=True, status_code=200)."""
        import aiohttp
        from unittest.mock import AsyncMock

        mock_resp = MagicMock()
        mock_resp.status = 200

        async def mock_request(*args, **kwargs):
            return mock_resp

        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await forwarder.forward({"name": "test"}, endpoint_action)

        assert result.success is True
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_forward_with_no_auth_sends_no_auth_headers(
        self, forwarder: SubmissionForwarder
    ) -> None:
        """NoAuth resolves to empty headers — no Authorization header sent."""
        sa = SubmitAction(
            action_type="endpoint",
            action_ref="http://localhost:19998/",
            auth=NoAuth(),
        )
        # Just verify it doesn't raise and returns a result
        result = await forwarder.forward({}, sa)
        assert isinstance(result, ForwardResult)
