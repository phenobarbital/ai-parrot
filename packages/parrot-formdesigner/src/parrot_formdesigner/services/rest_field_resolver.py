"""REST field resolver for FormDesigner FieldType.REST.

Implements three resolution modes — remote (external HTTP), internal (loopback
HTTP with SSRF guard), and callback (tenant-scoped Python coroutine registry).

Returns ``RestFieldResult`` — never raises from ``resolve()`` except for
``ConfigurationError`` (missing setup) and Jinja2 ``SecurityError``
(sandbox violation), which are treated as programmer errors.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any, Literal, Union
from urllib.parse import urlparse

import aiohttp
from jinja2.sandbox import SandboxedEnvironment, SecurityError as JinjaSecurityError
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from .auth_context import AuthContext
from .callback_registry import get_form_callback

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

RestFieldMode = Literal["remote", "internal", "callback"]


class ConfigurationError(Exception):
    """Raised when the resolver cannot proceed due to missing configuration.

    Propagates out of ``resolve()`` — it is a setup error, not a runtime one.
    """


# ---------------------------------------------------------------------------
# Spec models
# ---------------------------------------------------------------------------


class _RestFieldSpecBase(BaseModel):
    """Shared fields for all REST field spec shapes."""

    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int = 30
    response_path: str | None = None
    display_template: str | None = None
    persist_binary: bool = True
    response_schema: dict[str, Any] | None = None


class RemoteRestFieldSpec(_RestFieldSpecBase):
    """Call an arbitrary external HTTP endpoint."""

    mode: Literal["remote"] = "remote"
    endpoint: str
    http_method: Literal["GET", "POST", "PUT", "PATCH"] = "POST"
    auth_ref: str | None = None


class InternalRestFieldSpec(_RestFieldSpecBase):
    """Call an internal service endpoint (SSRF-guarded)."""

    mode: Literal["internal"] = "internal"
    endpoint: str
    http_method: Literal["GET", "POST", "PUT", "PATCH"] = "POST"

    @field_validator("endpoint")
    @classmethod
    def _leading_slash(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("internal endpoint must start with '/'")
        return v


class CallbackRestFieldSpec(_RestFieldSpecBase):
    """Invoke a pre-registered tenant-scoped Python coroutine."""

    mode: Literal["callback"] = "callback"
    callback_ref: str


# ---------------------------------------------------------------------------
# RestFieldSpec — discriminated union with .model_validate() helper
# ---------------------------------------------------------------------------

_AnyRestFieldSpec = Annotated[
    Union[RemoteRestFieldSpec, InternalRestFieldSpec, CallbackRestFieldSpec],
    Field(discriminator="mode"),
]
_rest_spec_adapter: TypeAdapter[RemoteRestFieldSpec | InternalRestFieldSpec | CallbackRestFieldSpec] = TypeAdapter(_AnyRestFieldSpec)


class RestFieldSpec:
    """Discriminated-union factory. Use ``RestFieldSpec.model_validate(data)``
    to obtain a typed concrete spec instance.
    """

    @classmethod
    def model_validate(
        cls,
        data: Any,
    ) -> RemoteRestFieldSpec | InternalRestFieldSpec | CallbackRestFieldSpec:
        """Validate and return the appropriate concrete spec.

        Args:
            data: Raw dict with a ``mode`` discriminator key.

        Returns:
            One of ``RemoteRestFieldSpec``, ``InternalRestFieldSpec``, or
            ``CallbackRestFieldSpec``.

        Raises:
            pydantic.ValidationError: On invalid input.
        """
        return _rest_spec_adapter.validate_python(data)


# ---------------------------------------------------------------------------
# Payload / output / result models
# ---------------------------------------------------------------------------


class RestCallbackInput(BaseModel):
    """Payload passed to all resolution modes (and directly to callbacks)."""

    model_config = ConfigDict(extra="forbid")

    form_id: str
    field_id: str
    session_id: str | None = None
    user_id: str | None = None
    tenant: str | None = None
    content_type: str
    content: bytes


class RestCallbackOutput(BaseModel):
    """Structured return value from a registered callback coroutine."""

    model_config = ConfigDict(extra="forbid")

    value: Any = None
    display: str | None = None
    blob_ref: str | None = None
    warnings: list[str] = []


class RestFieldResult(BaseModel):
    """Resolution result — always returned, never raises (except as noted)."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    raw_value: Any | None = None
    answer: Any | None = None
    blob_ref: str | None = None
    display: str | None = None
    status_code: int | None = None
    warnings: list[str] = []
    error: str | None = None


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class RestFieldResolver:
    """Resolve a ``FieldType.REST`` field against its spec.

    Mirrors ``RemoteResponseResolver`` for aiohttp patterns. Three modes:
    ``remote``, ``internal`` (SSRF-guarded), and ``callback``.

    Args:
        timeout: Default HTTP timeout in seconds. Overridden per-spec.
        internal_base_url: Base URL for internal-mode requests. Falls back
            to ``PARROT_INTERNAL_BASE_URL`` env var, then request host.
    """

    DEFAULT_TIMEOUT: int = 30

    def __init__(
        self,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        internal_base_url: str | None = None,
    ) -> None:
        self.timeout = timeout
        self._internal_base_url = internal_base_url
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_internal_base_url(self, *, request_host: str | None = None) -> str:
        """Return the base URL for internal-mode resolution.

        Raises:
            ConfigurationError: If no source is available.
        """
        if self._internal_base_url:
            return self._internal_base_url
        env = os.environ.get("PARROT_INTERNAL_BASE_URL")
        if env:
            return env
        if request_host:
            return f"http://{request_host}"
        raise ConfigurationError(
            "internal-mode field invoked without an internal_base_url. "
            "Set PARROT_INTERNAL_BASE_URL or pass internal_base_url to "
            "RestFieldResolver()."
        )

    def _check_ssrf(self, host: str | None) -> None:
        """Raise ValueError if ``host`` is not in the loopback allow-list.

        Args:
            host: Parsed hostname from the composed internal URL.

        Raises:
            ValueError: If host is None or not in the allow-list.
        """
        if host is None:
            raise ValueError("could not determine host from internal URL")
        allowed: set[str] = {"localhost", "127.0.0.1", "::1"}
        extra = os.environ.get("PARROT_INTERNAL_ALLOWED_HOSTS", "")
        allowed.update(h.strip() for h in extra.split(",") if h.strip())
        if host not in allowed:
            raise ValueError(f"internal host {host!r} not in allow-list")

    async def _http_call(
        self,
        endpoint: str,
        http_method: str,
        timeout_seconds: int,
        payload: RestCallbackInput,
        headers: dict[str, str],
    ) -> RestFieldResult:
        """Execute an HTTP call and return a RestFieldResult.

        Never raises — all errors are captured into the result.
        """
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        body = payload.model_dump(mode="json", exclude={"content"})

        try:
            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                method = getattr(session, http_method.lower())
                kw: dict[str, Any] = {"params": body} if http_method == "GET" else {"json": body}
                async with method(endpoint, **kw) as resp:
                    status = resp.status
                    if 200 <= status < 400:
                        try:
                            raw_value: Any = await resp.json(content_type=None)
                        except Exception:
                            raw_value = await resp.text()
                        return RestFieldResult(
                            success=True, raw_value=raw_value, status_code=status
                        )
                    try:
                        text = await resp.text()
                        error_detail = text[:200] or f"HTTP {status}"
                    except Exception:
                        error_detail = f"HTTP {status}"
                    self.logger.warning(
                        "RestFieldResolver: endpoint %r returned HTTP %d",
                        endpoint,
                        status,
                    )
                    return RestFieldResult(
                        success=False, status_code=status, error=error_detail
                    )

        except aiohttp.ClientError as exc:
            self.logger.warning(
                "RestFieldResolver: HTTP error for %r: %s", endpoint, exc
            )
            error_msg = str(exc) or f"HTTP client error: {type(exc).__name__}"
            return RestFieldResult(success=False, error=error_msg)

        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "RestFieldResolver: unexpected error for %r: %s", endpoint, exc
            )
            return RestFieldResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Mode-specific resolvers
    # ------------------------------------------------------------------

    async def _resolve_remote(
        self,
        spec: RemoteRestFieldSpec,
        payload: RestCallbackInput,
        auth_context: AuthContext | None,
    ) -> RestFieldResult:
        headers: dict[str, str] = {}
        if auth_context is not None:
            headers.update(auth_context.resolve_for(spec.auth_ref))
        return await self._http_call(
            spec.endpoint, spec.http_method, spec.timeout_seconds, payload, headers
        )

    async def _resolve_internal(
        self,
        spec: InternalRestFieldSpec,
        payload: RestCallbackInput,
    ) -> RestFieldResult:
        # ConfigurationError propagates intentionally
        base_url = self._resolve_internal_base_url()
        url = f"{base_url.rstrip('/')}{spec.endpoint}"

        parsed = urlparse(url)
        try:
            self._check_ssrf(parsed.hostname)
        except ValueError as exc:
            self.logger.warning(
                "RestFieldResolver: SSRF guard rejected %r: %s", url, exc
            )
            return RestFieldResult(success=False, error=str(exc))

        return await self._http_call(
            url, spec.http_method, spec.timeout_seconds, payload, {}
        )

    async def _resolve_callback(
        self,
        spec: CallbackRestFieldSpec,
        payload: RestCallbackInput,
        tenant: str | None,
    ) -> RestFieldResult:
        try:
            callback = get_form_callback(spec.callback_ref, tenant=tenant)
        except KeyError:
            return RestFieldResult(
                success=False,
                error=f"callback {spec.callback_ref!r} not registered",
            )
        try:
            output = await callback(payload)
            if isinstance(output, RestCallbackOutput):
                return RestFieldResult(
                    success=True,
                    raw_value=output.value,
                    blob_ref=output.blob_ref,
                    display=output.display,
                    warnings=list(output.warnings),
                )
            return RestFieldResult(success=True, raw_value=output)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "RestFieldResolver: callback %r raised: %s", spec.callback_ref, exc
            )
            return RestFieldResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def _apply_response_path(
        self, result: RestFieldResult, spec: _RestFieldSpecBase
    ) -> RestFieldResult:
        if not spec.response_path or result.raw_value is None:
            return result.model_copy(update={"answer": result.raw_value})
        try:
            from jsonpath_ng import parse as jp_parse  # noqa: PLC0415
            matches = jp_parse(spec.response_path).find(result.raw_value)
            if matches:
                answer = matches[0].value if len(matches) == 1 else [m.value for m in matches]
                return result.model_copy(update={"answer": answer})
            warnings = list(result.warnings) + [f"jsonpath_miss: {spec.response_path}"]
            return result.model_copy(update={"answer": None, "warnings": warnings})
        except Exception as exc:
            warnings = list(result.warnings) + [f"jsonpath_error: {exc}"]
            return result.model_copy(update={"answer": None, "warnings": warnings})

    def _apply_display_template(
        self, result: RestFieldResult, spec: _RestFieldSpecBase
    ) -> RestFieldResult:
        """Render ``display_template`` via Jinja2 SandboxedEnvironment.

        ``SecurityError`` (sandbox violation) propagates — it is a security
        event, not a soft failure. Other template errors become warnings.
        """
        if not spec.display_template:
            return result
        env = SandboxedEnvironment()
        try:
            tmpl = env.from_string(spec.display_template)
            display = tmpl.render(value=result.answer, raw=result.raw_value)
        except JinjaSecurityError:
            raise
        except Exception as exc:
            warnings = list(result.warnings) + [f"template_error: {exc}"]
            return result.model_copy(update={"warnings": warnings})
        return result.model_copy(update={"display": display})

    def _apply_response_schema(
        self, result: RestFieldResult, spec: _RestFieldSpecBase
    ) -> RestFieldResult:
        if not spec.response_schema or result.raw_value is None:
            return result
        try:
            import jsonschema  # noqa: PLC0415
            jsonschema.validate(result.raw_value, spec.response_schema)
        except Exception as exc:
            detail = str(getattr(exc, "message", exc))[:200]
            self.logger.warning("response_schema_mismatch: %s", detail)
            warnings = list(result.warnings) + [f"response_schema_mismatch: {detail}"]
            return result.model_copy(update={"warnings": warnings})
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve(
        self,
        spec: RemoteRestFieldSpec | InternalRestFieldSpec | CallbackRestFieldSpec,
        payload: RestCallbackInput,
        *,
        auth_context: AuthContext | None = None,
        tenant: str | None = None,
    ) -> RestFieldResult:
        """Resolve a REST field and return its result.

        Dispatches to the appropriate mode handler, then applies
        ``response_path``, ``display_template``, and ``response_schema``
        post-processing on success.

        Args:
            spec: Concrete spec instance (from ``RestFieldSpec.model_validate``).
            payload: Input data including binary content and metadata.
            auth_context: Optional auth context for ``remote`` mode.
            tenant: Tenant slug for ``callback`` mode registry lookup.

        Returns:
            ``RestFieldResult`` — always returned, never raises except for
            ``ConfigurationError`` and Jinja2 ``SecurityError``.

        Raises:
            ConfigurationError: ``internal`` mode with no base URL configured.
            SecurityError: Jinja2 sandbox violation in ``display_template``.
        """
        if isinstance(spec, RemoteRestFieldSpec):
            result = await self._resolve_remote(spec, payload, auth_context)
        elif isinstance(spec, InternalRestFieldSpec):
            result = await self._resolve_internal(spec, payload)
        else:
            result = await self._resolve_callback(spec, payload, tenant)

        if not result.success:
            return result

        result = self._apply_response_path(result, spec)
        result = self._apply_display_template(result, spec)
        result = self._apply_response_schema(result, spec)
        return result
