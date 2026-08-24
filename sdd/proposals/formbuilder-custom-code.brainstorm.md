---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Form Builder — Sandboxed Custom Code on Lifecycle Events

**Date**: 2026-08-24
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option D

---

## Problem Statement

`parrot-formdesigner` already has a lifecycle event system (FEAT-188 / FEAT-329):
a `FormSchema` declares `events: FormEventsConfig`, each binding names a
`handler_ref`, and `services/event_dispatcher.dispatch()` resolves that ref against
a **module-level registry populated at import time by the `@register_form_event`
decorator**. That design has a hard ceiling:

> **Every handler must be Python written by a platform engineer, shipped in the
> `parrot-formdesigner` distribution, and imported into the server process before
> any form can reference it.**

Consequences:

1. **Forms cannot carry their own behavior.** A tenant who needs "if `total > 5000`,
   require the `approver_email` field" must file a ticket and wait for a release.
   The form is data; its logic is code in someone else's repo.
2. **The LLM can author schemas but not behavior.** The form-creation toolkits can
   generate fields, validation, and layout — the moment a requirement is
   *conditional or computed*, generation stops and a human writes Python.
3. **No safe path for untrusted code.** There is deliberately no mechanism today to
   execute code that arrives with a form, because there is no sandbox, no capability
   model, and no approval gate in the formdesigner package. Adding `exec()` to the
   aiohttp worker would be a straightforward RCE against every tenant.
4. **The client is inert.** `renderers/html5.py` ships a lifecycle bridge, but it can
   only `fetch()` back to the server. Every conditional show/hide or computed total
   costs a network round trip, so authors avoid them.

**Who is affected**: form authors and tenant admins (blocked on engineering for
routine logic), platform engineers (absorbing per-tenant handler requests as
release work), and end users (latency and clumsy forms).

**Why now**: the formbuilder track (`formbuilder-database`, `-fieldtype-cardinality`,
`-formschema-persistency`, `-list-created-forms`) has made schema generation
capable enough that *behavior* is the remaining gap between a generated form and a
usable one.

## Constraints & Requirements

Decisions locked during Rounds 0–3 of discovery. These are inputs, not proposals.

- **C1 — Dual runtime.** Server-side Python **and** client-side TS/JS. Neither alone.
- **C2 — Event surface frozen to FEAT-188.** `onBeforeOpen`, `onSchemaLoaded`,
  `onBeforeSubmit`, `onAfterSubmit`, `onError` only. No new event names in v1 — no
  partial-save pair, no field-level events. (See Open Questions: the original brief
  named partial saves; this was consciously deferred.)
- **C3 — Tiered capabilities, declared per snippet.** Four tiers: pure form data →
  curated read-only helpers → brokered outbound calls → full `parrot` toolkit access.
  A snippet declares what it needs; the sandbox grants exactly that and nothing more.
  Higher tiers are deny-by-default per tenant and demand stronger approval.
- **C4 — Human approval gate.** The LLM drafts; a human approves before anything
  executes. Autonomous execution of freshly generated code is out of scope.
- **C5 — Warm-pool kernel isolation for Python.** gVisor/Docker workers held warm
  behind a provider interface. Not in-process `exec`, not a cold container per submit.
- **C6 — Web Worker for client code.** No DOM access by construction; the worker
  computes and posts results back to the host page, which applies them.
- **C7 — Client code is authoritative for client-only concerns.** Display formatting
  and pure-presentation logic with no server counterpart are trusted as-is. Anything
  with a server counterpart is re-run server-side.
- **C8 — Git-backed snippet artifacts.** Snippets live as files in the repo, reviewed
  and approved through normal PRs, loaded by the server. Not a runtime DB table.
- **C9 — Per-binding failure policy.** Reuse `FormEventBinding.required`:
  `required=True` fails closed (submission rejected), otherwise fail open (log and
  continue).
- **C10 — Non-negotiable environment rules.** `uv` only, venv activated, async
  throughout, Google-style docstrings + strict type hints, Pydantic for all
  structures, `self.logger` over `print`. See `CLAUDE.md`.

### Constraint tension worth stating plainly

**C8 (git-backed) pulls against C3/C4's multi-tenant runtime story.** If a snippet
must land via a merged PR, then a tenant cannot get bespoke logic without a commit
to a shared repo, and "the LLM drafts at runtime" becomes "the LLM opens a PR."
That is *coherent* — the PR review **is** the C4 approval gate, and it gives audit,
rollback, blame, and CI for free — but it means:

- Turnaround is CI-and-review time, not seconds.
- Tenant isolation is by directory convention and loader scoping, not by row-level
  database access control.
- A tenant's business logic is visible to anyone with repo read access.

Option D below is designed around C8 as chosen. Option C is retained as the honest
alternative if the multi-tenant cost proves unacceptable. This is flagged as
**OQ-1**, the single most consequential open question in this document.

---

## Options Explored

### Option A: In-Process Restricted Interpreter

Compile each snippet with a whitelist-only AST pass (reject `import`, attribute
access to dunders, comprehension bombs), then `exec()` it in the aiohttp worker
against a curated builtins dict. Snippets are pure functions over `FormEventContext`.

✅ **Pros:**
- Sub-millisecond dispatch; no IPC, no container, nothing to operate.
- Smallest possible diff — a compiler module plus a dispatcher branch.
- Works identically in CI, on a laptop, and in production with zero infrastructure.

❌ **Cons:**
- **A single sandbox escape is full RCE in the form server process**, with every
  tenant's DB credentials and auth context in reach. Python-level sandboxes have a
  long history of being defeated via frame walking and type confusion.
- Cannot enforce CPU or memory limits — a `while True` pins an event-loop worker and
  stalls unrelated requests. No preemption in a coroutine.
- Blocking snippet code silently violates the async contract.
- Directly violates **C5**.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `RestrictedPython` | AST whitelist compile | ~7.x, Zope-maintained, mature; explicitly *not* a security boundary against a determined attacker |
| `asteval` | Alternative restricted evaluator | Simpler surface, weaker coverage |
| stdlib `ast` | Custom validating NodeVisitor | No new dependency |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py:102` — `dispatch()` is the single interception point.
- `packages/ai-parrot-tools/src/parrot_tools/codeinterpreter/executor.py:242` — `IsolatedExecutor.validate_syntax()`, an existing syntax pre-check.

---

### Option B: Cold Container Per Invocation

Spin a fresh Docker/gVisor container for every event dispatch, feed it the context as
JSON on stdin, read an `EventResolution` from stdout, tear it down.

✅ **Pros:**
- Strongest isolation available: no cross-tenant residue, no state carried between
  invocations, kernel-enforced resource limits.
- Reuses `parrot_tools/codeinterpreter/executor.py` and `sandboxtool.py` nearly as-is.
- Trivially correct security story — easy to explain to an auditor.

❌ **Cons:**
- **100–500 ms added to every form submit**, on the user's critical path. `onBeforeOpen`
  would slow first paint too.
- Container churn under load; a submit spike becomes a container-creation storm.
- Requires a Docker socket in the request path — itself a privilege concern.
- Violates **C5**.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `docker` (SDK) | Container lifecycle | Already used by `IsolatedExecutor` |
| gVisor `runsc` | Kernel-level isolation runtime | **Not installed on this machine** — see Code Context |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/sandboxtool.py:55` — `SandboxTool`, a gVisor executor built for exactly this threat model.
- `packages/ai-parrot-tools/src/parrot_tools/codeinterpreter/executor.py:354` — `create_executor()`, with a Docker→subprocess fallback already written.

---

### Option C: Runtime Snippet Registry in Postgres

Snippets live in a versioned DB table (`draft`/`approved`/`published`, author,
approver, content hash), authored by the LLM at runtime, approved in-app by a tenant
admin, executed in a warm sandbox pool.

✅ **Pros:**
- True multi-tenancy: each tenant's logic is row-scoped, invisible to other tenants,
  and needs no repo access.
- Seconds from "LLM drafts" to "admin approves" to "live" — the actual promise of
  LLM-authored behavior.
- Approval workflow, audit trail, and instant rollback (flip a status column) live
  naturally in the data model.
- Fits the existing persistence stack — `services/form_version.py` and the
  formdesigner migrations already establish the pattern.

❌ **Cons:**
- **Violates C8.** The user explicitly chose git-backed artifacts.
- Approval UI is net-new product surface — a review screen with a diff view.
- Executable code in a database is a high-value target: a SQL injection anywhere in
  the app escalates to RCE.
- No CI on snippets by default; correctness gates must be rebuilt in-app.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncpg` | Snippet table access | Already a formdesigner dependency |
| `pydantic` | Snippet + manifest models | Already core to the package |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/form_version.py` — existing versioning service to mirror.
- `packages/parrot-formdesigner/migrations/` — established migration pattern.

---

### Option D: Git-Backed Snippet Bundles + Capability-Scoped Warm Sandbox Pool ⭐

**The unconventional move: stop treating the snippet as a string of code, and treat
it as a signed, capability-declaring artifact whose executor is chosen by its tier.**

A snippet is a directory in the repo containing the Python source, an optional TS
source, and a **capability manifest** declaring exactly what it may touch. Three
things follow from that framing:

1. **The manifest, not the sandbox, is the primary security boundary.** The sandbox
   enforces; the manifest *declares*. A snippet asking only for tier-1 (pure form
   data) can be verified statically and — because it provably cannot do I/O — run in
   the cheapest executor. A tier-3/4 snippet gets the expensive one. **Cost scales
   with declared power, so the common case stays fast.**
2. **The git commit is the approval gate (C4).** Merged to `dev` = approved. Signed
   commits, CI, blame, and rollback come free. `handler_ref` continues to resolve
   through the existing registry — the loader simply registers git-backed snippets
   under the same refs, so `event_dispatcher.dispatch()` needs no knowledge of them.
3. **The Python and TS halves are siblings in one bundle**, generated from one intent,
   so drift between them is a reviewable diff rather than a mystery bug.

Execution ladder, chosen per snippet by declared tier:

| Tier | Capability | Executor | Budget |
|---|---|---|---|
| 1 `pure` | payload + schema, no I/O | Warm subprocess worker, no network namespace | ~5 ms |
| 2 `helpers` | + `datetime`/`math`/`re`/`decimal`, form metadata, auth context | Warm subprocess worker | ~10 ms |
| 3 `brokered` | + allowlisted HTTP, allowlisted queries, notifications — all host-mediated | Warm gVisor/Docker worker | ~200 ms |
| 4 `toolkit` | + registered `parrot` tools/agents | Warm gVisor/Docker worker, per-tenant opt-in | ~2 s |

Tiers 3 and 4 never get raw sockets. They call a **host broker** over the worker
channel; the broker checks the request against the manifest allowlist and performs
the I/O in the trusted process. A snippet cannot reach anything it did not declare,
and the declaration is in the diff a human approved.

Client side: the TS half runs in a **Web Worker** (C6) — no DOM by construction. It
receives field values via `postMessage` and returns patches the host applies. Per
**C7**, presentation-only logic is authoritative; anything with a Python counterpart
is re-run server-side at `onBeforeSubmit`.

✅ **Pros:**
- Honours **every** locked constraint C1–C9.
- Cost scales with declared power — the overwhelmingly common tier-1/2 case costs
  milliseconds, not the ~200 ms a uniform container policy would impose.
- Manifest gives the LLM a **machine-checkable contract**: generation that requests
  an undeclared capability fails CI rather than failing in production.
- Extends the FEAT-188 registry rather than replacing it — `dispatch()` is untouched,
  and hand-written `@register_form_event` handlers keep working unchanged.
- Full audit, rollback, and CI inherited from git at zero build cost.

❌ **Cons:**
- **Largest surface of the four.** Manifest model, loader, tier router, warm pool,
  host broker, worker protocol, TS bundle pipeline, LLM generation prompts.
- Inherits every C8 multi-tenancy limitation (see the tension note above, **OQ-1**).
- Warm pools are stateful infrastructure: health checks, recycling, poison-worker
  detection, and a cold-start path all need building.
- **gVisor is not installed** in this environment; tiers 3–4 need an ops prerequisite
  or a documented degraded mode.
- Two languages to generate, review, and keep in agreement.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| gVisor `runsc` | Kernel isolation for tiers 3–4 | **Absent here**; `SandboxTool._verify_installation()` will fail — see Code Context |
| `docker` (SDK) | Warm worker lifecycle | Docker **is** present; already used by `IsolatedExecutor` |
| stdlib `ast` | Manifest conformance check at CI time | No new dependency |
| stdlib `multiprocessing` / `asyncio.subprocess` | Tier-1/2 warm workers | Prefer `asyncio.subprocess` — async-first per `CONTEXT.md` |
| `esbuild` or `swc` | TS → JS worker bundle | Build-time only; never at request time |
| `pydantic` | Manifest, snippet, and worker-protocol models | Already core |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/eval/sandbox/base.py:79,166` — `Sandbox` / `SandboxProvider` ABCs. **The pool implements these**, so the eval harness and the form runtime share one abstraction.
- `packages/ai-parrot-tools/src/parrot_tools/sandboxtool.py:24,55` — `SandboxConfig` (`network="none"`, `max_memory`, `max_cpu`, `timeout`) and `SandboxTool`, both written for untrusted LLM code.
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/event_registry.py:73` — `register_form_event()`; the loader registers git-backed snippets through this same door.
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py:102` — `dispatch()`; requires **no change**.
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py:423` — `_LIFECYCLE_SCRIPT_TEMPLATE`, the existing client bridge where the Worker boot code is injected.
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py:53,104,171,203` — `FormEventBinding`, `FormEventsConfig`, `EventResolution`, `FormEventAbort`, all reused verbatim.

---

## Recommendation

**Option D**, because it is the only option that satisfies the locked constraint set —
but the reasoning worth recording is *why the tier ladder matters*, not merely that it
complies.

Options A and B are the two ends of one bad axis. A is fast and unsafe: it puts
attacker-influenced code in the process holding every tenant's credentials, and cannot
stop an infinite loop from pinning a worker. B is safe and slow: it charges every form
submit ~200 ms of container setup so that the rare privileged snippet can be contained.
Both price *all* snippets at the cost of the *most dangerous* one.

Option D's insight is that **snippet danger is declared, not uniform**. A snippet that
touches only `payload` and `schema` is statically verifiable as I/O-free and can run in
a cheap warm subprocess; only a snippet that asks for network or toolkit access needs a
kernel boundary. Since the overwhelming majority of real form logic is tier 1–2
("require this field when that total exceeds N", "compute a subtotal"), the common path
gets A's latency with B's safety, and B's cost is paid only where it is genuinely owed.

The manifest carries a second benefit specific to LLM authorship: it converts
"is this generated code safe?" — a judgement call a reviewer makes under time
pressure — into "does this code stay inside its declared capabilities?", which CI
answers mechanically. The human reviewer is then spending attention on *business
correctness*, which is where human judgement is actually required.

**What is being traded away, honestly:**

- **Multi-tenant agility.** C8 means tenant logic ships through a shared repo and a
  merged PR. Option C is materially better on this axis and is retained above for
  exactly that reason. If tenant-scoped runtime authoring later proves to be the real
  requirement, the tier router, manifest model, host broker, and warm pool from
  Option D all survive a swap to DB-backed storage — only the loader changes. **The
  recommendation is structured so that OQ-1 can be answered "wrong" without wasting
  the work.**
- **Delivery time.** This is the largest of the four options. The mitigation is the
  phasing in Parallelism Assessment: tiers 1–2 plus the manifest deliver most of the
  user value and can ship before the gVisor pool exists.
- **An ops prerequisite.** gVisor must be installed for tiers 3–4, or they run
  degraded on plain Docker with that reduction documented and enforced.

---

## Feature Description

### User-Facing Behavior

**Form author (via the LLM):** describes a rule in natural language — *"when
`order_total` is over 5000, make `approver_email` required and show a warning."* The
assistant generates a snippet bundle: a Python half for `onBeforeSubmit`, a TS half
for live client feedback, and a manifest declaring `tier: pure`. The author sees the
generated code, the declared capabilities, and a plain-language summary of what it may
touch.

**Approver (tenant admin / engineer):** receives a PR. The diff shows both halves and
the manifest. CI has already verified that the code stays inside its declared tier,
that the Python and TS halves are registered under the same `handler_ref`, and that
tests pass. Approval is a merge.

**End user:** fills the form. As `order_total` crosses 5000, the Worker-computed rule
fires instantly — no round trip — and `approver_email` becomes required with the
warning shown. On submit, the server re-runs the Python half authoritatively. If the
client was bypassed or tampered with, the server still rejects the submission.

**Failure, as experienced:** a snippet bound with `required=True` that errors or times
out produces a clear rejection with a safe message via `FormEventAbort`. Bound
otherwise, the failure is logged and the submission proceeds — the user sees nothing.

### Internal Behavior

**Load (server boot):** a loader walks the git-backed snippet directory, parses each
manifest, verifies the source hash, and registers a thin async adapter under the
snippet's `handler_ref` via the existing `register_form_event()`. From
`event_dispatcher.dispatch()`'s perspective these are ordinary registered handlers —
**the dispatcher is not modified**.

**Dispatch (request time):** `dispatch()` resolves the binding from
`FormSchema.events` exactly as today and awaits the adapter. The adapter builds a
serialisable projection of `FormEventContext` — deliberately *not* the live object;
`auth_context` is reduced to declared claims only — and hands it to the tier router.

**Tier routing:** tiers 1–2 go to a warm `asyncio.subprocess` worker with no network
namespace. Tiers 3–4 go to a warm gVisor/Docker worker acquired from a pool
implementing `SandboxProvider.acquire()`. The pool keeps workers warm, recycles them
after N invocations or on health-check failure, and cold-starts on miss.

**Brokered I/O:** a tier-3/4 snippet requesting outbound work sends a typed request
over the worker channel. The **host broker** — in the trusted process — validates it
against the manifest allowlist, performs the call, and returns the result. The worker
never holds a socket or a credential.

**Return:** the worker returns a serialised `EventResolution` (or a `FormEventAbort`
signal). The adapter validates it against the existing Pydantic model and returns it.
`dispatch()` applies `payload` replacement and `schema_overrides` through
`apply_schema_overrides()` unchanged.

**Client path:** the renderer's existing `_LIFECYCLE_SCRIPT_TEMPLATE` gains a Worker
boot block. The pre-built JS bundle is served, spawned as a Web Worker, and fed field
changes by `postMessage`. It returns patches (visibility, computed values, hints); the
host page applies them. The Worker has no DOM and no same-origin fetch capability.

### Edge Cases & Error Handling

| Condition | Behavior |
|---|---|
| Snippet exceeds CPU/wall/memory budget | Worker killed, treated as failure, **C9** policy applies |
| Snippet raises | Same as above; original traceback logged internally, never surfaced to the end user |
| Snippet raises `FormEventAbort` | Controlled flow — re-raised intact, converted to HTTP by `FormAPIHandler`. `onError` deliberately **not** fired, matching FEAT-188 |
| Return value fails `EventResolution` validation | Treated as failure under **C9**; never partially applied |
| Snippet requests an undeclared capability | Broker denies, logs a security event, snippet fails. CI should have caught this earlier |
| Warm pool exhausted | Bounded queue wait, then timeout → **C9**. Never unbounded |
| gVisor absent | Tier 1–2 unaffected. Tiers 3–4 refuse to load at boot, or run degraded on Docker if explicitly configured — never silently |
| Worker poisoned / unhealthy | `health_check()` fails, worker destroyed and replaced; request retried once at most |
| Python and TS halves disagree | Server wins. Client patch is discarded and the divergence logged as an authoring bug |
| Client tampered / Worker blocked | Server re-runs authoritatively. Presentation-only (C7) logic degrades to unstyled but correct |
| Snippet file edited without manifest update | Hash mismatch at load → refuse to register; fail loudly at boot, not at request time |
| Two snippets claim one `handler_ref` | `register_form_event()` already raises on duplicate registration — surfaces as a boot failure |
| Binding `required=True`, snippet missing | Existing FEAT-188 `RuntimeError` behavior, unchanged |

---

## Capabilities

### New Capabilities
- `form-code-snippet-model`: Pydantic models for a snippet bundle, its capability manifest, and the tier enumeration.
- `form-code-snippet-loader`: Git-backed discovery, hash verification, and registration of snippets into the FEAT-188 registry.
- `form-code-sandbox-pool`: Warm worker pool implementing `SandboxProvider`, with health checks, recycling, and cold-start.
- `form-code-tier-router`: Routes a snippet to the cheapest executor satisfying its declared tier.
- `form-code-host-broker`: Trusted-process mediator for tier-3/4 outbound calls, enforcing manifest allowlists.
- `form-code-worker-protocol`: Serialisation contract between host and worker for context, resolution, abort, and broker calls.
- `form-code-client-worker`: Web Worker runtime and `postMessage` patch protocol in the HTML5 renderer.
- `form-code-ts-bundler`: Build-time TS → JS bundling for the client half.
- `form-code-llm-authoring`: Prompts and toolkit surface for generating conformant snippet bundles.
- `form-code-ci-conformance`: CI gate asserting each snippet stays inside its declared capabilities.

### Modified Capabilities
- `formbuilder-database` — `FormSchema.events` bindings may now reference git-backed snippets. No schema change; `handler_ref` semantics widen.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_formdesigner/services/event_dispatcher.py` | **depends on** | Intentionally **unmodified** — snippets arrive as ordinary registered handlers |
| `parrot_formdesigner/services/event_registry.py` | depends on | Loader calls `register_form_event()`; duplicate-ref guard reused as-is |
| `parrot_formdesigner/core/events.py` | extends | `FormEventBinding.required` semantics widen from "handler missing" to also cover "handler failed" (**C9**) — see Open Questions |
| `parrot_formdesigner/core/schema.py` | depends on | `FormSchema.events` unchanged; only `handler_ref` resolution widens |
| `parrot_formdesigner/renderers/html5.py` | modifies | `_LIFECYCLE_SCRIPT_TEMPLATE` gains Worker boot; existing remote-fetch bridge preserved |
| `parrot/eval/sandbox/base.py` | depends on | Pool implements the existing `Sandbox` / `SandboxProvider` ABCs |
| `parrot_tools/sandboxtool.py` | depends on | `SandboxConfig` / `SandboxTool` reused for tiers 3–4 |
| Deployment / ops | **new dependency** | gVisor `runsc` for tiers 3–4; warm pool is a new stateful component to size and monitor |
| CI | extends | New conformance gate; TS bundle build step |
| `pyproject.toml` (formdesigner) | modifies | New optional extra for sandbox dependencies |

**Breaking changes**: none intended. Every existing `@register_form_event` handler and
every existing `FormSchema.events` binding continues to work unchanged.

---

## Code Context

### User-Provided Code

No code was pasted by the user during discovery. The brief was prose; all references
below were verified by reading the codebase.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py:32
FormEventName = Literal[
    "onBeforeOpen", "onSchemaLoaded", "onBeforeSubmit", "onAfterSubmit", "onError",
]

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py:53
class FormEventBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handler_ref: str  # pattern: ^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$
    remote: bool = False    # line 76 — HTML5 client bridges via fetch
    required: bool = False  # line 77 — if True and handler missing -> 500

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py:104
class FormEventsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    onBeforeOpen: FormEventBinding | None = None
    onSchemaLoaded: FormEventBinding | None = None
    onBeforeSubmit: FormEventBinding | None = None
    onAfterSubmit: FormEventBinding | None = None
    onError: FormEventBinding | None = None

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py:124
class FormEventContext(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    event: FormEventName
    form_id: str
    tenant: str | None
    auth_context: Any                              # AuthContext; Any avoids circular import
    payload: Mapping[str, Any] | None = None       # submit only
    schema_dump: Mapping[str, Any] | None = None   # open / schema_loaded only
    error: BaseException | None = None             # onError only
    user_message: str | None = None                # onError mutable
    extra: dict[str, Any] = Field(default_factory=dict)

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py:171
class EventResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: Mapping[str, Any] | None = None
    schema_overrides: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] | None = None
    user_message: str | None = None

# From packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py:203
class FormEventAbort(Exception):
    def __init__(self, reason: str, *, user_message: str, status_code: int = 403) -> None: ...

# From packages/parrot-formdesigner/src/parrot_formdesigner/services/event_registry.py:73
def register_form_event(
    handler_ref: str, *, tenant: str | None = None,
) -> Callable[[FormEventHandler], FormEventHandler]: ...
# Handler signature: async def h(ctx: FormEventContext) -> EventResolution | None

# From packages/parrot-formdesigner/src/parrot_formdesigner/services/event_registry.py:149
def get_form_event(handler_ref: str, *, tenant: str | None = None) -> FormEventHandler: ...

# From packages/parrot-formdesigner/src/parrot_formdesigner/services/event_registry.py:180
def list_form_events(tenant: str | None = None) -> list[tuple[str | None, str]]: ...

# From packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py:69
def apply_schema_overrides(base: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]: ...
# Shallow merge, top-level keys only (spec §7 MVP decision)

# From packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py:102
async def dispatch(
    event: FormEventName, *, form: FormSchema, request: web.Request,
    tenant: str | None, auth_context: Any,
    payload: Mapping[str, Any] | None = None,
    schema_dump: Mapping[str, Any] | None = None,
    error: BaseException | None = None,
) -> EventResolution: ...

# From packages/ai-parrot/src/parrot/eval/sandbox/base.py:42
class SandboxSpec(BaseModel):
    kind: Literal["docker", "in_memory_state", "mock_api", "noop"] = "noop"
    image: str | None = None
    setup: list[str] = Field(default_factory=list)
    seed_state: dict[str, Any] | None = None
    git_truncate_after: str | None = None

# From packages/ai-parrot/src/parrot/eval/sandbox/base.py:60
class ExecResult(BaseModel):
    exit_code: int
    stdout: str = ""
    stderr: str = ""

# From packages/ai-parrot/src/parrot/eval/sandbox/base.py:79
class Sandbox(ABC):
    async def __aenter__(self) -> "Sandbox": ...            # line 95
    async def __aexit__(self, *exc: Any) -> None: ...       # line 104
    async def reset(self, seed_state: dict[str, Any] | None) -> None: ...  # line 113
    async def health_check(self) -> bool: ...               # line 122
    async def snapshot(self) -> dict[str, Any]: ...         # line 131
    async def exec(self, cmd: list[str]) -> ExecResult: ... # line 139

# From packages/ai-parrot/src/parrot/eval/sandbox/base.py:166
class SandboxProvider(ABC):
    async def acquire(self, spec: SandboxSpec) -> Sandbox: ...   # line 174
    async def release(self, sandbox: Sandbox) -> None: ...       # line 186

# From packages/ai-parrot-tools/src/parrot_tools/sandboxtool.py:24
@dataclass
class SandboxConfig:
    runtime: str = "runsc"
    network: str = "none"
    max_memory: str = "2G"
    max_cpu: float = 2.0
    timeout: int = 30
    python_image: str = "python:3.11-slim"
    enable_gpu: bool = False
    mount_paths: List[str] = field(default_factory=list)

# From packages/ai-parrot-tools/src/parrot_tools/sandboxtool.py:55
class SandboxTool(AbstractTool):
    def _verify_installation(self): ...       # line 99  — FAILS without runsc
    def _create_sandbox_container(self, code: str, session_id: str): ...  # line 186

# From packages/ai-parrot-tools/src/parrot_tools/codeinterpreter/executor.py:354
def create_executor(use_docker: bool = True, **kwargs) -> IsolatedExecutor | SubprocessExecutor: ...
# Already falls back Docker -> subprocess when Docker is unavailable
```

#### Verified Imports

```python
# Confirmed to resolve:
from parrot_formdesigner.core.events import (          # core/events.py
    FormEventName, FormEventBinding, FormEventsConfig,
    FormEventContext, EventResolution, FormEventAbort,
    VisitEventName, VisitEventContext,
)
from parrot_formdesigner.services.event_registry import (   # services/event_registry.py:73,149,180
    register_form_event, get_form_event, list_form_events,
)
from parrot_formdesigner.services.event_dispatcher import (  # services/event_dispatcher.py:69,102,205
    apply_schema_overrides, dispatch, dispatch_visit,
)
from parrot.eval.sandbox.base import (                  # eval/sandbox/base.py:42,60,79,166
    SandboxSpec, ExecResult, Sandbox, SandboxProvider,
)
from parrot_tools.sandboxtool import SandboxConfig, SandboxTool          # sandboxtool.py:24,55
from parrot_tools.codeinterpreter.executor import create_executor        # executor.py:354
```

#### Key Attributes & Constants

- `FormSchema.events` → `FormEventsConfig | None = None` (`core/schema.py:368`; documented `core/schema.py:342-347`)
- `FormEventBinding.required` → `bool = False` — **today means "handler missing → RuntimeError"**, not "handler failed" (`core/events.py:77`)
- `FormEventBinding.remote` → `bool = False` — HTML5 client bridges via `fetch` (`core/events.py:76`)
- `SandboxConfig.network` → `str = "none"` — network disabled by default (`sandboxtool.py:27`)
- `SandboxConfig.runtime` → `str = "runsc"` — gVisor by default (`sandboxtool.py:26`)
- `_EVENT_REGISTRY` → `dict[tuple[str | None, str], FormEventHandler]` — module-level, keyed `(tenant, handler_ref)` (`event_registry.py:66`)
- `_LIFECYCLE_SCRIPT_TEMPLATE` → client bridge with `EVENTS_CONFIG`, `emit()`, `bridge()` (`renderers/html5.py:423`)
- Remote event endpoint → `/api/v1/{tenant}/forms/{form_uid}/events/{eventName}` (`renderers/html5.py:449`), tenant-qualified per FEAT-421 (`html5.py:586`)
- `_VISIT_PRE_HOOKS` → `frozenset({"visit.onArrival"})` (`event_dispatcher.py:61`)

#### Verified Environment Facts

- **`runsc` (gVisor) is NOT installed** on the development machine — verified via `command -v runsc`. `SandboxTool._verify_installation()` (`sandboxtool.py:99`) will fail. Tiers 3–4 require an ops prerequisite.
- **`docker` IS installed** — verified via `command -v docker`. `IsolatedExecutor` is usable today.

### Does NOT Exist (Anti-Hallucination)

Searched for and confirmed absent across `packages/` (excluding `build/lib`):

- ~~`CodeSnippet`~~ — 0 hits. No snippet model exists anywhere.
- ~~`CapabilityManifest` / `capability_manifest`~~ — 0 hits. The tier/manifest concept is entirely new.
- ~~`snippet_registry`~~ — 0 hits. Only `event_registry` (handler refs) and `callback_registry` exist.
- ~~`SandboxedHandler`~~ — 0 hits.
- ~~`code_sandbox`~~ — 0 hits in the formdesigner package. Sandboxing lives only in `parrot_tools` and `parrot.eval`, neither wired to forms.
- ~~`onFieldChange`~~ — 0 hits. **Not** a member of `FormEventName`; field-level events do not exist (excluded by **C2**).
- ~~`onBeforePartialSave` / `onAfterPartialSave`~~ — 0 hits. Partial saves (`services/partial_saves.py`, `PartialSaveStore` at line 24) dispatch **no** lifecycle events at all (excluded by **C2**).
- ~~`parrot_formdesigner.services.event_dispatcher.dispatch_snippet`~~ — does not exist. Only `dispatch()` (line 102) and `dispatch_visit()` (line 205).
- ~~`RestrictedPython` / `asteval` / `simpleeval` / `wasmtime` / `pyodide`~~ — **not** dependencies of this repo. Any option using them adds a new dependency.
- ~~A Web Worker in the HTML5 renderer~~ — does not exist. `_LIFECYCLE_SCRIPT_TEMPLATE` only does `fetch`-based remote bridging; there is no client-side execution sandbox.
- ~~A TypeScript build step in `parrot-formdesigner`~~ — does not exist. No bundler is configured in the package.

---

## Parallelism Assessment

- **Internal parallelism**: **High.** The feature decomposes into four largely
  independent tracks that meet only at Pydantic contracts:
  1. **Contracts & loader** — manifest/snippet models, git discovery, registry
     adaptation. Touches `core/`, `services/`. *Must land first*; everything depends
     on the models.
  2. **Server sandbox** — tier router, warm pool, host broker, worker protocol. Pure
     backend, new modules, no shared files with track 3.
  3. **Client runtime** — Web Worker bridge, `postMessage` patch protocol, TS bundler.
     Touches `renderers/html5.py` and build config only.
  4. **LLM authoring & CI** — generation prompts, toolkit surface, conformance gate.
     Depends on track 1's contracts, not on 2 or 3.
  Tracks 2, 3, and 4 can run concurrently in separate worktrees once track 1 merges.

- **Cross-feature independence**: **Mostly independent, with one watch item.**
  In-flight formbuilder specs and their overlap:
  - `formbuilder-formschema-persistency` (FEAT-457, 15 tasks) — **watch item**. If it
    changes how `FormSchema` (and therefore `events`) is persisted, track 1 shares
    `core/schema.py` with it. Contact before touching that file.
  - `formbuilder-fieldtype-cardinality` (FEAT-456, 7 tasks) — touches field types, not
    events. No overlap expected.
  - `formbuilder-database`, `formbuilder-list-created-forms` — no overlap.
  Shared files to coordinate: `core/schema.py`, `core/events.py`, `renderers/html5.py`.

- **Recommended isolation**: **mixed**

- **Rationale**: Track 1 is a hard sequential prerequisite and is small — it should run
  alone in the feature worktree so its contracts stabilise before anything builds on
  them. Once merged, tracks 2/3/4 touch disjoint file sets (backend sandbox modules,
  the renderer, prompts+CI respectively) and gain real wall-clock from separate
  worktrees. Forcing all four sequentially would serialise roughly three weeks of
  independent work for no isolation benefit; forcing all four in parallel from day one
  would have three tracks building against contracts still in flux.

---

## Open Questions

- [ ] **OQ-1 (blocking, highest impact)** — Does git-backed storage (**C8**) survive contact with the multi-tenant requirement? A merged PR per tenant rule means turnaround measured in CI-and-review time, tenant logic visible to all repo readers, and isolation by directory convention rather than row-level access control. Option C exists precisely for this. Option D is structured so a later swap costs only the loader — but the answer should be deliberate, not discovered in production. — *Owner: Jesus Lara*
- [ ] **OQ-2** — Partial saves were named in the original brief but excluded by **C2**. Confirm this is a deliberate v1 deferral rather than an oversight. `PartialSaveStore` (`services/partial_saves.py:24`) currently dispatches no events, so adding them later is additive and non-breaking. — *Owner: Jesus Lara*
- [ ] **OQ-3** — **C9** reuses `FormEventBinding.required`, but its current meaning is "handler *missing* → `RuntimeError`" (`core/events.py:77`), not "handler *failed*". Widen `required` to cover both, or add a separate `on_failure: Literal["abort", "continue"]`? Widening is smaller but conflates two distinct conditions and silently changes behavior for existing bindings. — *Owner: Jesus Lara*
- [ ] **OQ-4** — gVisor is absent in this environment. Is installing `runsc` an acceptable deployment prerequisite for tiers 3–4, or must those tiers run degraded on plain Docker with the weaker boundary documented? — *Owner: Jesus Lara / ops*
- [ ] **OQ-5** — How much of `FormEventContext` crosses the sandbox boundary? `auth_context` is typed `Any` and is a live `AuthContext` object (`core/events.py:128`); it cannot be handed to a worker as-is. Proposal: project it down to manifest-declared claims only. Which claims are safe to expose at each tier? — *Owner: Jesus Lara*
- [ ] **OQ-6** — Warm pool sizing and recycling policy: workers per tier, invocations before recycle, queue depth before a submit is failed rather than queued. Needs a load-profile answer, not a guess. — *Owner: Jesus Lara / ops*
- [ ] **OQ-7** — Per **C7**, client code is authoritative for "client-only concerns". Where exactly is that line? A Web Worker cannot touch the DOM, so purely-visual logic must return patches the host applies — meaning the *host* decides what a patch may change. That allowlist needs defining. — *Owner: Jesus Lara*
- [ ] **OQ-8** — When the LLM generates a Python/TS pair from one intent, what enforces that they agree? CI equivalence tests over shared fixtures, generation from a single intermediate representation, or accepted drift with the server as tiebreaker? — *Owner: Jesus Lara*
