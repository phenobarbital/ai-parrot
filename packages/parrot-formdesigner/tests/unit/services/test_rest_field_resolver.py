"""Unit tests for parrot_formdesigner.services.rest_field_resolver.

Covers all spec §4 unit-test rows labelled Module 3, plus SSRF and
configuration-error scenarios.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from pydantic import TypeAdapter, ValidationError

from parrot_formdesigner.services.callback_registry import (
    _CALLBACK_REGISTRY,
    register_form_callback,
)
from parrot_formdesigner.services.rest_field_resolver import (
    AdditionalArg,
    CallbackRestFieldSpec,
    ConfigurationError,
    InternalRestFieldSpec,
    RemoteRestFieldSpec,
    RestCallbackInput,
    RestCallbackOutput,
    RestFieldResolver,
    RestFieldResult,
    RestFieldSpec,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_callback_registry():
    """Ensure a clean callback registry for every test."""
    _CALLBACK_REGISTRY.clear()
    yield
    _CALLBACK_REGISTRY.clear()


def _make_payload(**kwargs) -> RestCallbackInput:
    defaults = dict(
        form_id="form1",
        field_id="photo",
        session_id=None,
        user_id=None,
        tenant=None,
        content_type="image/jpeg",
        content=b"image-data",
    )
    defaults.update(kwargs)
    return RestCallbackInput(**defaults)


# ---------------------------------------------------------------------------
# Model / discriminated union
# ---------------------------------------------------------------------------


_spec_adapter: TypeAdapter = TypeAdapter(RestFieldSpec)


class TestRestFieldSpecModels:
    def test_discriminated_remote(self):
        spec = _spec_adapter.validate_python(
            {"mode": "remote", "endpoint": "https://api.test/x"}
        )
        assert isinstance(spec, RemoteRestFieldSpec)
        assert spec.mode == "remote"

    def test_discriminated_internal(self):
        spec = _spec_adapter.validate_python(
            {"mode": "internal", "endpoint": "/api/v1/x"}
        )
        assert isinstance(spec, InternalRestFieldSpec)
        assert spec.mode == "internal"

    def test_discriminated_callback(self):
        spec = _spec_adapter.validate_python(
            {"mode": "callback", "callback_ref": "planogram"}
        )
        assert isinstance(spec, CallbackRestFieldSpec)
        assert spec.callback_ref == "planogram"

    def test_internal_requires_leading_slash(self):
        with pytest.raises(ValidationError):
            _spec_adapter.validate_python({"mode": "internal", "endpoint": "api/x"})

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            _spec_adapter.validate_python(
                {"mode": "remote", "endpoint": "https://x", "unknown_field": 1}
            )

    def test_internal_extra_forbidden(self):
        with pytest.raises(ValidationError):
            InternalRestFieldSpec(mode="internal", endpoint="/x", surprise="!")

    def test_default_timeout(self):
        spec = RemoteRestFieldSpec(endpoint="https://x")
        assert spec.timeout_seconds == 30

    def test_persist_binary_default_true(self):
        spec = CallbackRestFieldSpec(callback_ref="fn")
        assert spec.persist_binary is True


# ---------------------------------------------------------------------------
# Resolver — callback mode
# ---------------------------------------------------------------------------


class TestResolverCallbackMode:
    @pytest.mark.asyncio
    async def test_callback_invokes_registered_fn(self):
        """Registered callback is awaited; its value becomes raw_value."""

        @register_form_callback("planogram")
        async def fn(payload, auth_context):
            return RestCallbackOutput(success=True, value={"compliance_score": 0.86})

        resolver = RestFieldResolver()
        spec = CallbackRestFieldSpec(callback_ref="planogram")
        result = await resolver.resolve(spec, _make_payload())

        assert result.success is True
        assert result.raw_value == {"compliance_score": 0.86}

    @pytest.mark.asyncio
    async def test_callback_missing_returns_error(self):
        """Unknown callback_ref returns success=False without raising."""
        resolver = RestFieldResolver()
        spec = CallbackRestFieldSpec(callback_ref="nope")
        result = await resolver.resolve(spec, _make_payload())

        assert result.success is False
        assert result.error is not None
        assert "nope" in result.error

    @pytest.mark.asyncio
    async def test_callback_failure_returns_error(self):
        """Callback returning success=False propagates the error."""

        @register_form_callback("failing")
        async def fn(payload, auth_context):
            return RestCallbackOutput(success=False, error="bad content")

        resolver = RestFieldResolver()
        spec = CallbackRestFieldSpec(callback_ref="failing")
        result = await resolver.resolve(spec, _make_payload())

        assert result.success is False
        assert "bad content" in (result.error or "")

    @pytest.mark.asyncio
    async def test_callback_exception_returns_error(self):
        """Unexpected exception from callback is captured in result."""

        @register_form_callback("exc_fn")
        async def fn(payload, auth_context):
            raise RuntimeError("something exploded")

        resolver = RestFieldResolver()
        spec = CallbackRestFieldSpec(callback_ref="exc_fn")
        result = await resolver.resolve(spec, _make_payload())

        assert result.success is False
        assert "exploded" in (result.error or "")

    @pytest.mark.asyncio
    async def test_callback_tenant_scoped(self):
        """Tenant-scoped callback wins over global."""

        @register_form_callback("x")
        async def global_fn(p, a):
            return RestCallbackOutput(success=True, value="global")

        @register_form_callback("x", tenant="acme")
        async def tenant_fn(p, a):
            return RestCallbackOutput(success=True, value="acme-specific")

        resolver = RestFieldResolver()
        spec = CallbackRestFieldSpec(callback_ref="x")
        result = await resolver.resolve(spec, _make_payload(), tenant="acme")

        assert result.raw_value == "acme-specific"


# ---------------------------------------------------------------------------
# Resolver — JSONPath extraction
# ---------------------------------------------------------------------------


class TestResolverJSONPath:
    @pytest.mark.asyncio
    async def test_jsonpath_extraction(self):
        """response_path='$.score' extracts answer=0.86 from raw dict."""

        @register_form_callback("score_fn")
        async def fn(p, a):
            return RestCallbackOutput(success=True, value={"score": 0.86, "other": 1})

        resolver = RestFieldResolver()
        spec = CallbackRestFieldSpec(
            callback_ref="score_fn", response_path="$.score"
        )
        result = await resolver.resolve(spec, _make_payload())

        assert result.success is True
        assert result.answer == pytest.approx(0.86)
        assert result.raw_value == {"score": 0.86, "other": 1}

    @pytest.mark.asyncio
    async def test_jsonpath_miss_appends_warning(self):
        """Non-matching JSONPath yields answer=None + warning string."""

        @register_form_callback("data_fn")
        async def fn(p, a):
            return RestCallbackOutput(success=True, value={"different": 1})

        resolver = RestFieldResolver()
        spec = CallbackRestFieldSpec(
            callback_ref="data_fn", response_path="$.missing"
        )
        result = await resolver.resolve(spec, _make_payload())

        assert result.success is True
        assert result.answer is None
        assert any("jsonpath_miss" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_no_jsonpath_answer_equals_raw_value(self):
        """Without response_path, answer equals raw_value."""

        @register_form_callback("raw_fn")
        async def fn(p, a):
            return RestCallbackOutput(success=True, value={"x": 1})

        resolver = RestFieldResolver()
        spec = CallbackRestFieldSpec(callback_ref="raw_fn")
        result = await resolver.resolve(spec, _make_payload())

        assert result.answer == {"x": 1}
        assert result.raw_value == {"x": 1}


# ---------------------------------------------------------------------------
# Resolver — display template
# ---------------------------------------------------------------------------


class TestResolverDisplayTemplate:
    @pytest.mark.asyncio
    async def test_display_template_rendered(self):
        """display_template='Score: {{ answer }}' renders correctly."""

        @register_form_callback("tmpl_fn")
        async def fn(p, a):
            return RestCallbackOutput(success=True, value={"compliance_score": 0.86})

        resolver = RestFieldResolver()
        spec = CallbackRestFieldSpec(
            callback_ref="tmpl_fn",
            response_path="$.compliance_score",
            display_template="Score: {{ answer }}",
        )
        result = await resolver.resolve(spec, _make_payload())

        assert result.display == "Score: 0.86"

    @pytest.mark.asyncio
    async def test_display_template_sandbox_blocks_unsafe(self):
        """Templates accessing __class__ / os raise a sandbox error."""

        @register_form_callback("unsafe_fn")
        async def fn(p, a):
            return RestCallbackOutput(success=True, value=1)

        resolver = RestFieldResolver()
        spec = CallbackRestFieldSpec(
            callback_ref="unsafe_fn",
            # Access __mro__ triggers Jinja2 SandboxedEnvironment SecurityError
            display_template="{{ ''.__class__.__mro__[2].__subclasses__() }}",
        )
        result = await resolver.resolve(spec, _make_payload())

        # The sandbox should block this; result still has a warning
        assert any("display_template_error" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Resolver — response_schema validation
# ---------------------------------------------------------------------------


class TestResolverResponseSchema:
    @pytest.mark.asyncio
    async def test_response_schema_miss_emits_warning_not_reject(self):
        """Schema validation failure appends warning; success is still True."""

        @register_form_callback("schema_fn")
        async def fn(p, a):
            return RestCallbackOutput(success=True, value="not a dict")

        resolver = RestFieldResolver()
        spec = CallbackRestFieldSpec(
            callback_ref="schema_fn",
            response_schema={"type": "object"},
        )
        result = await resolver.resolve(spec, _make_payload())

        # response_schema miss → informational only
        assert result.success is True
        assert any("response_schema_mismatch" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Resolver — internal mode
# ---------------------------------------------------------------------------


class TestResolverInternalMode:
    @pytest.mark.asyncio
    async def test_internal_prepends_base_url(self):
        """internal_base_url='http://localhost:8080' prepended to endpoint."""
        resolver = RestFieldResolver(internal_base_url="http://localhost:8080")
        spec = InternalRestFieldSpec(endpoint="/api/v1/x")

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"ok": True})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await resolver.resolve(spec, _make_payload())

        assert result.success is True
        mock_session.post.assert_called_once()
        call_url = mock_session.post.call_args[0][0]
        assert call_url == "http://localhost:8080/api/v1/x"

    @pytest.mark.asyncio
    async def test_internal_no_base_url_returns_config_error_result(self, monkeypatch):
        """Missing base URL → RestFieldResult with configuration_error (never raises).

        resolve() must honour the "never-raises" contract — ConfigurationError
        is captured in the result envelope rather than propagated to the caller.
        """
        monkeypatch.delenv("PARROT_INTERNAL_BASE_URL", raising=False)
        resolver = RestFieldResolver()
        spec = InternalRestFieldSpec(endpoint="/api/v1/x")

        result = await resolver.resolve(spec, _make_payload())
        assert result.success is False
        assert result.error is not None
        assert "configuration_error" in result.error

    @pytest.mark.asyncio
    async def test_internal_env_var_used(self, monkeypatch):
        """PARROT_INTERNAL_BASE_URL env var is used when constructor arg absent."""
        monkeypatch.setenv("PARROT_INTERNAL_BASE_URL", "http://localhost:9090")

        resolver = RestFieldResolver()
        spec = InternalRestFieldSpec(endpoint="/ping")

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"pong": True})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await resolver.resolve(spec, _make_payload())

        assert result.success is True
        url = mock_session.post.call_args[0][0]
        assert url == "http://localhost:9090/ping"

    @pytest.mark.asyncio
    async def test_internal_ssrf_guard_rejects_external_host(self):
        """Non-loopback host → success=False (SSRF guard)."""
        resolver = RestFieldResolver(internal_base_url="http://evil.com")
        spec = InternalRestFieldSpec(endpoint="/steal")

        result = await resolver.resolve(spec, _make_payload())
        assert result.success is False
        assert result.error is not None


# ---------------------------------------------------------------------------
# Resolver — remote mode via aiohttp mock
# ---------------------------------------------------------------------------


class TestResolverRemoteMode:
    @pytest.mark.asyncio
    async def test_remote_dispatches_via_aiohttp(self):
        """Remote mode sends POST to absolute URL with auth headers."""
        from parrot_formdesigner.services.auth_context import AuthContext

        auth = AuthContext(scheme="bearer", token="tok123")
        spec = RemoteRestFieldSpec(endpoint="https://api.vendor.test/analyse")

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"result": 42})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            resolver = RestFieldResolver()
            result = await resolver.resolve(spec, _make_payload(), auth_context=auth)

        assert result.success is True
        assert result.raw_value == {"result": 42}

    @pytest.mark.asyncio
    async def test_remote_timeout_returns_error_not_raise(self):
        """aiohttp timeout → success=False, no exception raised to caller."""
        spec = RemoteRestFieldSpec(endpoint="https://slow.test/x", timeout_seconds=1)

        with patch(
            "aiohttp.ClientSession",
            side_effect=aiohttp.ServerTimeoutError("timeout"),
        ):
            resolver = RestFieldResolver()
            result = await resolver.resolve(spec, _make_payload())

        assert result.success is False
        assert result.error is not None
        assert result.status_code is None


# ---------------------------------------------------------------------------
# AdditionalArg model + spec integration
# ---------------------------------------------------------------------------


class TestAdditionalArg:
    def test_private_requires_value(self):
        with pytest.raises(ValidationError):
            AdditionalArg(name="prompt", visibility="private")

    def test_private_with_value_ok(self):
        arg = AdditionalArg(name="prompt", visibility="private", value="hello")
        assert arg.value == "hello"

    def test_public_value_optional(self):
        arg = AdditionalArg(name="tenant", visibility="public")
        assert arg.value is None
        assert arg.data_type == "string"
        assert arg.required is False

    def test_spec_accepts_additional_args(self):
        spec = _spec_adapter.validate_python(
            {
                "mode": "remote",
                "endpoint": "https://api.test/x",
                "additional_args": [
                    {"name": "prompt", "visibility": "private", "value": "system"},
                    {"name": "tenant", "visibility": "public", "required": True},
                ],
            }
        )
        assert isinstance(spec, RemoteRestFieldSpec)
        assert len(spec.additional_args) == 2
        assert spec.additional_args[0].visibility == "private"
        assert spec.additional_args[1].required is True

    def test_spec_rejects_duplicate_arg_names(self):
        with pytest.raises(ValidationError):
            RemoteRestFieldSpec(
                endpoint="https://api.test/x",
                additional_args=[
                    AdditionalArg(name="x", visibility="public"),
                    AdditionalArg(name="x", visibility="private", value=1),
                ],
            )

    def test_default_additional_args_empty(self):
        spec = RemoteRestFieldSpec(endpoint="https://api.test/x")
        assert spec.additional_args == []


# ---------------------------------------------------------------------------
# Request body shaping (_build_request_kwargs)
# ---------------------------------------------------------------------------


class TestBuildRequestKwargs:
    def test_bytes_no_extras_uses_binary_post(self):
        payload = _make_payload(content=b"img", extra_fields={})
        kwargs = RestFieldResolver._build_request_kwargs(payload)
        assert kwargs == {
            "data": b"img",
            "headers": {"Content-Type": "image/jpeg"},
        }

    def test_bytes_with_extras_uses_multipart(self):
        payload = _make_payload(
            content=b"img",
            extra_fields={"prompt": "describe", "tenant": "acme", "n": 3},
        )
        kwargs = RestFieldResolver._build_request_kwargs(payload)
        assert "data" in kwargs
        assert isinstance(kwargs["data"], aiohttp.FormData)
        # Inspect underlying fields
        fields = kwargs["data"]._fields
        names = [f[0]["name"] for f in fields]
        assert "file" in names
        assert "prompt" in names
        assert "tenant" in names
        assert "n" in names

    def test_dict_with_extras_merges_into_json(self):
        payload = _make_payload(
            content={"a": 1, "b": 2},
            content_type="application/json",
            extra_fields={"b": 99, "tenant": "acme"},
        )
        kwargs = RestFieldResolver._build_request_kwargs(payload)
        assert kwargs == {"json": {"a": 1, "b": 99, "tenant": "acme"}}

    def test_dict_no_extras_passthrough(self):
        payload = _make_payload(
            content={"a": 1},
            content_type="application/json",
            extra_fields={},
        )
        kwargs = RestFieldResolver._build_request_kwargs(payload)
        assert kwargs == {"json": {"a": 1}}

    def test_bytes_with_json_extra_value_serialized(self):
        payload = _make_payload(
            content=b"img",
            extra_fields={"metadata": {"k": "v"}, "flag": True},
        )
        kwargs = RestFieldResolver._build_request_kwargs(payload)
        form = kwargs["data"]
        # Bool encoded as "true", dict as JSON string
        encoded = {f[0]["name"]: f[2] for f in form._fields}
        assert encoded["flag"] == "true"
        assert encoded["metadata"] == '{"k": "v"}'


# ---------------------------------------------------------------------------
# Callback receives extra_fields via payload
# ---------------------------------------------------------------------------


class TestCallbackReceivesExtraFields:
    @pytest.mark.asyncio
    async def test_callback_sees_extra_fields(self):
        captured: dict = {}

        @register_form_callback("with_extras")
        async def fn(payload, auth_context):
            captured["extras"] = dict(payload.extra_fields)
            return RestCallbackOutput(success=True, value=payload.extra_fields)

        resolver = RestFieldResolver()
        spec = CallbackRestFieldSpec(callback_ref="with_extras")
        payload = _make_payload(extra_fields={"prompt": "p", "tenant": "t"})
        result = await resolver.resolve(spec, payload)

        assert result.success is True
        assert captured["extras"] == {"prompt": "p", "tenant": "t"}
