---
type: Wiki Overview
title: 'Feature Specification: Unified Credential Broker — one declarative per-user
  auth abstraction for tools & MCP'
id: doc:sdd-specs-unified-credential-broker-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Connecting a tool or MCP server that needs **per-user** authentication currently
relates_to:
- concept: mod:parrot.a2a.server
  rel: mentions
- concept: mod:parrot.auth.audit
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.oauth2.workiq_provider
  rel: mentions
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.human.suspended_store
  rel: mentions
- concept: mod:parrot.integrations.mcp.fireflies_a2a
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk
  rel: mentions
- concept: mod:parrot.mcp.client
  rel: mentions
- concept: mod:parrot.security.audit_ledger
  rel: mentions
- concept: mod:parrot.services.vault_token_sync
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
---

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

…(truncated)…
