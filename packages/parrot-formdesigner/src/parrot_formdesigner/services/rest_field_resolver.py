"""RestFieldResolver service for FieldType.REST form fields.

Implements the three REST dispatch modes (remote / internal / callback),
JSONPath response extraction, Jinja2 display-template rendering, and
informational response-schema validation. **Never raises** — all errors
flow into ``RestFieldResult``.

Mirrors — does NOT subclass — ``RemoteResponseResolver`` (FEAT-167).

See spec §2 Architectural Design, §7 Patterns to Follow, and §8 Q2/Q3/Q5
for detailed design decisions and resolution order rules.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Annotated, Any, Literal, Union
from urllib.parse import urlparse

import aiohttp
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, ConfigDict, Field, field_validator

from parrot_formdesigner.services.auth_context import AuthContext
from parrot_formdesigner.services.callback_registry import get_form_callback

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local exceptions
# ---------------------------------------------------------------------------


class ConfigurationError(Exception):
    """Raised when resolver cannot determine the internal base URL.

    This exception surfaces on the *first* internal-mode invocation when
    no ``internal_base_url`` constructor arg, ``PARROT_INTERNAL_BASE_URL``
    env var, or request-host fallback is available.
    """


# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

RestFieldMode = Literal["remote", "internal", "callback"]

# ---------------------------------------------------------------------------
# Spec models (discriminated union)
# ---------------------------------------------------------------------------


class _RestFieldSpecBase(BaseModel):
    """Shared fields for all RestFieldSpec modes.

    Attributes:
        timeout_seconds: Per-request timeout. Defaults to 30.
        response_path: JSONPath expression (jsonpath-ng) for answer extraction.
        display_template: Jinja2 template rendered with ``answer`` in context.
        persist_binary: Whether to write the blob to blob storage. Defaults True.
        response_schema: Optional JSON Schema for informational validation.
    """

    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int = 30
    response_path: str | None = None
    display_template: str | None = None
    persist_binary: bool = True
    response_schema: dict[str, Any] | None = None


class RemoteRestFieldSpec(_RestFieldSpecBase):
    """Spec for mode='remote': calls an absolute external URL.

    Attributes:
        mode: Literal discriminator — always ``"remote"``.
        endpoint: Absolute URL (must start with ``http://`` or ``https://``).
        http_method: HTTP verb to use. Defaults to ``"POST"``.
        auth_ref: Optional auth reference passed to ``AuthContext.resolve_for``.
    """

    mode: Literal["remote"] = "remote"
    endpoint: str
    http_method: Literal["GET", "POST", "PUT", "PATCH"] = "POST"
    auth_ref: str | None = None


class InternalRestFieldSpec(_RestFieldSpecBase):
    """Spec for mode='internal': calls a relative path on the running server.

    The ``endpoint`` must start with ``"/"``; the resolver prepends
    ``internal_base_url`` (see resolution order in ``RestFieldResolver``).

    Attributes:
        mode: Literal discriminator — always ``"internal"``.
        endpoint: Relative path starting with ``"/"``
            (e.g. ``"/api/v1/networkninja/photo-analyze"``).
        http_method: HTTP verb to use. Defaults to ``"POST"``.
    """

    mode: Literal["internal"] = "internal"
    endpoint: str
    http_method: Literal["GET", "POST", "PUT", "PATCH"] = "POST"

    @field_validator("endpoint")
    @classmethod
    def _leading_slash(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(
                "internal mode endpoint must start with '/' "
                f"(got {v!r}). Use a relative path like '/api/v1/...'."
            )
        return v


class CallbackRestFieldSpec(_RestFieldSpecBase):
    """Spec for mode='callback': invokes a pre-registered Python coroutine.

    Attributes:
        mode: Literal discriminator — always ``"callback"``.
        callback_ref: Key in the callback registry (see ``callback_registry``).
    """

    mode: Literal["callback"] = "callback"
    callback_ref: str


# Annotated discriminated union — Pydantic v2 idiom
RestFieldSpec = Annotated[
    Union[RemoteRestFieldSpec, InternalRestFieldSpec, CallbackRestFieldSpec],
    Field(discriminator="mode"),
]

# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class RestCallbackInput(BaseModel):
    """Payload delivered to a registered callback coroutine.

    Attributes:
        form_id: ID of the parent form.
        field_id: ID of the field triggering the upload.
        session_id: User session ID (may be ``None``).
        user_id: Authenticated user ID (may be ``None``).
        tenant: Tenant slug (may be ``None``).
        content_type: MIME type of the uploaded content.
        content: Uploaded payload — bytes for binary, str for text, dict for JSON.
        extra_fields: Additional form fields forwarded for context.
    """

    model_config = ConfigDict(extra="forbid")

    form_id: str
    field_id: str
    session_id: str | None
    user_id: str | None
    tenant: str | None
    content_type: str
    content: Any
    extra_fields: dict[str, Any] = Field(default_factory=dict)


class RestCallbackOutput(BaseModel):
    """Return value from a registered callback coroutine.

    Attributes:
        success: Whether the callback completed successfully.
        value: Extracted or computed answer value.
        status_code: Optional synthetic HTTP status code for logging.
        error: Human-readable error message on failure.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    value: Any | None = None
    status_code: int | None = None
    error: str | None = None


class RestFieldResult(BaseModel):
    """Output of ``RestFieldResolver.resolve()``.

    Never raises — all errors are captured here.

    Warnings use the convention ``"<code>: <detail>"`` e.g.
    ``"jsonpath_miss: $.compliance_score"`` or
    ``"response_schema_mismatch: missing 'violations'"``.

    Attributes:
        success: True when the resolver obtained a usable response.
        raw_value: Raw API / callback response before JSONPath extraction.
        answer: Value after JSONPath extraction (or ``raw_value`` if no path).
        blob_ref: Set by the upload handler after blob persistence.
        display: Rendered Jinja2 ``display_template`` string.
        status_code: HTTP status code (remote / internal modes only).
        warnings: Informational warning strings (NOT ``RenderWarning``).
        error: Human-readable error message on failure.
    """

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
# Jinja2 sandboxed environment (module-level singleton)
# ---------------------------------------------------------------------------

_SANDBOX_ENV = SandboxedEnvironment()

# Per-render timeout in seconds (configurable via env var, spec §7).
# Rendering runs in a thread executor so this is a real wall-clock timeout.
_JINJA2_DISPLAY_TIMEOUT: float = float(
    os.environ.get("JINJA2_DISPLAY_TIMEOUT_SECONDS", "2")
)

# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class RestFieldResolver:
    """Dispatch FieldType.REST field uploads by mode.

    Supports three modes:
    - ``remote``: POST/GET to an absolute external URL.
    - ``internal``: POST/GET to a relative path on the running server.
    - ``callback``: Invoke a pre-registered Python coroutine.

    Mirrors the ``RemoteResponseResolver`` aiohttp pattern. **Never raises**
    from ``resolve()`` — all errors flow into ``RestFieldResult``.

    Args:
        timeout: Default HTTP timeout in seconds. Defaults to 30.
        internal_base_url: Explicit base URL for ``internal`` mode
            (e.g. ``"http://localhost:8080"``). Takes priority over the
            ``PARROT_INTERNAL_BASE_URL`` env var and request-host fallback.
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
        # Cache SSRF allow-list at construction time (not per-call).
        self._ssrf_allowed_hosts: set[str] = {"localhost", "127.0.0.1", "::1"}
        _extra = os.environ.get("PARROT_INTERNAL_ALLOWED_HOSTS", "")
        self._ssrf_allowed_hosts.update(h.strip() for h in _extra.split(",") if h.strip())

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def resolve(
        self,
        spec: RemoteRestFieldSpec | InternalRestFieldSpec | CallbackRestFieldSpec,
        payload: RestCallbackInput,
        *,
        auth_context: AuthContext | None = None,
        tenant: str | None = None,
        request_host: str | None = None,
    ) -> RestFieldResult:
        """Dispatch by ``spec.mode`` and return the result.

        Never raises. All errors are captured in the returned
        ``RestFieldResult``.

        Args:
            spec: The validated ``RestFieldSpec`` for this field.
            payload: Callback input carrying content, IDs, and metadata.
            auth_context: Optional inbound auth context for header injection.
            tenant: Tenant slug for callback registry lookup.
            request_host: Host string from the inbound request
                (e.g. ``"localhost:8080"``). Used as the last-resort
                fallback for ``internal`` mode base-URL resolution when
                neither ``internal_base_url`` nor
                ``PARROT_INTERNAL_BASE_URL`` is configured.

        Returns:
            ``RestFieldResult`` — always; never raises.
        """
        try:
            if spec.mode == "remote":
                result = await self._dispatch_remote(
                    spec,  # type: ignore[arg-type]
                    payload,
                    auth_context=auth_context,
                )
            elif spec.mode == "internal":
                result = await self._dispatch_internal(
                    spec,  # type: ignore[arg-type]
                    payload,
                    auth_context=auth_context,
                    request_host=request_host,
                )
            elif spec.mode == "callback":
                result = await self._dispatch_callback(
                    spec,  # type: ignore[arg-type]
                    payload,
                    auth_context=auth_context,
                    tenant=tenant,
                )
            else:
                return RestFieldResult(
                    success=False,
                    error=f"unknown mode {spec.mode!r}",
                )
        except ConfigurationError as exc:
            # ConfigurationError is a programmer/deployment error.
            # Capture it in the result envelope — the "never-raises" contract
            # applies to all callers including handlers that have no try/except.
            self.logger.error("RestFieldResolver configuration error: %s", exc)
            return RestFieldResult(
                success=False,
                error=f"configuration_error: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("RestFieldResolver.resolve unexpected error: %s", exc)
            return RestFieldResult(success=False, error=str(exc))

        # Post-process: JSONPath extraction, display template, response schema
        result = await self._post_process(result, spec)
        return result

    # ------------------------------------------------------------------
    # Private dispatch methods
    # ------------------------------------------------------------------

    async def _dispatch_remote(
        self,
        spec: RemoteRestFieldSpec,
        payload: RestCallbackInput,
        *,
        auth_context: AuthContext | None,
    ) -> RestFieldResult:
        """Call an absolute external URL (remote mode)."""
        headers: dict[str, str] = {}
        if auth_context is not None:
            headers.update(auth_context.resolve_for(spec.auth_ref))

        effective_timeout = spec.timeout_seconds or self.timeout
        timeout = aiohttp.ClientTimeout(total=effective_timeout)

        try:
            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                raw_value, status_code = await self._http_call(
                    session, spec.endpoint, spec.http_method, payload
                )
            if raw_value is None:
                return RestFieldResult(
                    success=False,
                    status_code=status_code,
                    error=f"HTTP {status_code}",
                )
            return RestFieldResult(
                success=True,
                raw_value=raw_value,
                status_code=status_code,
            )
        except aiohttp.ClientError as exc:
            self.logger.warning(
                "RestFieldResolver remote error for %r: %s", spec.endpoint, exc
            )
            return RestFieldResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "RestFieldResolver remote unexpected error for %r: %s",
                spec.endpoint,
                exc,
            )
            return RestFieldResult(success=False, error=str(exc))

    async def _dispatch_internal(
        self,
        spec: InternalRestFieldSpec,
        payload: RestCallbackInput,
        *,
        auth_context: AuthContext | None,
        request_host: str | None = None,
    ) -> RestFieldResult:
        """Call a relative path on the running server (internal mode)."""
        # ConfigurationError propagates to resolve(), which captures it.
        base_url = self._resolve_internal_base_url(request_host=request_host)

        full_url = f"{base_url.rstrip('/')}{spec.endpoint}"
        parsed = urlparse(full_url)
        try:
            self._check_ssrf(parsed.hostname or "")
        except ValueError as exc:
            return RestFieldResult(success=False, error=str(exc))

        headers: dict[str, str] = {}
        if auth_context is not None:
            # Cascade the inbound auth headers into the internal call
            headers.update(auth_context.resolve_for(None))

        effective_timeout = spec.timeout_seconds or self.timeout
        timeout = aiohttp.ClientTimeout(total=effective_timeout)

        try:
            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                raw_value, status_code = await self._http_call(
                    session, full_url, spec.http_method, payload
                )
            if raw_value is None:
                return RestFieldResult(
                    success=False,
                    status_code=status_code,
                    error=f"HTTP {status_code}",
                )
            return RestFieldResult(
                success=True,
                raw_value=raw_value,
                status_code=status_code,
            )
        except aiohttp.ClientError as exc:
            self.logger.warning(
                "RestFieldResolver internal error for %r: %s", full_url, exc
            )
            return RestFieldResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "RestFieldResolver internal unexpected error for %r: %s",
                full_url,
                exc,
            )
            return RestFieldResult(success=False, error=str(exc))

    async def _dispatch_callback(
        self,
        spec: CallbackRestFieldSpec,
        payload: RestCallbackInput,
        *,
        auth_context: AuthContext | None,
        tenant: str | None,
    ) -> RestFieldResult:
        """Invoke a pre-registered Python coroutine (callback mode)."""
        try:
            callback = get_form_callback(spec.callback_ref, tenant=tenant)
        except KeyError:
            err = (
                f"callback {spec.callback_ref!r} is not registered "
                f"(tenant={tenant!r}). Register it with "
                "@register_form_callback before starting the server."
            )
            self.logger.warning("RestFieldResolver: %s", err)
            return RestFieldResult(success=False, error=err)

        try:
            output: RestCallbackOutput = await callback(payload, auth_context)
            if not output.success:
                return RestFieldResult(
                    success=False,
                    error=output.error,
                    status_code=output.status_code,
                )
            return RestFieldResult(
                success=True,
                raw_value=output.value,
                status_code=output.status_code,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "RestFieldResolver callback %r raised: %s",
                spec.callback_ref,
                exc,
            )
            return RestFieldResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    async def _post_process(
        self,
        result: RestFieldResult,
        spec: RemoteRestFieldSpec | InternalRestFieldSpec | CallbackRestFieldSpec,
    ) -> RestFieldResult:
        """Apply JSONPath extraction, display template, and schema validation.

        Mutates a copy of the result. All post-processing errors are
        appended as warnings (never cause failure on a successful result).
        """
        warnings: list[str] = list(result.warnings)
        answer = result.raw_value

        # JSONPath extraction
        if result.success and spec.response_path and result.raw_value is not None:
            try:
                from jsonpath_ng import parse as jsonpath_parse  # deferred import

                expr = jsonpath_parse(spec.response_path)
                matches = expr.find(result.raw_value)
                if matches:
                    answer = matches[0].value
                else:
                    warnings.append(f"jsonpath_miss: {spec.response_path}")
                    self.logger.warning(
                        "RestFieldResolver: JSONPath %r found no match in response",
                        spec.response_path,
                    )
                    answer = None
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"jsonpath_error: {exc}")
                self.logger.warning(
                    "RestFieldResolver: JSONPath error (%s): %s",
                    spec.response_path,
                    exc,
                )
                answer = None

        # Response-schema validation (informational only)
        if result.success and spec.response_schema and result.raw_value is not None:
            try:
                import jsonschema  # optional dep — test extra

                jsonschema.validate(result.raw_value, spec.response_schema)
            except ImportError:
                warnings.append("response_schema_mismatch: jsonschema not installed")
            except Exception as exc:  # noqa: BLE001
                detail = str(exc)[:200]
                warnings.append(f"response_schema_mismatch: {detail}")
                self.logger.warning(
                    "RestFieldResolver: response schema validation failed: %s", detail
                )

        # Jinja2 display template (sandboxed, with per-render timeout).
        # Rendering is synchronous (Jinja2 limitation) so it runs in a
        # thread executor. asyncio.wait_for() caps wall-clock time to
        # _JINJA2_DISPLAY_TIMEOUT seconds (default 2s, spec §7).
        display: str | None = None
        if result.success and spec.display_template:
            try:
                tmpl = _SANDBOX_ENV.from_string(spec.display_template)
                _captured_answer = answer
                _captured_raw = result.raw_value
                display = await asyncio.wait_for(
                    asyncio.to_thread(
                        lambda: tmpl.render(
                            answer=_captured_answer, raw_value=_captured_raw
                        )
                    ),
                    timeout=_JINJA2_DISPLAY_TIMEOUT,
                )
            except asyncio.TimeoutError:
                warnings.append(
                    f"display_template_error: render timed out after "
                    f"{_JINJA2_DISPLAY_TIMEOUT}s"
                )
                self.logger.warning(
                    "RestFieldResolver: display template timed out (%ss)",
                    _JINJA2_DISPLAY_TIMEOUT,
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"display_template_error: {exc}")
                self.logger.warning(
                    "RestFieldResolver: display template render error: %s", exc
                )

        return RestFieldResult(
            success=result.success,
            raw_value=result.raw_value,
            answer=answer,
            blob_ref=result.blob_ref,
            display=display,
            status_code=result.status_code,
            warnings=warnings,
            error=result.error,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _http_call(
        self,
        session: aiohttp.ClientSession,
        url: str,
        method: str,
        payload: RestCallbackInput,
    ) -> tuple[Any | None, int]:
        """Make the HTTP call and return (parsed_response_or_None, status_code).

        Returns ``(None, status_code)`` for non-2xx responses.
        """
        method_name = method.lower()
        http_method = getattr(session, method_name)

        # Build request body: prefer JSON if content is dict, else bytes
        if isinstance(payload.content, dict):
            request_kwargs: dict[str, Any] = {"json": payload.content}
        elif isinstance(payload.content, bytes):
            request_kwargs = {
                "data": payload.content,
                "headers": {"Content-Type": payload.content_type},
            }
        else:
            request_kwargs = {"data": str(payload.content)}

        async with http_method(url, **request_kwargs) as resp:
            status = resp.status
            if 200 <= status < 400:
                try:
                    value = await resp.json(content_type=None)
                except Exception:
                    value = await resp.text()
                return value, status
            else:
                return None, status

    def _resolve_internal_base_url(self, *, request_host: str | None = None) -> str:
        """Resolve the internal base URL using the precedence chain.

        Resolution order (spec §7 Q2):
        1. Constructor argument ``internal_base_url``.
        2. ``PARROT_INTERNAL_BASE_URL`` environment variable.
        3. ``request_host`` fallback (only when request-bound).
        4. Raise ``ConfigurationError`` (fail fast).

        Args:
            request_host: Optional host string threaded in by the handler
                (e.g. ``"localhost:8080"``). Only used as last resort before
                raising.

        Returns:
            Resolved base URL string.

        Raises:
            ConfigurationError: When no base URL can be determined.
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
            "Set PARROT_INTERNAL_BASE_URL or pass internal_base_url= to "
            "RestFieldResolver()."
        )

    def _check_ssrf(self, host: str) -> None:
        """Reject internal-mode calls to hosts outside the allow-list.

        Allow-list: ``localhost``, ``127.0.0.1``, ``::1``, plus any host
        configured via ``PARROT_INTERNAL_ALLOWED_HOSTS`` (comma-separated).
        The list is cached at construction time — not re-read on every call.

        Args:
            host: Hostname extracted from the resolved internal URL.

        Raises:
            ValueError: When the host is not in the allow-list.
        """
        if host not in self._ssrf_allowed_hosts:
            raise ValueError(
                f"internal host {host!r} is not in the SSRF allow-list "
                f"(PARROT_INTERNAL_ALLOWED_HOSTS). Allowed: "
                f"{sorted(self._ssrf_allowed_hosts)}"
            )
