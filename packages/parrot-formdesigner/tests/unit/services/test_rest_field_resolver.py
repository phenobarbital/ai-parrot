"""Unit tests for RestFieldResolver — mocked aiohttp, no live HTTP calls."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from parrot_formdesigner.services.callback_registry import (
    _CALLBACK_REGISTRY,
    register_form_callback,
)
from parrot_formdesigner.services.rest_field_resolver import (
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
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(**kwargs) -> RestCallbackInput:
    defaults = dict(
        form_id="f1",
        field_id="field1",
        session_id=None,
        user_id=None,
        tenant=None,
        content_type="text/plain",
        content=b"hello",
    )
    defaults.update(kwargs)
    return RestCallbackInput(**defaults)


def _mock_aiohttp_response(status: int, json_body: object | None = None, text_body: str = "") -> tuple:
    """Return (session_cls_mock, resp_mock) configured for the given response."""
    resp = AsyncMock()
    resp.status = status
    if json_body is not None:
        resp.json = AsyncMock(return_value=json_body)
    else:
        resp.json = AsyncMock(side_effect=Exception("not json"))
    resp.text = AsyncMock(return_value=text_body)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)

    method_mock = MagicMock(return_value=resp)

    session = AsyncMock()
    session.get = method_mock
    session.post = method_mock
    session.put = method_mock
    session.patch = method_mock
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    session_cls = MagicMock(return_value=session)
    return session_cls, resp


@pytest.fixture(autouse=True)
def clean_callback_registry():
    _CALLBACK_REGISTRY.clear()
    yield
    _CALLBACK_REGISTRY.clear()


@pytest.fixture()
def resolver() -> RestFieldResolver:
    return RestFieldResolver()


@pytest.fixture()
def payload() -> RestCallbackInput:
    return _make_payload()


# ---------------------------------------------------------------------------
# RestFieldSpec discriminated union
# ---------------------------------------------------------------------------


class TestRestFieldSpec:
    def test_discriminated_remote(self) -> None:
        spec = RestFieldSpec.model_validate(
            {"mode": "remote", "endpoint": "https://api.test/x"}
        )
        assert isinstance(spec, RemoteRestFieldSpec)
        assert spec.mode == "remote"

    def test_discriminated_internal(self) -> None:
        spec = RestFieldSpec.model_validate(
            {"mode": "internal", "endpoint": "/internal/x"}
        )
        assert isinstance(spec, InternalRestFieldSpec)

    def test_discriminated_callback(self) -> None:
        spec = RestFieldSpec.model_validate(
            {"mode": "callback", "callback_ref": "my_cb"}
        )
        assert isinstance(spec, CallbackRestFieldSpec)

    def test_internal_requires_leading_slash(self) -> None:
        with pytest.raises(ValidationError):
            RestFieldSpec.model_validate({"mode": "internal", "endpoint": "api/x"})

    def test_extra_forbid_raises(self) -> None:
        with pytest.raises(ValidationError):
            RestFieldSpec.model_validate(
                {"mode": "remote", "endpoint": "https://x", "unknown": 1}
            )


# ---------------------------------------------------------------------------
# Remote mode
# ---------------------------------------------------------------------------


class TestRemoteMode:
    async def test_remote_success_returns_json(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        spec = RestFieldSpec.model_validate(
            {"mode": "remote", "endpoint": "https://api.test/score"}
        )
        session_cls, _ = _mock_aiohttp_response(200, json_body={"score": 0.9})
        with patch("aiohttp.ClientSession", session_cls):
            result = await resolver.resolve(spec, payload)
        assert result.success is True
        assert result.raw_value == {"score": 0.9}
        assert result.status_code == 200

    async def test_remote_4xx_returns_failure(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        spec = RestFieldSpec.model_validate(
            {"mode": "remote", "endpoint": "https://api.test/err"}
        )
        session_cls, _ = _mock_aiohttp_response(404, text_body="Not found")
        with patch("aiohttp.ClientSession", session_cls):
            result = await resolver.resolve(spec, payload)
        assert result.success is False
        assert result.status_code == 404

    async def test_remote_timeout_returns_failure(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        import aiohttp as _aiohttp

        spec = RestFieldSpec.model_validate(
            {"mode": "remote", "endpoint": "https://api.test/slow"}
        )
        with patch("aiohttp.ClientSession") as session_cls:
            session_cls.return_value.__aenter__ = AsyncMock(
                side_effect=_aiohttp.ServerTimeoutError()
            )
            session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await resolver.resolve(spec, payload)
        assert result.success is False
        assert result.status_code is None
        assert result.error


# ---------------------------------------------------------------------------
# Internal mode
# ---------------------------------------------------------------------------


class TestInternalMode:
    async def test_internal_no_base_url_raises_config_error(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        os.environ.pop("PARROT_INTERNAL_BASE_URL", None)
        spec = RestFieldSpec.model_validate({"mode": "internal", "endpoint": "/x"})
        with pytest.raises(ConfigurationError):
            await resolver.resolve(spec, payload)

    async def test_internal_from_env_var(
        self, payload: RestCallbackInput, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PARROT_INTERNAL_BASE_URL", "http://127.0.0.1:8080")
        resolver = RestFieldResolver()
        spec = RestFieldSpec.model_validate({"mode": "internal", "endpoint": "/api/x"})
        session_cls, _ = _mock_aiohttp_response(200, json_body={"ok": True})
        with patch("aiohttp.ClientSession", session_cls):
            result = await resolver.resolve(spec, payload)
        assert result.success is True

    async def test_internal_ssrf_evil_host_returns_failure(
        self, payload: RestCallbackInput, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PARROT_INTERNAL_BASE_URL", "http://evil.com")
        monkeypatch.delenv("PARROT_INTERNAL_ALLOWED_HOSTS", raising=False)
        resolver = RestFieldResolver()
        spec = RestFieldSpec.model_validate({"mode": "internal", "endpoint": "/x"})
        result = await resolver.resolve(spec, payload)
        assert result.success is False
        assert "allow-list" in (result.error or "")

    async def test_internal_constructor_base_url(
        self, payload: RestCallbackInput, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PARROT_INTERNAL_BASE_URL", raising=False)
        resolver = RestFieldResolver(internal_base_url="http://127.0.0.1:9000")
        spec = RestFieldSpec.model_validate({"mode": "internal", "endpoint": "/ping"})
        session_cls, _ = _mock_aiohttp_response(200, json_body={"pong": True})
        with patch("aiohttp.ClientSession", session_cls):
            result = await resolver.resolve(spec, payload)
        assert result.success is True


# ---------------------------------------------------------------------------
# Callback mode
# ---------------------------------------------------------------------------


class TestCallbackMode:
    async def test_callback_missing_returns_error(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        spec = RestFieldSpec.model_validate(
            {"mode": "callback", "callback_ref": "nope"}
        )
        result = await resolver.resolve(spec, payload)
        assert result.success is False
        assert result.error

    async def test_callback_success_raw_value(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        @register_form_callback("my_cb")
        async def cb(inp: RestCallbackInput):
            return {"computed": 42}

        spec = RestFieldSpec.model_validate(
            {"mode": "callback", "callback_ref": "my_cb"}
        )
        result = await resolver.resolve(spec, payload)
        assert result.success is True
        assert result.raw_value == {"computed": 42}

    async def test_callback_structured_output(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        @register_form_callback("struct_cb")
        async def cb(inp: RestCallbackInput) -> RestCallbackOutput:
            return RestCallbackOutput(value="val", display="Display!", blob_ref="s3://b/k")

        spec = RestFieldSpec.model_validate(
            {"mode": "callback", "callback_ref": "struct_cb"}
        )
        result = await resolver.resolve(spec, payload)
        assert result.success is True
        assert result.display == "Display!"
        assert result.blob_ref == "s3://b/k"

    async def test_callback_exception_returns_failure(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        @register_form_callback("bad_cb")
        async def cb(inp):
            raise RuntimeError("boom")

        spec = RestFieldSpec.model_validate(
            {"mode": "callback", "callback_ref": "bad_cb"}
        )
        result = await resolver.resolve(spec, payload)
        assert result.success is False
        assert "boom" in (result.error or "")

    async def test_callback_tenant_lookup(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        @register_form_callback("shared_cb")
        async def global_cb(inp):
            return "global"

        @register_form_callback("shared_cb", tenant="acme")
        async def tenant_cb(inp):
            return "acme-specific"

        spec = RestFieldSpec.model_validate(
            {"mode": "callback", "callback_ref": "shared_cb"}
        )
        result = await resolver.resolve(spec, payload, tenant="acme")
        assert result.raw_value == "acme-specific"


# ---------------------------------------------------------------------------
# JSONPath post-processing
# ---------------------------------------------------------------------------


class TestJsonPathPostProcessing:
    async def test_jsonpath_hit_extracts_value(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        @register_form_callback("jp_cb")
        async def cb(inp):
            return {"score": 0.86, "other": "x"}

        spec = RestFieldSpec.model_validate(
            {"mode": "callback", "callback_ref": "jp_cb", "response_path": "$.score"}
        )
        result = await resolver.resolve(spec, payload)
        assert result.answer == 0.86
        assert result.warnings == []

    async def test_jsonpath_miss_adds_warning(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        @register_form_callback("jp_miss_cb")
        async def cb(inp):
            return {"score": 0.86}

        spec = RestFieldSpec.model_validate(
            {
                "mode": "callback",
                "callback_ref": "jp_miss_cb",
                "response_path": "$.missing",
            }
        )
        result = await resolver.resolve(spec, payload)
        assert result.answer is None
        assert any("jsonpath_miss: $.missing" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# display_template post-processing
# ---------------------------------------------------------------------------


class TestDisplayTemplate:
    async def test_display_template_renders(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        @register_form_callback("tmpl_cb")
        async def cb(inp):
            return 42

        spec = RestFieldSpec.model_validate(
            {
                "mode": "callback",
                "callback_ref": "tmpl_cb",
                "display_template": "Score: {{ value }}",
            }
        )
        result = await resolver.resolve(spec, payload)
        assert result.display == "Score: 42"

    async def test_display_template_security_error_propagates(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        """SecurityError from the Jinja2 sandbox must propagate out of resolve()."""
        from jinja2.sandbox import SecurityError

        @register_form_callback("sec_cb")
        async def cb(inp):
            return "val"

        spec = RestFieldSpec.model_validate(
            {
                "mode": "callback",
                "callback_ref": "sec_cb",
                "display_template": "{{ value }}",
            }
        )
        # Patch the sandboxed environment so render() raises SecurityError,
        # verifying that the resolver does NOT swallow it.
        mock_tmpl = MagicMock()
        mock_tmpl.render.side_effect = SecurityError("sandbox violation")
        mock_env = MagicMock()
        mock_env.from_string.return_value = mock_tmpl

        with patch(
            "parrot_formdesigner.services.rest_field_resolver.SandboxedEnvironment",
            return_value=mock_env,
        ):
            with pytest.raises(SecurityError):
                await resolver.resolve(spec, payload)


# ---------------------------------------------------------------------------
# response_schema post-processing
# ---------------------------------------------------------------------------


class TestResponseSchema:
    async def test_schema_match_no_warning(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        @register_form_callback("schema_ok_cb")
        async def cb(inp):
            return {"name": "Alice", "age": 30}

        spec = RestFieldSpec.model_validate(
            {
                "mode": "callback",
                "callback_ref": "schema_ok_cb",
                "response_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                },
            }
        )
        result = await resolver.resolve(spec, payload)
        assert result.success is True
        assert result.warnings == []

    async def test_schema_mismatch_adds_warning(
        self, resolver: RestFieldResolver, payload: RestCallbackInput
    ) -> None:
        @register_form_callback("schema_bad_cb")
        async def cb(inp):
            return {"name": 123}  # wrong type

        spec = RestFieldSpec.model_validate(
            {
                "mode": "callback",
                "callback_ref": "schema_bad_cb",
                "response_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            }
        )
        result = await resolver.resolve(spec, payload)
        assert result.success is True
        assert any("response_schema_mismatch" in w for w in result.warnings)
