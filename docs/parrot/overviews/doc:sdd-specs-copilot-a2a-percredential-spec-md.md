---
type: Wiki Overview
title: 'Feature Specification: AI-Parrot ⇄ M365 Copilot via A2A, with parrot-owned
  per-user tool credentials'
id: doc:sdd-specs-copilot-a2a-percredential-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: An AI-Parrot agent must be invokable from inside the Microsoft 365 Copilot
relates_to:
- concept: mod:parrot.a2a.models
  rel: mentions
- concept: mod:parrot.a2a.server
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.oauth2
  rel: mentions
- concept: mod:parrot.auth.oauth2.service
  rel: mentions
- concept: mod:parrot.auth.oauth2_routes
  rel: mentions
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.core.exceptions
  rel: mentions
- concept: mod:parrot.human.suspended_store
  rel: mentions
- concept: mod:parrot.interfaces.o365
  rel: mentions
- concept: mod:parrot.services.vault_token_sync
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: AI-Parrot ⇄ M365 Copilot via A2A, with parrot-owned per-user tool credentials

**Feature ID**: FEAT-263
**Date**: 2026-06-26
**Author**: Jesus
**Status**: approved
**Target version**: 0.x (continuation of in-flight `wip: a2a server + ms agent sdk`)

> **Source**: research-grounded proposal `sdd/proposals/copilot-a2a-percredential.proposal.md`
> (enrichment mode, overall confidence medium). Full audit at `sdd/state/FEAT-263/`.

---

## 1. Motivation & Business Requirements

### Problem Statement

An AI-Parrot agent must be invokable from inside the Microsoft 365 Copilot
surface via Copilot Studio's A2A connection. The connection itself already works
(Copilot connects and invokes parrot as an A2A sub-agent). **The hard part is
per-user tool authentication**: tools bundled in the agent require credentials
scoped to the *individual end user* (`work-iq` → Entra OBO, `jira` → Atlassian
3LO, `fireflies` → MCP credential), but A2A does not carry tool credentials and
Copilot's connector framework only manages credentials for tools Copilot itself
knows about — tools inside an A2A agent are invisible to it. Therefore **parrot
must own the full per-user credential lifecycle for its own tools** (Model B —
custody in parrot, closed decision from the brainstorm).

Codebase research overturned the brainstorm's framing: ~70% of the asserted
"must be built" machinery already exists (see §6). The genuinely-new surface is
a narrow **A2A↔credential bridge** plus a greenfield **AuditLedger**.

### Goals

- G1. On an A2A task that needs a missing per-user credential, **suspend** the
  task and return a consent link; **no secret ever appears** in any A2A payload
  or Copilot transcript.
- G2. After OOB consent, **resume** the suspended A2A task via nonce correlation
  and return the tool result.
- G3. Extract a **stable per-user identity** from the inbound A2A request
  (OQ#1 resolved: identity is present) and key all credential lookups by it.
- G4. Build an **append-only, KMS-signed `AuditLedger`** recording
  `key_fingerprint` (never the secret) for every credentialed tool invocation.
- G5. Reuse existing primitives (`CredentialResolver`, `IntegrationsService`,
  `oauth2_routes`, `SuspendedExecutionStore`, OBO, `VaultTokenSync`, scrubber)
  rather than introduce parallel machinery.
- G6. Prove the bridge **end-to-end with a tool-agnostic stub credentialed
  tool** in v1; real tool verticals (jira/fireflies/work-iq) are separate gated
  sub-tasks.

### Non-Goals (explicitly out of scope)

- Making parrot a *standalone* Copilot/Outlook sidebar agent (separate track).
- Credential custody inside Copilot's Power Platform connection store —
  *Model A was rejected in the brainstorm (§3); custody stays in parrot.*
- Re-opening `AgentCard.to_dict` serialization — **already fixed** (camelCase,
  intentionally omits `supportedInterfaces`; see §6 and the brainstorm §11
  which is superseded).
- Rebuilding the OAuth2 `IntegrationsService` / provider registry / persistence
  schema — reused as-is.
- Shipping the `jira`, `fireflies`, or `work-iq` tool verticals as part of v1
  acceptance — each is a gated follow-up task (see §3 Module group B).

---

## 2. Architectural Design

### Overview

The bridge lives in `A2AServer` (satellite `parrot.a2a.server`). Today
`process_message()` delegates straight to `agent.ask()` with no identity and no
credential awareness. v1 inserts a credential-aware loop around tool execution:

1. **Identity** — extract the verifiable per-user identity claim from the A2A
   request and carry it as the canonical key (email-consistent with
   `TeamsHumanChannel`).
2. **Resolve** — before/while running a credentialed tool, call
   `CredentialResolver.resolve(channel, user_id)`. `None` is the documented
   signal that the user has not authorized.
3. **Suspend** — on `None`, persist the in-flight state via
   `SuspendedExecutionStore` and return an A2A **TEXT** artifact carrying the
   consent link from `CredentialResolver.get_auth_url(...)` (which is produced
   by the existing `IntegrationsService.start_connect` → auth URL + state nonce).
4. **Consent (OOB)** — the user clicks the link, completes Entra/Atlassian/MCP
   auth on parrot's existing `oauth2_routes` callback surface; the token is
   persisted to the vault by the existing `IntegrationsService.persist_credential`
   / `VaultTokenSync`.
5. **Resume** — a new **OAuth-callback resume trigger** correlates the callback
   (by nonce) to the suspended A2A task and calls `agent.resume(...)`, which
   re-runs the tool with a `CredentialResolver`-provided client and returns the
   result over A2A.
6. **Audit** — every credentialed invocation appends a KMS-signed
   `AuditLedgerEntry` recording `key_fingerprint` (never the secret).

v1 proves steps 1–6 with a **stub credentialed tool** so the bridge is validated
independently of any external IdP.

### Component Diagram

```
Copilot ── A2A task ──▶ A2AServer.process_message  (identity extract)
                          │
                          ├─ credentialed tool? ──▶ CredentialResolver.resolve(channel, user_id)
                          │        │ None
                          │        ├─ SuspendedExecutionStore.save(SuspendedExecution, ttl)
                          │        └─ A2A TEXT artifact = consent link (get_auth_url → IntegrationsService.start_connect)
                          │
   user OOB ─▶ oauth2_routes callback ─▶ IntegrationsService.persist_credential ─▶ VaultTokenSync
                          │
                          └─ NEW: nonce ⇄ interaction_id ─▶ agent.resume(session_id, user_input, state)
                                     │
                                     ▼
                          tool runs w/ resolved client ─▶ AuditLedger.append(key_fingerprint)
                                     │
                                     ▼
                          A2A response = result   (AbstractTool scrubber on the way out)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `A2AServer.process_message` (`parrot.a2a.server`) | **modify** | add identity extraction + credential gate + suspend path |
| `CredentialResolver` (`parrot.auth.credentials`) | uses | `resolve()`/`get_auth_url()` — the link-out contract |
| `IntegrationsService` (`parrot.auth.oauth2.service`) | uses | `start_connect` (auth_url+nonce), `persist_credential` |
| `setup_oauth2_routes` (`parrot.auth.oauth2_routes`) | extends | add nonce→suspended-A2A-task correlation on callback |
| `SuspendedExecutionStore` (`parrot.human.suspended_store`) | uses | reuse suspend/resume; new resume trigger (OAuth callback) |
| `AbstractBot.resume` (`parrot.bots.abstract`) | uses | `resume(session_id, user_input, state)` |
| `AbstractTool` scrubber (`parrot.tools.abstract`) | relies on | single output-scrub seam — "no secrets in conversational plane" |
| `O365Interface.acquire_token_on_behalf_of` (`parrot.interfaces.o365`) | uses (gated) | reuse for work-iq vertical |
| `VaultTokenSync` (`parrot.services.vault_token_sync`) | uses | encrypted per-user token persistence |
| `AuditLedger` | **create** | does not exist — greenfield, KMS-signed |

### Data Models

```python
# NEW — parrot/security/audit_ledger.py (greenfield)
from pydantic import BaseModel, Field
from datetime import datetime, timezone

class AuditLedgerEntry(BaseModel):
    """Append-only, KMS-signed record of a credentialed tool invocation."""
    entry_id: str
    user_id: str                 # canonical identity (email)
    channel: str                 # e.g. "a2a:copilot"
    tool: str
    provider: str                # "jira" | "o365" | "work-iq" | "fireflies" | "stub"
    key_fingerprint: str         # hash of the credential — NEVER the secret
    signature: str               # KMS signature over the canonical entry bytes
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# REUSE — parrot.human.suspended_store.SuspendedExecution already carries
# interaction_id, session_id, user_id, agent_name, tool_call_id, messages.
# The A2A bridge correlates the OAuth `state` nonce ⇄ interaction_id.
```

### New Public Interfaces

```python
# parrot/security/audit_ledger.py
class AuditLedger:
    async def append(self, entry: AuditLedgerEntry) -> None: ...
    async def verify(self, entry_id: str) -> bool: ...   # re-check KMS signature

# A2AServer (parrot.a2a.server) — new private seams on process_message:
#   _extract_identity(request) -> str
#   _on_missing_credential(tool, channel, user_id, task) -> Task   # suspend + consent link
#   resume_from_oauth_callback(nonce, user_input) -> None          # nonce → resume
```

---

## 3. Module Breakdown

> Group A = v1 (bridge + audit + stub proof). Group B = gated tool verticals
> (separate tasks; each blocked on its external verification).

### Group A — v1 (in scope for acceptance)

#### Module A1: A2A identity extraction
- **Path**: `packages/ai-parrot-server/src/parrot/a2a/server.py`
- **Responsibility**: extract the verifiable per-user identity from the inbound
  A2A request (OQ#1 resolved: present) and thread it as the canonical key into
  `process_message`. Document exactly where in the payload the claim lands.
- **Depends on**: existing `A2AServer`.

#### Module A2: Credential gate + suspend-on-missing
- **Path**: `packages/ai-parrot-server/src/parrot/a2a/server.py`
- **Responsibility**: before/while a credentialed tool runs, call
  `CredentialResolver.resolve(channel, user_id)`; on `None`, persist a
  `SuspendedExecution` and return an A2A TEXT artifact with the consent link
  from `get_auth_url` (backed by `IntegrationsService.start_connect`).
- **Depends on**: A1; `CredentialResolver`, `SuspendedExecutionStore`,
  `IntegrationsService`.

#### Module A3: OAuth-callback resume trigger (nonce correlation)
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2_routes.py` (+ a small
  correlation store / A2A hook in `parrot.a2a.server`)
- **Responsibility**: on a successful callback, map the OAuth `state` nonce ⇄
  `interaction_id`, load the `SuspendedExecution`, and call
  `agent.resume(session_id, user_input, state)` to finish the A2A task.
- **Depends on**: A2; existing `make_oauth2_callback` / `IntegrationsService.persist_credential`.

#### Module A4: AuditLedger (KMS-signed, append-only)
- **Path**: `packages/ai-parrot/src/parrot/security/audit_ledger.py` (new)
- **Responsibility**: `append(entry)` / `verify(entry_id)`; KMS signature over
  canonical bytes; `key_fingerprint` derived as a hash of the credential.
- **Depends on**: none (greenfield). Wired into A2/A3 at invocation time.

#### Module A5: Stub credentialed tool + end-to-end proof
- **Path**: `packages/ai-parrot/src/parrot/tools/` (a stub/echo tool that
  declares a credential requirement) + tests.
- **Responsibility**: tool-agnostic vertical proving task→suspend→link→callback
  →vault→resume→result→audit, with no external IdP.
- **Depends on**: A1–A4.

### Group B — gated tool verticals (separate tasks, NOT in v1 acceptance)

#### Module B1: `jira` vertical (most reuse-ready)
- Reuse the already-registered `jira_provider` in `OAuth2ProviderRegistry` +
  `jira_oauth` + `jira_connect_tool`. *Gate*: none beyond v1 bridge.

#### Module B2: `fireflies` vertical (MCP-credential)
- Wire via MCP using the telegram `mcp_persistence` (`vault_credential_name`)
  precedent. *Gate*: **OQ#6** — confirm MCP server is static-key vs MCP-OAuth.

#### Module B3: `work-iq` vertical (greenfield + OBO)
- Build the tool on `O365Interface.acquire_token_on_behalf_of`. *Gate*:
  **OQ#5** — verify work-iq OBO support + resource id + scopes empirically.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_extract_identity_present` | A1 | identity claim extracted from a representative A2A request |
| `test_extract_identity_missing_fails_closed` | A1 | absent identity → no service-identity fallback (negative) |
| `test_resolve_none_triggers_suspend` | A2 | `resolve()==None` → `SuspendedExecution` saved + TEXT consent link returned |
| `test_no_secret_in_a2a_payload` | A2 | suspend/response payload contains link + state only, never a token |
| `test_callback_nonce_resumes_task` | A3 | callback nonce → `agent.resume` called with correct state |
| `test_audit_append_and_verify` | A4 | `append` then `verify` round-trips a valid KMS signature |
| `test_audit_records_fingerprint_not_secret` | A4 | entry has `key_fingerprint`, never the raw credential |
| `test_no_service_identity_fallback` | A2/A4 | a credentialed tool with no per-user cred never runs under a service identity |

### Integration Tests
| Test | Description |
|---|---|
| `test_stub_end_to_end` | A5: task → suspend → consent link → simulated callback → vault → resume → result → audit entry |
| `test_resume_after_ttl_expiry` | suspended entry expired → graceful re-prompt, no crash |

### Test Data / Fixtures
```python
@pytest.fixture
def a2a_request_with_identity():
    """Representative Copilot A2A message carrying the per-user identity claim."""
    ...

@pytest.fixture
def fake_redis():
    """In-memory redis.asyncio double for SuspendedExecutionStore."""
    ...
```

---

## 5. Acceptance Criteria

> Complete when ALL are true. **v1 = Group A only** (tool verticals are gated).

- [ ] An A2A task needing a missing credential **suspends** and returns a TEXT
  consent link; no secret appears in any A2A payload or Copilot transcript.
- [ ] OOB consent persists a per-user credential keyed by canonical identity;
  the suspended A2A task **resumes via nonce** and returns the tool result.
- [ ] Per-user identity is extracted from the inbound A2A request and used as
  the credential key (OQ#1).
- [ ] `AuditLedger` records a KMS-signed entry with `key_fingerprint` (never the
  secret) for every credentialed invocation; `verify()` passes.
- [ ] **Negative**: a credentialed tool with no per-user credential never runs
  under a service identity (no `client_credentials` fallback path).
- [ ] End-to-end stub vertical passes (`test_stub_end_to_end`).
- [ ] Reuses `CredentialResolver` / `IntegrationsService` / `oauth2_routes` /
  `SuspendedExecutionStore` / `VaultTokenSync` — no parallel machinery added.
- [ ] All unit + integration tests pass (`pytest packages/ -v` for changed areas).
- [ ] No breaking changes to the existing A2A `message/send` happy path.
- [ ] `AgentCard.to_dict` is NOT modified.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified 2026-06-26 against the
> monorepo (`packages/*/src/parrot`). Implementation agents MUST NOT reference
> imports/attributes/methods not listed here without re-verifying.

### Verified Imports
```python
from parrot.auth.credentials import (
    CredentialResolver, OAuthCredentialResolver, StaticCredentialResolver,
)  # verified: packages/ai-parrot/src/parrot/auth/__init__.py:46-48,97-98
from parrot.auth.oauth2 import OAuth2ProviderRegistry, IntegrationsService
# verified: packages/ai-parrot/src/parrot/auth/oauth2/__init__.py:31,36,51,56
from parrot.a2a.models import AgentCard, AgentSkill, AgentCapabilities
# verified: packages/ai-parrot/src/parrot/a2a/__init__.py:73-74,163-164
from parrot.a2a.server import A2AServer, A2AEnabledMixin
# verified: parrot/a2a/__init__.py:120 lazy-routes "A2AServer" -> "parrot.a2a.server"
# concrete file: packages/ai-parrot-server/src/parrot/a2a/server.py
from parrot.human.suspended_store import SuspendedExecution, SuspendedExecutionStore
# verified: packages/ai-parrot-server/src/parrot/human/suspended_store.py:33,64
from parrot.services.vault_token_sync import VaultTokenSync
# verified: packages/ai-parrot-server/src/parrot/services/vault_token_sync.py:55
from parrot.core.exceptions import HumanInteractionInterrupt
# verified: packages/ai-parrot/src/parrot/core/exceptions.py:12
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/auth/credentials.py
class CredentialResolver(ABC):                                                  # :27
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...   # :31  None == not authorized
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...        # :40
    async def is_connected(self, channel: str, user_id: str) -> bool: ...       # :44

# packages/ai-parrot/src/parrot/auth/oauth2/service.py
class IntegrationsService:                                                      # :67
    async def start_connect(self, user_id, agent_id, provider_id,
                            return_origin) -> ConnectInitResponse: ...          # :140  (auth_url, state nonce, scopes, expires_in=600)
    async def persist_credential(self, user_id, provider_id,
                                 token_set) -> UsersIntegrationRow: ...         # :289

# packages/ai-parrot/src/parrot/auth/oauth2/registry.py
class OAuth2ProviderRegistry:                                                   # :69
    def register(self, provider: OAuth2Provider) -> None: ...                   # :96
    def get(self, provider_id: str) -> Optional[OAuth2Provider]: ...            # :106
    def all(self) -> list[OAuth2Provider]: ...                                  # (used in service.py:98)

# packages/ai-parrot/src/parrot/auth/oauth2_routes.py
def make_oauth2_callback(provider_id: str): ...                                 # :151  -> handler; delegates manager.handle_callback(code, state) :170
def setup_oauth2_routes(app, provider_id, callback_path): ...                   # :202  (route excluded from auth middleware :216)

# packages/ai-parrot-server/src/parrot/human/suspended_store.py
class SuspendedExecution(BaseModel):                                            # :33  interaction_id, session_id, user_id, agent_name, tool_call_id, messages, created_at
class SuspendedExecutionStore:                                                  # :64  key "hitl:suspended:{interaction_id}"
    async def save(self, record: SuspendedExecution, ttl: int) -> None: ...     # :103
    async def load(self, interaction_id: str) -> Optional[SuspendedExecution]:  # :128
    async def delete(self, interaction_id: str) -> None: ...                    # :149

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    async def resume(self, session_id: str, user_input: str,
                     state: Dict[str, Any]) -> AIMessage: ...                   # :3462

# packages/ai-parrot-server/src/parrot/a2a/server.py
class A2AServer:                                                                # :31
    async def process_message(self, message: Message) -> Task: ...             # :245  (TODAY: no identity, no credential gate, no suspend)
    async def _handle_jsonrpc(self, request) -> web.Response: ...               # :691  (message/send, tasks/get, tasks/list)

# packages/ai-parrot/src/parrot/interfaces/o365.py
def acquire_token_on_behalf_of(self, user_assertion: str,
                               scopes: Optional[List[str]] = None
                               ) -> Dict[str, Any]: ...                         # :621  (gated — work-iq vertical)

# packages/ai-parrot-server/src/parrot/services/vault_token_sync.py
class VaultTokenSync:                                                           # :55
    async def store_tokens(self, nav_user_id: str, provider: str,
                           tokens: Dict[str, Any]) -> None: ...                 # :106  (stores {provider}:{key})
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| credential gate (A2) | `CredentialResolver.resolve` | method call | `auth/credentials.py:31` |
| consent link (A2) | `CredentialResolver.get_auth_url` / `IntegrationsService.start_connect` | method call | `credentials.py:40`, `service.py:140` |
| suspend (A2) | `SuspendedExecutionStore.save` | method call | `suspended_store.py:103` |
| resume (A3) | `AbstractBot.resume` | method call | `bots/abstract.py:3462` |
| callback hook (A3) | `make_oauth2_callback` | extend handler | `oauth2_routes.py:151` |
| audit (A4) | (new) `AuditLedger.append` | method call | new file |

### Does NOT Exist (Anti-Hallucination)
- ~~`AuditLedger`~~, ~~`key_fingerprint`~~, ~~`audit_ledger`~~, ~~`AuditLog`~~ —
  **zero matches** across all packages; A4 builds this from scratch.
- ~~`work-iq` / `WorkIQ` / `work_iq` toolkit~~ — does not exist anywhere; B3 is greenfield.
- ~~native `FirefliesToolkit`~~ — fireflies is MCP-based only (`parrot/mcp/*` +
  telegram MCP); there is no native fireflies tool class.
- ~~`AgentCard.supportedInterfaces`~~ — intentionally NOT emitted (a2a-dotnet v0.3
  uses `additionalInterfaces`); do NOT add it. See `a2a/models.py:372-381`.
- ~~`A2AServer` per-user identity / suspend attributes~~ — none exist today;
  `process_message` (server.py:245) delegates straight to `agent.ask`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Link-out via the contract**: `resolve()==None` ⇒ surface `get_auth_url()`.
  Do not invent a parallel resolver. (`auth/credentials.py`)
- **Nonce reuse**: `IntegrationsService.start_connect` already issues the OAuth
  `state` nonce — reuse it as the suspend↔callback correlation key; do not mint
  a second nonce. (`auth/oauth2/service.py:140`)
- **Suspend/resume**: reuse `SuspendedExecution(interaction_id, session_id,
  user_id, agent_name, tool_call_id, messages)` verbatim; the A2A bridge adds a
  new *trigger* (OAuth callback), not a new store.
- **Scrubber discipline**: tools receive a resolved client, never a raw token in
  context; the single `AbstractTool` output-scrub seam stays the only exit.
- **Canonical identity**: key the vault by email (consistent with
  `TeamsHumanChannel`); A2A identity claim → canonical id mapping.
- async/await throughout; Pydantic models; `self.logger`.

### Known Risks / Gotchas
- **In-flight collision**: `6d9b8b3ed wip: a2a server + ms agent sdk` and
  FEAT-259 msagentsdk tenant-auth touch the same A2A server. Coordinate /
  rebase to avoid divergence.
- **AuditLedger KMS dependency**: signing/verify needs a KMS backend; choose the
  signing primitive early (it gates A4 + the AC). Decide local-dev fallback.
- **`A2AServer` lives in the satellite** `ai-parrot-server` (PEP 420 namespace);
  the bridge code lands there, but `CredentialResolver`/`AuditLedger` live in
  core `ai-parrot` — mind the package boundary and import direction.
- **`process_message` runs to completion synchronously today** and `_handle_jsonrpc`
  only knows `message/send`/`tasks/get`/`tasks/list`; suspend must return a
  well-formed terminal-or-input-required Task without breaking the happy path.
- **OQ#2**: if Copilot's A2A client does not honor `input-required` + resume,
  fall back to link-in-response → user re-prompts after consent (robust default).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (KMS client) | tbd | sign/verify `AuditLedgerEntry` (A4) — select during A4 |
| `azure-identity` / `msal` | existing | OBO for work-iq vertical (B3, gated) — already in `interfaces/o365.py` |
| `redis.asyncio` | existing | `SuspendedExecutionStore` backing |

---

## 8. Open Questions

### Resolved (carried forward from the proposal)
- [x] **OQ#1 — Does Copilot's low-code A2A connection deliver a verifiable
  per-user identity?** — *Resolved*: **Yes**, identity is present in the A2A
  request; vault-keying proceeds directly. *Spec note*: A1 must document exactly
  where the claim lands.
- [x] **AuditLedger fate** — *Resolved*: **build the full append-only,
  KMS-signed `AuditLedger`** (Module A4); `key_fingerprint` is a hard AC.
- [x] **v1 reference vertical** — *Resolved*: **bridge-only, tool-agnostic**
  (stub credentialed tool, Module A5); jira/fireflies/work-iq are gated Group B.

### Resolved (2026-06-27 — TASK-1648 / TASK-1649 unblocked)

…(truncated)…
