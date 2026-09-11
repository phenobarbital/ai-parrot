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
from yarl import URL

from parrot_formdesigner.core.snippets import CapabilityDenied, CapabilityManifest, CapabilityTier
from parrot_formdesigner.services.sandbox.protocol import BrokerRequest, BrokerResponse

logger = logging.getLogger(__name__)

_ALLOWLIST_FIELD_BY_KIND: dict[str, str] = {
    "http_hosts": "http_hosts",
    "query_tables": "query_tables",
    "notifications": "notifications",
    "toolkits": "toolkits",
}

#: Post-review security fix: only these BrokerRequest.args keys are ever
#: forwarded to aiohttp — a snippet-controlled `proxy`/`ssl`/
#: `allow_redirects`/`headers` value could otherwise be used to bypass
#: the allowlist boundary this broker exists to enforce.
_ALLOWED_HTTP_ARGS: frozenset[str] = frozenset({"json", "params"})

#: Hard cap on a broker HTTP response body, in bytes — the trusted
#: process must never buffer an unbounded response on a sandboxed
#: snippet's behalf.
_MAX_RESPONSE_BODY_BYTES = 1_048_576

#: Only these two tiers may ever reach a broker call — defense in depth
#: in case handle() is ever invoked outside the TierRouter->gVisor path
#: this class was designed for.
_BROKER_ELIGIBLE_TIERS = (CapabilityTier.BROKERED, CapabilityTier.TOOLKIT)


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
        # Post-review security fix: defense in depth — only tiers
        # BROKERED/TOOLKIT may ever have a non-empty allowlist honored,
        # in case handle() is ever called for a bundle outside the
        # TierRouter->gVisor path this class was designed for.
        if manifest.tier not in _BROKER_ELIGIBLE_TIERS:
            raise CapabilityDenied(
                f"manifest tier={manifest.tier!r} is not eligible for any broker request "
                "(only BROKERED/TOOLKIT may use the host broker)"
            )
        field_name = _ALLOWLIST_FIELD_BY_KIND.get(request.kind)
        if field_name is None:
            raise CapabilityDenied(f"unrecognised broker request kind: {request.kind!r}")
        allowed_targets: tuple[str, ...] = getattr(manifest.allowlist, field_name)
        if request.target not in allowed_targets:
            raise CapabilityDenied(
                f"{request.kind}={request.target!r} is not in the declared allowlist " f"{allowed_targets!r}"
            )

    def _log_denial(self, request: BrokerRequest, *, tenant: str | None, handler_ref: str, reason: str) -> None:
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
            raise CapabilityDenied(f"broker call cap ({self._max_calls_per_invocation}) exceeded for this invocation")
        self._call_count += 1

        try:
            self._check_allowlist(request, manifest)

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
        except CapabilityDenied as exc:
            # Post-review fix: this used to only wrap _check_allowlist —
            # a CapabilityDenied raised later during dispatch (e.g.
            # _handle_http's path-shape validation) went unlogged. Every
            # denial, wherever it originates, must emit the same
            # structured security event (spec §5 Operational AC).
            self._log_denial(request, tenant=tenant, handler_ref=handler_ref, reason=str(exc))
            raise

    async def _handle_http(self, request: BrokerRequest) -> BrokerResponse:
        """Perform an allowlisted outbound HTTP call via aiohttp.

        Post-review security fix: the original implementation built the
        URL by string-formatting `request.target` and `request.args["path"]`
        together (``f"https://{target}{path}"``). A snippet-controlled
        `path` of `"@evil.example/"` produced `https://allowed.example@
        evil.example/` — a userinfo-based allowlist bypass whose ACTUAL
        connection target is `evil.example`, not the allowlisted host.
        `request.args` was also forwarded to aiohttp verbatim, letting a
        snippet supply `proxy`/`ssl`/`allow_redirects`/`headers` and
        redirect or downgrade the connection out from under the allowlist.

        Fixed by building the URL with `yarl.URL.build()` — host and path
        are distinct fields, not concatenated strings, so a path value
        can never redirect the actual connection target — forwarding
        only an explicit args allowlist (`_ALLOWED_HTTP_ARGS`), disabling
        automatic redirects (a redirect target is not re-checked against
        the allowlist), applying an explicit timeout, and bounding the
        response body read.
        """
        method = request.args.get("method", "GET")
        path = request.args.get("path", "/")
        if not path.startswith("/"):
            # A path not starting with "/" is exactly the shape of a
            # userinfo-injection attempt (e.g. "@evil.example.com/") that
            # this fix's URL.build() call would otherwise reject with a
            # bare ValueError — deny it explicitly with a clear signal
            # instead of letting an internal yarl error leak out.
            raise CapabilityDenied(f"http_hosts path must start with '/', got {path!r}")
        url = URL.build(scheme="https", host=request.target, path=path)
        safe_kwargs = {k: v for k, v in request.args.items() if k in _ALLOWED_HTTP_ARGS}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.request(method, url, allow_redirects=False, **safe_kwargs) as resp:
                body_bytes = await resp.content.read(_MAX_RESPONSE_BODY_BYTES)
                body = body_bytes.decode("utf-8", errors="replace")
                return BrokerResponse(result={"status": resp.status, "body": body})
