"""HTTP surface for a tenant's own BYOK credentials.

Values are **write-only through this API**. They go in through ``PUT`` and come
out only inside the process, when the agent builder constructs a client. Nothing
here returns a secret: the listing and item reads serialize
:class:`~parrot.security.secrets.base.SecretMeta`, which has no field capable of
carrying one, so a leak would take a deliberate new field rather than a slip.

**The tenant comes from the middleware, never from the request.** Every handler
reads it through :func:`~parrot_saas.tenancy.middleware.current_tenant`. Taking
it from the path or the body instead is the one change that would turn this into
a cross-tenant reader, which is why it is stated here rather than assumed.

**Mutations invalidate the tenant's runtime.** A cached runtime holds agents
built from the previous credentials — or no agents at all, for a tenant that has
just uploaded its first key — so without the eviction an upload would appear to
do nothing until the cache expired half an hour later.

**On error responses**: as in :mod:`~parrot_saas.handlers.tenants`,
``BaseView.error()`` is avoided. It raises rather than returns, and its status
map silently turns anything outside 400/401/403/404/406/412/428 into a 400 —
which would misreport both the 503 and the 204 used here.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView

from ..llm.credentials import ANTHROPIC_API_KEY_SECRET, GOOGLE_API_KEY_SECRET
from ..tenancy.middleware import current_tenant
from .tenants import APP_TENANT_RUNTIMES, json_error

#: Key under which ``setup_saas_api`` publishes the memoising store factory.
APP_SECRET_STORE_FACTORY = "saas_secret_store_factory"

#: Accepted secret names: two or three lowercase segments, ``provider:field``.
#: Three segments exist for per-source webhook secrets (``webhook:<src>:hmac``).
#: This is not cosmetic — the key is bound into the ciphertext's AAD, so it is
#: part of the encryption context rather than a free-form label.
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*(:[a-z0-9][a-z0-9_-]*){1,2}$")

#: Upper bound on a secret name.
MAX_KEY_LENGTH = 128

#: Upper bound on a secret value. Provider API keys are tens of bytes; this is
#: generous while keeping a single request from writing a huge encrypted row.
MAX_VALUE_LENGTH = 8192

#: Names this deployment knows what to do with. Advisory only — the store holds
#: whatever a tenant writes — but it lets a UI render the right form without
#: hard-coding the strings a second time.
KNOWN_KEYS = (GOOGLE_API_KEY_SECRET, ANTHROPIC_API_KEY_SECRET)

#: PBAC resource this surface is gated by. ``ResourceType`` is a closed enum
#: with no secret member, but ``ResourcePolicy.covers_resource`` supports custom
#: string types, which is what ``policies/saas.yaml`` relies on.
PBAC_RESOURCE_TYPE = "saas"
PBAC_RESOURCE_NAME = "secrets"

logger = logging.getLogger("parrot_saas.handlers.secrets")


def _meta_json(meta: Any) -> dict:
    """Render :class:`SecretMeta` for the wire.

    Built field by field rather than with ``asdict`` so that a field added to
    ``SecretMeta`` later cannot start appearing in responses on its own.

    Args:
        meta: The metadata record.

    Returns:
        A JSON-safe dict carrying no secret material.
    """
    return {
        "key": meta.key,
        "fingerprint": meta.fingerprint,
        "created_at": meta.created_at.isoformat() if meta.created_at else None,
        "updated_at": meta.updated_at.isoformat() if meta.updated_at else None,
    }


class _SecretViewBase(BaseView):
    """Shared plumbing: tenant, store, authorization, validation."""

    def _tenant(self):
        """Return the tenant resolved by the middleware.

        Raises:
            RuntimeError: If the middleware did not run for this route, which
                would otherwise mean serving secrets with no tenant at all.
        """
        return current_tenant(self.request)

    def _store(self) -> tuple[Optional[Any], Optional[web.Response]]:
        """Resolve the secret store, or explain why there is none.

        Returns:
            ``(store, None)``, or ``(None, response)`` carrying a 503.
        """
        factory = self.request.app.get(APP_SECRET_STORE_FACTORY)
        if factory is None:
            return None, json_error(
                503,
                "secret_store_unavailable",
                "no secret store is configured; call setup_saas_api(app)",
            )
        try:
            return factory(), None
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            # Typically a missing vault master key. Unlike runtime construction,
            # a secrets request genuinely cannot proceed without a store, and
            # answering 200 with an empty list would be a lie.
            logger.error("secret store unavailable: %s", exc)
            return None, json_error(
                503,
                "secret_store_unavailable",
                f"the secret store could not be opened: {exc}",
            )

    async def _authorize(self, action: str) -> Optional[web.Response]:
        """Check the tenant-admin policy for one action.

        Enforced whenever a policy decision point is configured. When none is —
        ``setup_pbac`` returns nothing at all if its policy directory is
        missing — this logs and allows, matching the convention already used by
        the agent handlers. That is defensible *here* specifically because
        authorization is not the isolation boundary: without a PDP the
        degradation is "any authenticated user of this tenant" rather than
        "only its admin", never access to another tenant, whose separation the
        resolution middleware enforces independently.

        Args:
            action: The policy action, e.g. ``"saas:secret:write"``.

        Returns:
            ``None`` when allowed, or a 403 response.
        """
        pdp = self.request.app.get("abac")
        evaluator = getattr(pdp, "_evaluator", None) if pdp is not None else None
        if evaluator is None:
            logger.warning(
                "no PBAC policy engine configured; serving %s without an "
                "authorization decision",
                action,
            )
            return None

        try:
            from navigator_auth.abac.context import EvalContext
            from navigator_auth.abac.policies.environment import Environment

            session = self.request.get("session") or {}
            try:
                from navigator_auth.conf import AUTH_SESSION_OBJECT

                userinfo = session.get(AUTH_SESSION_OBJECT, {}) or {}
            except ImportError:  # pragma: no cover - navigator-auth optional
                userinfo = {}
            ctx = EvalContext(
                self.request,
                user=self.request.get("user"),
                userinfo=userinfo,
                session=session,
            )
            result = evaluator.check_access(
                ctx=ctx,
                resource_type=PBAC_RESOURCE_TYPE,
                resource_name=PBAC_RESOURCE_NAME,
                action=action,
                env=Environment(),
            )
        except Exception as exc:  # noqa: BLE001 - see below
            # A broken evaluation must not become an open door on this surface.
            logger.error("PBAC evaluation failed for %s: %s", action, exc)
            return json_error(
                403, "forbidden", "the authorization decision could not be made"
            )

        if not result.allowed:
            logger.warning(
                "PBAC denied %s for tenant %s (policy=%s)",
                action,
                self._tenant().tenant_id,
                getattr(result, "matched_policy", None),
            )
            return json_error(
                403,
                "forbidden",
                getattr(result, "reason", None) or f"{action} is not permitted",
            )
        return None

    async def _invalidate_runtime(self, tenant_id: str) -> None:
        """Drop the tenant's cached runtime after a credential change.

        The agents in a live runtime were built from the previous credentials,
        so skipping this makes an upload look like a no-op until the cache TTL
        expires.

        Args:
            tenant_id: Tenant whose runtime should be rebuilt on next use.
        """
        runtimes = self.request.app.get(APP_TENANT_RUNTIMES)
        if runtimes is not None:
            await runtimes.invalidate(tenant_id)

    def _key(self) -> tuple[Optional[str], Optional[web.Response]]:
        """Read and validate the secret name from the path.

        Returns:
            ``(key, None)`` or ``(None, response)`` carrying a 400.
        """
        key = self.request.match_info.get("key", "")
        if len(key) > MAX_KEY_LENGTH or not KEY_PATTERN.match(key):
            return None, json_error(
                400,
                "invalid_key",
                "a secret name is two or three lowercase segments separated by "
                "':' (for example 'anthropic:api_key')",
                key=key[:MAX_KEY_LENGTH],
            )
        return key, None

    async def _value(self) -> tuple[Optional[str], Optional[web.Response]]:
        """Read and validate the secret value from the JSON body.

        The value is only ever accepted in the body. A query parameter would be
        recorded verbatim in the access log, which writes the plaintext to disk.

        Returns:
            ``(value, None)`` or ``(None, response)`` carrying a 400.
        """
        import json

        raw = await self.request.text()
        if not raw.strip():
            return None, json_error(
                400, "invalid_json", "request body is required"
            )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, json_error(
                400, "invalid_json", f"request body is not valid JSON: {exc}"
            )
        if not isinstance(payload, dict):
            return None, json_error(
                400, "invalid_json", "request body must be a JSON object"
            )

        value = payload.get("value")
        if not isinstance(value, str) or not value.strip():
            return None, json_error(
                400,
                "invalid_value",
                "'value' must be a non-empty string",
            )
        if len(value) > MAX_VALUE_LENGTH:
            return None, json_error(
                400,
                "invalid_value",
                f"'value' exceeds {MAX_VALUE_LENGTH} characters",
            )
        return value, None


class SecretCollectionView(_SecretViewBase):
    """List the tenant's secrets as metadata."""

    _logger_name: str = "parrot_saas.SecretCollectionView"

    async def get(self) -> web.Response:
        """Return metadata for every secret this tenant owns.

        Never returns a value. The fingerprint is what makes the listing
        useful: a client can tell whether an upload changed anything, and
        correlate a key with the audit ledger, without either side handling
        plaintext.
        """
        denied = await self._authorize("saas:secret:list")
        if denied is not None:
            return denied
        store, error = self._store()
        if error is not None:
            return error

        tenant = self._tenant()
        metas = await store.list_keys(tenant.tenant_id)
        return web.json_response(
            {
                "secrets": [_meta_json(m) for m in metas],
                "count": len(metas),
                "known_keys": list(KNOWN_KEYS),
            }
        )


class SecretRotateView(_SecretViewBase):
    """Re-encrypt a tenant's secrets under a fresh data key."""

    _logger_name: str = "parrot_saas.SecretRotateView"

    async def post(self) -> web.Response:
        """Rotate this tenant's data-encryption key.

        Values are unchanged; only the key protecting them is replaced. The
        runtime is still invalidated because the rotation touches every row of
        the tenant and a rebuild is the cheap way to be sure nothing cached is
        holding a stale handle.
        """
        denied = await self._authorize("saas:secret:rotate")
        if denied is not None:
            return denied
        store, error = self._store()
        if error is not None:
            return error

        tenant = self._tenant()
        rotated = await store.rotate_dek(tenant.tenant_id)
        await self._invalidate_runtime(tenant.tenant_id)
        logger.info(
            "rotated the data key for tenant %s (%d secrets re-encrypted)",
            tenant.tenant_id,
            rotated,
        )
        return web.json_response({"rotated": rotated})


class SecretItemView(_SecretViewBase):
    """Read metadata for, write, or remove one secret."""

    _logger_name: str = "parrot_saas.SecretItemView"

    async def get(self) -> web.Response:
        """Return one secret's metadata — never its value."""
        denied = await self._authorize("saas:secret:list")
        if denied is not None:
            return denied
        key, error = self._key()
        if error is not None:
            return error
        store, error = self._store()
        if error is not None:
            return error

        tenant = self._tenant()
        for meta in await store.list_keys(tenant.tenant_id):
            if meta.key == key:
                return web.json_response(_meta_json(meta))
        return json_error(404, "unknown_secret", f"no secret named {key!r}")

    async def put(self) -> web.Response:
        """Store or replace a secret value."""
        denied = await self._authorize("saas:secret:write")
        if denied is not None:
            return denied
        key, error = self._key()
        if error is not None:
            return error
        value, error = await self._value()
        if error is not None:
            return error
        store, error = self._store()
        if error is not None:
            return error

        tenant = self._tenant()
        meta = await store.put(tenant.tenant_id, key, value)
        await self._invalidate_runtime(tenant.tenant_id)

        # The upsert leaves created_at alone and stamps updated_at, so equal
        # timestamps mean this call created the row.
        created = meta.created_at == meta.updated_at
        logger.info(
            "tenant %s stored secret %s (fingerprint=%s, created=%s)",
            tenant.tenant_id,
            key,
            meta.fingerprint,
            created,
        )
        return web.json_response(_meta_json(meta), status=201 if created else 200)

    async def delete(self) -> web.Response:
        """Remove a secret."""
        denied = await self._authorize("saas:secret:delete")
        if denied is not None:
            return denied
        key, error = self._key()
        if error is not None:
            return error
        store, error = self._store()
        if error is not None:
            return error

        tenant = self._tenant()
        removed = await store.delete(tenant.tenant_id, key)
        if not removed:
            return json_error(404, "unknown_secret", f"no secret named {key!r}")

        await self._invalidate_runtime(tenant.tenant_id)
        logger.info("tenant %s removed secret %s", tenant.tenant_id, key)
        return web.Response(status=204)


def setup_secret_routes(
    app: web.Application, *, base: str = "/api/v1/saas/secrets"
) -> None:
    """Register the tenant secrets routes.

    ``rotate-dek`` is registered **before** the ``{key}`` route on purpose:
    aiohttp resolves resources in registration order, so the dynamic pattern
    would otherwise swallow the static path.

    Args:
        app: The aiohttp application.
        base: Base path for the collection.
    """
    _app = app.get_app() if hasattr(app, "get_app") else app
    _app.router.add_view(base, SecretCollectionView)
    _app.router.add_view(f"{base}/rotate-dek", SecretRotateView)
    _app.router.add_view(f"{base}/{{key}}", SecretItemView)


__all__ = (
    "APP_SECRET_STORE_FACTORY",
    "KEY_PATTERN",
    "KNOWN_KEYS",
    "MAX_KEY_LENGTH",
    "MAX_VALUE_LENGTH",
    "SecretCollectionView",
    "SecretItemView",
    "SecretRotateView",
    "setup_secret_routes",
)
