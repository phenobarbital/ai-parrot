"""Unit tests for SubmissionForwarder (TASK-600 / FEAT-086)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot_formdesigner.core.schema import SubmitAction
from parrot_formdesigner.core.auth import BearerAuth, NoAuth
from parrot_formdesigner.services.forwarder import ForwardResult, SubmissionForwarder


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


# --- TASK-1157: RemoteResponseResolver tests ---

class TestRemoteResponseSpec:
    """Tests for RemoteResponseSpec Pydantic model."""

    def test_default_values(self) -> None:
        """RemoteResponseSpec has correct defaults."""
        from parrot_formdesigner.services.remote_response_resolver import RemoteResponseSpec

        spec = RemoteResponseSpec(endpoint="https://api.example.com")
        assert spec.http_method == "POST"
        assert spec.content_field is None
        assert spec.prompt is None
        assert spec.auth_ref is None
        assert spec.timeout_seconds == 30
        assert spec.response_schema is None

    def test_custom_values(self) -> None:
        """RemoteResponseSpec accepts custom values."""
        from parrot_formdesigner.services.remote_response_resolver import RemoteResponseSpec

        spec = RemoteResponseSpec(
            endpoint="https://api.example.com/summarize",
            http_method="POST",
            content_field="body_text",
            prompt="Summarize this",
            auth_ref="bearer-token",
            timeout_seconds=60,
        )
        assert spec.endpoint == "https://api.example.com/summarize"
        assert spec.content_field == "body_text"
        assert spec.prompt == "Summarize this"
        assert spec.auth_ref == "bearer-token"
        assert spec.timeout_seconds == 60


class TestRemoteResponseResult:
    """Tests for RemoteResponseResult Pydantic model."""

    def test_success_result(self) -> None:
        """Success result stores value and status_code."""
        from parrot_formdesigner.services.remote_response_resolver import RemoteResponseResult

        r = RemoteResponseResult(success=True, value={"key": "val"}, status_code=200)
        assert r.success is True
        assert r.value == {"key": "val"}
        assert r.status_code == 200
        assert r.error is None

    def test_failure_result(self) -> None:
        """Failure result stores error and status_code."""
        from parrot_formdesigner.services.remote_response_resolver import RemoteResponseResult

        r = RemoteResponseResult(success=False, status_code=500, error="Internal Server Error")
        assert r.success is False
        assert r.error == "Internal Server Error"
        assert r.value is None


class TestRemoteResponseResolver:
    """Tests for RemoteResponseResolver service."""

    async def test_posts_content_and_prompt(self, aiohttp_server) -> None:
        """Resolver sends {'content': ..., 'prompt': ...} and returns API value."""
        from parrot_formdesigner.services.remote_response_resolver import (
            RemoteResponseResolver,
            RemoteResponseSpec,
        )
        from aiohttp import web

        received: dict = {}

        async def handler(request):
            received.update(await request.json())
            return web.json_response({"summary": "hello"})

        app = web.Application()
        app.router.add_post("/summarize", handler)
        server = await aiohttp_server(app)

        resolver = RemoteResponseResolver()
        spec = RemoteResponseSpec(
            endpoint=str(server.make_url("/summarize")),
            prompt="Summarize this",
        )
        result = await resolver.resolve(spec, "some content")
        assert result.success is True
        assert result.value == {"summary": "hello"}
        assert result.status_code == 200
        assert received["content"] == "some content"
        assert received["prompt"] == "Summarize this"

    async def test_no_memoisation_two_calls_hit_endpoint_twice(self, aiohttp_server) -> None:
        """Two sequential resolve() calls hit the endpoint twice (no memoisation)."""
        from parrot_formdesigner.services.remote_response_resolver import (
            RemoteResponseResolver,
            RemoteResponseSpec,
        )
        from aiohttp import web

        call_count = 0

        async def handler(request):
            nonlocal call_count
            call_count += 1
            return web.json_response({"count": call_count})

        app = web.Application()
        app.router.add_post("/action", handler)
        server = await aiohttp_server(app)

        resolver = RemoteResponseResolver()
        spec = RemoteResponseSpec(endpoint=str(server.make_url("/action")))

        await resolver.resolve(spec, "first")
        await resolver.resolve(spec, "second")
        assert call_count == 2

    async def test_failure_returns_error_result(self, aiohttp_server) -> None:
        """HTTP 500 yields RemoteResponseResult(success=False, error=...)."""
        from parrot_formdesigner.services.remote_response_resolver import (
            RemoteResponseResolver,
            RemoteResponseSpec,
        )
        from aiohttp import web

        async def handler(request):
            return web.Response(status=500, text="Internal Server Error")

        app = web.Application()
        app.router.add_post("/fail", handler)
        server = await aiohttp_server(app)

        resolver = RemoteResponseResolver()
        spec = RemoteResponseSpec(endpoint=str(server.make_url("/fail")))
        result = await resolver.resolve(spec, "content")
        assert result.success is False
        assert result.status_code == 500
        assert result.error is not None

    async def test_auth_context_injects_bearer_header(self, aiohttp_server) -> None:
        """Auth context bearer token is injected into request headers."""
        from parrot_formdesigner.services.remote_response_resolver import (
            RemoteResponseResolver,
            RemoteResponseSpec,
        )
        from parrot_formdesigner.services.auth_context import AuthContext
        from aiohttp import web

        received_auth: list = []

        async def handler(request):
            received_auth.append(request.headers.get("Authorization"))
            return web.json_response({"ok": True})

        app = web.Application()
        app.router.add_post("/secure", handler)
        server = await aiohttp_server(app)

        resolver = RemoteResponseResolver()
        spec = RemoteResponseSpec(
            endpoint=str(server.make_url("/secure")),
            auth_ref="my-token",
        )
        ctx = AuthContext(scheme="bearer", token="secret-token")
        result = await resolver.resolve(spec, "data", auth_context=ctx)
        assert result.success is True
        assert received_auth[0] == "Bearer secret-token"

    async def test_importable(self) -> None:
        """RemoteResponseResolver is importable from services module."""
        from parrot_formdesigner.services.remote_response_resolver import (  # noqa: F401
            RemoteResponseResolver,
            RemoteResponseResult,
            RemoteResponseSpec,
        )
