---
type: Wiki Overview
title: FEAT-259 — Auth & OBO Layer (MS Agents SDK Path)
id: doc:sdd-proposals-auth-obo-msagentsdk-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The parent FEAT-259 proposal delivered the transport layer: `MSAgentSDKWrapper`,'
---

---
id: FEAT-259
title: "Per-user authentication & OBO for ai-parrot agents via Microsoft 365 Agents SDK"
slug: auth-obo-msagentsdk
type: feature
mode: enrichment
status: discussion
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-26
  summary_oneline: "Add per-user OAuth sign-in, OBO token exchange, and credential bridging to the MS Agents SDK integration"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-259/
relates_to:
  - FEAT-259 proposal (microsoft-copilot-agent-sdk.proposal.md) — transport/bridge feasibility
  - FEAT-XXX brainstorm (brainstorm-copilot-a2a-percredential.md) — A2A per-credential path
spike_gate: "OQ#1 — does Copilot Studio relay the OAuth sign-in card + tokens/response invoke to a connected SDK agent?"
created: 2026-06-26
updated: 2026-06-26
---

# FEAT-259 — Auth & OBO Layer (MS Agents SDK Path)

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `file: sdd/proposals/auth-obo-research.md`
> **Audit**: [`sdd/state/FEAT-259/`](../state/FEAT-259/)
> **Depends on**: FEAT-259 transport/bridge (implemented — wrapper, agent, config, patches)

---

## 0. Origin

The parent FEAT-259 proposal delivered the transport layer: `MSAgentSDKWrapper`,
`ParrotM365Agent`, `MSAgentSDKConfig`, and the MCS empty-200 patch. That layer
authenticates the **bot↔connector** channel (inbound JWT/API-key, outbound MSAL
service connection). It does **not** authenticate **end users** or acquire
per-user tokens for downstream APIs (Graph, Work IQ, Jira, Fireflies).

This proposal addresses the auth gap: per-user OAuth sign-in via the Bot
Framework Token Service, OBO exchange for Microsoft-cluster APIs, and the
credential bridge into ai-parrot's tool layer.

> *Full research*: `sdd/proposals/auth-obo-research.md`

**Initial signals**:
- The MS Agents SDK has a native token service (Bot Framework OAuth) that
  collapses most of what was designed for the A2A path
- Four tools (`o365`, `work-iq`, `jira`, `fireflies`) need three distinct auth
  mechanisms — three native to the token service, one custom
- A spike gate (OQ#1) blocks the entire sign-in flow on the Copilot Studio surface

---

## 1. Synthesis Summary

The Microsoft 365 Agents SDK provides a managed OAuth layer via the Bot Framework
Token Service — a per-user, server-side token store keyed by user + OAuth
connection, with refresh handled automatically. This collapses the custom OAuth
dance, credential storage, and suspend/resume infrastructure designed for the A2A
path. ai-parrot's `CredentialResolver` becomes a thin adapter over the SDK's
token client rather than owning the flow. Three of four target tools (`o365`,
`work-iq`, `jira`) fit the native OAuth connection model; `fireflies` (static
API key) requires a custom capture surface. The critical unknown is whether
Copilot Studio relays the sign-in card and `invoke` activities to the connected
SDK agent — everything in the sign-in flow depends on this.

---

## 2. Codebase Findings

> All entries grounded in `sdd/state/FEAT-259/findings/`. No fabricated paths.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-integrations/.../msagentsdk/wrapper.py` | `handle_request()` | 251-360 | Inbound JWT + API-key auth; outbound MSAL service connection | F005 |
| 2 | `packages/ai-parrot-integrations/.../msagentsdk/wrapper.py` | `MsalConnectionManager` | 149-177 | Bot↔connector auth only — `SERVICE_CONNECTION` | F005 |
| 3 | `packages/ai-parrot-integrations/.../msagentsdk/wrapper.py` | `_AnonymousConnectionManager` | 22-59 | Dev-only anonymous path | F005 |
| 4 | `packages/ai-parrot-integrations/.../msagentsdk/agent.py` | `on_turn()` | 52-74 | Routes `message` + `conversationUpdate`; **ignores `invoke`** | F006 |
| 5 | `packages/ai-parrot-integrations/.../msagentsdk/agent.py` | `_handle_message()` | 92-108 | Calls `ask(question, session_id, user_id)` — no token injection | F006 |
| 6 | `packages/ai-parrot-integrations/.../msagentsdk/models.py` | `MSAgentSDKConfig` | 58-71 | No `oauth_connections` or `obo_scopes` fields | F008 |
| 7 | `packages/ai-parrot-integrations/.../msagentsdk/_patches.py` | `patch_mcs_connector_empty_response` | full | MCS empty-200 tolerance | F003 |
| 8 | `packages/ai-parrot/src/parrot/auth/credentials.py` | `CredentialResolver` | — | Abstract + OAuth + Static resolvers exist; **not used by msagentsdk** | F007 |
| 9 | `packages/ai-parrot/src/parrot/auth/context.py` | `_pctx_var` | 33-35 | ContextVar for PermissionContext; **not used by msagentsdk** | F007 |

### 2.2 Constraints Discovered

- **No `invoke` handling.** `on_turn` ignores all activity types except `message`
  and `conversationUpdate`. The OAuth sign-in round-trip requires handling
  `signin/verifyState` and `signin/tokenExchange` invoke activities.
  *Implication*: sign-in flow cannot complete until invoke routing is added.
  *Evidence*: F006

- **Only service connection exists.** `MsalConnectionManager` is initialized with
  a single `SERVICE_CONNECTION` for bot↔connector auth. No user-facing OAuth
  connection is configured.
  *Implication*: user token acquisition requires new OAuth connections on Azure
  Bot and new config fields in `MSAgentSDKConfig`.
  *Evidence*: F005, F008

- **Identity is channel-only.** User identity is `from_property.id` (channel id).
  `aad_object_id` (Entra object id) is not extracted.
  *Implication*: cannot key the token service vault or perform OBO without the
  Entra identity. Must extract from `from.aad_object_id` or validated claims.
  *Evidence*: F006

- **No token→tool bridge.** `_handle_message` passes `question`, `session_id`,
  `user_id` to `ask()` with no mechanism to inject resolved credentials into
  `CredentialResolver` / `_pctx_var`.
  *Implication*: even with SDK tokens acquired, tools have no path to receive them.
  *Evidence*: F006, F007

- **`CredentialResolver` exists but is disconnected.** The abstract class and
  OAuth/Static resolvers exist in `parrot/auth/credentials.py` but are not
  imported or used by the msagentsdk module.
  *Implication*: the adapter pattern is viable — the interface exists, only the
  SDK-backed implementation and the bridge wiring are missing.
  *Evidence*: F007

- **`AuditLedger` does not exist.** Referenced in the research as a target
  component, not as existing code.
  *Implication*: needs to be built from scratch. Scope depends on spec.
  *Evidence*: F007

- **`_pctx_var` is scoped to dataset/DB tools.** The ContextVar carries
  `PermissionContext`, not general credentials. Repurposing it for OAuth tokens
  requires either extending `PermissionContext` or introducing a parallel
  `CredentialContext`.
  *Evidence*: F007

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `47d43b7` | recent | Jesus | wrapper for ms agent sdk | msagentsdk/wrapper.py |
| `634705203` | recent | Jesus | fix: address code review issues — lazy import, path sanitization, error handling, tests | msagentsdk/ |
| `de5abdc` | recent | Jesus | feat: TASK-1639 — Integration Wrapper | msagentsdk/wrapper.py |
| `210652e` | recent | Jesus | feat: TASK-1638 — Bridge Agent | msagentsdk/agent.py |
| `9c03dfe` | recent | Jesus | feat: TASK-1637 — Package Scaffold + Config Model | msagentsdk/models.py |

---

## 3. Probable Scope

### What's New

- **OAuth connection config** — `MSAgentSDKConfig.oauth_connections` mapping tool
  names to Azure Bot OAuth connection names; `obo_scopes` for OBO exchange targets
- **`invoke` activity handler** — `on_turn` routes `signin/verifyState` and
  `signin/tokenExchange` to complete the sign-in round-trip
- **`BFTokenServiceCredentialResolver`** — `CredentialResolver` adapter that
  fetches per-user tokens from the SDK token client
- **Token→tool bridge** — `_pctx_var` (or a new `CredentialContext`) set by the
  bridge before `ask()`, carrying resolved credential context
- **Sign-in card emission** — when a tool reports missing credentials, emit a
  native OAuthCard instead of failing
- **`AuditLedger`** — records `key_fingerprint` per credentialed tool invocation
- **Fireflies key capture** — out-of-band link-out for static API key (unless
  Fireflies OAuth is confirmed)

### What Changes

- **`MSAgentSDKConfig`** — new fields: `oauth_connections`, `obo_scopes`
  *Evidence*: F008
- **`on_turn()`** — add `invoke` routing for sign-in activities
  *Evidence*: F006
- **`_handle_message()`** — inject resolved credential context into `ask()` via
  `_pctx_var` or new mechanism
  *Evidence*: F006, F007
- **Identity extraction** — extract `aad_object_id` from Activity or validated
  claims as canonical user identity
  *Evidence*: F006

### What's Untouched (Non-Goals)

- **Bot↔connector auth** — `MsalConnectionManager` / `SERVICE_CONNECTION` unchanged
- **Inbound JWT/API-key validation** — `handle_request()` unchanged
- **MCS empty-200 patch** — `_patches.py` unchanged
- **A2A path** — separate FEAT-XXX, not touched here
- **Account-linking** (Entra ⇄ Atlassian/Fireflies) — not assumed; identity
  mapping is a future concern

### Architecture Fork (OQ#2)

Two approaches to user token acquisition:

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| **A: Adopt `AgentApplication`** | Replace raw `CloudAdapter` with SDK's `AgentApplication` + `UserAuthorization` layer | Native auto-sign-in, OBO handlers, less code | Bigger structural change to wrapper; may conflict with custom CloudAdapter setup |
| **B: Manual token client** | Keep raw `CloudAdapter`; drive the user-token client manually | Minimal structural change; full control | More code; must implement sign-in card emission + invoke handling manually |

**Recommendation**: Approach A if the Python SDK exposes `AgentApplication` with
the same OAuth/OBO surface as .NET. Approach B as fallback if the Python API
surface is incomplete (OQ#4).

### Patterns to Follow

- **`CredentialResolver` interface** — existing abstract class in
  `parrot/auth/credentials.py`. The new resolver should subclass this.
  *Evidence*: F007
- **`_pctx_var` ContextVar pattern** — existing per-request context in
  `parrot/auth/context.py`. Extend or parallel for credential context.
  *Evidence*: F007
- **Integration wrapper pattern** — follow the structure established by
  `MSAgentSDKWrapper` for config-driven setup.
  *Evidence*: F005

### Per-Resource Auth Design

| Tool | IdP | Mechanism | Azure Bot OAuth Connection | Sign-in UX |
|------|-----|-----------|---------------------------|------------|
| `o365` / Graph | Entra | Azure Bot OAuth connection (Entra v2) → user token; OBO native | `graph_sso` | native sign-in card / Teams SSO |
| `work-iq` | Entra | same Entra connection; OBO to Work IQ scopes | shared with `o365` | shared sign-in |
| `jira` | Atlassian | Azure Bot OAuth connection (generic OAuth2) | `jira_oauth` | native sign-in card |
| `fireflies` | none | static API key — does NOT fit OAuth model | — | custom capture |

One Entra sign-in amortizes across `o365` + `work-iq` (same connection, OBO to
different scopes). Jira is a separate connection but still native.

### Integration Risks

- **Spike gate (OQ#1)**: if Copilot Studio does not relay sign-in cards / invoke
  activities, the entire native OAuth path is unavailable on that surface. Fallback
  is the A2A-style link-out — significantly more code.
  *Evidence*: research §8.1

- **Python SDK API gap (OQ#4)**: the documented OBO/turn-token APIs
  (`GetTurnTokenAsync`, `ExchangeTurnTokenAsync`, `UserAuthorization`,
  `OBOConnectionName`, `OBOScopes`) are .NET names. Python equivalents are
  unverified. If absent, Approach A is unavailable.
  *Evidence*: research §3

- **`invoke` timeout**: long-running ai-parrot turns vs the synchronous-response
  requirement of `invoke` activities. Sign-in invokes must respond within the
  framework's timeout window.
  *Evidence*: research §8.7

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | BF Token Service provides managed per-user OAuth with server-side storage and refresh | F005, research §1 sources | high | documented in multiple Microsoft sources; verified SERVICE_CONNECTION pattern shows SDK auth integration works |
| C2 | `on_turn` ignores `invoke` activities — sign-in round-trip cannot complete | F006 | high | direct code read; test confirms ignore behavior |
| C3 | Only `SERVICE_CONNECTION` exists — no user-facing OAuth | F005, F008 | high | direct code read of wrapper + config model |
| C4 | `_handle_message` has no token injection path | F006, F007 | high | direct code read; `ask()` signature confirmed |
| C5 | `CredentialResolver` abstract class exists and can be subclassed | F007 | high | direct code read |
| C6 | `_pctx_var` ContextVar exists for per-request context | F007 | high | direct code read |
| C7 | Identity is channel-only (`from_property.id`); no `aad_object_id` | F006 | high | direct code read |
| C8 | `AuditLedger` does not exist — must be built | F007 | high | grep found zero results |
| C9 | MCS empty-200 patch is evidence of Copilot Studio connector quirks | F003 | high | direct code read |
| C10 | OBO exchange requires an exchangeable token with `api://botid-{clientId}/defaultScopes` | research §3, sources | medium | documented for .NET; Python equivalent unverified |
| C11 | Three of four tools fit native OAuth connections | research §2 | medium | design inference from documented OAuth connection capabilities; Jira generic OAuth2 unverified in practice |
| C12 | Copilot Studio relays sign-in cards + invoke activities to SDK agents | research §8.1 | low | **UNVERIFIED — this is the spike gate**; documented for Teams/Web Chat but not confirmed for Copilot/pva-studio channel |
| C13 | Python SDK exposes OBO/turn-token APIs equivalent to .NET | research §3, §8.4 | low | docs state "for all languages, details similar" but no Python-specific confirmation |
| C14 | Fireflies does not offer OAuth/MCP-OAuth | research §2.1 | low | not investigated; carried from A2A research |

Distribution: **9** high, **2** medium, **3** low.

> The two low-confidence claims (C12, C13) are load-bearing for the
> recommended architecture. Overall confidence is **high for the gap analysis
> and design direction**, but the implementation path depends on the spike gate.

---

## 5. Open Questions

### Resolved (during proposal phase)

*None — this is a new proposal.*

### Unresolved (defer to spike / spec)

- [ ] **OQ#1 [SPIKE GATE]: Does Copilot Studio relay the OAuth sign-in card + `tokens/response` / `signin/*` invoke to a connected M365 Agents SDK agent?** — *Owner*: Jesus
  *Blocks claims*: C12
  *Plausible answers*: a) yes, fully relayed · b) partially (card renders but invoke is swallowed by MCS) · c) no, Copilot surface does not support interactive sign-in
  *If negative*: fall back to A2A-style link-out for all tools on the Copilot surface

- [ ] **OQ#2: Architecture fork — adopt `AgentApplication` + `UserAuthorization` vs keep raw `CloudAdapter`?** — *Owner*: Jesus
  *Blocks claims*: C10, C13
  *Plausible answers*: a) adopt AgentApplication (less code, native OBO) · b) keep CloudAdapter (minimal change, full control) · c) hybrid (CloudAdapter + manual UserAuthorization import)
  *Depends on*: OQ#4 (Python API surface)

- [ ] **OQ#3: Does Copilot Studio forward the end user's identity (`aad_object_id`) or Copilot's service identity?** — *Owner*: Jesus
  *Blocks claims*: C7
  *Plausible answers*: a) user's AAD object id in `from.aad_object_id` · b) Copilot's service identity · c) depends on channel configuration

- [ ] **OQ#4: Python SDK API surface for OBO/turn-token** — *Owner*: Jesus
  *Blocks claims*: C10, C13
  *Action*: inspect `microsoft_agents.*` Python packages for `UserAuthorization`, `GetTurnTokenAsync` / `ExchangeTurnTokenAsync` equivalents

- [ ] **OQ#5: Fireflies — OAuth/MCP-OAuth vs static API key** — *Owner*: tbd
  *Blocks claims*: C14
  *Plausible answers*: a) Fireflies offers OAuth → model as generic BF connection · b) static key only → custom link-out

- [ ] **OQ#6: Token-service vs parrot-vault custody for non-Microsoft tokens (Jira)** — *Owner*: Jesus
  *Blocks claims*: C11
  *Plausible answers*: a) rely solely on BF Token Service · b) mirror into parrot vault for portability/audit independence

- [ ] **OQ#7: `invoke` timeout vs long-running ai-parrot turns** — *Owner*: Jesus
  *Blocks claims*: C2
  *Plausible answers*: a) sign-in invokes are fast (token verification only) — no conflict · b) need async invoke handler that responds immediately and resumes processing

---

## 6. Recommended Next Step

**Spike first** (OQ#1), then `/sdd-spec FEAT-259` — *Rationale*: the gap analysis
and design direction have high confidence (C1-C9), but the implementation path
is gated on whether Copilot Studio supports the native sign-in flow. The spike
resolves OQ#1, OQ#3, and partially OQ#4 in one experiment.

### Spike Plan

1. **Sign-in relay (the gate, OQ#1).** Configure one Azure Bot OAuth connection
   (Graph). Force a turn that requires the token; observe whether a sign-in card
   renders in the Copilot Studio test pane and whether a `signin/verifyState` /
   `tokenExchange` invoke comes back to the endpoint. Log the raw invoke.
   Resolves OQ#1, OQ#3.
2. **OBO exchange** for one Graph scope, then a Work IQ scope off the same
   connection. Resolves OQ#4, confirms §3 design.
3. **Token→tool bridge**: set `_pctx_var` from the resolved token; confirm a
   tool inside ai-parrot can use it via `CredentialResolver`.
4. **Fireflies decision** (OQ#5): probe for OAuth; if none, prototype the
   link-out capture.

### Alternatives

- **`/sdd-brainstorm FEAT-259`** — if you want to explore alternative auth
  architectures (e.g., pure A2A path, hybrid, or third-party token broker).
- **`/sdd-spec FEAT-259`** directly — if you accept the spike risk and want to
  spec optimistically (spec both paths: native OAuth + link-out fallback).
- **Manual review** — the spike gate makes this the safest path before committing
  to implementation scope.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-259/state.json` |
| Source (raw) | `sdd/state/FEAT-259/source.md` |
| Research (original) | `sdd/proposals/auth-obo-research.md` |
| Findings (digests) | `sdd/state/FEAT-259/findings/F001-*.md` through `F008-*.md` |
| Parent proposal | `sdd/proposals/microsoft-copilot-agent-sdk.proposal.md` |
| Related brainstorm | `sdd/proposals/brainstorm-copilot-a2a-percredential.md` |

**Budget consumed**:
- Files read: 12 / 40
- Grep calls: 11 / 25
- Git calls: 3 / 10
- Wall time: — / 300s
- Truncated: **no**

**Mode determination**: `enrichment` — the source is a completed research
document with verified findings; the proposal enriches it into the standard
format with codebase grounding.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Source document | `sdd/proposals/auth-obo-research.md` |
| Operator | Jesus / Claude |
| Research verification | All 14 claims in §6 of source verified against codebase (2026-06-26) |
| Key divergence from A2A path | BF Token Service replaces custom OAuth dance, storage, suspend/resume |
