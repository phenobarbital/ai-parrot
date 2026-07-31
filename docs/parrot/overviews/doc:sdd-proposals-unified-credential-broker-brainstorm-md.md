---
type: Wiki Overview
title: 'Brainstorm: Unified Credential Broker — one declarative per-user auth abstraction
  for tools & MCP'
id: doc:sdd-proposals-unified-credential-broker-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Connecting a tool or MCP server that needs **per-user** authentication currently
relates_to:
- concept: mod:parrot.auth.audit
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.oauth2.workiq_provider
  rel: mentions
- concept: mod:parrot.human.suspended_store
  rel: mentions
- concept: mod:parrot.integrations.mcp.fireflies_a2a
  rel: mentions
- concept: mod:parrot.mcp.client
  rel: mentions
- concept: mod:parrot.security.audit_ledger
  rel: mentions
- concept: mod:parrot.services.vault_token_sync
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Unified Credential Broker — one declarative per-user auth abstraction for tools & MCP

**Date**: 2026-06-29
**Author**: Jesus
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Connecting a tool or MCP server that needs **per-user** authentication currently
requires bespoke code per integration. FEAT-263 added per-tool convenience methods
on `A2AServer` — `wire_fireflies_resolver()`, `wire_workiq_resolver()`,
`wire_jira_resolver()` — each a thin wrapper over a *generic*
`register_credential_resolver(provider_id, resolver)`. The proliferation creates the
false impression that **every new MCP needs a new method**, and it hides four pieces
of genuine design debt:

1. **The resolver registry is trapped inside `A2AServer`.** `_credential_resolvers`
   and the gate (`_try_invoke_with_gate`) live in
   `packages/ai-parrot-server/src/parrot/a2a/server.py`. No other surface can reach
   it.
2. **There is no resolution seam in the core `agent.ask()` / ReAct tool loop.**
   Nothing resolves a tool's `credential_provider` during normal chat. The MSAgentSDK
   path is therefore *uncabled*: the `_resolver_var` ContextVar set in
   `parrot/integrations/msagentsdk/agent.py` is **dead — nothing reads it**, and the
   per-user `CredentialRequired → OAuthCard` path never fires for agent-internal tool
   calls.
3. **Resolver *construction* is hand-wired per provider** — vault keys, OBO scopes,
   OOB capture URLs are coded into call sites rather than declared as config.
4. **The MSAgentSDK BF Token Service OBO exchange is a documented stub**
   (`_obo_exchange` returns the original token), and there are **two** divergent
   `AuditLedger` implementations.

**Affected:** integration developers (must write/maintain glue per MCP), end users
(per-user tools silently never gate on the chat surface), and ops (two audit ledgers,
no single config source).

**Why now:** the motivating task — incorporate Fireflies.ai (static-key MCP) and
work.iq (OBO MCP) into `examples/msagent/server.py` with per-user auth — exposed that
the FEAT-263 verticals only function through `A2AServer`, not through the
`MSAgentSDKWrapper` chat path the example uses.

## Constraints & Requirements

- **Adding a new MCP/tool on an existing auth mechanism (OBO, OAuth2 3LO, static key)
  must be a CONFIG entry, not new code.** A genuinely-new auth mechanism is one new
  resolver *strategy* — the irreducible minimum.
- **One surface-agnostic resolution seam** consulted by the core tool loop, so the
  same `tool.credential_provider` resolves identically on chat, A2A, and CLI.
- **Each surface renders the single `CredentialRequired`/`NeedsAuth` signal its own
  way**: A2A → suspend + consent link; MSAgentSDK → Adaptive Card (static key) or
  OAuthCard (OAuth/OBO); CLI → print URL.
- **Secrets never enter the LLM-visible plane.** Resolved credentials must not appear
  in tool args/schema, model context, or the conversational transcript. The existing
  `OutputScrubber` stays the sole outbound redaction seam.
- **Config is declared on the AgentDefinition** (each agent carries its own
  credentialed-provider config; broker built at `configure()`), with an **in-package**
  YAML bots-manifest loader analogous to `env/integrations_bots.yaml`.
- **Credentials are reusable across surfaces** — vault keyed by a canonical user identity
  (Entra OID/email), so consent given on A2A is honored in chat and vice-versa.
- **Missing credential must request AND auto-resume** — the surface prompts (card/sign-in)
  and the operation resumes automatically on consent completion; the user does not re-type.
- **Replace** the `A2AServer` embedded registry/gate with broker calls (the broker is
  the backend), preserving the A2A suspend/resume happy path and FEAT-263 acceptance.
- **Canonical OBO** = `O365Interface.acquire_token_on_behalf_of` + `VaultTokenSync`
  (works today). **Canonical audit** = KMS/HMAC-signed
  `parrot.security.audit_ledger`; retire `parrot.auth.audit`.
- async/await throughout; Pydantic models; `self.logger`; no LangChain; no `requests`/
  `httpx` (use `aiohttp`).

---

## Options Explored

### Option A: Surface-agnostic `CredentialBroker` + a single core tool-loop seam (declarative)

A standalone `CredentialBroker` owns a `provider_id → CredentialResolver` registry,
built once from **declarative config** (per-agent on the AgentDefinition, plus an
optional YAML manifest block). A `CredentialResolverFactory` maps an `auth:` kind
(`obo | oauth2 | static_key | mcp`) to a fully-constructed resolver strategy — so a
new integration on an existing kind is just a config line.

The broker is consulted by **one seam in the core tool-execution path**
(`AbstractTool.execute()` / `ToolManager.execute_tool`, between arg-validation and the
`_execute()` call). When a tool declares `credential_provider`, the broker resolves
the per-user credential, sets it on a **per-call ContextVar** that the tool reads via a
helper (`current_credential()`), appends a signed `AuditLedgerEntry`, then runs
`_execute()`. On a miss it raises a surface-neutral
`CredentialRequired(provider, auth_url, auth_kind)`. Each surface catches that one
signal and renders it: A2A suspends + returns the consent link (existing
`SuspendedExecutionStore` + nonce + `resume_from_oauth_callback`); MSAgentSDK emits an
Adaptive Card (static key) or OAuthCard (OAuth/OBO); CLI prints the URL.

`A2AServer`'s embedded registry and `_try_invoke_with_gate` are **replaced** by broker
calls; the `wire_*` methods are deleted. MCP-backed tools get their per-user token via
the broker feeding `MCPClientConfig.header_provider` / `token_supplier` / `user_id`
(FEAT-262 machinery), so no separate MCP auth path is needed.

✅ **Pros:**
- New MCP on an existing auth kind = **config only**; new auth kind = one strategy.
- **Fixes the uncabled chat path** — agent-internal tool calls finally gate per-user.
- One signal, N renderers — surfaces stay thin and consistent.
- Secrets isolated on a ContextVar; reuses `OutputScrubber` for egress.
- Single canonical audit ledger; single canonical OBO strategy.

❌ **Cons:**
- **Largest blast radius** — touches core `AbstractTool.execute()`/`ToolManager`,
  which every tool flows through. Requires careful backward-compat (tools without
  `credential_provider` must be unaffected).
- Replacing the A2A gate risks regressing the in-flight A2A happy path + FEAT-263
  acceptance if not adaptered carefully.
- AgentDefinition gains a new credential-config field (none exists today).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2) | `ProviderCredentialConfig`, `CredentialRequired` payload, broker config models | already a core dep |
| `aiohttp` | OOB capture endpoint, MCP HTTP transport, O365 OBO calls | mandated transport |
| `msal` / `azure-identity` | OBO exchange via `O365Interface` | already in `interfaces/o365.py` |
| `redis.asyncio` | `SuspendedExecutionStore` backing (A2A resume) | existing |
| `contextvars` (stdlib) | per-call credential injection | mirrors `_current_pctx` pattern |
| `hmac`/`hashlib` (stdlib) | `LocalHMACSigner` dev fallback for the KMS ledger | existing in `security/audit_ledger.py` |

🔗 **Existing Code to Reuse:**
- `parrot/auth/credentials.py` — `CredentialResolver` ABC + `OAuthCredentialResolver`,
  `StaticCredentialResolver` (the strategy base + two strategies).
- `parrot/auth/oauth2/workiq_provider.py` — `WorkIQOBOCredentialResolver` (the `obo`
  strategy, working today).
- `parrot/integrations/mcp/fireflies_a2a.py` — `FirefliesCredentialResolver` (the
  `static_key` strategy).
- `parrot/security/audit_ledger.py` — `AuditLedger` (canonical, KMS/HMAC-signed).
- `parrot/tools/abstract.py` — `execute()`/`_execute()` seam, `OutputScrubber`,
  `AbstractToolArgsSchema._context_fields`.
- `parrot/tools/manager.py` — `execute_tool()` + `exec_kwargs` propagation + `clone()`.
- `parrot/mcp/client.py` — `MCPClientConfig.header_provider`/`token_supplier`/`user_id`
  for per-user MCP token injection.
- `parrot/human/suspended_store.py` + `A2AServer.resume_from_oauth_callback` — A2A
  suspend/resume (surface-specific rendering of `NeedsAuth`).

---

### Option B: Shared registry only — extract the broker but keep resolution in the surfaces

Lift `_credential_resolvers` out of `A2AServer` into a standalone `CredentialBroker`
(registry + factory + config), but **do not touch `AbstractTool`/`ToolManager`**. Each
surface keeps its own resolution call: `A2AServer._try_invoke_with_gate` consults the
broker, and a **new MSAgentSDK hook** consults it (finally reading `_resolver_var`).

✅ **Pros:**
- Much smaller blast radius — core tool loop untouched; lower regression risk.
- Still removes the `wire_*` proliferation and makes config declarative.
- Incremental: the core seam (Option A) can land later as a follow-up.

❌ **Cons:**
- **Does not fully fix the uncabled chat path** — only gates tools the surface invokes
  explicitly (A2A structured `data["tool"]`); agent-internal ReAct tool calls during
  `agent.ask()` still bypass the gate unless each surface re-implements interception.
- Resolution logic is **duplicated per surface** (A2A hook + MSAgentSDK hook + future
  CLI), re-growing the fragmentation in a new place.
- Two code paths to keep in sync; the "one seam" guarantee is not met.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2) | broker config + `CredentialRequired` | core dep |
| `redis.asyncio` | A2A suspend store | existing |

🔗 **Existing Code to Reuse:**
- Same resolver strategies as Option A.
- `parrot/integrations/msagentsdk/agent.py` `_resolver_var` (finally given a consumer).
- `A2AServer` gate (re-pointed at the broker rather than replaced wholesale).

---

### Option C: MCP-native auth — push resolution into `MCPClientConfig` (unconventional)

Treat every credentialed integration as an **MCP server** and resolve per-user
credentials entirely through the FEAT-262 MCP auth machinery:
`MCPClientConfig.header_provider(context)` + `token_supplier` + per-user `user_id`,
backed by a thin `provider_id → resolver` map. No tool-loop seam, no `credential_provider`
gate — the credential is injected as an HTTP header at MCP call time, keyed by the
`ReadonlyContext`'s user.

✅ **Pros:**
- Reuses an **already-built, FEAT-262-tested** per-user MCP auth path
  (`get_headers()` precedence, OAuth2 presets, `user_id` scoping).
- Zero changes to `AbstractTool`/`ToolManager`; credential never leaves the transport
  layer (strong secret hygiene by construction).
- Naturally declarative — MCP servers are already config objects.

❌ **Cons:**
- **Only covers MCP-backed tools.** Native tools (`jira_connect_tool`, the work.iq
  *adapter*, any `AbstractTool` subclass) are left out — so it does not generalize to
  "any tool needing per-user auth," failing the core requirement.
- No surface-neutral `NeedsAuth` signal — the consent/sign-in UX (Adaptive Card,
  OAuthCard, A2A suspend) has nowhere natural to hook; a missing credential surfaces as
  an MCP transport error, not a consent prompt.
- Static-key OOB capture and Entra OBO sign-in don't map cleanly to "just set a
  header" without a resolver that can also emit an auth URL.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | MCP HTTP transport + header injection | existing |
| `pydantic` | `MCPClientConfig` / `MCPOAuth2Config` | existing FEAT-262 |

🔗 **Existing Code to Reuse:**
- `parrot/mcp/client.py` — `MCPClientConfig` (`header_provider`, `token_supplier`,
  `user_id`, `oauth2`), `get_headers()`.
- `parrot/tools/mcp_mixin.py` — `add_mcp_server()`.

---

## Recommendation

**Option A** is recommended. It is the only option that satisfies the two hard
requirements together: *(a)* adding an MCP on an existing auth kind becomes config-only,
and *(b)* there is **one** surface-agnostic resolution seam so per-user gating works
identically on the chat path, A2A, and CLI — fixing the uncabled MSAgentSDK chat path
that motivated this work.

Option B is the safer increment but explicitly **fails requirement (b)**: it leaves
agent-internal tool calls ungated and re-duplicates resolution per surface, which is the
same fragmentation we are trying to kill — just relocated. Option C reuses the most
existing code and has the best secret hygiene, but **only covers MCP-backed tools**, so
native credentialed tools fall through; it cannot be the general abstraction.

What Option A trades off, accepted deliberately: a **high blast radius** in
`AbstractTool.execute()`/`ToolManager` and the risk of replacing the A2A gate. We accept
this because the seam is additive and gated on the *presence* of `credential_provider`
(tools without it are wholly unaffected, preserving every existing tool's behavior), and
because the A2A replacement is done as an **adapter that re-points the existing gate at
the broker** — the suspend/nonce/`resume_from_oauth_callback` flow and FEAT-263
acceptance tests stay green. Option B's seam is, in effect, Phase 2 of Option A, so if
scope must shrink we can land the broker + A2A adapter first and add the core seam
second without rework.

---

## Feature Description

### User-Facing Behavior

- **Integration developer**: declares a credentialed provider once, in the agent's
  definition (or a YAML manifest), e.g.
  `credentials: { workiq: {auth: obo, source: o365, scope: "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"}, fireflies: {auth: static_key, vault_key: "fireflies:api_key", capture_url: "..."} }`.
  A tool declares `credential_provider = "workiq"`. **No wiring method, no construction
  code.** Adding `jira: {auth: oauth2, provider: jira}` is another config line.
- **End user (work.iq / OBO)**: asks something that triggers the work.iq tool; if not
  signed in, receives an **OAuthCard** (MSAgentSDK) or a consent link (A2A); one Entra
  sign-in covers o365 + work.iq; the answer arrives after consent.
- **End user (Fireflies / static key)**: on first use receives an **Adaptive Card** with
  an OOB capture link to paste their Fireflies API key; subsequent calls just work.
- **Secrets are never visible** in the chat, the tool's arguments, or logs — only a
  `key_fingerprint` is recorded.

### Internal Behavior

1. At `agent.configure()`, the agent builds a `CredentialBroker` from its declarative
   credential config via a `CredentialResolverFactory` (auth-kind → strategy), and hands
   it to the `ToolManager`.
2. On a tool call, the single seam in `AbstractTool.execute()` / `ToolManager` checks
   `tool.credential_provider`. If set, it calls `broker.resolve(provider, channel,
   user_id, **ctx)`.
3. **Resolved** → the credential is placed on a per-call ContextVar (read by the tool via
   `current_credential()`); `AuditLedger.append(key_fingerprint=…)` records the
   invocation; `_execute()` runs; `OutputScrubber` redacts egress.
4. **Missing** → the broker returns `NeedsAuth(auth_url, auth_kind)`; the seam raises
   `CredentialRequired(provider, auth_url, auth_kind)`. The active **surface** catches it
   and renders the right prompt (A2A suspend+link / Adaptive Card / OAuthCard / CLI URL).
5. On a miss the operation is **suspended** (state keyed by nonce; on chat, a Bot
   Framework `ConversationReference` is stored too). After consent the surface's resume
   trigger fires — A2A `resume_from_oauth_callback`; on MSAgentSDK the
   `signin/verifyState`/`signin/tokenExchange` invoke (OAuth/OBO) or the `store_key`
   capture route (static key) — which re-runs the tool and **proactively delivers** the
   result. The user never re-types.
6. MCP-backed tools resolve the same way; the broker supplies the token to
   `MCPClientConfig.header_provider`/`token_supplier` so the MCP call carries the
   per-user bearer.

### Edge Cases & Error Handling

- **No identity** + credentialed tool → fail closed; never fall back to a service
  identity (preserve FEAT-263 invariant).
- **Tool with `credential_provider` but no matching broker config** → fail closed with a
  clear "no resolver for provider" error (no silent skip).
- **OBO exchange fails / Entra token absent** → treat as missing credential → re-prompt
  (no crash).
- **Static-key surface that cannot render a card** (e.g. plain channel) → fall back to a
  plain-text capture link.
- **Suspend TTL expiry** → graceful re-prompt, no crash (existing A2A behavior).
- **Backward compat** — a tool without `credential_provider` skips the broker entirely;
  `execute()` behavior is byte-for-byte unchanged.
- **Two AuditLedgers** — `parrot.auth.audit` is migrated to the canonical
  `parrot.security.audit_ledger`; the BF resolver's `.record()` calls are re-pointed at
  `.append()`.

---

## Capabilities

### New Capabilities
- `unified-credential-broker`: surface-agnostic `CredentialBroker` + `CredentialResolverFactory`
  (auth-kind → strategy), built declaratively from agent/manifest config.
- `tool-credential-seam`: a single per-call credential-resolution hook in
  `AbstractTool.execute()`/`ToolManager`, with ContextVar injection and
  `current_credential()` helper.
- `credential-required-signal`: surface-neutral `CredentialRequired(provider, auth_url,
  auth_kind)` + per-surface renderers (A2A suspend, MSAgentSDK Adaptive/OAuth card, CLI).
- `agent-credential-config`: declarative `credentials:` block on the AgentDefinition (+
  in-package YAML manifest loader).
- `canonical-identity-mapping`: normalize A2A (`from.email`/`oid`) and MSAgentSDK
  (`aad_object_id`) to one canonical key (Entra OID/email) so vault-stored credentials
  are **reusable across surfaces**; `channel` is audit context, not a storage scope.
- `chat-path-suspend-resume`: store a Bot Framework `ConversationReference` + suspended
  tool call keyed by nonce; `signin/verifyState`/`signin/tokenExchange` (OAuth/OBO) and
  the `store_key` capture route (static key) trigger an auto-resume that re-runs the tool
  and proactively delivers the result — parity with A2A `resume_from_oauth_callback`.

### Modified Capabilities
- `copilot-a2a-percredential` (FEAT-263): `A2AServer` gate replaced by broker calls;
  `wire_*` methods removed; verticals reused as broker strategies.
- `auth-obo-msagentsdk` (FEAT-261): `_resolver_var`/BF path superseded by the broker;
  OBO standardized on `O365Interface.acquire_token_on_behalf_of`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/auth/credentials.py` | extends | host `CredentialBroker`, `CredentialResolverFactory`, `CredentialRequired`, `NeedsAuth` |
| `parrot/tools/abstract.py` | modifies | add credential seam between validate (`:563`) and `_execute` (`:589`); formalize `credential_provider`; `current_credential()` |
| `parrot/tools/manager.py` | modifies | broker handle + propagate via `exec_kwargs`; carry broker on `clone()` |
| `parrot/bots/abstract.py` | modifies | new `credentials` config field; build broker in `configure()` (`:1241`) |
| `parrot/a2a/server.py` | modifies (replace) | drop `_credential_resolvers`/`_try_invoke_with_gate`/`wire_*`; call broker; keep suspend/resume rendering |
| `parrot/integrations/msagentsdk/{agent,auth,wrapper}.py` | modifies | consume broker; render `CredentialRequired` as Adaptive/OAuth card; retire dead `_resolver_var`/stub OBO; store `ConversationReference` + suspend; make `signin/verifyState`/`signin/tokenExchange` the resume triggers; proactive result delivery |
| in-package manifest loader (new) | creates | parse a `credentials:` YAML manifest inside `packages/ai-parrot`; feed the broker alongside per-agent config |
| canonical-identity mapping (new) | creates | normalize A2A `from.email`/`oid` + MSAgentSDK `aad_object_id` → one vault key (cross-surface reuse) |
| OOB capture + `store_key` route (example app) | creates | mounted on the same aiohttp `web.Application`; static-key capture triggers chat-path resume |
| `parrot/auth/oauth2/workiq_provider.py` | depends on | becomes the `obo` strategy |
| `parrot/integrations/mcp/fireflies_a2a.py` | depends on | becomes the `static_key` strategy |
| `parrot/security/audit_ledger.py` | depends on | canonical ledger |
| `parrot/auth/audit.py` | removes/migrates | fold into the canonical ledger |
| `parrot/mcp/client.py` | depends on | `header_provider`/`token_supplier`/`user_id` fed by broker |
| `examples/msagent/server.py` + README | extends | demonstrate Fireflies + work.iq via declarative config on both surfaces |

---

## Code Context

### User-Provided Code
_None pasted verbatim; the user's intent ("efficient abstraction for any kind of auth —
OBO, OAuth, static keys") is captured in Constraints and Option A._

### Verified Codebase References

#### Classes & Signatures
```python
# parrot/auth/credentials.py:27
class CredentialResolver(ABC):
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...      # :31 (None == not authorized)
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...           # abstract
    async def is_connected(self, channel: str, user_id: str) -> bool: ...          # default: resolve() is not None
# :49 class OAuthCredentialResolver(CredentialResolver): __init__(self, oauth_manager)  (Jira 3LO)
# :70 @dataclass StaticCredentials(server_url, username, password, token, auth_type="basic_auth")
# :81 class StaticCredentialResolver(CredentialResolver): __init__(server_url, username, password, token, auth_type)

# parrot/tools/abstract.py
#   :115 args_schema: Type[BaseModel] = AbstractToolArgsSchema
#   :50  AbstractToolArgsSchema._context_fields: ClassVar[frozenset[str]] = frozenset()  # injected runtime fields
#   :256 @abstractmethod async def _execute(self, **kwargs) -> Any
#   :490 async def execute(self, *args, **kwargs) -> ToolResult
#         :506 pctx = kwargs.pop('_permission_context', None)
#         :507 resolver = kwargs.pop('_resolver', None)          # PERMISSION resolver (not credential)
#         :509-527 permission check (BEFORE _execute)
#         :536 self._current_pctx = pctx
#         :563 arg validation  ──►  [CREDENTIAL SEAM INSERTS HERE]  ──►  :589 raw_result = await self._execute(*args, **resolved_kwargs)
#         :622-651 OutputScrubber.scrub(result/error/metadata)     # sole outbound redaction

# parrot/tools/manager.py
#   :1189 async def execute_tool(self, tool_name, parameters, permission_context=None) -> Any
#         :1277 exec_kwargs = dict(parameters)
#         :1281 exec_kwargs['_resolver'] = self._resolver        # AbstractPermissionResolver
#         :1283 result = await tool.execute(**exec_kwargs)
#   :1490 def clone(self, *, include_search_tool=False) -> "ToolManager"  (:1522 copies resolver=self._resolver)

# parrot/bots/abstract.py
#   :156 class AbstractBot(MCPEnabledMixin, ToolInterface, ...)
#   :248 __init__(self, name='Nav', system_prompt=None, llm=None, tools=None, ... **kwargs)
#   :342 self.tool_manager = ToolManager(logger=..., debug=..., include_search_tool=...)
#   :1241 async def configure(self, app=None) -> None             # broker built HERE

# parrot/security/audit_ledger.py  (CANONICAL)
#   :79  class AuditLedgerEntry(BaseModel): entry_id, user_id, channel, tool, provider, key_fingerprint, signature, created_at
#   :134 class AbstractKMSSigner(ABC): async sign(data: bytes)->str ; async verify(data, signature)->bool
#   :165 class LocalHMACSigner(AbstractKMSSigner): __init__(secret: Optional[bytes]=None)
#   :203 class AuditLedger: __init__(signer=None, storage=None)
#   :245 async def append(self, *, user_id, channel, tool, provider, credential_material) -> AuditLedgerEntry
#   :314 async def verify(self, entry_id: str) -> bool

# parrot/auth/audit.py  (TO RETIRE/MIGRATE)

…(truncated)…
