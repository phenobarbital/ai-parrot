---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Form Builder — Sandboxed Custom Code on Lifecycle Events

**Feature ID**: FEAT-459
**Date**: 2026-08-24
**Author**: Jesus Lara
**Status**: draft
**Target version**: `parrot-formdesigner` 0.11.0

**Source brainstorm**: `sdd/proposals/formbuilder-custom-code.brainstorm.md`
(Recommended Option D — Git-Backed Snippet Bundles + Capability-Scoped Warm Sandbox Pool)

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot-formdesigner` already has a lifecycle event system (FEAT-188 / FEAT-329):
a `FormSchema` declares `events: FormEventsConfig`, each binding names a
`handler_ref`, and `services/event_dispatcher.dispatch()` resolves that ref against
a module-level registry populated at import time by the `@register_form_event`
decorator. That design has a hard ceiling:

> **Every handler must be Python written by a platform engineer, shipped in the
> `parrot-formdesigner` distribution, and imported into the server process before
> any form can reference it.**

Consequences:

1. **Forms cannot carry their own behavior.** A tenant who needs "if `total > 5000`,
   require the `approver_email` field" must file a ticket and wait for a release.
   The form is data; its logic is code in someone else's repo.
2. **The LLM can author schemas but not behavior.** Form-creation toolkits generate
   fields, validation, and layout — the moment a requirement is *conditional or
   computed*, generation stops and a human writes Python.
3. **No safe path for untrusted code.** There is deliberately no mechanism today to
   execute code that arrives with a form: no sandbox, no capability model, no approval
   gate in the formdesigner package. Adding `exec()` to the aiohttp worker would be a
   straightforward RCE against every tenant.
4. **The client is inert.** `renderers/html5.py` ships a lifecycle bridge, but it can
   only `fetch()` back to the server. Every conditional show/hide or computed total
   costs a network round trip, so authors avoid them.

**Who is affected**: form authors and tenant admins (blocked on engineering for routine
logic), platform engineers (absorbing per-tenant handler requests as release work), and
end users (latency and clumsy forms).

**Why now**: the formbuilder track (`formbuilder-database`, `-fieldtype-cardinality`,
`-formschema-persistency`, `-list-created-forms`) has made schema generation capable
enough that *behavior* is the remaining gap between a generated form and a usable one.

### Goals

Each goal below is a locked constraint from brainstorm discovery Rounds 0–3
(referenced as **C1**–**C10**) and maps to acceptance criteria in §5.

- **G1 (C1)** — Execute custom logic on both the server (Python) and the client
  (TS/JS). Neither runtime alone satisfies the feature.
- **G2 (C2)** — Bind custom code only to the existing FEAT-188 event surface:
  `onBeforeOpen`, `onSchemaLoaded`, `onBeforeSubmit`, `onAfterSubmit`, `onError`.
- **G3 (C3)** — Grant capabilities per snippet via a declared manifest across four
  tiers (`pure` → `helpers` → `brokered` → `toolkit`), deny-by-default per tenant.
- **G4 (C4)** — Require human approval before any snippet executes. The LLM drafts;
  a person approves.
- **G5 (C5)** — Isolate server-side Python in warm-pooled workers behind a provider
  interface. Never in-process `exec`; never a cold container per submit.
- **G6 (C6)** — Run client code in a Web Worker with no DOM access.
- **G7 (C7)** — Treat client code as authoritative only for client-only presentation
  concerns; re-run everything with a server counterpart server-side.
- **G8 (C8)** — Store snippets as git-backed artifacts, approved through PR review.
- **G9 (C9)** — Apply a per-binding failure policy: abort (reject the submission) or
  continue (log and proceed).
- **G10** — Introduce zero breaking changes. Every existing `@register_form_event`
  handler and every existing `FormSchema.events` binding keeps working unchanged.

### Non-Goals (explicitly out of scope)

- **Partial-save events.** `onBeforePartialSave` / `onAfterPartialSave` are NOT added
  (C2). `PartialSaveStore` (`services/partial_saves.py:24`) dispatches no lifecycle
  events today and continues not to. Adding them later is additive and non-breaking.
  See §8 OQ-2.
- **Field-level events.** `onFieldChange` / `onBlur` / `onCalculate` are NOT added
  (C2). Client-side reactivity is achieved through the Web Worker patch protocol
  against existing events, not through new server event names.
- **Runtime DB-backed snippet authoring.** Rejected in brainstorm as Option C in favour
  of git-backed storage (C8) — see `proposals/formbuilder-custom-code.brainstorm.md`
  Option C. The multi-tenancy cost of that choice is tracked as §8 OQ-1.
- **In-process restricted interpreters.** Rejected in brainstorm as Option A
  (`RestrictedPython` / `asteval`) — a sandbox escape would be full RCE in the form
  server process, and CPU/memory limits are unenforceable in a coroutine.
- **Cold-container-per-invocation execution.** Rejected in brainstorm as Option B —
  ~100–500 ms on every submit's critical path.
- **Autonomous execution of freshly generated code.** Excluded by C4.
- **Deep-merge of `schema_overrides`.** `apply_schema_overrides()` remains shallow
  (top-level keys only), per the FEAT-188 MVP decision.

---

## 2. Architectural Design

### Overview

A **snippet bundle** is a directory in the repository containing a Python source file,
an optional TypeScript source file, and a **capability manifest** declaring exactly
what the code may touch. Three consequences follow from treating the snippet as a
declaring artifact rather than a string of code:

1. **The manifest is the primary security boundary; the sandbox enforces it.** A
   snippet declaring tier `pure` is statically verifiable as I/O-free and therefore
   runs in the cheapest executor. Only a snippet that asks for network or toolkit
   access pays for a kernel boundary. **Cost scales with declared power, so the
   common case stays fast.**
2. **The git commit is the approval gate (G4/C4).** Merged to `dev` = approved.
   Signed commits, CI, blame, and rollback come free.
3. **The Python and TS halves are siblings in one bundle**, generated from one intent,
   so drift between them is a reviewable diff rather than a mystery bug.

**Critically, `event_dispatcher.dispatch()` is NOT modified.** The loader registers
each snippet's async adapter under its `handler_ref` through the existing
`register_form_event()` (`services/event_registry.py:73`). From the dispatcher's
perspective, git-backed snippets are ordinary registered handlers. This is what makes
G10 (zero breaking changes) achievable.

**Execution ladder** — the executor is chosen per snippet by its declared tier:

| Tier | Capability | Executor | Target budget |
|---|---|---|---|
| 1 `pure` | payload + schema, no I/O | Warm subprocess worker, no network namespace | ~5 ms |
| 2 `helpers` | + `datetime`/`math`/`re`/`decimal`, form metadata, declared auth claims | Warm subprocess worker | ~10 ms |
| 3 `brokered` | + allowlisted HTTP, allowlisted queries, notifications — all host-mediated | Warm gVisor worker | ~200 ms |
| 4 `toolkit` | + registered `parrot` tools/agents | Warm gVisor worker, per-tenant opt-in | ~2 s |

Tiers 3 and 4 never receive raw sockets or credentials. They issue typed requests over
the worker channel to a **host broker** running in the trusted process, which validates
each request against the manifest allowlist and performs the I/O itself.

**gVisor is a hard prerequisite for tiers 3–4** (resolved OQ-4). If `runsc` is absent,
tiers 3–4 refuse to load at boot with a clear error. Tiers 1–2 are unaffected and
require no container runtime. There is no silent degradation to a weaker boundary.

**User-facing flow:**

- **Author** describes a rule in natural language. The assistant generates a bundle:
  a Python half for `onBeforeSubmit`, a TS half for live feedback, and a manifest
  declaring `tier: pure`. The author sees the code, the declared capabilities, and a
  plain-language summary of what it may touch.
- **Approver** receives a PR. The diff shows both halves and the manifest. CI has
  already verified tier conformance, `handler_ref` agreement between halves, and tests.
  Approval is a merge.
- **End user** fills the form. The Worker-computed rule fires instantly with no round
  trip. On submit, the server re-runs the Python half authoritatively — a tampered or
  bypassed client changes nothing.

### Component Diagram

```
                        ┌──────────────── BUILD / CI (offline) ─────────────────┐
                        │  LLM authoring → snippet bundle → PR → conformance     │
                        │  gate → TS bundler → merge = approval (G4)             │
                        └───────────────────────┬───────────────────────────────┘
                                                │ git-backed artifacts (G8)
                                                ▼
  ┌─────────── SERVER BOOT ────────────┐
  │  SnippetLoader                     │
  │   walk dir → parse manifest        │
  │   → verify source hash             │
  │   → build async adapter            │
  │   → register_form_event(ref) ──────┼──► _EVENT_REGISTRY  (event_registry.py:65)
  └────────────────────────────────────┘         ▲
                                                 │ UNMODIFIED lookup
  ┌─────────── REQUEST PATH ───────────┐         │
  │  FormAPIHandler                    │         │
  │    └─► dispatch()  ────────────────┼─────────┘   (event_dispatcher.py:102)
  │          └─► SnippetAdapter                  │
  │                └─► ContextProjector  (strips live AuthContext → declared claims)
  │                      └─► TierRouter
  │                            ├─ tier 1-2 ─► SubprocessWorkerPool  ─┐
  │                            └─ tier 3-4 ─► GVisorWorkerPool ──────┤ implements
  │                                                 │                │ SandboxProvider
  │                                                 ▼                │ (base.py:166)
  │                                            HostBroker  ◄─────────┘
  │                                        (allowlist-checked I/O in
  │                                         the TRUSTED process only)
  │                                                 │
  │          ◄──── EventResolution | FormEventAbort ┘
  └────────────────────────────────────┘

  ┌─────────── CLIENT PATH ────────────┐
  │  html5.py _LIFECYCLE_SCRIPT_TEMPLATE (:423)                     │
  │    └─► Worker boot ─► Web Worker (no DOM, G6)                   │
  │            ◄── postMessage: field values                        │
  │            ──► postMessage: patches ─► host applies (allowlist)  │
  └─────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `services/event_dispatcher.dispatch()` | **depends on (unmodified)** | Snippets arrive as ordinary registered handlers. No change to this function — the key design constraint enabling G10. |
| `services/event_registry.register_form_event()` | uses | Loader registers snippet adapters through this door. Its duplicate-ref `ValueError` is reused as the two-snippets-one-ref guard. |
| `core/events.FormEventBinding` | **extends** | Adds `on_failure` field (resolved OQ-3). Additive with a default; existing bindings unaffected. |
| `core/events.FormEventContext` | depends on | Projected to a serialisable form before crossing the sandbox boundary. Never passed live. |
| `core/events.EventResolution` | uses | Worker return value is validated against this existing model, unchanged. |
| `core/events.FormEventAbort` | uses | Worker abort signal is rehydrated into this exception, preserving FEAT-188 semantics (`onError` NOT fired on abort). |
| `core/schema.FormSchema.events` | depends on | Unchanged. Only `handler_ref` resolution widens to include git-backed snippets. |
| `renderers/html5.py` | modifies | `_LIFECYCLE_SCRIPT_TEMPLATE` (:423) gains a Worker boot block. The existing remote-fetch bridge is preserved intact. |
| `parrot.eval.sandbox.SandboxProvider` | implements | Both worker pools implement the existing ABC, so the eval harness and the form runtime share one abstraction. |
| `parrot_tools.sandboxtool.SandboxConfig` | uses | Reused for tier 3–4 worker configuration (`network="none"`, `max_memory`, `max_cpu`, `timeout`). |
| Deployment / ops | **new dependency** | gVisor `runsc` required for tiers 3–4 (hard prerequisite). Warm pools are new stateful components to size and monitor. |
| CI | extends | New tier-conformance gate; TS bundle build step. |
| `packages/parrot-formdesigner/pyproject.toml` | modifies | New optional extra for sandbox dependencies. |

### Data Models

```python
# NEW — parrot_formdesigner/core/snippets.py

class CapabilityTier(StrEnum):
    """Declared power level of a snippet; selects its executor."""
    PURE = "pure"          # payload + schema only, no I/O
    HELPERS = "helpers"    # + curated stdlib subset, metadata, declared claims
    BROKERED = "brokered"  # + host-mediated allowlisted outbound calls
    TOOLKIT = "toolkit"    # + registered parrot tools/agents


class BrokerAllowlist(BaseModel):
    """Explicit outbound permissions for tier BROKERED / TOOLKIT."""
    model_config = ConfigDict(extra="forbid")
    http_hosts: tuple[str, ...] = ()      # exact hostnames; no wildcards in v1
    query_tables: tuple[str, ...] = ()    # fully-qualified table names
    notifications: tuple[str, ...] = ()   # channel identifiers
    toolkits: tuple[str, ...] = ()        # registered parrot toolkit names


class CapabilityManifest(BaseModel):
    """What a snippet declares it needs. The security contract, and the
    unit CI checks the source against."""
    model_config = ConfigDict(extra="forbid")
    tier: CapabilityTier
    auth_claims: tuple[str, ...] = ()     # AuthContext keys projected in (OQ-5)
    stdlib_modules: tuple[str, ...] = ()  # subset of a fixed curated allowlist
    allowlist: BrokerAllowlist = BrokerAllowlist()
    timeout_ms: int = Field(default=5_000, ge=1, le=30_000)
    max_memory_mb: int = Field(default=128, ge=16, le=2_048)


class SnippetBundle(BaseModel):
    """One git-backed snippet: manifest + Python half + optional TS half."""
    model_config = ConfigDict(extra="forbid")
    handler_ref: str = Field(
        ...,
        # Same pattern as FormEventBinding.handler_ref (core/events.py:69)
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$",
    )
    event: FormEventName                  # reused verbatim from core/events.py:32
    tenant: str | None = None             # None = global, matching registry semantics
    manifest: CapabilityManifest
    python_source: str
    python_sha256: str
    client_source: str | None = None      # compiled JS for the Web Worker
    client_sha256: str | None = None


class SandboxContext(BaseModel):
    """Serialisable projection of FormEventContext that crosses the boundary.

    Deliberately NOT FormEventContext: `auth_context` is a live object typed
    `Any` (core/events.py:112) and must never be handed to a worker.
    """
    model_config = ConfigDict(extra="forbid")
    event: FormEventName
    form_id: str
    tenant: str | None
    claims: Mapping[str, Any]             # only manifest-declared auth_claims
    payload: Mapping[str, Any] | None = None
    schema_dump: Mapping[str, Any] | None = None
    user_message: str | None = None
    extra: Mapping[str, Any] = {}


class SandboxOutcome(BaseModel):
    """What a worker returns. Exactly one of `resolution` / `abort` is set."""
    model_config = ConfigDict(extra="forbid")
    resolution: EventResolution | None = None   # reused from core/events.py:170
    abort: AbortSignal | None = None
    duration_ms: float
    broker_calls: int = 0


class AbortSignal(BaseModel):
    """Serialisable form of FormEventAbort (core/events.py:201)."""
    model_config = ConfigDict(extra="forbid")
    reason: str
    user_message: str
    status_code: int = 403


# MODIFIED — parrot_formdesigner/core/events.py (additive, resolved OQ-3)
class FormEventBinding(BaseModel):
    handler_ref: str      # existing, line 69
    remote: bool = False  # existing, line 74
    required: bool = False  # existing, line 75 — STILL means "handler MISSING → 500"
    on_failure: Literal["abort", "continue"] = "continue"  # NEW — handler FAILED
```

**Design note on `on_failure` (resolved OQ-3):** `required` and `on_failure` describe
two distinct conditions and are deliberately kept separate. `required=True` continues
to mean *the handler is not registered* → `RuntimeError` at dispatch, exactly as
FEAT-188 defines it. `on_failure` governs *the handler ran and failed* (raised, timed
out, exceeded budget, or returned an invalid resolution). Widening `required` to cover
both was rejected because it would silently change runtime behavior for every existing
binding that already sets `required=True`, violating G10.

### New Public Interfaces

```python
# parrot_formdesigner/services/snippet_loader.py
class SnippetLoader:
    """Discovers git-backed snippet bundles and registers them."""
    def __init__(self, root: Path, *, strict: bool = True) -> None: ...
    async def discover(self) -> list[SnippetBundle]: ...
    async def register_all(self) -> int:
        """Register every discovered bundle via register_form_event().

        Returns:
            Count of registered snippets.

        Raises:
            SnippetIntegrityError: source hash mismatch against the manifest.
            SnippetTierUnavailableError: bundle declares tier 3/4 but the
                gVisor runtime is unavailable (hard prerequisite, OQ-4).
            ValueError: propagated from register_form_event() on duplicate ref.
        """


# parrot_formdesigner/services/sandbox/router.py
class TierRouter:
    """Selects the cheapest executor satisfying a snippet's declared tier."""
    def __init__(
        self,
        subprocess_pool: SandboxProvider,
        gvisor_pool: SandboxProvider | None,
    ) -> None: ...
    async def execute(
        self, bundle: SnippetBundle, ctx: SandboxContext,
    ) -> SandboxOutcome: ...


# parrot_formdesigner/services/sandbox/pool.py
class SubprocessWorkerPool(SandboxProvider):   # parrot.eval.sandbox.base:166
    async def acquire(self, spec: SandboxSpec) -> Sandbox: ...
    async def release(self, sandbox: Sandbox) -> None: ...

class GVisorWorkerPool(SandboxProvider):
    @classmethod
    def is_available(cls) -> bool:
        """True when the `runsc` runtime is present and usable."""


# parrot_formdesigner/services/sandbox/broker.py
class HostBroker:
    """Performs manifest-allowlisted I/O in the TRUSTED process."""
    async def handle(
        self, request: BrokerRequest, manifest: CapabilityManifest,
    ) -> BrokerResponse:
        """Raises CapabilityDenied when the request is outside the allowlist."""
```

---

## 3. Module Breakdown

Modules map to the brainstorm's four parallel tracks. **Track 1 (M1–M3) is a hard
sequential prerequisite** — everything else builds on its contracts.

### Track 1 — Contracts & Loader

#### Module 1: Snippet & Manifest Models
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/snippets.py`
- **Responsibility**: `CapabilityTier`, `BrokerAllowlist`, `CapabilityManifest`,
  `SnippetBundle`, `SandboxContext`, `SandboxOutcome`, `AbortSignal`, and the typed
  exceptions (`SnippetIntegrityError`, `SnippetTierUnavailableError`,
  `CapabilityDenied`).
- **Depends on**: `core/events.py` (`FormEventName`, `EventResolution`).

#### Module 2: `on_failure` Binding Extension
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py`
- **Responsibility**: Add `on_failure: Literal["abort","continue"] = "continue"` to
  `FormEventBinding` (line 54). Update the class docstring to distinguish it from
  `required`. Re-export unchanged from `core/__init__.py`.
- **Depends on**: nothing. **Must not alter** existing field semantics (G10).

#### Module 3: Snippet Loader & Registry Adapter
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippet_loader.py`
- **Responsibility**: Walk the git-backed snippet root, parse manifests, verify SHA-256
  source hashes, build the async adapter closure per bundle, register each through
  `register_form_event()`. Refuse to register tier 3/4 bundles when gVisor is absent.
- **Depends on**: Module 1, `services/event_registry.py:73`.

### Track 2 — Server Sandbox

#### Module 4: Context Projector
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/projector.py`
- **Responsibility**: Convert a live `FormEventContext` into a `SandboxContext`,
  projecting `auth_context` down to manifest-declared `auth_claims` only. Reject
  non-serialisable values loudly rather than silently dropping them.
- **Depends on**: Module 1, `core/events.py:106`.

#### Module 5: Worker Protocol
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/protocol.py`
- **Responsibility**: Framed request/response encoding between host and worker —
  `SandboxContext` in; `SandboxOutcome`, `AbortSignal`, or `BrokerRequest` out.
  Length-prefixed JSON with a strict size cap.
- **Depends on**: Module 1.

#### Module 6: Subprocess Worker Pool (tiers 1–2)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/pool.py`
- **Responsibility**: `SubprocessWorkerPool` implementing `SandboxProvider`. Warm
  `asyncio.subprocess` workers with no network namespace, wall/CPU/memory budgets,
  recycling after N invocations, health checks, bounded acquire queue, cold-start path.
- **Depends on**: Modules 1, 5; `parrot.eval.sandbox.base:166`.

#### Module 7: gVisor Worker Pool (tiers 3–4)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/gvisor_pool.py`
- **Responsibility**: `GVisorWorkerPool` implementing `SandboxProvider`, backed by
  `SandboxConfig` (`sandboxtool.py:24`). `is_available()` probes `runsc`; absence is a
  hard boot failure for tiers 3–4, never a silent downgrade.
- **Depends on**: Modules 1, 5; `parrot_tools.sandboxtool`.

#### Module 8: Host Broker
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/broker.py`
- **Responsibility**: Validate every `BrokerRequest` against the manifest allowlist and
  perform the I/O in the trusted process using `aiohttp`. Emit a security log event and
  raise `CapabilityDenied` on any undeclared request. Enforce a per-invocation call cap.
- **Depends on**: Modules 1, 5.

#### Module 9: Tier Router & Snippet Adapter
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/router.py`
- **Responsibility**: Route a bundle to the cheapest satisfying executor; own the
  end-to-end adapter that `dispatch()` sees as a plain handler — project context,
  execute, validate the returned `EventResolution`, rehydrate `AbortSignal` into
  `FormEventAbort`, and apply the `on_failure` policy.
- **Depends on**: Modules 1, 2, 4, 5, 6, 7, 8.

### Track 3 — Client Runtime

#### Module 10: Web Worker Runtime & Patch Protocol
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/worker_bridge.py`
- **Responsibility**: Generate the Worker boot block injected into
  `_LIFECYCLE_SCRIPT_TEMPLATE` (`renderers/html5.py:423`); define the `postMessage`
  patch protocol and the host-side allowlist of patch operations (OQ-7). Preserve the
  existing remote-fetch bridge untouched.
- **Depends on**: Module 1.

#### Module 11: TS Bundler Integration
- **Path**: `packages/parrot-formdesigner/scripts/build_snippet_bundles.py`
- **Responsibility**: Build-time TS → JS compilation of client halves into worker-ready
  bundles with content hashes. **Never invoked at request time.**
- **Depends on**: Module 1.

### Track 4 — Authoring & CI

#### Module 12: CI Tier-Conformance Gate
- **Path**: `packages/parrot-formdesigner/scripts/check_snippet_conformance.py`
- **Responsibility**: Static `ast` analysis asserting each snippet stays inside its
  declared tier — no imports beyond `stdlib_modules`, no I/O at tiers 1–2, no broker
  calls outside the allowlist, Python/TS halves agree on `handler_ref` and `event`,
  hashes match sources.
- **Depends on**: Module 1.

#### Module 13: LLM Authoring Surface
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/snippet_authoring.py`
- **Responsibility**: Toolkit + prompts for generating conformant bundles from a natural
  language rule: emit Python half, TS half, and manifest; run the conformance gate
  locally before proposing; surface a plain-language capability summary for the approver.
- **Depends on**: Modules 1, 12.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_manifest_rejects_unknown_tier` | M1 | `CapabilityManifest` rejects a tier outside `CapabilityTier` |
| `test_manifest_forbids_extra_fields` | M1 | `extra="forbid"` holds across all new models |
| `test_bundle_handler_ref_pattern` | M1 | `handler_ref` enforces the dotted pattern from `core/events.py:69` |
| `test_on_failure_defaults_to_continue` | M2 | New field defaults to `"continue"` |
| `test_required_semantics_unchanged` | M2 | `required=True` still means *missing* handler → `RuntimeError`, NOT failed handler (G10) |
| `test_existing_bindings_deserialize` | M2 | Bindings serialised before this feature still parse |
| `test_loader_rejects_hash_mismatch` | M3 | Edited source without manifest update → `SnippetIntegrityError` at load |
| `test_loader_rejects_tier3_without_gvisor` | M3 | `SnippetTierUnavailableError` when `runsc` absent (OQ-4) |
| `test_loader_duplicate_ref_raises` | M3 | Two bundles, one `handler_ref` → `ValueError` from the registry |
| `test_projector_strips_live_auth_context` | M4 | `SandboxContext.claims` contains only declared `auth_claims`; live object never crosses |
| `test_projector_rejects_unserialisable` | M4 | Non-JSON-serialisable payload fails loudly |
| `test_protocol_enforces_size_cap` | M5 | Oversized frame rejected, not truncated |
| `test_pool_recycles_after_n` | M6 | Worker retired after the configured invocation count |
| `test_pool_kills_on_timeout` | M6 | Wall-clock budget exceeded → worker killed, failure surfaced |
| `test_pool_bounded_queue_times_out` | M6 | Exhausted pool times out rather than waiting unboundedly |
| `test_pool_replaces_unhealthy_worker` | M6 | Failed `health_check()` → destroy and replace |
| `test_gvisor_pool_is_available_probe` | M7 | `is_available()` correctly reports a missing `runsc` |
| `test_broker_denies_undeclared_host` | M8 | HTTP to a non-allowlisted host → `CapabilityDenied` + security log |
| `test_broker_denies_undeclared_table` | M8 | Query outside `query_tables` denied |
| `test_broker_enforces_call_cap` | M8 | Per-invocation broker call limit enforced |
| `test_router_selects_cheapest_tier` | M9 | Tier 1 routes to subprocess pool, tier 3 to gVisor pool |
| `test_router_abort_rehydrates_exception` | M9 | `AbortSignal` → `FormEventAbort` with reason/message/status intact |
| `test_router_invalid_resolution_is_failure` | M9 | Malformed return → `on_failure` policy, never partially applied |
| `test_router_on_failure_abort` | M9 | `on_failure="abort"` raises through `dispatch()` |
| `test_router_on_failure_continue` | M9 | `on_failure="continue"` logs and returns an empty `EventResolution()` |
| `test_worker_patch_allowlist` | M10 | Patch operations outside the host allowlist are discarded |
| `test_conformance_rejects_undeclared_import` | M12 | Tier-1 snippet importing `socket` fails the gate |
| `test_conformance_rejects_half_mismatch` | M12 | Python/TS halves disagreeing on `handler_ref` fails |

### Integration Tests

| Test | Description |
|---|---|
| `test_snippet_runs_via_dispatch_unmodified` | Registered snippet fires through the **unmodified** `dispatch()` and returns an `EventResolution` |
| `test_snippet_abort_produces_http_error` | Snippet aborting `onBeforeSubmit` yields the correct status + safe user message; `onError` is NOT fired |
| `test_schema_overrides_applied_shallow` | Snippet-returned overrides flow through `apply_schema_overrides()` with shallow-merge semantics preserved |
| `test_payload_replacement_on_before_submit` | Snippet-replaced payload reaches the persistence layer |
| `test_legacy_handler_still_works` | A hand-written `@register_form_event` handler is unaffected by the loader (G10) |
| `test_tier3_brokered_http_end_to_end` | Tier-3 snippet performs an allowlisted call through the broker and receives the result |
| `test_client_worker_patch_round_trip` | Rendered form boots the Worker, posts field values, receives and applies a patch |
| `test_client_bypass_rejected_by_server` | Submitting with the client bypassed still fails server-side validation (G7) |
| `test_timeout_under_load_fails_closed` | Concurrent submits exceeding pool capacity honour `on_failure="abort"` |

### Test Data / Fixtures

```python
@pytest.fixture
def pure_manifest() -> CapabilityManifest:
    """Tier-1 manifest: no I/O, no claims, no allowlist."""
    return CapabilityManifest(tier=CapabilityTier.PURE, timeout_ms=1_000)

@pytest.fixture
def snippet_root(tmp_path: Path) -> Path:
    """Git-backed snippet tree with one valid tier-1 bundle."""

@pytest.fixture
def sandbox_ctx() -> SandboxContext:
    """Minimal onBeforeSubmit projection with a two-field payload."""

@pytest.fixture
def fake_gvisor_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force GVisorWorkerPool.is_available() to return False."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

**Baseline**
- [ ] All unit tests pass (`pytest packages/parrot-formdesigner/tests/ -v`)
- [ ] All integration tests pass (`pytest packages/parrot-formdesigner/tests/integration/ -v`)
- [ ] `ruff check` and `mypy` clean on all changed files
- [ ] Documentation updated in `docs/`, including the snippet-authoring guide and the gVisor ops prerequisite

**Goal-derived (each traces to a locked constraint)**
- [ ] **G1/C1** — A single bundle executes its Python half server-side and its JS half in the browser Worker within one form lifecycle
- [ ] **G2/C2** — Snippets bind only to the five `FormEventName` members; no new event names exist in `core/events.py:32`
- [ ] **G3/C3** — All four tiers are implemented; a snippet receives exactly its declared capabilities and no more; tiers 3–4 are deny-by-default per tenant
- [ ] **G4/C4** — No snippet executes unless it is present in a merged commit; the loader refuses unhashed or unverified sources
- [ ] **G5/C5** — Server-side Python runs only in pooled workers; no `exec`/`eval` of snippet source exists in the aiohttp process
- [ ] **G6/C6** — Client code runs in a Web Worker with no DOM handle; patches are applied by the host through an allowlist
- [ ] **G7/C7** — A tampered or disabled client cannot bypass any rule with a server counterpart
- [ ] **G8/C8** — Snippets load exclusively from the git-backed tree; no runtime DB table stores executable code
- [ ] **G9/C9** — `on_failure="abort"` rejects the submission via `FormEventAbort`; `on_failure="continue"` logs and proceeds with an empty resolution
- [ ] **G10** — `services/event_dispatcher.py` `dispatch()` is byte-for-byte unchanged; all pre-existing handlers and bindings pass their original tests

**Operational**
- [ ] gVisor absence is a loud boot failure for tiers 3–4 and a no-op for tiers 1–2 (OQ-4)
- [ ] Tier-1 dispatch overhead ≤ 15 ms p95 on a warm pool (target 5 ms; measured, not asserted by construction)
- [ ] Pool exhaustion produces a bounded timeout, never an unbounded wait
- [ ] A denied capability request emits a structured security log event including tenant, `handler_ref`, and the denied request
- [ ] CI conformance gate fails the build on any snippet that exceeds its declared tier

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every entry below was re-verified against the working tree on 2026-08-24 at
> commit `644b99c1f`. **Line numbers differ from the brainstorm** — the brainstorm
> listed `FormEventsConfig` at 104 and `FormEventContext` at 124; the verified
> positions are **78** and **106**. Use the numbers in this section, not the
> brainstorm's.

### Verified Imports

All of the following were confirmed to import successfully at runtime
(`python -c` against the activated venv), not merely by reading source:

```python
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py
from parrot_formdesigner.core.events import (
    FormEventName,       # line 32  (Literal alias)
    VisitEventName,      # line 40
    FormEventBinding,    # line 54
    FormEventsConfig,    # line 78
    FormEventContext,    # line 106
    VisitEventContext,   # line 136
    EventResolution,     # line 170
    FormEventAbort,      # line 201
)

# Also re-exported from the package root — verified: core/__init__.py:17-23, __all__:95
from parrot_formdesigner.core import (
    EventResolution, FormEventAbort, FormEventBinding,
    FormEventContext, FormEventName, FormEventsConfig,
)

# verified: packages/parrot-formdesigner/src/parrot_formdesigner/services/event_registry.py
from parrot_formdesigner.services.event_registry import (
    register_form_event,  # line 73
    get_form_event,       # line 149
    list_form_events,     # line 180
)

# verified: packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py
from parrot_formdesigner.services.event_dispatcher import (
    apply_schema_overrides,  # line 69
    dispatch,                # line 102
    dispatch_visit,          # line 205
)

# verified: packages/ai-parrot/src/parrot/eval/sandbox/base.py
from parrot.eval.sandbox.base import (
    SandboxSpec,       # line 42
    ExecResult,        # line 60
    Sandbox,           # line 79
    SandboxProvider,   # line 166
)
# Equivalently via the package __init__ — verified: eval/sandbox/__init__.py:10, __all__:20
from parrot.eval.sandbox import (
    SandboxSpec, ExecResult, Sandbox, SandboxProvider,
    NoopSandbox, NoopSandboxProvider, AgentFactory,
)

# verified by source read: packages/ai-parrot-tools/src/parrot_tools/sandboxtool.py
from parrot_tools.sandboxtool import SandboxConfig, SandboxTool  # lines 24, 55

# verified by source read: packages/ai-parrot-tools/src/parrot_tools/codeinterpreter/executor.py
from parrot_tools.codeinterpreter.executor import create_executor  # line 354
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py
FormEventName = Literal[                                    # line 32
    "onBeforeOpen", "onSchemaLoaded", "onBeforeSubmit",
    "onAfterSubmit", "onError",
]

class FormEventBinding(BaseModel):                          # line 54
    model_config = ConfigDict(extra="forbid")
    handler_ref: str = Field(                               # line 69
        ..., pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$",
    )
    remote: bool = False    # line 74 — HTML5 client bridges via fetch
    required: bool = False  # line 75 — if True and handler MISSING → 500

class FormEventsConfig(BaseModel):                          # line 78
    model_config = ConfigDict(extra="forbid")
    onBeforeOpen: FormEventBinding | None = None
    onSchemaLoaded: FormEventBinding | None = None
    onBeforeSubmit: FormEventBinding | None = None
    onAfterSubmit: FormEventBinding | None = None
    onError: FormEventBinding | None = None

class FormEventContext(BaseModel):                          # line 106
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    event: FormEventName
    form_id: str
    tenant: str | None
    auth_context: Any                              # line 112 — live AuthContext
    payload: Mapping[str, Any] | None = None       # submit only
    schema_dump: Mapping[str, Any] | None = None   # open / schema_loaded only
    error: BaseException | None = None             # onError only
    user_message: str | None = None                # onError mutable
    extra: dict[str, Any] = Field(default_factory=dict)

class EventResolution(BaseModel):                           # line 170
    model_config = ConfigDict(extra="forbid")
    payload: Mapping[str, Any] | None = None
    schema_overrides: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] | None = None
    user_message: str | None = None

class FormEventAbort(Exception):                            # line 201
    def __init__(
        self, reason: str, *, user_message: str, status_code: int = 403,
    ) -> None: ...
    # NOTE: onError is deliberately NOT fired for FormEventAbort (FEAT-188 §7)

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema(BaseModel):                                # line 313
    events: FormEventsConfig | None = None                  # line 368

# packages/parrot-formdesigner/src/parrot_formdesigner/services/event_registry.py
FormEventHandler = Callable[..., Awaitable[EventResolution | None]]   # line 57
_EVENT_REGISTRY: dict[tuple[str | None, str], FormEventHandler] = {}  # line 65

def register_form_event(                                    # line 73
    handler_ref: str, *, tenant: str | None = None,
) -> Callable[[FormEventHandler], FormEventHandler]: ...
    # Raises ValueError on duplicate (tenant, handler_ref) — no silent override.
    # Raises TypeError if the decorated function is not async.

def get_form_event(                                         # line 149
    handler_ref: str, *, tenant: str | None = None,
) -> FormEventHandler: ...
    # Resolution: (tenant, ref) → (None, ref) → KeyError

def list_form_events(tenant: str | None = None) -> list[tuple[str | None, str]]: ...  # line 180

# packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py
_VISIT_PRE_HOOKS: frozenset[str] = frozenset({"visit.onArrival"})   # line 61

def apply_schema_overrides(                                 # line 69
    base: dict[str, Any], overrides: Mapping[str, Any],
) -> dict[str, Any]: ...
    # SHALLOW merge, top-level keys only (FEAT-188 §7 MVP decision)

async def dispatch(                                         # line 102
    event: FormEventName, *, form: FormSchema, request: web.Request,
    tenant: str | None, auth_context: Any,
    payload: Mapping[str, Any] | None = None,
    schema_dump: Mapping[str, Any] | None = None,
    error: BaseException | None = None,
) -> EventResolution: ...

async def dispatch_visit(...) -> EventResolution: ...       # line 205

# packages/ai-parrot/src/parrot/eval/sandbox/base.py
class SandboxSpec(BaseModel):                               # line 42
    kind: Literal["docker", "in_memory_state", "mock_api", "noop"] = "noop"
    image: str | None = None
    setup: list[str] = Field(default_factory=list)
    seed_state: dict[str, Any] | None = None
    git_truncate_after: str | None = None

class ExecResult(BaseModel):                                # line 60
    exit_code: int
    stdout: str = ""
    stderr: str = ""

class Sandbox(ABC):                                         # line 79
    async def __aenter__(self) -> "Sandbox": ...            # line 95
    async def __aexit__(self, *exc: Any) -> None: ...       # line 104
    async def reset(self, seed_state: dict[str, Any] | None) -> None: ...  # line 113
    async def health_check(self) -> bool: ...               # line 122
    async def snapshot(self) -> dict[str, Any]: ...         # line 131
    async def exec(self, cmd: list[str]) -> ExecResult: ... # line 139

class SandboxProvider(ABC):                                 # line 166
    async def acquire(self, spec: SandboxSpec) -> Sandbox: ...  # line 174
    async def release(self, sandbox: Sandbox) -> None: ...      # line 186

class NoopSandbox(Sandbox): ...                             # line 209
class NoopSandboxProvider(SandboxProvider): ...             # line 259

# packages/ai-parrot-tools/src/parrot_tools/sandboxtool.py
@dataclass
class SandboxConfig:                                        # line 24
    runtime: str = "runsc"          # line 26 — gVisor by default
    network: str = "none"           # line 27 — network disabled by default
    max_memory: str = "2G"
    max_cpu: float = 2.0
    timeout: int = 30
    python_image: str = "python:3.11-slim"
    enable_gpu: bool = False
    mount_paths: List[str] = field(default_factory=list)

@dataclass
class ExecutionResult: ...                                  # line 41
class SandboxTool(AbstractTool):                            # line 55
    def _verify_installation(self): ...                     # line 99 — FAILS without runsc

# packages/ai-parrot-tools/src/parrot_tools/codeinterpreter/executor.py
class IsolatedExecutor: ...                                 # line 24
class SubprocessExecutor: ...                               # line 270
def create_executor(                                        # line 354
    use_docker: bool = True, **kwargs,
) -> IsolatedExecutor | SubprocessExecutor: ...
    # Already falls back Docker → subprocess when Docker is unavailable

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py
_LIFECYCLE_SCRIPT_TEMPLATE = (...)                          # line 423 (used at line 574)
# Client bridge: EVENTS_CONFIG, emit(), bridge(); remote endpoint
# '/api/v1/{tenant}/forms/{form_uid}/events/{eventName}'  (line 449; tenant-qualified per FEAT-421)

# packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py
class PartialSaveStore: ...                                 # line 24 — dispatches NO lifecycle events
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SnippetLoader.register_all()` | `register_form_event()` | decorator call | `services/event_registry.py:73` |
| `SnippetAdapter` | `dispatch()` | resolved from `_EVENT_REGISTRY` | `services/event_dispatcher.py:102`, `event_registry.py:65` |
| `SnippetAdapter` | `EventResolution` | return value validation | `core/events.py:170` |
| `SnippetAdapter` | `FormEventAbort` | rehydrated from `AbortSignal` | `core/events.py:201` |
| `ContextProjector` | `FormEventContext` | reads, projects `auth_context` | `core/events.py:106,112` |
| `FormEventBinding.on_failure` | `FormEventBinding` | new field on existing model | `core/events.py:54` |
| `SubprocessWorkerPool` | `SandboxProvider` | implements ABC | `parrot/eval/sandbox/base.py:166` |
| `GVisorWorkerPool` | `SandboxConfig` | constructs config | `parrot_tools/sandboxtool.py:24` |
| Worker boot block | `_LIFECYCLE_SCRIPT_TEMPLATE` | template extension | `renderers/html5.py:423` |
| Snippet resolution | `FormSchema.events` | unchanged read | `core/schema.py:368` |

### Does NOT Exist (Anti-Hallucination)

Re-confirmed absent on 2026-08-24 across `packages/` (excluding `build/lib`):

- ~~`CodeSnippet`~~ — 0 hits. No snippet model exists; M1 creates the first.
- ~~`CapabilityManifest` / `capability_manifest`~~ — 0 hits. Entirely new concept.
- ~~`snippet_registry`~~ — 0 hits. Only `event_registry` and `callback_registry` exist.
- ~~`SandboxedHandler`~~ — 0 hits.
- ~~`code_sandbox`~~ — 0 hits in `parrot-formdesigner`. Sandboxing lives only in
  `parrot_tools` and `parrot.eval`, neither wired to forms.
- ~~`onFieldChange`~~ — 0 hits. **Not** a `FormEventName` member. Excluded by C2.
- ~~`onBeforePartialSave` / `onAfterPartialSave`~~ — 0 hits. Excluded by C2.
- ~~`event_dispatcher.dispatch_snippet`~~ — does not exist. Only `dispatch()` (:102)
  and `dispatch_visit()` (:205).
- ~~`FormEventBinding.on_failure`~~ — **does not exist yet**; M2 adds it. Do not assume
  it is present when reading the current source.
- ~~`RestrictedPython` / `asteval` / `simpleeval` / `wasmtime` / `pyodide`~~ — not
  dependencies of this repo, and this spec does **not** add them (Option A rejected).
- ~~A Web Worker in the HTML5 renderer~~ — does not exist. `_LIFECYCLE_SCRIPT_TEMPLATE`
  only does `fetch`-based remote bridging.
- ~~A TypeScript build step in `parrot-formdesigner`~~ — does not exist; M11 creates it.
- ~~`parrot.eval.sandbox` pooling implementation~~ — only `NoopSandboxProvider`
  (`base.py:259`) exists. There is **no** real pooling provider to inherit from; M6/M7
  are the first concrete implementations.

### Verified Environment Facts

- **`runsc` (gVisor) is NOT installed** on the development machine (`command -v runsc`
  → absent). `SandboxTool._verify_installation()` (`sandboxtool.py:99`) will fail.
  Tiers 3–4 therefore cannot be exercised locally without an ops step — tests for M7
  must be skippable via the `fake_gvisor_absent` fixture.
- **`docker` IS installed** (`command -v docker` → present). `IsolatedExecutor` is
  usable today, but is **not** the chosen tier-3/4 runtime (OQ-4 resolved to a hard
  gVisor prerequisite).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **async-first throughout** — no blocking I/O in async contexts (`.agent/CONTEXT.md`).
  Prefer `asyncio.subprocess` over `multiprocessing` for tier-1/2 workers.
- **Pydantic models for all structured data**, `model_config = ConfigDict(extra="forbid")`
  on every new model, matching the existing `core/events.py` convention.
- **Google-style docstrings + strict type hints** on every function and class.
- **`self.logger` / module logger, never `print`.** The existing `sandboxtool.py` uses
  `print` in `create_executor()` — do NOT copy that pattern.
- **Never use `requests`/`httpx`** — the host broker uses `aiohttp`.
- **`uv` exclusively**, venv activated before any Python command.
- Follow the `SandboxProvider` acquire/release contract exactly so the pools remain
  drop-in for the eval harness.
- Register snippets through `register_form_event()` rather than touching
  `_EVENT_REGISTRY` directly — the duplicate-ref guard is a feature, not an obstacle.

### Known Risks / Gotchas

Derived from the brainstorm's edge-case table; each row is a behavior the
implementation must produce.

| Condition | Required behavior |
|---|---|
| Snippet exceeds CPU/wall/memory budget | Worker killed; treated as failure; `on_failure` policy applies |
| Snippet raises | As above. Traceback logged internally, **never** surfaced to the end user |
| Snippet raises `FormEventAbort` | Controlled flow — re-raised intact; `onError` **NOT** fired (FEAT-188 §7) |
| Return value fails `EventResolution` validation | Treated as failure; **never** partially applied |
| Snippet requests an undeclared capability | Broker denies, emits a security log event, snippet fails. CI should have caught it earlier |
| Warm pool exhausted | Bounded queue wait then timeout → `on_failure`. **Never** an unbounded wait |
| gVisor absent | Tiers 1–2 unaffected; tiers 3–4 refuse to load at boot. **Never** a silent downgrade |
| Worker poisoned / unhealthy | `health_check()` fails → destroy and replace; retry the request at most once |
| Python and TS halves disagree | Server wins; client patch discarded; divergence logged as an authoring bug |
| Client tampered / Worker blocked | Server re-runs authoritatively; presentation-only logic degrades to unstyled but correct |
| Snippet edited without manifest update | SHA mismatch at load → refuse to register. Fail at **boot**, not at request time |
| Two snippets claim one `handler_ref` | Existing `register_form_event()` `ValueError` surfaces as a boot failure |
| Binding `required=True`, snippet missing | Existing FEAT-188 `RuntimeError`, unchanged |

**Additional risks specific to this spec:**

- **`auth_context` is typed `Any` and is a live object** (`core/events.py:112`). Handing
  it to a worker is impossible and unsafe. The projector must be written first and used
  everywhere; there must be no code path that serialises `FormEventContext` directly.
- **`dispatch()` must remain unmodified.** Any task that finds itself editing
  `event_dispatcher.py` has misunderstood the design — re-read §2 Overview.
- **CSRF token store is in-process memory** (warning emitted on package import) and will
  not work under `gunicorn -w N > 1`. Worker pools are similarly per-process; sizing
  must account for N processes × pool size, not a single global pool.
- **`SandboxConfig.network` defaults to `"none"`** (`sandboxtool.py:27`) — keep it that
  way. Tier-3/4 outbound access goes through the broker, never the worker's own stack.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| gVisor `runsc` | latest stable | Kernel-level isolation for tiers 3–4. **Hard prerequisite** — absent on the current dev machine; ops task required |
| `esbuild` *or* `swc` | latest stable | Build-time TS → JS bundling for client halves (M11). Never invoked at request time |
| `aiohttp` | existing | Host broker outbound calls. Already a dependency |
| `pydantic` | existing | All new models. Already core |
| stdlib `ast` | — | CI tier-conformance analysis (M12). No new dependency |
| stdlib `asyncio.subprocess` | — | Tier-1/2 warm workers (M6). No new dependency |
| stdlib `hashlib` | — | SHA-256 source integrity. No new dependency |

No new *Python* runtime dependency is introduced. The additions are a container
runtime (ops) and a JS bundler (build-time).

---

## Worktree Strategy

- **Default isolation unit**: `mixed`

- **Phase 1 — sequential, single worktree.** Modules **M1, M2, M3** (Track 1) run in
  dependency order in one worktree. They define the Pydantic contracts every other
  track builds against, and M2 touches `core/events.py`, a file with cross-feature
  exposure. These must stabilise and merge before anything else starts.

- **Phase 2 — parallelizable across three worktrees** once Phase 1 merges:
  - **Worktree A — Track 2 (server sandbox)**: M4, M5, M6, M7, M8, M9. All new files
    under `services/sandbox/`. Internally sequential (M9 depends on M4–M8), but shares
    no files with B or C.
  - **Worktree B — Track 3 (client runtime)**: M10, M11. Touches
    `renderers/html5.py` and build config only.
  - **Worktree C — Track 4 (authoring & CI)**: M12, M13. Depends on Track 1's contracts,
    not on Track 2 or 3. All new files under `scripts/` and `tools/`.

- **Rationale**: Forcing all thirteen modules sequentially would serialise roughly three
  weeks of genuinely independent work for no isolation benefit — Tracks 2, 3, and 4
  touch disjoint file sets. Conversely, starting all four tracks on day one would have
  three tracks building against contracts still in flux, which is the more expensive
  failure. Splitting at the Track-1 boundary buys the parallelism where it is real and
  pays the sequencing cost only where the dependency is genuine.

- **Cross-feature dependencies — coordinate before touching shared files:**
  - **`formbuilder-formschema-persistency` (FEAT-457, 15 tasks, in flight)** — the live
    watch item. If it changes how `FormSchema` (and therefore `events`) is persisted, it
    shares `core/schema.py` with this feature. This spec reads `FormSchema.events`
    (line 368) but does **not** modify it, which should keep the conflict surface to
    zero — confirm before M3 lands.
  - **`formdesigner-unknown-fields-capture` (FEAT-458, spec just landed on `dev`)** —
    same package; check for overlap in `core/` before Phase 1.
  - **`formbuilder-fieldtype-cardinality` (FEAT-456)** — touches field types, not
    events. No overlap expected.
  - **`formbuilder-database`, `formbuilder-list-created-forms`** — no overlap.
  - Shared files to watch: `core/schema.py`, `core/events.py`, `renderers/html5.py`.

---

## 8. Open Questions

> Carried forward from `sdd/proposals/formbuilder-custom-code.brainstorm.md`.
> Three were resolved during `/sdd-spec` clarification and are reflected in the
> spec body; five remain open.

**Resolved**

- [x] **OQ-3** — How should the per-binding failure policy (C9) be expressed, given that
  `required` currently means "handler *missing*" rather than "handler *failed*"?
  — *Resolved during /sdd-spec*: **Add a new `on_failure: Literal["abort","continue"]
  = "continue"` field** to `FormEventBinding`. Keep `required` semantics untouched.
  The two conditions stay distinct; the change is additive and preserves G10.
  *Reflected in*: §2 Data Models (`FormEventBinding` block + design note),
  §3 Module 2, §4 `test_required_semantics_unchanged`, §5 G9/G10 criteria.
- [x] **OQ-4** — gVisor is absent in this environment. Is `runsc` an acceptable
  deployment prerequisite for tiers 3–4, or must those tiers run degraded on plain
  Docker? — *Resolved during /sdd-spec*: **Hard prerequisite.** Tiers 3–4 refuse to
  load at boot when `runsc` is unavailable. Tiers 1–2 are unaffected and need no
  container runtime. No silent degradation to a weaker boundary.
  *Reflected in*: §2 Overview, §3 Modules 3 and 7, §5 operational criteria,
  §6 Verified Environment Facts, §7 External Dependencies.
- [x] **v1 scope** — Should FEAT-459 cover all four tracks or a reduced slice?
  — *Resolved during /sdd-spec*: **Full Option D — all four tracks, tiers 1–4.**
  *Reflected in*: §3 (thirteen modules across four tracks), Worktree Strategy.

**Open**

- [ ] **OQ-1 (highest impact)** — Does git-backed storage (C8) survive contact with the
  multi-tenant requirement? A merged PR per tenant rule means turnaround measured in
  CI-and-review time, tenant logic visible to all repo readers, and isolation by
  directory convention rather than row-level access control. Brainstorm Option C exists
  precisely for this. The architecture here is deliberately structured so that a later
  swap to DB-backed storage costs **only M3 (the loader)** — M1, M4–M9 all survive. The
  answer should still be deliberate rather than discovered in production.
  — *Owner: Jesus Lara*
- [ ] **OQ-2** — Partial saves were named in the original brief but excluded by C2.
  Confirm this is a deliberate v1 deferral rather than an oversight. `PartialSaveStore`
  (`services/partial_saves.py:24`) currently dispatches no events, so adding them later
  is additive and non-breaking. — *Owner: Jesus Lara*
- [ ] **OQ-5** — Which `AuthContext` claims are safe to expose at each tier? The spec
  establishes the mechanism (`CapabilityManifest.auth_claims` + `ContextProjector`); the
  concrete per-tier claim allowlist still needs deciding. Blocks M4's default policy,
  not its structure. — *Owner: Jesus Lara*
- [ ] **OQ-6** — Warm pool sizing and recycling policy: workers per tier, invocations
  before recycle, queue depth before a submit is failed rather than queued. Needs a
  load-profile answer, not a guess. Note the per-process multiplier under multi-worker
  gunicorn (see §7). — *Owner: Jesus Lara / ops*
- [ ] **OQ-7** — Per C7, client code is authoritative for "client-only concerns". Where
  exactly is that line? A Web Worker cannot touch the DOM, so purely-visual logic must
  return patches the host applies — meaning the *host* decides what a patch may change.
  That allowlist needs defining. Blocks M10's policy table, not its structure.
  — *Owner: Jesus Lara*
- [ ] **OQ-8** — When the LLM generates a Python/TS pair from one intent, what enforces
  that they agree? CI equivalence tests over shared fixtures, generation from a single
  intermediate representation, or accepted drift with the server as tiebreaker? M12
  currently checks only `handler_ref`/`event` agreement, not semantic equivalence.
  — *Owner: Jesus Lara*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-24 | Jesus Lara | Initial draft from `formbuilder-custom-code.brainstorm.md` (Option D). Resolved OQ-3 (`on_failure` field), OQ-4 (gVisor hard prerequisite), and v1 scope (full four-track, tiers 1–4). Codebase contract re-verified at commit `644b99c1f`; brainstorm line numbers for `FormEventsConfig` and `FormEventContext` corrected. |
