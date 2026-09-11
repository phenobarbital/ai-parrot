"""Host broker: manifest-allowlisted I/O for tier BROKERED/TOOLKIT (FEAT-459 / M11).

Runs in the TRUSTED process. Tier 3/4 workers issue typed BrokerRequests
over the worker channel (TASK-3168's protocol) instead of touching a
socket directly; this class validates each request against the snippet's
declared CapabilityManifest.allowlist and performs the I/O itself.

Deny-by-default: any request kind/target not explicitly present in the
allowlist raises CapabilityDenied and is logged as a security event.
"""

from __future__ import annotations

import logging

import aiohttp

from parrot_formdesigner.core.snippets import CapabilityDenied, CapabilityManifest
from parrot_formdesigner.services.sandbox.protocol import BrokerRequest, BrokerResponse

logger = logging.getLogger(__name__)

_ALLOWLIST_FIELD_BY_KIND: dict[str, str] = {
    "http_hosts": "http_hosts",
    "query_tables": "query_tables",
    "notifications": "notifications",
    "toolkits": "toolkits",
}


class HostBroker:
    """Validates and executes BrokerRequests against a manifest allowlist."""

    def __init__(self, *, max_calls_per_invocation: int = 10) -> None:
        """
        Args:
            max_calls_per_invocation: Hard cap on handle() calls for a
                single snippet execution. 10 is a conservative starting
                default (not spec-mandated — the spec's OQ-6 table covers
                pool sizing, not broker call limits) chosen so a
                misbehaving or compromised-manifest snippet cannot loop
                indefinitely against an allowlisted host; tune via a
                follow-up if real broker traffic patterns justify a
                different number. A NEW HostBroker instance (or an
                explicit reset) is required per snippet invocation — this
                counter is NOT request-scoped by itself.
        """
        self._max_calls_per_invocation = max_calls_per_invocation
        self._call_count = 0
        self.logger = logger

    def _check_allowlist(self, request: BrokerRequest, manifest: CapabilityManifest) -> None:
        """Raise CapabilityDenied if `request` is outside `manifest.allowlist`.

        Exact string match only — no wildcards (spec: "exact hostnames;
        no wildcards in v1").
        """
        field_name = _ALLOWLIST_FIELD_BY_KIND.get(request.kind)
        if field_name is None:
            raise CapabilityDenied(f"unrecognised broker request kind: {request.kind!r}")
        allowed_targets: tuple[str, ...] = getattr(manifest.allowlist, field_name)
        if request.target not in allowed_targets:
            raise CapabilityDenied(
                f"{request.kind}={request.target!r} is not in the declared allowlist "
                f"{allowed_targets!r}"
            )

    def _log_denial(
        self, request: BrokerRequest, *, tenant: str | None, handler_ref: str, reason: str
    ) -> None:
        """Structured security log event (spec §5 Operational AC)."""
        self.logger.warning(
            "capability_denied tenant=%r handler_ref=%r kind=%r target=%r reason=%r",
            tenant,
            handler_ref,
            request.kind,
            request.target,
            reason,
        )

    async def handle(
        self,
        request: BrokerRequest,
        manifest: CapabilityManifest,
        *,
        tenant: str | None,
        handler_ref: str,
    ) -> BrokerResponse:
        """Validate and execute one BrokerRequest.

        Note: extends the spec §2 skeleton's `handle(request, manifest)`
        signature with required `tenant`/`handler_ref` keyword-only args
        — needed to satisfy the spec's own §5 AC that a denial log
        include both, which BrokerRequest itself does not carry.

        Args:
            request: The typed request from a tier 3/4 worker.
            manifest: The executing snippet's CapabilityManifest.
            tenant: For the security log event only.
            handler_ref: For the security log event only.

        Returns:
            BrokerResponse with the I/O result.

        Raises:
            CapabilityDenied: request is outside the allowlist, OR the
                per-invocation call cap has been exceeded.
        """
        if self._call_count >= self._max_calls_per_invocation:
            self._log_denial(
                request,
                tenant=tenant,
                handler_ref=handler_ref,
                reason=f"call cap exceeded ({self._max_calls_per_invocation})",
            )
            raise CapabilityDenied(
                f"broker call cap ({self._max_calls_per_invocation}) exceeded for this invocation"
            )
        self._call_count += 1

        try:
            self._check_allowlist(request, manifest)
        except CapabilityDenied as exc:
            self._log_denial(request, tenant=tenant, handler_ref=handler_ref, reason=str(exc))
            raise

        if request.kind == "http_hosts":
            return await self._handle_http(request)
        if request.kind == "query_tables":
            # FILL IN: no concrete query backend is specified by the spec
            #   — bounded by whatever this deployment's data layer is
            #   (likely asyncpg against the same tenant schema
            #   FormRegistry/DbSnippetStore use); the shape here MUST
            #   still go through _check_allowlist above unchanged.
            raise NotImplementedError("query_tables broker path not yet implemented")
        if request.kind == "notifications":
            # FILL IN: no concrete notification channel backend specified.
            raise NotImplementedError("notifications broker path not yet implemented")
        if request.kind == "toolkits":
            # FILL IN: dispatch into a registered parrot toolkit
            #   (parrot.tools.ToolManager or similar) — do not reimplement
            #   toolkit invocation here; call the existing manager.
            raise NotImplementedError("toolkits broker path not yet implemented")
        raise CapabilityDenied(
            f"unhandled broker request kind: {request.kind!r}"
        )  # unreachable given _check_allowlist

    async def _handle_http(self, request: BrokerRequest) -> BrokerResponse:
        """Perform an allowlisted outbound HTTP call via aiohttp."""
        method = request.args.get("method", "GET")
        path = request.args.get("path", "/")
        url = f"https://{request.target}{path}"
        extra_kwargs = {k: v for k, v in request.args.items() if k not in ("method", "path")}
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, **extra_kwargs) as resp:
                body = await resp.text()
                return BrokerResponse(result={"status": resp.status, "body": body})
