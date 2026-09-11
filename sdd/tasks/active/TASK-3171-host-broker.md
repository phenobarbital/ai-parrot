# TASK-3171: Host broker — `services/sandbox/broker.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3161, TASK-3168
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11. Tiers 3-4 never receive raw sockets or credentials —
they issue typed `BrokerRequest`s (TASK-3168) over the worker channel, and
this **host broker**, running in the trusted process, validates each
request against the snippet's manifest allowlist and performs the actual
I/O itself using `aiohttp`. This is the enforcement point for
`BrokerAllowlist` (TASK-3161) — the manifest is the declared contract,
this module is what makes violating it impossible rather than merely
against policy.

---

## Scope

- Implement `HostBroker.handle(request: BrokerRequest, manifest:
  CapabilityManifest) -> BrokerResponse` in
  `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/broker.py`.
- Validate `request.kind`/`request.target` against the matching
  `BrokerAllowlist` field (`http_hosts`, `query_tables`, `notifications`,
  `toolkits`) — raise `CapabilityDenied` (TASK-3161) on any undeclared
  request, and emit a structured security log event (tenant, `handler_ref`
  — passed in, see blueprint — and the denied request) on every denial.
- Enforce a per-invocation broker call cap (a new constructor parameter;
  the spec does not name an exact default — pick a conservative one and
  justify it, since this is a "decision deferred to implementation"-style
  gap the spec's OQ-6 table does not cover).
- Implement the actual `http_hosts` I/O path using `aiohttp` (never
  `requests`/`httpx`, per `.agent/CONTEXT.md`). `query_tables` and
  `notifications`/`toolkits` I/O paths may be stubbed as `# FILL IN` since
  the spec gives no concrete query/notification backend to call —
  document the shape, do not invent a database connection here.
- Write `packages/parrot-formdesigner/tests/unit/test_host_broker.py`.

**NOT in scope**: anything about how a `BrokerRequest` reaches this class
(that is the worker-side responsibility, wired inside TASK-3170's gVisor
worker's message loop — a `# FILL IN` gap noted there); `parrot_tools`
toolkit invocation internals for the `toolkits` allowlist category
(stub the call site, do not reimplement toolkit dispatch here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/broker.py` | CREATE | `HostBroker` |
| `packages/parrot-formdesigner/tests/unit/test_host_broker.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiohttp  # existing dependency — verified: spec §7 External Dependencies table
from parrot_formdesigner.core.snippets import BrokerAllowlist, CapabilityDenied, CapabilityManifest  # TASK-3161
from parrot_formdesigner.services.sandbox.protocol import BrokerRequest, BrokerResponse  # TASK-3168
```

### Existing Signatures to Use
```python
# spec §2 New Public Interfaces — the method this task implements:
class HostBroker:
    async def handle(
        self, request: BrokerRequest, manifest: CapabilityManifest,
    ) -> BrokerResponse:
        """Raises CapabilityDenied when the request is outside the allowlist."""

# TASK-3161 — packages/parrot-formdesigner/src/parrot_formdesigner/core/snippets.py
class BrokerAllowlist(BaseModel):
    http_hosts: tuple[str, ...] = ()      # exact hostnames; no wildcards in v1
    query_tables: tuple[str, ...] = ()
    notifications: tuple[str, ...] = ()
    toolkits: tuple[str, ...] = ()

class CapabilityDenied(Exception): ...
```

### Does NOT Exist
- ~~`services/sandbox/broker.py`~~ — created by this task.
- ~~Wildcard host matching~~ — `http_hosts` is "exact hostnames; no
  wildcards in v1" (spec §2 `BrokerAllowlist` docstring, verbatim). Do
  not implement prefix/suffix/glob matching — an exact string comparison
  only.
- ~~A concrete query-table execution backend~~ — the spec names
  `query_tables` as an allowlist category but does not specify which
  database/ORM executes an allowlisted query; do not invent a SQLAlchemy
  or asyncpg call here without a defined query shape — stub it.
- ~~A structured security-logging utility already in this repo~~ — none
  found under `parrot_formdesigner/`; use the module logger at `WARNING`
  or above with a consistent structured message (see blueprint), do not
  search for or invent a call to a nonexistent `security_log()` helper.

---

## Implementation Notes

### Key Constraints
- **Deny by default.** Any `request.kind` not matching a known allowlist
  field name, or a `target` not present in that field's tuple, is denied
  — there is no "allow unless explicitly denied" branch anywhere in this
  module.
- The security log event on denial MUST include: tenant, `handler_ref`,
  and the denied request's `kind`/`target` (spec §5 Operational AC: "A
  denied capability request emits a structured security log event
  including tenant, handler_ref, and the denied request"). Since
  `BrokerRequest` (TASK-3168) has no `tenant`/`handler_ref` fields of its
  own, `handle()` must accept them as extra parameters — see blueprint
  signature, which extends the spec's abstract `HostBroker.handle()`
  skeleton with these two required keyword-only args (necessary to meet
  this specific acceptance criterion; the spec's own §2 skeleton is
  incomplete on this point).
- `http_hosts` I/O uses `aiohttp.ClientSession` — never `requests`/`httpx`.
- The per-invocation call cap counts calls to `handle()` for a single
  snippet execution — the caller (TASK-3172's `TierRouter`, or the
  worker's own broker-request loop) is responsible for constructing a
  fresh `HostBroker` (or resetting its counter) per snippet invocation;
  document this clearly since it is easy to get wrong (a shared broker
  instance across invocations would need explicit per-invocation
  counters, not a single lifetime counter).

### References in Codebase
- None directly — this is new security-boundary code. Cross-check
  `BrokerAllowlist`'s field names (TASK-3161) carefully; a typo here is a
  security hole, not just a bug.

---

## Implementation Blueprint

### Steps (in order)
1. Implement the allowlist-check helper — *why*: it is reused by all four
   `kind` branches and is the actual security boundary; get it right and
   tested before wiring any I/O.
2. Implement the structured denial log.
3. Implement the `http_hosts` branch with real `aiohttp` I/O.
4. Stub the remaining three branches with a documented `# FILL IN`.
5. Implement the call-cap check.
6. Write and run tests, prioritizing the two denial tests and the call-cap test.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/broker.py` (CREATE)
```python
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
            tenant, handler_ref, request.kind, request.target, reason,
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
                request, tenant=tenant, handler_ref=handler_ref,
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
        raise CapabilityDenied(f"unhandled broker request kind: {request.kind!r}")  # unreachable given _check_allowlist

    async def _handle_http(self, request: BrokerRequest) -> BrokerResponse:
        """Perform an allowlisted outbound HTTP call via aiohttp."""
        method = request.args.get("method", "GET")
        path = request.args.get("path", "/")
        url = f"https://{request.target}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, **{
                k: v for k, v in request.args.items() if k not in ("method", "path")
            }) as resp:
                body = await resp.text()
                return BrokerResponse(result={"status": resp.status, "body": body})
```
**Why this shape**: `_check_allowlist` is a single, small, exhaustively
tested function precisely because it IS the security boundary — every
other piece of this module (call cap, logging, I/O dispatch) surrounds it
but does not duplicate its logic. The `handle()` signature's addition of
`tenant`/`handler_ref` over the spec's bare `(request, manifest)` skeleton
is called out explicitly as a deliberate, documented deviation (not a
hallucination) required to satisfy a different, unambiguous acceptance
criterion in the same spec.

### `packages/parrot-formdesigner/tests/unit/test_host_broker.py` (CREATE)
```python
"""Unit tests for HostBroker — FEAT-459 / TASK-3171."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.snippets import BrokerAllowlist, CapabilityDenied, CapabilityManifest, CapabilityTier
from parrot_formdesigner.services.sandbox.broker import HostBroker
from parrot_formdesigner.services.sandbox.protocol import BrokerRequest


def _manifest(**allowlist_kwargs) -> CapabilityManifest:
    return CapabilityManifest(
        tier=CapabilityTier.BROKERED, allowlist=BrokerAllowlist(**allowlist_kwargs)
    )


async def test_broker_denies_undeclared_host() -> None:
    broker = HostBroker()
    manifest = _manifest(http_hosts=("allowed.example.com",))
    request = BrokerRequest(kind="http_hosts", target="evil.example.com")
    with pytest.raises(CapabilityDenied):
        await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")


async def test_broker_denies_undeclared_table() -> None:
    broker = HostBroker()
    manifest = _manifest(query_tables=("orders",))
    request = BrokerRequest(kind="query_tables", target="users")
    with pytest.raises(CapabilityDenied):
        await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")


async def test_broker_denies_wildcard_style_host_match() -> None:
    """Exact match only — a declared 'example.com' does not cover 'sub.example.com'."""
    broker = HostBroker()
    manifest = _manifest(http_hosts=("example.com",))
    request = BrokerRequest(kind="http_hosts", target="sub.example.com")
    with pytest.raises(CapabilityDenied):
        await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")


async def test_broker_enforces_call_cap() -> None:
    broker = HostBroker(max_calls_per_invocation=1)
    manifest = _manifest(http_hosts=("allowed.example.com",))
    request = BrokerRequest(kind="http_hosts", target="allowed.example.com", args={"method": "GET", "path": "/"})
    # FILL IN: monkeypatch/mock aiohttp.ClientSession so the first call
    #   succeeds without real network I/O, then assert the SECOND call
    #   raises CapabilityDenied due to the call cap, not a network error.
    pass


async def test_broker_logs_denial_with_tenant_and_handler_ref(caplog: pytest.LogCaptureFixture) -> None:
    broker = HostBroker()
    manifest = _manifest(http_hosts=())
    request = BrokerRequest(kind="http_hosts", target="evil.example.com")
    with pytest.raises(CapabilityDenied):
        await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")
    assert "acme" in caplog.text
    assert "x.onBeforeSubmit" in caplog.text


async def test_broker_allows_declared_host(monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: mock aiohttp.ClientSession.request to avoid real network
    #   I/O, assert handle() returns a BrokerResponse with denied=False
    #   for a target that IS in the allowlist.
    pass
```
**Why**: the three denial tests (undeclared host, undeclared table,
wildcard-rejection) and the structured-logging test are the security-
critical assertions and are written in full; the two tests requiring
mocked `aiohttp` network I/O are stubbed since the exact mocking approach
(monkeypatch vs. `aioresponses` vs. a fake session) is an implementation
choice left to the implementer.

### FILL IN checklist
- [ ] `broker.py::handle` — `query_tables`/`notifications`/`toolkits` branches (explicitly stubbed `NotImplementedError` — real backends are undefined by the spec; leave as-is unless a concrete backend is chosen, and note the decision)
- [ ] `test_broker_enforces_call_cap` — mock `aiohttp` for the allowed first call
- [ ] `test_broker_allows_declared_host` — mock `aiohttp` for the success path

---

## Acceptance Criteria

- [ ] An `http_hosts` request whose target is not in `manifest.allowlist.http_hosts` raises `CapabilityDenied` and logs tenant + handler_ref + the denied request
- [ ] A `query_tables` request outside `manifest.allowlist.query_tables` raises `CapabilityDenied` (denial check happens before any backend dispatch, even though the dispatch itself is a FILL IN stub)
- [ ] `http_hosts` matching is exact-string only — a declared `example.com` does not match `sub.example.com`
- [ ] `handle()` raises `CapabilityDenied` once `max_calls_per_invocation` is exceeded, independent of allowlist status
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_host_broker.py -v`
- [ ] `ruff check` and `mypy` clean on `services/sandbox/broker.py`
- [ ] No `requests` or `httpx` import anywhere in this file

---

## Test Specification

See the blueprint's test file above — 6 test functions, 2 stubbed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 New Public Interfaces `HostBroker`, §3 Module 11, §5 Operational ACs — denial logging requirement)
2. **Check dependencies** — TASK-3161 and TASK-3168 must be `done`
3. **Verify the Codebase Contract** — confirm `BrokerAllowlist`'s four field names in `core/snippets.py` are unchanged
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:` (the three unimplemented broker-request kinds may remain `NotImplementedError` if genuinely out of scope — record that explicitly rather than inventing a backend)
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3171-host-broker.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
