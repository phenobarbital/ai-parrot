---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Form Builder — Sandboxed Custom Code on Lifecycle Events

**Feature ID**: FEAT-459
**Date**: 2026-08-24
**Author**: Jesus Lara
**Status**: approved
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
- **G8 (C8, revised — resolved OQ-1)** — Store snippets in a **hybrid dual-source**
  model: platform-wide snippets are git-backed and approved by PR review; tenant-specific
  snippets live in a versioned DB table and are approved in-app by a tenant admin. Both
  sources feed the same registry and the same sandbox.
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
- **A single-source storage model.** OQ-1 resolved to a hybrid: neither pure-git
  (brainstorm Option D as originally written) nor pure-DB (brainstorm Option C). Both
  loaders ship in v1.
- **Tenant snippets escalating to tiers 3–4 by default.** DB-sourced tenant snippets are
  capped at tier 2 (`helpers`) unless a platform operator explicitly raises the cap for
  that tenant. Tiers 3–4 remain a platform-operator concern.
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
2. **Approval is source-specific but always human (G4/C4).** For git-backed platform
   snippets the merged commit *is* the gate — signed commits, CI, blame, and rollback
   come free. For DB-backed tenant snippets a tenant admin publishes a draft through an
   approval service that mirrors `FormVersionService.publish()`
   (`services/form_version.py:306`). Neither source can execute unapproved code.
3. **The Python and TS halves are siblings in one bundle**, generated from one intent,
   and CI asserts they agree by running both against shared fixtures (resolved OQ-8).

### Dual-source storage (resolved OQ-1)

Snippets come from two sources that share every downstream component — one manifest
model, one sandbox, one broker, one router:

| Source | Scope | Approval gate | Tier cap | Changes at |
|---|---|---|---|---|
| **Git** | platform-wide (`tenant=None`) | merged PR | 1–4 | deploy time |
| **DB** | one tenant | in-app publish by tenant admin | 1–2 by default | runtime |

**Precedence falls out of the existing registry for free.** `get_form_event()`
(`services/event_registry.py:149`) already resolves `(tenant, handler_ref)` first and
falls back to `(None, handler_ref)`. Git snippets register globally (`tenant=None`);
DB snippets register under their tenant slug. A tenant snippet therefore overrides a
platform snippet of the same `handler_ref` with **no change to the registry or the
dispatcher**.

**Runtime updates need a resolver, not re-registration.** `_EVENT_REGISTRY` has no
public unregister, and `register_form_event()` raises `ValueError` on a duplicate key
(`event_registry.py:141`). A DB snippet that is edited and re-published therefore
cannot re-register. The design instead registers **one stable resolver closure per
`(tenant, handler_ref)`** at startup; on each dispatch the closure looks up the
currently-published version through a read-through cache modelled on
`FormRegistry._read_through()` (`services/registry.py:1035`). Re-publishing swaps the
row; the registry entry never changes.

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
      ┌─────────── BUILD / CI (offline) ────────────┐   ┌──── RUNTIME (in-app) ─────┐
      │ LLM authoring → bundle → PR → conformance    │   │ LLM drafts → tenant admin │
      │ + equivalence gate → TS bundler → MERGE = ✅ │   │ publishes → DB row = ✅   │
      └──────────────────┬──────────────────────────┘   └─────────────┬─────────────┘
                         │ git artifacts (tenant=None)                │ DB rows (tenant=slug)
                         ▼                                            ▼
  ┌─────────── SERVER BOOT ─────────────────────────────────────────────────────────┐
  │  GitSnippetLoader                      DbSnippetStore (+ ApprovalService)       │
  │   walk dir → parse manifest             read-through cache, published version   │
  │   → verify SHA-256 → adapter            → STABLE RESOLVER closure per           │
  │   → register_form_event(ref,             (tenant, ref); re-publish swaps the    │
  │        tenant=None) ──────────┐          row, NOT the registry entry            │
  │                               │                    │                            │
  │                               └──► _EVENT_REGISTRY ◄┘  (event_registry.py:65)   │
  └─────────────────────────────────────────┬───────────────────────────────────────┘
                                            ▲
             get_form_event() precedence:   │  (tenant, ref) → (None, ref)
             tenant DB snippet OVERRIDES    │  — existing behaviour, unmodified
             platform git snippet           │     (event_registry.py:149)
                                            │
  ┌─────────── REQUEST PATH ───────────┐    │ UNMODIFIED lookup
  │  FormAPIHandler                    │    │
  │    └─► dispatch()  ────────────────┼────┘   (event_dispatcher.py:102)
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


class SnippetSource(StrEnum):
    """Where a bundle came from. Determines its approval gate and tier cap."""
    GIT = "git"   # platform-wide, tenant=None, approved by merged PR
    DB = "db"     # tenant-scoped, approved in-app by a tenant admin


class SnippetStatus(StrEnum):
    """Lifecycle of a DB-sourced tenant snippet. GIT bundles are always PUBLISHED
    by construction — an unmerged snippet does not exist on disk."""
    DRAFT = "draft"
    PUBLISHED = "published"
    REVOKED = "revoked"


class SnippetBundle(BaseModel):
    """One snippet from either source: manifest + Python half + optional TS half."""
    model_config = ConfigDict(extra="forbid")
    source: SnippetSource
    status: SnippetStatus = SnippetStatus.PUBLISHED
    version: int = 1                      # DB snippets increment; git is always 1
    approved_by: str | None = None        # tenant admin id (DB) or commit sha (git)
    approved_at: datetime | None = None
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

### Auth claim projection policy (resolved OQ-5)

`AuthContext` (`services/auth_context.py:20`) carries four fields, and two of them are
**live credentials**:

| Field | Line | Crosses the sandbox boundary? |
|---|---|---|
| `scheme` | :39 | Yes, tier ≥ 2 — non-secret metadata |
| `token` | :40 | **Never, at any tier** — bearer token / API key |
| `headers` | :41 | **Never, at any tier** — pre-built credential headers |
| `claims` | :42 | Only the subkeys named in `CapabilityManifest.auth_claims` |

Per-tier policy:

| Tier | Projected identity |
|---|---|
| 1 `pure` | Nothing. `claims={}`, no `scheme`. Payload and schema only. |
| 2 `helpers` | `scheme` + manifest-declared subkeys of `claims`, drawn from a fixed safe set (`sub`, `tenant`, `roles`, `scope`, `email`, `preferred_username`) |
| 3 `brokered` | Identical to tier 2 |
| 4 `toolkit` | Identical to tier 2 |

**The governing invariant: the projected identity set never grows with tier.** Higher
tiers buy more *actions* — mediated by the host broker — never more *secrets*. A tier-4
snippet is strictly more powerful than a tier-2 snippet in what it can ask the broker to
do, and exactly equally ignorant of credentials.

This is enforced **structurally, not by policy**: `SandboxContext` has no `token` and no
`headers` field, so there is no code path that could serialise one. A future contributor
cannot leak a credential by forgetting a filter — the field does not exist.

### Client patch allowlist (resolved OQ-7)

A Web Worker has no DOM (G6), so client logic returns **typed patch operations** that
the host page applies. The host owns the allowlist; anything not on it is discarded and
logged. Patches are operations over existing field UIDs — **never markup, never
structure**.

Permitted operations:

| Operation | Effect |
|---|---|
| `set_visibility(field_uid, bool)` | Show or hide a field |
| `set_required(field_uid, bool)` | Toggle the required marker |
| `set_enabled(field_uid, bool)` | Enable or disable input |
| `set_value(field_uid, value)` | Write a computed value — only for fields the schema marks computable |
| `set_hint(field_uid, text)` | Inline help or validation message |
| `narrow_options(field_uid, subset)` | Restrict a select to a **subset of its already-declared** options — never new ones |

Structurally refused (the host has no handler for them):

- The submit URL / `form.action`, and the CSRF token meta tag (`renderers/html5.py`)
- `form_uid`, `form_id`, `tenant` — identity is server-owned
- Adding or removing fields or sections — structure is server-owned
- Any change to a field's `name` or `uid`, which would remap submitted data
- Raw HTML or DOM injection — patches are typed operations, and no `innerHTML` path exists
- Navigation, cookies, and storage access

Because the server re-runs every rule with a server counterpart (G7/C7), a forged or
malicious patch can at worst produce a *misleading UI*; it can never produce an invalid
submission.

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

Sixteen modules across four tracks. **Track 1 (M1–M6) is a hard sequential
prerequisite** — it defines the contracts and both loading paths everything else
builds on.

### Track 1 — Contracts & Dual-Source Loading

#### Module 1: Snippet & Manifest Models
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/snippets.py`
- **Responsibility**: `CapabilityTier`, `SnippetSource`, `SnippetStatus`,
  `BrokerAllowlist`, `CapabilityManifest`, `SnippetBundle`, `SandboxContext`,
  `SandboxOutcome`, `AbortSignal`, plus typed exceptions (`SnippetIntegrityError`,
  `SnippetTierUnavailableError`, `CapabilityDenied`, `SnippetNotApprovedError`).
- **Depends on**: `core/events.py` (`FormEventName`, `EventResolution`).

#### Module 2: `on_failure` Binding Extension
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py`
- **Responsibility**: Add `on_failure: Literal["abort","continue"] = "continue"` to
  `FormEventBinding` (line 54); document how it differs from `required`. Re-export
  unchanged from `core/__init__.py`.
- **Depends on**: nothing. **Must not alter** existing field semantics (G10).

#### Module 3: Snippet Source Protocol & Resolver Adapter
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/base.py`
- **Responsibility**: The `SnippetSourceProtocol` both loaders implement, and the
  **stable resolver closure** registered once per `(tenant, handler_ref)` via
  `register_form_event()`. The closure resolves the currently-published bundle at
  dispatch time, which is what makes runtime DB updates possible without
  re-registration (see §2 Dual-source storage). Also owns the shared adapter that
  `dispatch()` sees as an ordinary handler.
- **Depends on**: Module 1, `services/event_registry.py:73`.
- **Note**: This module exists specifically so that OQ-1 can be revisited later at the
  cost of one implementation, not an architecture.

#### Module 4: Git Snippet Loader
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/git_loader.py`
- **Responsibility**: Walk the git-backed snippet root, parse manifests, verify SHA-256
  source hashes, emit `SnippetBundle(source=GIT, tenant=None)`. Refuse tier 3/4 bundles
  when gVisor is absent.
- **Depends on**: Modules 1, 3.

#### Module 5: Tenant Snippet Store & Migration
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/db_store.py`
  + `packages/parrot-formdesigner/migrations/007_snippet_store.sql`
- **Responsibility**: Versioned per-tenant snippet table (`tenant`, `handler_ref`,
  `event`, `manifest`, sources, hashes, `status`, `version`, `approved_by`,
  `approved_at`); read-through cache modelled on `FormRegistry._read_through()`
  (`services/registry.py:1035`); `on_startup`/`on_shutdown` hooks mirroring
  `registry.py:711,750`. Enforces the tier-2 cap for DB snippets unless an operator
  raised it for that tenant.
- **Depends on**: Modules 1, 3.

#### Module 6: Tenant Approval Service
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/approval.py`
- **Responsibility**: Draft → published → revoked lifecycle for DB snippets, mirroring
  `FormVersionService.publish()` / `.get_published()` / `.list_versions()`
  (`services/form_version.py:306,431,480`). Records approver identity and timestamp;
  refuses to publish a bundle that fails the conformance gate. **This is the C4 human
  approval gate for the DB source.**
- **Depends on**: Modules 1, 5, 15.

### Track 2 — Server Sandbox

#### Module 7: Context Projector
- **Path**: `.../services/sandbox/projector.py`
- **Responsibility**: Convert a live `FormEventContext` into a `SandboxContext`,
  applying the per-tier claim policy from §2 (resolved OQ-5). `token` and `headers`
  are structurally absent from the target model. Reject non-serialisable values loudly.
- **Depends on**: Module 1, `core/events.py:106`, `services/auth_context.py:20`.

#### Module 8: Worker Protocol
- **Path**: `.../services/sandbox/protocol.py`
- **Responsibility**: Length-prefixed JSON framing with a strict size cap —
  `SandboxContext` in; `SandboxOutcome`, `AbortSignal`, or `BrokerRequest` out.
- **Depends on**: Module 1.

#### Module 9: Subprocess Worker Pool (tiers 1–2)
- **Path**: `.../services/sandbox/pool.py`
- **Responsibility**: `SubprocessWorkerPool` implementing `SandboxProvider`. Warm
  `asyncio.subprocess` workers, no network namespace, wall/CPU/memory budgets,
  recycling, health checks, bounded acquire queue, cold-start path. **All sizing knobs
  configurable with documented defaults (resolved OQ-6).**
- **Depends on**: Modules 1, 8; `parrot.eval.sandbox.base:166`.

#### Module 10: gVisor Worker Pool (tiers 3–4)
- **Path**: `.../services/sandbox/gvisor_pool.py`
- **Responsibility**: `GVisorWorkerPool` implementing `SandboxProvider`, backed by
  `SandboxConfig` (`sandboxtool.py:24`). `is_available()` probes `runsc`; absence is a
  hard boot failure for tiers 3–4, never a silent downgrade.
- **Depends on**: Modules 1, 8; `parrot_tools.sandboxtool`.

#### Module 11: Host Broker
- **Path**: `.../services/sandbox/broker.py`
- **Responsibility**: Validate every `BrokerRequest` against the manifest allowlist and
  perform the I/O in the trusted process with `aiohttp`. Emit a structured security log
  event and raise `CapabilityDenied` on any undeclared request. Enforce a
  per-invocation call cap.
- **Depends on**: Modules 1, 8.

#### Module 12: Tier Router
- **Path**: `.../services/sandbox/router.py`
- **Responsibility**: Route a bundle to the cheapest satisfying executor; project
  context, execute, validate the returned `EventResolution`, rehydrate `AbortSignal`
  into `FormEventAbort`, apply the `on_failure` policy.
- **Depends on**: Modules 1, 2, 7, 8, 9, 10, 11.

### Track 3 — Client Runtime

#### Module 13: Web Worker Runtime & Patch Allowlist
- **Path**: `.../renderers/worker_bridge.py`
- **Responsibility**: Generate the Worker boot block injected into
  `_LIFECYCLE_SCRIPT_TEMPLATE` (`renderers/html5.py:423`); implement the `postMessage`
  patch protocol and the **host-side allowlist from §2 (resolved OQ-7)** — six permitted
  operations, everything else discarded and logged. Preserve the existing remote-fetch
  bridge untouched.
- **Depends on**: Module 1.

#### Module 14: TS Bundler Integration
- **Path**: `packages/parrot-formdesigner/scripts/build_snippet_bundles.py`
- **Responsibility**: Build-time TS → JS compilation into worker-ready bundles with
  content hashes. **Never invoked at request time.**
- **Depends on**: Module 1.

### Track 4 — Authoring & CI

#### Module 15: Conformance & Equivalence Gate
- **Path**: `packages/parrot-formdesigner/scripts/check_snippet_conformance.py`
- **Responsibility**: Two gates. **(a) Tier conformance** — static `ast` analysis
  asserting no imports beyond `stdlib_modules`, no I/O at tiers 1–2, no broker calls
  outside the allowlist, hashes matching sources. **(b) Semantic equivalence
  (resolved OQ-8)** — every bundle ships fixture cases; the gate executes the Python
  half and the compiled JS half against the same fixtures and fails on divergent
  output. Importable by Module 6 so DB publishes run the same checks as PRs.
- **Depends on**: Module 1.

#### Module 16: LLM Authoring Surface
- **Path**: `.../tools/snippet_authoring.py`
- **Responsibility**: Toolkit and prompts for generating conformant bundles from a
  natural-language rule: emit the Python half, the TS half, the manifest, **and the
  equivalence fixtures OQ-8 requires**; run the gate locally before proposing; surface
  a plain-language capability summary for the approver. Targets both sources — a PR for
  platform snippets, a draft row for tenant snippets.
- **Depends on**: Modules 1, 15.

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
| `test_git_loader_rejects_hash_mismatch` | M4 | Edited source without manifest update → `SnippetIntegrityError` at load |
| `test_git_loader_rejects_tier3_without_gvisor` | M4 | `SnippetTierUnavailableError` when `runsc` absent (OQ-4) |
| `test_git_loader_duplicate_ref_raises` | M4 | Two bundles, one `handler_ref` → `ValueError` from the registry |
| `test_projector_strips_live_auth_context` | M7 | `SandboxContext.claims` contains only declared `auth_claims`; live object never crosses |
| `test_projector_rejects_unserialisable` | M7 | Non-JSON-serialisable payload fails loudly |
| `test_protocol_enforces_size_cap` | M8 | Oversized frame rejected, not truncated |
| `test_pool_recycles_after_n` | M9 | Worker retired after the configured invocation count |
| `test_pool_kills_on_timeout` | M9 | Wall-clock budget exceeded → worker killed, failure surfaced |
| `test_pool_bounded_queue_times_out` | M9 | Exhausted pool times out rather than waiting unboundedly |
| `test_pool_replaces_unhealthy_worker` | M9 | Failed `health_check()` → destroy and replace |
| `test_gvisor_pool_is_available_probe` | M10 | `is_available()` correctly reports a missing `runsc` |
| `test_broker_denies_undeclared_host` | M11 | HTTP to a non-allowlisted host → `CapabilityDenied` + security log |
| `test_broker_denies_undeclared_table` | M11 | Query outside `query_tables` denied |
| `test_broker_enforces_call_cap` | M11 | Per-invocation broker call limit enforced |
| `test_router_selects_cheapest_tier` | M12 | Tier 1 routes to subprocess pool, tier 3 to gVisor pool |
| `test_router_abort_rehydrates_exception` | M12 | `AbortSignal` → `FormEventAbort` with reason/message/status intact |
| `test_router_invalid_resolution_is_failure` | M12 | Malformed return → `on_failure` policy, never partially applied |
| `test_router_on_failure_abort` | M12 | `on_failure="abort"` raises through `dispatch()` |
| `test_router_on_failure_continue` | M12 | `on_failure="continue"` logs and returns an empty `EventResolution()` |
| `test_worker_patch_allowlist` | M13 | Patch operations outside the host allowlist are discarded |
| `test_conformance_rejects_undeclared_import` | M15 | Tier-1 snippet importing `socket` fails the gate |
| `test_conformance_rejects_half_mismatch` | M15 | Python/TS halves disagreeing on `handler_ref` fails |
| `test_resolver_survives_republish` | M3 | Re-publishing a DB snippet swaps the row; the registry entry is untouched and no `ValueError` is raised |
| `test_resolver_registers_once_per_key` | M3 | Exactly one `register_form_event()` call per `(tenant, handler_ref)` regardless of version count |
| `test_db_store_read_through_cache` | M5 | Published version served from cache; invalidated on republish |
| `test_db_snippet_capped_at_tier2` | M5 | A tenant bundle declaring tier 3 is rejected unless the operator raised that tenant's cap |
| `test_approval_refuses_unconformant` | M6 | `publish()` rejects a bundle failing the conformance gate |
| `test_approval_records_approver` | M6 | Published row carries `approved_by` and `approved_at` |
| `test_draft_never_executes` | M6 | A `DRAFT` snippet is never resolved by the resolver closure |
| `test_projector_never_emits_token` | M7 | `SandboxContext` model has no `token`/`headers` field; a live `AuthContext` cannot round-trip one |
| `test_projector_tier1_has_no_claims` | M7 | Tier 1 receives `claims={}` and no `scheme` |
| `test_projector_claims_are_allowlisted` | M7 | Only manifest-declared subkeys from the safe set are projected |
| `test_projector_tier4_claims_equal_tier2` | M7 | The identity set does not grow with tier |
| `test_patch_rejects_structure_change` | M13 | Add/remove field, rename `uid`, or action-URL patches are discarded and logged |
| `test_patch_narrow_options_subset_only` | M13 | `narrow_options` accepts a subset of declared options and rejects new ones |
| `test_equivalence_gate_detects_divergence` | M15 | Python and JS halves returning different results for a shared fixture fail the build |
| `test_equivalence_gate_requires_fixtures` | M15 | A bundle shipping no fixture cases fails the gate |

### Integration Tests

| Test | Description |
|---|---|
| `test_snippet_runs_via_dispatch_unmodified` | Registered snippet fires through the **unmodified** `dispatch()` and returns an `EventResolution` |
| `test_snippet_abort_produces_http_error` | Snippet aborting `onBeforeSubmit` yields the correct status + safe user message; `onError` is NOT fired |
| `test_schema_overrides_applied_shallow` | Snippet-returned overrides flow through `apply_schema_overrides()` with shallow-merge semantics preserved |
| `test_payload_replacement_on_before_submit` | Snippet-replaced payload reaches the persistence layer |
| `test_legacy_handler_still_works` | A hand-written `@register_form_event` handler is unaffected by either loader (G10) |
| `test_tenant_db_snippet_overrides_git` | With both a global git snippet and a tenant DB snippet on one `handler_ref`, the tenant's runs — via the existing registry fallback, no dispatcher change |
| `test_git_snippet_serves_other_tenants` | A tenant without an override still gets the platform git snippet |
| `test_republish_takes_effect_without_restart` | Publishing a new DB version changes dispatch behaviour with no process restart and no re-registration |
| `test_revoked_snippet_falls_back_to_git` | Revoking a tenant snippet restores the platform snippet for that tenant |
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
- [ ] **G8/C8 (hybrid)** — Both sources load into one registry: git snippets register globally, DB snippets per tenant; a tenant snippet overrides a platform snippet of the same `handler_ref` purely through the existing `get_form_event()` fallback
- [ ] **G8b** — No DB snippet executes in `DRAFT` or `REVOKED` status; publishing records `approved_by` and `approved_at`
- [ ] **G8c** — Re-publishing a DB snippet changes behaviour without a restart and without a second `register_form_event()` call
- [ ] **G9/C9** — `on_failure="abort"` rejects the submission via `FormEventAbort`; `on_failure="continue"` logs and proceeds with an empty resolution
- [ ] **G10** — `services/event_dispatcher.py` `dispatch()` is byte-for-byte unchanged; all pre-existing handlers and bindings pass their original tests

**Operational**
- [ ] gVisor absence is a loud boot failure for tiers 3–4 and a no-op for tiers 1–2 (OQ-4)
- [ ] Tier-1 dispatch overhead ≤ 15 ms p95 on a warm pool (target 5 ms; measured, not asserted by construction)
- [ ] Pool exhaustion produces a bounded timeout, never an unbounded wait
- [ ] A denied capability request emits a structured security log event including tenant, `handler_ref`, and the denied request
- [ ] CI conformance gate fails the build on any snippet that exceeds its declared tier
- [ ] **Claim projection (OQ-5)** — `SandboxContext` has no `token`/`headers` field; tier 1 receives no identity at all; the projected claim set is identical for tiers 2, 3, and 4
- [ ] **Pool tuning (OQ-6)** — Every pool sizing knob is configurable, ships a documented default, and a tuning runbook lands in `docs/`
- [ ] **Patch allowlist (OQ-7)** — The host applies only the six allowlisted patch operations; everything else is discarded and logged
- [ ] **Half equivalence (OQ-8)** — Every bundle ships equivalence fixtures; CI executes both halves against them and fails on divergence
- [ ] DB-sourced tenant snippets are capped at tier 2 unless a platform operator explicitly raises that tenant's cap

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

def _clear_event_registry_for_tests() -> None: ...          # line 206 — TEST ONLY
# CRITICAL: there is NO public unregister/override API. register_form_event() raises
# ValueError when (tenant, handler_ref) is already present (line 141). This is why
# M3 registers ONE stable resolver closure per key rather than re-registering
# on every DB republish.

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

# packages/parrot-formdesigner/src/parrot_formdesigner/services/auth_context.py
class AuthContext(BaseModel):                               # line 20
    scheme: Literal["none", "bearer", "api_key", "custom"]  # line 39 — safe metadata
    token: str | None = None                                # line 40 — SECRET, never projected
    headers: dict[str, str] = {}                            # line 41 — SECRET, never projected
    claims: dict[str, Any] = {}                             # line 42 — selectively projectable

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:                                         # line 240
    async def on_startup(self, app: "web.Application") -> None: ...   # line 711
    async def on_shutdown(self, app: "web.Application") -> None: ...  # line 750
    async def _read_through(self, ...) -> ...: ...          # line 1035 — cache pattern for M5
class FormStorage(ABC): ...                                 # line 63 — storage ABC precedent

# packages/parrot-formdesigner/src/parrot_formdesigner/services/form_version.py
class FormVersionService:                                   # line 251
    async def publish(self, ...) -> ...: ...                # line 306 — approval pattern for M6
    async def get_published(self, ...) -> ...: ...          # line 431
    async def list_versions(self, ...) -> ...: ...          # line 480

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
| Tenant-over-platform precedence | `get_form_event()` | existing tenant→global fallback | `services/event_registry.py:149` |
| `ContextProjector` | `AuthContext.claims` | reads `claims` only; never `token`/`headers` | `services/auth_context.py:39-42` |
| `DbSnippetStore` | `FormRegistry._read_through()` | cache pattern precedent | `services/registry.py:1035` |
| `DbSnippetStore` | `FormRegistry.on_startup/on_shutdown` | aiohttp lifecycle precedent | `services/registry.py:711,750` |
| `SnippetApprovalService` | `FormVersionService.publish()` | publish/version pattern precedent | `services/form_version.py:306` |
| `007_snippet_store.sql` | `migrations/` | next sequential migration (006 is latest) | `packages/parrot-formdesigner/migrations/` |

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
  (`base.py:259`) exists. There is **no** real pooling provider to inherit from; M9/M10
  are the first concrete implementations.
- ~~`unregister_form_event` / `override_form_event`~~ — **do not exist**. The registry
  exposes only `register_form_event`, `get_form_event`, `list_form_events`, and the
  test-only `_clear_event_registry_for_tests()` (`event_registry.py:206`). Do not
  attempt to mutate `_EVENT_REGISTRY` directly.
- ~~A snippet table or migration~~ — does not exist. `migrations/` currently ends at
  `006_backfill_element_uids.py`; M5 adds `007_snippet_store.sql`.
- ~~`SnippetSource` / `SnippetStatus` / `SnippetApprovalService`~~ — do not exist; M1
  and M6 create them.

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

### Pool sizing defaults (resolved OQ-6)

Starting values, **all configurable**; a tuning runbook ships in `docs/`. These are
defensible defaults chosen to fail safe under load, not measured against a traffic
profile — the runbook explains how to tune each against real p95 numbers.

| Knob | Default | Rationale |
|---|---|---|
| `tier12_pool_size` | 4 workers **per process** | Covers typical concurrent submits without holding much RSS. Under gunicorn `-w N` the real total is N × 4 — size against that, not this number |
| `tier34_pool_size` | 2 workers per process | Tier 3–4 traffic is rare by design; containers are expensive to hold warm |
| `recycle_after_invocations` | 500 | Bounds any slow state leak in a long-lived worker |
| `recycle_after_seconds` | 3600 | Backstop for low-traffic workers that never hit the invocation count |
| `acquire_queue_timeout_ms` | 2000 | Bounded wait, then `on_failure` policy. **Never unbounded** |
| `max_queue_depth` | 32 | Beyond this, fail fast rather than accumulate latency |
| `health_check_interval_s` | 30 | Detects poisoned workers between requests, not on the hot path |
| `cold_start_timeout_ms` | 5000 | A pool miss must not hang a submit indefinitely |
| Default `timeout_ms` (manifest) | 5000 | Per-snippet, overridable within `[1, 30_000]` |
| Default `max_memory_mb` (manifest) | 128 | Per-snippet, overridable within `[16, 2048]` |

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

**Additional risks introduced by the hybrid source model (OQ-1):**

- **The registry has no unregister.** `register_form_event()` raises `ValueError` on a
  duplicate key (`event_registry.py:141`) and there is no public removal API — only
  `_clear_event_registry_for_tests()` (:206). Any design that re-registers a DB snippet
  on republish **will** break. Register the stable resolver closure exactly once per
  `(tenant, handler_ref)`; version lookup happens inside the closure.
- **Two trust models, one execution path.** A git snippet is gated by PR review; a DB
  snippet by in-app publish. The sandbox does not distinguish them, so the *approval*
  code is now security-critical in its own right — M6 must refuse to publish anything
  that fails the M15 gate, and that check cannot be bypassed by a direct DB write.
- **Executable code in a table is a high-value target.** A SQL injection anywhere in the
  application escalates toward RCE via the snippet path. The tier-2 cap on DB snippets
  is the primary mitigation; the sandbox is the second.
- **Two audit trails.** Git history covers platform snippets; `approved_by`/`approved_at`
  rows cover tenant snippets. Incident response needs both, and they must be
  correlatable — log `source` on every dispatch.
- **Cache coherence across processes.** The read-through cache is per-process. Under
  multi-worker gunicorn, a republish must invalidate every worker's cache, not just the
  one that served the publish request. See OQ-6's per-process multiplier note.

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

- **Phase 1 — sequential, single worktree.** Modules **M1–M6** (Track 1) run in
  dependency order in one worktree. They define the Pydantic contracts, both loading
  paths, and the approval gate that every other track builds against. M2 touches
  `core/events.py`, a file with cross-feature exposure, and M5 adds a migration —
  both warrant a single serialized worktree. These must merge before Phase 2 starts.

  Within Phase 1 there is one internal parallel opportunity: **M4 (git loader)** and
  **M5+M6 (DB store + approval)** are independent once **M3 (source protocol)** lands.
  If Phase 1 becomes the critical path, split those into two short-lived worktrees.

- **Phase 2 — parallelizable across three worktrees** once Phase 1 merges:
  - **Worktree A — Track 2 (server sandbox)**: M7–M12. All new files under
    `services/sandbox/`. Internally sequential (M12 depends on M7–M11), shares no files
    with B or C.
  - **Worktree B — Track 3 (client runtime)**: M13, M14. Touches `renderers/html5.py`
    and build config only.
  - **Worktree C — Track 4 (authoring & CI)**: M15, M16. Depends on Track 1's
    contracts, not on Track 2 or 3.

  **Ordering caveat introduced by OQ-1**: M6 (approval service) depends on M15
  (conformance gate) to refuse unconformant publishes. Either land a minimal M15 stub
  in Phase 1 and complete it in Worktree C, or accept that M6's gate-enforcement task
  closes after Worktree C merges. The former is preferred — the stub is small and keeps
  the security property true from the first commit.

- **Rationale**: Forcing all sixteen modules sequentially would serialise weeks of
  genuinely independent work — Tracks 2, 3, and 4 touch disjoint file sets. Starting all
  four tracks on day one would have three tracks building against contracts still in
  flux, the more expensive failure. Splitting at the Track-1 boundary buys parallelism
  where it is real and pays sequencing cost only where the dependency is genuine. The
  hybrid decision (OQ-1) grew Track 1 from three modules to six, which makes Phase 1
  the critical path — hence the internal split option above.

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

> All questions carried from `sdd/proposals/formbuilder-custom-code.brainstorm.md`
> are now **resolved**. Each resolution names where it is reflected in the spec body,
> so the decision trail is auditable and no decision lives only in this section.

- [x] **OQ-1 (highest impact)** — Does git-backed storage survive the multi-tenant
  requirement? — *Resolved 2026-08-24*: **Hybrid.** Platform-wide snippets stay
  git-backed and PR-approved; tenant-specific snippets live in a versioned DB table
  approved in-app by a tenant admin. Both feed one registry, one sandbox, one broker.
  Precedence is free — `get_form_event()` already resolves `(tenant, ref)` before
  `(None, ref)` (`event_registry.py:149`). DB snippets are capped at tier 2 unless an
  operator raises that tenant's cap.
  *Reflected in*: §1 G8 + Non-Goals, §2 Overview → "Dual-source storage" + Component
  Diagram, §2 Data Models (`SnippetSource`, `SnippetStatus`), §3 Modules 3–6,
  §4 dual-source unit + integration tests, §5 G8/G8b/G8c, §6 contract additions,
  §7 "Additional risks introduced by the hybrid source model", Worktree Strategy Phase 1.
- [x] **OQ-2** — Are partial-save events a deliberate v1 deferral? — *Resolved
  2026-08-24*: **Confirmed deferral.** v1 ships the five existing `FormEventName`
  members only. `PartialSaveStore` (`services/partial_saves.py:24`) dispatches no
  events today, so adding `onBeforePartialSave` / `onAfterPartialSave` later is
  additive and non-breaking.
  *Reflected in*: §1 Goals G2 + Non-Goals, §6 "Does NOT Exist".
- [x] **OQ-3** — How should the per-binding failure policy be expressed, given that
  `required` means "handler *missing*"? — *Resolved during /sdd-spec*: **Add a new
  `on_failure: Literal["abort","continue"] = "continue"` field.** `required` semantics
  are untouched; the two conditions stay distinct; the change is additive (G10).
  *Reflected in*: §2 Data Models + design note, §3 Module 2,
  §4 `test_required_semantics_unchanged`, §5 G9/G10.
- [x] **OQ-4** — Is gVisor an acceptable prerequisite for tiers 3–4? — *Resolved
  during /sdd-spec*: **Hard prerequisite.** Tiers 3–4 refuse to load at boot when
  `runsc` is unavailable; tiers 1–2 are unaffected and need no container runtime. No
  silent degradation.
  *Reflected in*: §2 Overview, §3 Modules 4 and 10, §5 operational criteria,
  §6 Verified Environment Facts, §7 External Dependencies.
- [x] **OQ-5** — Which `AuthContext` claims are safe at each tier? — *Resolved
  2026-08-24*: **`token` and `headers` never cross the boundary at any tier** — they
  are live credentials (`auth_context.py:40,41`). Tier 1 receives no identity at all.
  Tiers 2–4 receive `scheme` plus manifest-declared subkeys of `claims` from a fixed
  safe set (`sub`, `tenant`, `roles`, `scope`, `email`, `preferred_username`). The
  governing invariant: **the projected identity set never grows with tier** — higher
  tiers buy more brokered *actions*, never more *secrets*. Enforced structurally:
  `SandboxContext` has no `token`/`headers` field, so no code path can serialise one.
  *Reflected in*: §2 "Auth claim projection policy", §3 Module 7, §4 four projector
  tests, §5 OQ-5 criterion, §6 `AuthContext` contract entry.
- [x] **OQ-6** — How should the warm pools be sized? — *Resolved 2026-08-24*:
  **Documented defaults, every knob configurable, plus a tuning runbook.** Ten knobs
  with starting values chosen to fail safe under load rather than to match an assumed
  traffic profile. Note the per-process multiplier: under gunicorn `-w N` the real pool
  total is N × the configured size.
  *Reflected in*: §3 Module 9, §5 OQ-6 criterion, §7 "Pool sizing defaults" table.
- [x] **OQ-7** — Where is the line for client-authoritative logic? — *Resolved
  2026-08-24*: **A six-operation host-side allowlist.** The Worker returns typed patch
  operations — `set_visibility`, `set_required`, `set_enabled`, `set_value`,
  `set_hint`, `narrow_options` — over existing field UIDs. Never markup, never
  structure, never identity, never the action URL or CSRF token. Anything else is
  discarded and logged. Because the server re-runs every rule with a counterpart
  (G7/C7), a forged patch can at worst mislead the UI, never corrupt a submission.
  *Reflected in*: §2 "Client patch allowlist", §3 Module 13, §4 three patch tests,
  §5 OQ-7 criterion.
- [x] **OQ-8** — What enforces that the Python and TS halves agree? — *Resolved
  2026-08-24*: **CI equivalence tests over shared fixtures.** Every bundle ships fixture
  cases; the gate executes both halves against them and fails the build on divergent
  output. The LLM authoring surface must generate the fixtures alongside the code, and
  the same gate is importable by the DB approval service so in-app publishes are held
  to the PR standard.
  *Reflected in*: §2 Overview point 3, §3 Modules 15 and 16, §4 two equivalence tests,
  §5 OQ-8 criterion.

### Decisions deferred to implementation

Not open questions — these are bounded choices a task may make and record:

- The exact safe-claim set may be narrowed further per deployment; the spec fixes the
  *maximum*, not a mandate to expose all six.
- Whether M15's stub lands in Phase 1 or M6's gate-enforcement task closes after
  Worktree C (see Worktree Strategy "Ordering caveat").
- Cross-process cache invalidation mechanism for DB republishes under multi-worker
  gunicorn (listen/notify, TTL, or explicit broadcast) — the requirement is fixed, the
  mechanism is not.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.2 | 2026-08-24 | Jesus Lara | Resolved all six remaining open questions. **OQ-1 → hybrid dual-source storage** (git for platform, DB for tenant), which grew Track 1 from 3 to 6 modules and added the stable-resolver design forced by the registry having no unregister API. OQ-2 deferral confirmed. OQ-5 claim-projection policy (credentials never cross; identity set does not grow with tier). OQ-6 pool defaults + tuning runbook. OQ-7 six-operation patch allowlist. OQ-8 CI equivalence fixtures. Module count 13 → 16; contract extended with `AuthContext`, `FormRegistry`, `FormVersionService`, and registry-mutation facts. |
| 0.1 | 2026-08-24 | Jesus Lara | Initial draft from `formbuilder-custom-code.brainstorm.md` (Option D). Resolved OQ-3 (`on_failure` field), OQ-4 (gVisor hard prerequisite), and v1 scope (full four-track, tiers 1–4). Codebase contract re-verified at commit `644b99c1f`; brainstorm line numbers for `FormEventsConfig` and `FormEventContext` corrected. |
