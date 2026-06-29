---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Unified Credential Broker — one declarative per-user auth abstraction for tools & MCP

**Feature ID**: FEAT-264
**Date**: 2026-06-29
**Author**: Jesus
**Status**: approved
**Target version**: 0.x (continuation of the in-flight Copilot / MS Agent SDK + A2A per-user credential work; supersedes parts of FEAT-261 / FEAT-263)

> **Source**: brainstorm `sdd/proposals/unified-credential-broker.brainstorm.md`
> (Recommended Option A; all 13 design/open questions resolved). Rejected
> alternatives (surface-only registry; MCP-native-auth-only) are NOT carried into
> the body — see the brainstorm for their tradeoffs.

---

## 1. Motivation & Business Requirements

### Problem Statement

Connecting a tool or MCP server that needs **per-user** authentication currently
requires bespoke code per integration. FEAT-263 added per-tool convenience methods on
`A2AServer` — `wire_fireflies_resolver()`, `wire_workiq_resolver()`,
`wire_jira_resolver()` — each a thin wrapper over a *generic*
`register_credential_resolver(provider_id, resolver)`. The proliferation creates the
false impression that **every new MCP needs a new method**, and hides four pieces of
real design debt:

1. **The resolver registry is trapped inside `A2AServer`** (`_credential_resolvers` +
   `_try_invoke_with_gate`) and unreachable from any other surface.
2. **There is no resolution seam in the core `agent.ask()` / ReAct tool loop** —
   nothing resolves a tool's `credential_provider` during normal chat, so the MSAgentSDK
   path is *uncabled*: the `_resolver_var` ContextVar is set but **never read**, and
   per-user gating never fires for agent-internal tool calls.
3. **Resolver *construction* is hand-wired per provider** (vault keys, OBO scopes, OOB
   capture URLs coded into call sites) rather than config-driven.
4. **The MSAgentSDK BF Token Service OBO exchange is a documented stub**, and there are
   **two divergent `AuditLedger` implementations**.

Affected: integration developers (glue per MCP), end users (per-user tools silently
never gate on chat), ops (two ledgers, no single config source). Trigger: incorporating
Fireflies.ai (static-key MCP) and work.iq (OBO MCP) into `examples/msagent/server.py`
exposed that the FEAT-263 verticals only function through `A2AServer`, not the
`MSAgentSDKWrapper` chat path the example uses.

### Goals

- **G1.** Adding a new MCP/tool on an **existing** auth mechanism (OBO, OAuth2 3LO,
  static key) is a **config entry, not code**; a genuinely-new auth mechanism is one new
  resolver *strategy*.
- **G2.** **One** surface-agnostic resolution seam in the core tool loop, so the same
  `tool.credential_provider` resolves identically on chat, A2A, and CLI — fixing the
  uncabled MSAgentSDK chat path.
- **G3.** Each surface renders the **single** `CredentialRequired`/`NeedsAuth` signal its
  own way (A2A suspend+consent link; MSAgentSDK Adaptive Card for static key / OAuthCard
  for OAuth/OBO; CLI URL).
- **G4.** **Secrets never enter the LLM-visible plane** — resolved credentials live on a
  per-call ContextVar, never in tool args/schema/transcript; `OutputScrubber` stays the
  sole egress seam.
- **G5.** Config is **declared on the AgentDefinition** (broker built at `configure()`),
  plus an **in-package** YAML manifest loader.
- **G6.** **Credentials are reusable across surfaces** — vault keyed by a canonical user
  identity (Entra OID/email); consent on A2A is honored in chat and vice-versa.
- **G7.** A missing credential **requests AND auto-resumes** the operation — the user
  never re-types; this includes a chat-path suspend/resume with parity to A2A.
- **G8.** **Replace** the `A2AServer` embedded gate with broker calls (adapter-backed, so
  FEAT-263 acceptance stays green); **one** canonical audit ledger; **one** canonical OBO
  strategy.

### Non-Goals (explicitly out of scope)

- A surface-only registry that leaves the chat path ungated (brainstorm Option B,
  rejected — fails G2).
- MCP-native-auth-only resolution that ignores native (non-MCP) tools (brainstorm Option
  C, rejected — fails G1's "any tool").
- A production KMS implementation beyond a pluggable interface + an Azure Key Vault
  backend (other KMS backends are future strategies).
- Re-opening `AgentCard.to_dict` serialization (already settled in FEAT-263).
- Replacing the OAuth2 `IntegrationsService` / provider registry / persistence schema —
  reused as-is.

---

## 2. Architectural Design

### Overview

A standalone, **surface-agnostic `CredentialBroker`** owns a
`provider_id → CredentialResolver` registry, built once from **declarative config**
(per-agent on the AgentDefinition, plus an in-package YAML manifest). A
`CredentialResolverFactory` maps an `auth:` kind (`obo | oauth2 | static_key | mcp`) to a
fully-constructed resolver strategy, so a new integration on an existing kind is a config
line.

The broker is consulted by **one seam in the core tool-execution path**
(`AbstractTool.execute()` / `ToolManager.execute_tool`, between arg validation and the
`_execute()` call). When a tool declares `credential_provider`, the broker resolves the
per-user credential (keyed by **canonical identity**), sets it on a **per-call
ContextVar** that the tool reads via `current_credential()`, appends a signed
`AuditLedgerEntry`, then runs `_execute()`. On a miss it raises a surface-neutral
`CredentialRequired(provider, auth_url, auth_kind)`; the active surface catches it and
renders the right prompt, **suspends** the operation, and **auto-resumes** on consent.

`A2AServer`'s embedded registry and `_try_invoke_with_gate` are **replaced** by broker
calls (the `wire_*` sugar is deleted); the suspend/nonce/`resume_from_oauth_callback`
flow is preserved as the A2A renderer. The MSAgentSDK surface gains parity: it stores a
Bot Framework `ConversationReference`, renders an Adaptive/OAuth card, and uses the
existing `signin/verifyState` / `signin/tokenExchange` invokes (OAuth/OBO) and the
`store_key` capture route (static key) as **resume triggers** that re-run the tool and
proactively deliver the result. MCP-backed tools receive their per-user token through
the broker feeding `MCPClientConfig.header_provider` / `token_supplier` / `user_id`.

### Component Diagram

```
AgentDefinition.credentials ─┐                  in-package YAML manifest ─┐
                             ▼                                            ▼
                     AbstractBot.configure() ──► CredentialBroker ◄── CredentialResolverFactory
                                                      │ registry: provider_id → resolver        (auth_kind → strategy:
                                                      │                                           obo|oauth2|static_key|mcp)
ToolManager.execute_tool ─► AbstractTool.execute ─────┤
   (tool.credential_provider?) ── yes ──► broker.resolve(provider, channel, canonical_user_id)
        │                                        │ ResolvedCredential          │ NeedsAuth(auth_url, auth_kind)
        │                                        ▼                             ▼
        │                          ContextVar(credential) + AuditLedger    raise CredentialRequired(provider, url, kind)
        │                                        ▼                             │
        │                                   _execute() ──► OutputScrubber      ├─ A2A: suspend(nonce) + consent link ─► resume_from_oauth_callback
        └── no ──► _execute() (unchanged)                                      └─ MSAgentSDK: store ConversationReference + card
                                                                                  ├─ OAuth/OBO ─► OAuthCard ─► signin/verifyState|tokenExchange ─► resume
                                                                                  └─ static key ─► Adaptive Card ─► /…/capture store_key ─► proactive resume
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.auth.credentials.CredentialResolver` | extends | host `CredentialBroker`, `CredentialResolverFactory`, `CredentialRequired`, `NeedsAuth`; resolvers become strategies |
| `parrot.tools.abstract.AbstractTool.execute` | modifies | insert credential seam between validate (:563) and `_execute` (:589); formalize `credential_provider`; add `current_credential()` |
| `parrot.tools.manager.ToolManager.execute_tool` | modifies | hold the broker; propagate via `exec_kwargs`; carry broker on `clone()` |
| `parrot.bots.abstract.AbstractBot` | modifies | new `credentials` config field; build broker in `configure()` (:1241) |
| `parrot.a2a.server.A2AServer` | modifies (replace) | drop `_credential_resolvers` / `_try_invoke_with_gate` / `wire_*`; call broker; keep `_extract_identity`, `_on_missing_credential` (as renderer), `resume_from_oauth_callback` |
| `parrot.integrations.msagentsdk.{agent,auth,wrapper}` | modifies | consume broker; Adaptive/OAuth card; retire dead `_resolver_var` + stub `_obo_exchange`; `ConversationReference` suspend + resume triggers + proactive delivery |
| `parrot.auth.oauth2.workiq_provider.WorkIQOBOCredentialResolver` | depends on | becomes the `obo` strategy (canonical OBO = `O365Interface.acquire_token_on_behalf_of` + vault) |
| `parrot.integrations.mcp.fireflies_a2a.FirefliesCredentialResolver` | depends on | becomes the `static_key` strategy |
| `parrot.security.audit_ledger.AuditLedger` | depends on | canonical ledger; add `AzureKeyVaultSigner` |
| `parrot.auth.audit.AuditLedger` | removes / migrates | fold `.record()` callers into `.append()` |
| `parrot.mcp.client.MCPClientConfig` | depends on | `header_provider` / `token_supplier` / `user_id` fed by broker |
| `examples/msagent/server.py` + README | extends | demo Fireflies + work.iq via declarative config on both surfaces; mount OOB capture route |

### Data Models

```python
# parrot/auth/credentials.py (new models)
from pydantic import BaseModel, Field
from typing import Any, Literal, Optional

AuthKind = Literal["obo", "oauth2", "static_key", "mcp"]

class ProviderCredentialConfig(BaseModel):
    """Declarative per-provider credential config (AgentDefinition / manifest)."""
    provider: str                       # e.g. "workiq", "fireflies", "jira"
    auth: AuthKind                      # selects the resolver strategy
    options: dict[str, Any] = Field(default_factory=dict)  # scope/source/vault_key/capture_url/...

class ResolvedCredential(BaseModel):
    provider: str
    secret: Any                         # NEVER logged / scrubbed on egress
    key_fingerprint: str                # SHA-256 of secret (for audit)

class NeedsAuth(BaseModel):
    provider: str
    auth_url: str                       # consent / OOB capture URL (NEVER a secret)
    auth_kind: AuthKind                 # drives surface rendering (card type)
```

### New Public Interfaces

```python
# parrot/auth/credentials.py
class CredentialResolverFactory:
    def build(self, cfg: ProviderCredentialConfig) -> CredentialResolver: ...

class CredentialBroker:
    def __init__(self, *, audit_ledger: "AuditLedger | None" = None,
                 identity_mapper: "CanonicalIdentityMapper | None" = None) -> None: ...
    def register(self, provider: str, resolver: CredentialResolver) -> None: ...
    @classmethod
    def from_config(cls, configs: list[ProviderCredentialConfig], **deps) -> "CredentialBroker": ...
    async def resolve(self, provider: str, channel: str, user_id: str,
                      **ctx: Any) -> "ResolvedCredential | NeedsAuth": ...

# parrot/auth/credentials.py — surface-neutral signal
class CredentialRequired(Exception):
    def __init__(self, provider: str, auth_url: str, auth_kind: str) -> None: ...

# parrot/tools/abstract.py — injection helper read by tools
def current_credential() -> Any | None: ...   # reads the per-call ContextVar
```

---

## 3. Module Breakdown

> Maps to Task Artifacts. M1→M3 are the coupled spine (sequential, one worktree). The
> rest parallelize once the seam contract is frozen.

### Module 1: CredentialBroker + Factory + config models
- **Path**: `packages/ai-parrot/src/parrot/auth/credentials.py` (+ `auth/broker.py` if size warrants)
- **Responsibility**: `ProviderCredentialConfig`, `ResolvedCredential`, `NeedsAuth`,
  `CredentialRequired`, `CredentialResolverFactory` (auth_kind→strategy),
  `CredentialBroker.resolve()` returning a resolved credential or `NeedsAuth`; audit
  append on success.
- **Depends on**: existing `CredentialResolver` ABC; canonical `AuditLedger` (M9).

### Module 2: Resolver strategies
- **Path**: reuse `parrot/auth/oauth2/workiq_provider.py` (obo), `parrot/integrations/mcp/fireflies_a2a.py` (static_key), `parrot/auth/credentials.py` `OAuthCredentialResolver` (oauth2); add an `mcp` strategy.
- **Responsibility**: adapt existing resolvers to be constructed by the factory from
  `ProviderCredentialConfig.options`; no behavior change to OBO/static-key semantics.
- **Depends on**: M1.

### Module 3: Core tool-loop seam + ContextVar injection
- **Path**: `packages/ai-parrot/src/parrot/tools/abstract.py`, `tools/manager.py`
- **Responsibility**: formalize `credential_provider` on `AbstractTool` (default `None`);
  insert the broker call between arg validation (:563) and `_execute` (:589); set/reset a
  per-call ContextVar; expose `current_credential()`; raise `CredentialRequired` on miss;
  propagate the broker into `execute_tool` `exec_kwargs` and `clone()`. **Tools without
  `credential_provider` are unaffected.**
- **Depends on**: M1.

### Module 4: AgentDefinition config + broker build + in-package manifest loader
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py` (+ a new `parrot/auth/manifest.py` loader)
- **Responsibility**: new `credentials: list[ProviderCredentialConfig]` field; build the
  `CredentialBroker` in `configure()` and hand it to `ToolManager`; in-package YAML
  manifest loader (shape analogous to `env/integrations_bots.yaml`).
- **Depends on**: M1, M3.

### Module 5: Canonical identity mapping
- **Path**: `packages/ai-parrot/src/parrot/auth/identity.py` (new)
- **Responsibility**: `CanonicalIdentityMapper` normalizing A2A (`from.email`/`oid`) and
  MSAgentSDK (`aad_object_id`) to one vault key (Entra OID/email) so credentials are
  reusable across surfaces; `channel` carried for audit context only, not storage scope.
- **Depends on**: M1.

### Module 6: A2A gate replacement
- **Path**: `packages/ai-parrot-server/src/parrot/a2a/server.py`
- **Responsibility**: remove `_credential_resolvers`, `_try_invoke_with_gate`, and the
  three `wire_*` methods; route gating through the shared broker; keep `_extract_identity`
  (feed the identity mapper), `_on_missing_credential` (now the A2A renderer of
  `NeedsAuth`), and `resume_from_oauth_callback`. No regression to the `message/send`
  happy path.
- **Depends on**: M1, M3, M5.

### Module 7: MSAgentSDK surface — render + suspend/resume
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/{agent,auth,wrapper}.py`
- **Responsibility**: consume the broker; render `CredentialRequired` as an Adaptive Card
  (static key) or OAuthCard (OAuth/OBO); store a Bot Framework `ConversationReference` +
  suspended tool call keyed by nonce; make `signin/verifyState` / `signin/tokenExchange`
  (OAuth/OBO) and the `store_key` capture route (static key) the **resume triggers** that
  re-run the tool and proactively deliver the result; retire the dead `_resolver_var` and
  the stub `_obo_exchange`.
- **Depends on**: M1, M3, M5.

### Module 8: Audit-ledger reconciliation + Azure Key Vault signer
- **Path**: `packages/ai-parrot/src/parrot/security/audit_ledger.py`; remove/migrate `parrot/auth/audit.py`
- **Responsibility**: make `parrot.security.audit_ledger` canonical; re-point
  `BFTokenServiceResolver` audit calls from `.record()` to `.append()`; add a pluggable
  `AzureKeyVaultSigner(AbstractKMSSigner)` (LocalHMACSigner stays the dev default).
- **Depends on**: none (parallelizable once M1 lands).

### Module 9: MCP per-user token injection
- **Path**: `packages/ai-parrot/src/parrot/mcp/client.py`, `tools/mcp_mixin.py`
- **Responsibility**: feed the broker-resolved per-user token into
  `MCPClientConfig.header_provider` / `token_supplier` keyed by `user_id`, so MCP-backed
  tools call with the per-user bearer.
- **Depends on**: M1, M3.

### Module 10: Example — Fireflies + work.iq on both surfaces
- **Path**: `examples/msagent/server.py` + `examples/msagent/README.md`
- **Responsibility**: declarative `credentials` config for `fireflies` (static_key) and
  `workiq` (obo); register `WorkIQTool` + a Fireflies tool; mount the OOB capture +
  `store_key` route on the same aiohttp app; document chat + A2A behavior end-to-end.
- **Depends on**: M1–M9.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_factory_builds_each_auth_kind` | M1/M2 | factory builds obo/oauth2/static_key/mcp resolvers from config |
| `test_broker_resolve_returns_credential` | M1 | resolved cred returned + audit appended |
| `test_broker_resolve_returns_needsauth` | M1 | miss → `NeedsAuth(auth_url, auth_kind)`, no secret |
| `test_new_provider_is_config_only` | M1/M4 | adding a provider on an existing auth kind needs no new code |
| `test_seam_resolves_and_injects_contextvar` | M3 | tool with `credential_provider` gets cred via `current_credential()` |
| `test_seam_noop_without_provider` | M3 | tool without `credential_provider` runs byte-for-byte unchanged |
| `test_no_secret_in_args_or_scrubbed_output` | M3/G4 | secret never in args/schema; `OutputScrubber` redacts egress |
| `test_canonical_identity_cross_surface` | M5/G6 | A2A `from.email` and MSAgentSDK `aad_object_id` map to the same vault key |
| `test_a2a_gate_replaced_no_wire_methods` | M6 | `wire_*` removed; gating goes through broker; suspend/consent unchanged |
| `test_msagent_static_key_renders_adaptive_card` | M7 | static-key miss → Adaptive Card with capture link (not OAuthCard) |
| `test_msagent_obo_renders_oauthcard` | M7 | OBO miss → OAuthCard |
| `test_msagent_resume_after_signin` | M7/G7 | `signin/verifyState` re-runs the suspended tool + proactive delivery |
| `test_msagent_resume_after_store_key` | M7/G7 | capture `store_key` triggers proactive resume |
| `test_audit_single_canonical_ledger` | M8 | `auth.audit` callers re-pointed; KMS verify() passes |
| `test_mcp_token_injected_per_user` | M9 | broker token reaches `MCPClientConfig.header_provider` |
| `test_fail_closed_no_identity` | M3/M6 | credentialed tool + no identity → fail closed, no service identity |

### Integration Tests
| Test | Description |
|---|---|
| `test_chat_path_obo_end_to_end` | MSAgentSDK chat: workiq miss → OAuthCard → sign-in → auto-resume → result |
| `test_chat_path_static_key_end_to_end` | MSAgentSDK chat: fireflies miss → Adaptive Card → capture → auto-resume → result |
| `test_a2a_vertical_regression` | FEAT-263 Fireflies + work.iq A2A flows still pass through the broker (no acceptance regression) |
| `test_cross_surface_reuse` | consent on A2A → credential honored on chat for the same canonical user |

### Test Data / Fixtures
```python
@pytest.fixture
def broker_config():
    return [
        ProviderCredentialConfig(provider="fireflies", auth="static_key",
                                 options={"vault_key": "fireflies:api_key", "capture_url": "https://app/capture"}),
        ProviderCredentialConfig(provider="workiq", auth="obo",
                                 options={"source": "o365", "scope": "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"}),
    ]

@pytest.fixture
def fake_vault():  # in-memory VaultTokenSync double (read_tokens/store_tokens)
    ...
```

---

## 5. Acceptance Criteria

> Complete when ALL are true.

- [ ] Adding a provider on an existing auth kind (obo/oauth2/static_key/mcp) requires
  **only** a `ProviderCredentialConfig` entry — no new method, gate, or wiring code (G1).
- [ ] A **single** seam in `AbstractTool.execute()`/`ToolManager` resolves
  `tool.credential_provider` for chat, A2A, and CLI alike; the MSAgentSDK chat path gates
  per-user tool calls (G2).
- [ ] A missing credential raises one surface-neutral `CredentialRequired(provider,
  auth_url, auth_kind)`; each surface renders it (A2A suspend+link, MSAgentSDK Adaptive
  Card for static key / OAuthCard for OAuth/OBO, CLI URL) (G3).
- [ ] No secret appears in tool args/schema, model context, transcript, or logs; only a
  `key_fingerprint` is recorded; `OutputScrubber` remains the sole egress seam (G4).
- [ ] Broker config is declared on the AgentDefinition and built at `configure()`; an
  in-package YAML manifest loader exists (G5).
- [ ] Credentials are reusable across surfaces — vault keyed by canonical identity; a
  credential captured on A2A resolves in chat for the same user (G6).
- [ ] A missing credential requests **and auto-resumes** the operation on both surfaces;
  the user never re-types (G7). MSAgentSDK stores a `ConversationReference` and resumes
  via sign-in invokes / capture route with proactive delivery.
- [ ] `A2AServer` `wire_*` + embedded gate are removed; gating routes through the broker;
  FEAT-263 Fireflies/work.iq/jira flows still pass (G8, adapter-backed).
- [ ] One canonical audit ledger (`parrot.security.audit_ledger`); `parrot.auth.audit`
  callers migrated; `verify()` passes; pluggable signer with Azure Key Vault backend
  (LocalHMACSigner dev default).
- [ ] Canonical OBO = `O365Interface.acquire_token_on_behalf_of` + vault; the stub
  `_obo_exchange` and the dead `_resolver_var` are removed.
- [ ] Negative: a credentialed tool with no per-user credential never runs under a service
  identity (no `client_credentials` fallback).
- [ ] All unit + integration tests pass (`pytest packages/ -v` for changed areas).
- [ ] No breaking changes to tools without `credential_provider`, nor to the A2A
  `message/send` happy path.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified 2026-06-29 against the monorepo
> (`packages/*/src/parrot`). Implementation agents MUST NOT reference imports /
> attributes / methods not listed here without re-verifying.

### Verified Imports
```python
from parrot.auth.credentials import (
    CredentialResolver, OAuthCredentialResolver, StaticCredentialResolver,
)  # verified: credentials.py:27,49,81
from parrot.auth.oauth2.workiq_provider import WorkIQOBOCredentialResolver, WorkIQOAuth2Provider  # :66,203
from parrot.integrations.mcp.fireflies_a2a import FirefliesCredentialResolver  # :49
from parrot.security.audit_ledger import (
    AuditLedger, AuditLedgerEntry, AbstractKMSSigner, LocalHMACSigner,
)  # verified: security/audit_ledger.py:203,79,134,165
from parrot.human.suspended_store import SuspendedExecution, SuspendedExecutionStore
from parrot.services.vault_token_sync import VaultTokenSync           # store_tokens/read_tokens
from parrot.mcp.client import MCPClientConfig                         # mcp/client.py:132
```

### Existing Class Signatures
```python
# parrot/auth/credentials.py
class CredentialResolver(ABC):                                               # :27
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...  # :31  None == not authorized
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...        # abstract
    async def is_connected(self, channel: str, user_id: str) -> bool: ...       # default: resolve() is not None
class OAuthCredentialResolver(CredentialResolver):                           # :49  __init__(self, oauth_manager)
@dataclass
class StaticCredentials:                                                     # :70  server_url, username, password, token, auth_type
class StaticCredentialResolver(CredentialResolver):                         # :81  __init__(server_url, username, password, token, auth_type)

# parrot/tools/abstract.py
class AbstractToolArgsSchema(BaseModel):                                     # _context_fields: ClassVar[frozenset[str]] = frozenset()  # :50
class AbstractTool:
    args_schema: Type[BaseModel] = AbstractToolArgsSchema                    # :115
    @abstractmethod
    async def _execute(self, **kwargs) -> Any: ...                           # :256
    async def execute(self, *args, **kwargs) -> ToolResult:                  # :490
        # :506 pctx = kwargs.pop('_permission_context', None)
        # :507 resolver = kwargs.pop('_resolver', None)   # PERMISSION resolver, NOT credential
        # :509-527 permission check (BEFORE _execute)
        # :536 self._current_pctx = pctx
        # :563 arg validation  ── [CREDENTIAL SEAM INSERTS HERE] ──  :589 raw_result = await self._execute(*args, **resolved_kwargs)
        # :622-651 OutputScrubber.scrub(result/error/metadata)   # sole outbound redaction

# parrot/tools/manager.py
class ToolManager:
    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any],
                           permission_context: Optional["PermissionContext"] = None) -> Any:  # :1189
        # :1277 exec_kwargs = dict(parameters)
        # :1281 exec_kwargs['_resolver'] = self._resolver   # AbstractPermissionResolver
        # :1283 result = await tool.execute(**exec_kwargs)
    def clone(self, *, include_search_tool: bool = False) -> "ToolManager": ...  # :1490 (:1522 copies resolver)

# parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, ToolInterface, ...):                      # :156
    def __init__(self, name='Nav', system_prompt=None, llm=None, tools=None, ..., **kwargs): ...  # :248
    # :342 self.tool_manager = ToolManager(logger=..., debug=..., include_search_tool=...)
    async def configure(self, app=None) -> None: ...                         # :1241  (broker built HERE)

# parrot/security/audit_ledger.py  (CANONICAL)
class AuditLedgerEntry(BaseModel):                                          # :79  entry_id,user_id,channel,tool,provider,key_fingerprint,signature,created_at
class AbstractKMSSigner(ABC):                                              # :134 async sign(data: bytes)->str ; async verify(data, signature)->bool
class LocalHMACSigner(AbstractKMSSigner):                                  # :165 __init__(secret: Optional[bytes]=None)
class AuditLedger:                                                         # :203 __init__(signer=None, storage=None)
    async def append(self, *, user_id, channel, tool, provider, credential_material) -> AuditLedgerEntry: ...  # :245
    async def verify(self, entry_id: str) -> bool: ...                      # :314

# parrot/auth/audit.py  (TO RETIRE/MIGRATE)
@dataclass
class AuditEntry:                                                           # :21 timestamp,user_id,channel,tool,connection,key_fingerprint,action
class AuditLedger:                                                          # :46 __init__(logger=None); def record(entry); async def flush()

# parrot/mcp/client.py
@dataclass
class MCPClientConfig:                                                      # :132 name,url,command,...,auth_credential,auth_type,auth_config,token_supplier,
    #   headers, header_provider, oauth2, auth_preset, user_id, transport, ...
    async def get_headers(self, context=None) -> Dict[str, str]: ...        # :238 static → auth_credential → header_provider(context)

# parrot/integrations/msagentsdk/auth.py
_resolver_var: ContextVar = ContextVar("msagentsdk_resolver", default=None)  # :38 SET in agent.py, NEVER READ (dead)
class CredentialRequired(Exception): __init__(self, tool, connection_name)   # :41 (msagentsdk-local; to be unified)
class BFTokenServiceResolver(CredentialResolver):                            # :68 resolve(channel,user_id,**kwargs); :319 _obo_exchange is a STUB

# parrot/auth/oauth2/workiq_provider.py
class WorkIQOBOCredentialResolver(CredentialResolver):                       # :66 __init__(o365_interface,o365_oauth_manager,vault_token_sync,workiq_scope)
class WorkIQOAuth2Provider(OAuth2Provider): credential_resolver() -> WorkIQOBOCredentialResolver  # :203
WORKIQ_SCOPE = "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"            # :54

# parrot/integrations/mcp/fireflies_a2a.py
class FirefliesCredentialResolver(CredentialResolver):                       # :49 __init__(vault_token_sync, oob_capture_url)
    #   resolve() → vault fireflies:api_key or None ; get_auth_url() → oob_capture_url ; store_key(user_id, api_key)

# parrot/a2a/server.py  (REPLACE the gate)
class A2AServer:                                                            # :50
    def __init__(self, agent, ..., credential_resolvers=None, suspended_store=None, audit_ledger=None): ...  # :84
    # :134 self._credential_resolvers: Dict[str, Any]        # LIFT into broker
    def _extract_identity(self, message) -> Optional[str]: ...              # :289  KEEP (feed identity mapper)
    def register_credential_resolver(self, provider, resolver): ...         # :352  generic API
    async def _on_missing_credential(self, ...): ...                        # :373  becomes the A2A renderer of NeedsAuth
    async def resume_from_oauth_callback(self, interaction_id, user_input=""): ...  # :473  KEEP
    def wire_jira_resolver/wire_fireflies_resolver/wire_workiq_resolver(...) # :539/:571/:613  DELETE (sugar)
    async def _try_invoke_with_gate(self, ...): ...                         # :718  REPLACE with broker.resolve
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CredentialBroker.resolve` | `CredentialResolver.resolve` | method call | `credentials.py:31` |
| credential seam | `AbstractTool._execute` | inject before call | `tools/abstract.py:589` |
| seam injection | `AbstractToolArgsSchema._context_fields` / ContextVar | runtime field | `tools/abstract.py:50` |
| broker build | `AbstractBot.configure` | method | `bots/abstract.py:1241` |
| audit | `AuditLedger.append` | method call | `security/audit_ledger.py:245` |
| obo strategy | `O365Interface.acquire_token_on_behalf_of` | method call | `interfaces/o365.py:621` (per FEAT-263 contract) |
| A2A render | `A2AServer._on_missing_credential` / `resume_from_oauth_callback` | method | `a2a/server.py:373,473` |
| MCP token | `MCPClientConfig.header_provider` | callback | `mcp/client.py:132` |

### Does NOT Exist (Anti-Hallucination)
- ~~`credential_provider` on `AbstractTool` base~~ — declared only by subclasses
  (`WorkIQTool:93`, `stub_credentialed_tool:79`); the base must formalize it (default `None`).
- ~~Credential-resolution hook in `AbstractTool.execute()`/`ToolManager`~~ — only
  `_permission_context` + `_resolver` (a *permission* resolver) flow in today.
- ~~`oauth_connections` / `obo_scopes` / `credentials` field on `AbstractBot` / AgentDefinition~~ —
  none exist (only on `MSAgentSDKConfig`).
- ~~A reader of `msagentsdk._resolver_var`~~ — set, never consumed (dead).
- ~~A working BF Token Service OBO exchange~~ — `_obo_exchange` returns the original token (`msagentsdk/auth.py:319`).
- ~~A single `AuditLedger`~~ — two exist (`security/audit_ledger.py` KMS-signed vs `auth/audit.py` `.record()`), NOT interchangeable.
- ~~In-package loader for `env/integrations_bots.yaml`~~ — parsed by the external Navigator layer, not inside `packages/ai-parrot`; a new loader is required.
- ~~`AzureKeyVaultSigner`~~ — does not exist; only `LocalHMACSigner` ships today.
- ~~`CanonicalIdentityMapper`~~ — does not exist; greenfield (M5).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **One signal, N renderers**: the broker only resolves or returns `NeedsAuth`; surfaces
  own the UX (A2A suspend+link, MSAgentSDK card, CLI URL). Do not push UX into the broker.
- **Secret hygiene**: resolved credential lives on a per-call ContextVar (mirror the
  existing `self._current_pctx` pattern); read via `current_credential()`; never place it
  in tool args/schema. `OutputScrubber` (abstract.py:622-651) stays the only egress seam.
- **Additive seam**: gate strictly on the presence of `tool.credential_provider`; tools
  without it must be byte-for-byte unchanged through `execute()`.
- **Reuse strategies, don't fork**: OBO = `WorkIQOBOCredentialResolver` (O365 + vault);
  static-key = `FirefliesCredentialResolver`; oauth2 = `OAuthCredentialResolver`.
- **Canonical identity first**: key the vault by Entra OID/email, never by raw
  channel-scoped id, or cross-surface reuse silently breaks.
- async/await throughout; Pydantic v2 models; `self.logger`; `aiohttp` only.

### Known Risks / Gotchas
- **High blast radius** in `AbstractTool.execute()`/`ToolManager` — every tool flows
  through it. Mitigation: gate on `credential_provider` presence + a regression test that
  a no-provider tool is unchanged.
- **Replacing the A2A gate** risks FEAT-263 acceptance + the `message/send` happy path.
  Mitigation: adapter-backed replacement; keep `_extract_identity` / suspend / resume;
  run the FEAT-263 vertical tests as regression.
- **Chat-path proactive resume** needs a stored Bot Framework `ConversationReference` and
  proactive-message send; the SDK API for proactive continue must be verified before M7.
- **Canonical identity mismatch**: A2A may carry email while MSAgentSDK carries
  `aad_object_id`; the mapper must reconcile (prefer OID, fall back to email) or reuse
  fails. Edge: anonymous/dev users have neither — fail closed.
- **Two `CredentialRequired`** classes (msagentsdk-local vs new core) — unify on the core
  one; migrate the msagentsdk handler.
- **KMS dependency**: production signing needs Azure Key Vault; `LocalHMACSigner` is
  dev-only — do not ship it as the prod default.
- **MCP `header_provider`** receives a `ReadonlyContext`; the per-user token must be
  resolved at call time (not connect time) to stay per-user.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2` | broker config + signal models (existing core dep) |
| `aiohttp` | existing | OOB capture endpoint, MCP HTTP, O365 OBO calls |
| `msal` / `azure-identity` | existing | OBO exchange via `O365Interface` |
| `azure-keyvault-keys` / `azure-identity` | tbd | `AzureKeyVaultSigner` (prod KMS backend) |
| `redis.asyncio` | existing | `SuspendedExecutionStore` backing |
| `microsoft-agents-hosting-aiohttp` | `~=0.9` | `ConversationReference` + proactive resume (MSAgentSDK) |

---

## 8. Open Questions

> Resolved items carried from the brainstorm (decision trail). No blocking unresolved
> questions remain; the items below are implementation-time confirmations.

- [x] Flow type / base branch — *Resolved in brainstorm*: `feature` on `dev`.
- [x] Blast radius — *Resolved in brainstorm*: core seam in `AbstractTool.execute()`/`ToolManager` (all surfaces resolve uniformly).
- [x] Config source — *Resolved in brainstorm*: declarative on the AgentDefinition (built at `configure()`) + in-package YAML manifest loader.
- [x] A2A gate treatment — *Resolved in brainstorm*: **replace** the embedded gate; broker is the backend (adapter-backed to keep FEAT-263 acceptance green).
- [x] Credential injection — *Resolved in brainstorm*: per-call ContextVar + `current_credential()`; secrets never in LLM-visible kwargs.
- [x] Static-key UX on chat — *Resolved in brainstorm*: Adaptive Card with OOB capture link; OAuthCard reserved for OAuth/OBO.
- [x] Canonical OBO — *Resolved in brainstorm*: `O365Interface.acquire_token_on_behalf_of` + `VaultTokenSync`.
- [x] Canonical audit ledger — *Resolved in brainstorm*: KMS/HMAC-signed `parrot.security.audit_ledger`; migrate/retire `parrot.auth.audit`.
- [x] Manifest loader — *Resolved in brainstorm*: in-package loader in `packages/ai-parrot` (plus per-agent config).
- [x] Cross-surface credential reuse / `channel` keying — *Resolved in brainstorm*: vault keyed by canonical identity (Entra OID/email); `channel` is audit-only; needs `CanonicalIdentityMapper`.
- [x] OOB capture endpoint ownership — *Resolved in brainstorm*: mounted on the same aiohttp `web.Application` as the server; capture completion triggers resume.
- [x] KMS backend — *Resolved in brainstorm*: pluggable `AbstractKMSSigner`; `LocalHMACSigner` dev default; **Azure Key Vault** first prod backend.
- [x] Chat-path resume — *Resolved in brainstorm*: request creds **and auto-resume**; store `ConversationReference` + nonce; resume triggers = sign-in invokes (OAuth/OBO) + `store_key` route (static key); proactive delivery.
- [ ] Proactive-message SDK API — *Owner: impl (M7)*: confirm the `microsoft-agents` proactive-continue API for delivering the resumed result.
- [ ] Identity precedence rule — *Owner: impl (M5)*: confirm OID-then-email precedence and the anonymous/dev fail-closed behavior.

---

## Worktree Strategy

- **Default isolation unit**: `mixed`.
- **Spine (sequential, one worktree)**: M1 (broker/factory/models) → M3 (core seam) →
  M4 (agent config/build) → M6 (A2A replacement) → M7 (MSAgentSDK surface). The seam
  contract is the spine everything else depends on; it must not be split.
- **Parallelizable (after the seam contract freezes)**: M2 (strategy adapters), M5
  (canonical identity), M8 (audit reconciliation + Azure Key Vault signer), M9 (MCP token
  injection). M10 (example) is last and depends on all.
- **Cross-feature dependencies**: touches files owned by FEAT-263 (`a2a/server.py`),
  FEAT-261 (`msagentsdk/*`), FEAT-262 (`mcp/client.py`) — all merged to `dev`, so no live
  worktree conflict, but this feature **supersedes** the FEAT-261/263 wiring; coordinate
  the gate replacement to avoid reintroducing `wire_*`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-29 | Jesus | Initial draft from brainstorm `unified-credential-broker` (Option A). All 13 design/open questions resolved and carried forward; Code Context re-verified against current monorepo. |
