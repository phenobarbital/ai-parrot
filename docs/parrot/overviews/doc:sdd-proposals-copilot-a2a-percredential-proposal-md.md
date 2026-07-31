---
type: Wiki Overview
title: FEAT-263 — AI-Parrot ⇄ M365 Copilot via A2A, with parrot-owned per-user tool
  credentials
id: doc:sdd-proposals-copilot-a2a-percredential-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Continuation of in-progress work integrating one AI-Parrot agent (bundling
---

---
id: FEAT-263
title: Publish AI-Parrot as an A2A connected agent in M365 Copilot with parrot-owned per-user tool credentials
slug: copilot-a2a-percredential
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-26
  summary_oneline: Expose an AI-Parrot agent to M365 Copilot over A2A with parrot-owned per-user credential acquisition
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-263/
created: 2026-06-26
updated: 2026-06-26
---

# FEAT-263 — AI-Parrot ⇄ M365 Copilot via A2A, with parrot-owned per-user tool credentials

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `file: sdd/proposals/brainstorm-copilot-a2a-percredential.md`
> **Audit**: [`sdd/state/FEAT-263/`](../state/FEAT-263/)

---

## 0. Origin

Continuation of in-progress work integrating one AI-Parrot agent (bundling
`work-iq`, `fireflies.ai`, and `jira` tools) into the Microsoft 365 Copilot
surface via the Agent-to-Agent (A2A) protocol. The base artifact is the
brainstorm `sdd/proposals/brainstorm-copilot-a2a-percredential.md` (full source
preserved at `sdd/state/FEAT-263/source-original.md`).

> "We have great advances of integrating one ai-parrot Agent into Microsoft
> Copilot using Agent-to-Agent protocol… The hard part is **not** the
> connection. It is per-user tool authentication." — brainstorm §1

**Initial signals** (extracted, not interpreted):
- Verbs: "publish", "acquire", "persist", "reuse" → a build-out, not a bug.
- Named entities: A2A, AgentCard, Copilot Studio, `work-iq`, `jira`,
  `fireflies`, Entra OBO, Atlassian 3LO, CredentialResolver, vault.
- Decision state: **Model B (credential custody in parrot) — CLOSED**.
- Spike gate carried in: OQ#1 (inbound user identity).

---

## 1. Synthesis Summary

The brainstorm frames per-user credential acquisition as mostly new machinery.
Codebase research overturns that framing: **~70% of the "must be built" list
already exists.** `CredentialResolver` already encodes the link-out contract
(`resolve()→None` signals "surface `get_auth_url()`"); a full OAuth2
`IntegrationsService` with a **jira + o365** provider registry, state-nonce
issuance, and a parrot-owned OAuth callback web surface (`oauth2_routes`) is
already in place; `SuspendedExecutionStore`, the `AbstractTool` output-scrubber
seam, Entra **OBO** (`o365.acquire_token_on_behalf_of`), PBAC, and
`VaultTokenSync` all exist. The **AgentCard serialization fix has already
landed** (camelCase + a documented decision to *omit* `supportedInterfaces`),
superseding the brainstorm's §11 dual-emit plan. The genuinely-new, in-scope
work is therefore narrow: the **A2A↔credential bridge** inside
`A2AServer.process_message` (identity extraction + suspend-on-missing-credential
+ consent-link response + OAuth-callback-as-resume-trigger), **building the
`work-iq` tool** (which does not exist) on the existing OBO, wiring **fireflies
as an MCP-credential integration** (it is MCP-based), and **building the
`AuditLedger`** (which does not exist at all — operator confirmed it is in
scope). The OQ#1 identity spike gate is **resolved YES** by the operator.
Recommendation: proceed to `/sdd-spec` with a tightly-bounded new surface over
verified primitives.

---

## 2. Codebase Findings

> Grounded in `sdd/state/FEAT-263/findings/`. Every entry cites the finding ID(s)
> that justify it. No fabricated paths or symbols.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/auth/credentials.py` | `CredentialResolver` | 27-111 | `resolve(channel,user_id)→creds\|None` + `get_auth_url` — **the link-out contract** | F001 |
| 2 | `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | `IntegrationsService` | 67-333 | `start_connect`(auth_url+nonce), `persist_credential`, registry w/ jira+o365 | F002 |
| 3 | `packages/ai-parrot/src/parrot/auth/oauth2_routes.py` | `setup_oauth2_routes` / `make_oauth2_callback` | 151-221 | parrot-owned OAuth callback web surface; origin allowlist; `handle_callback(code,state)` | F003 |
| 4 | `packages/ai-parrot-server/src/parrot/human/suspended_store.py` | `SuspendedExecutionStore` | 64-162 | Redis suspend/resume; today resume = HITL message | F004 |
| 5 | `packages/ai-parrot/src/parrot/a2a/models.py` | `AgentCard.to_dict` | 353-385 | camelCase card; **deliberately omits `supportedInterfaces`** | F005 |
| 6 | `packages/ai-parrot-server/src/parrot/a2a/server.py` | `A2AServer.process_message` | 245-332 | **GAP**: no identity, no credential check, no suspend — the core new bridge | F006 |
| 7 | `packages/ai-parrot/src/parrot/tools/abstract.py` | `AbstractTool` (output scrubber) | 98-637 | single output-scrub seam — "no secrets in conversational plane" | F008 |
| 8 | `packages/ai-parrot/src/parrot/interfaces/o365.py` | `acquire_token_on_behalf_of` | 621-660 | Entra OBO implemented — reuse for work-iq + o365 | F009 |
| 9 | `packages/ai-parrot/src/parrot/services/vault_token_sync.py` | `VaultTokenSync.store_tokens` | — | encrypted per-user token persistence (custody store) | F011 |

> `PermissionContext` (multi-tenant isolation, brainstorm §6 invariant #5) also
> exists at `packages/ai-parrot/src/parrot/auth/permission.py` with PBAC at
> `auth/pbac.py` and `auth/dataplane_guard.py` (referenced by the telegram
> wrapper and `IntegrationsService._check_pbac`).

### 2.2 Constraints Discovered

- **`resolve()==None` is already the credential-acquisition signal.** The
  link-out flow is a *contract*, not a new invention. *Implication*: build the
  A2A bridge ON `CredentialResolver`; do not introduce a parallel resolver.
  *Evidence*: F001

- **OAuth callback surface is auth-middleware-excluded and origin-allowlisted.**
  `make_oauth2_callback` delegates token exchange to `manager.handle_callback`,
  validates `return_origin` against `WEB_OAUTH_ALLOWED_ORIGINS`, and requires
  `user_id` in the state payload. *Implication*: A2A consent links must reuse
  this surface; the **new** piece is correlating the callback back to a
  *suspended A2A task* by nonce (today it resumes the web/chat session).
  *Evidence*: F003, F002

- **`SuspendedExecutionStore` resume assumes a human-approver message.** Resume
  today rehydrates tool-loop state and injects a human's answer as the
  `ask_human` tool_result. *Implication*: the OAuth-callback / form-POST resume
  trigger is genuinely new, exactly as brainstorm §5/§8 states. The
  `user_id` field is already first-class. *Evidence*: F004

- **Output scrubbing happens at exactly one seam.** `AbstractTool` scrubs
  result+error at one boundary ("the ONLY place scrubbing happens on the way
  out"). *Implication*: invariants #1/#3 ("no secrets in the conversational
  plane") have a real enforcement point to extend. *Evidence*: F008

- **AgentCard serialization is already correct.** `to_dict` emits camelCase and
  intentionally omits `supportedInterfaces` (verified against a2a-dotnet: v0.3
  uses `additionalInterfaces`; flat `url`+`preferredTransport` are required and
  sufficient). *Implication*: brainstorm §11 dual-emit is **superseded**;
  remaining card risk is empirical autopopulate (OQ#9), not code. *Evidence*: F005

### 2.3 Recent History (Relevant)

| Commit | Area | Message |
|--------|------|---------|
| `6d9b8b3ed` | a2a core | **wip: a2a server + ms agent sdk** (this work is in flight) |
| `05885166d` | ai-parrot-server | TASK-1370 — Move A2A server files to satellite |
| `e7c97b7c3` | ai-parrot-server | TASK-1367 — lazy `__getattr__` on host `__init__` |
| `b865256f4` | auth/oauth2 | TASK-1342 — OAuth2 Relocation to `parrot/auth/oauth2/` |
| `ebe33d620` | auth/oauth2 | fix code-review issues |

> Confirms continuation-work, not greenfield. The spec must coordinate with the
> in-flight MS Agent SDK branch (FEAT-259 msagentsdk tenant-auth). *Evidence*: F011

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **A2A↔credential bridge** in `A2AServer.process_message` — derive per-user
  identity from the A2A request (OQ#1 resolved: identity is present), check
  `CredentialResolver`, and on a missing credential **suspend** the task and
  return a TEXT artifact carrying the consent link from `get_auth_url`.
  *Evidence*: F006, F001
- **OAuth-callback / form-POST resume trigger** correlated by nonce to a
  *suspended A2A task* (the existing callback resumes web/chat, not A2A).
  *Evidence*: F003, F004
- **`work-iq` tool** — does not exist anywhere; build it on the existing O365
  OBO (`acquire_token_on_behalf_of`). *Evidence*: F010, F009
- **`AuditLedger` (full, KMS-signed, append-only)** — does not exist; operator
  confirmed it is IN scope; records `key_fingerprint` per credentialed
  invocation. *Evidence*: F007

### What Changes

- **`A2AServer.process_message`** gains identity + credential-gate + suspend
  (currently delegates straight to `agent.ask`). *Evidence*: F006
- **fireflies** is wired as an MCP-credential integration reusing the telegram
  `mcp_persistence` (`vault_credential_name`) precedent, not a bespoke api-key
  form. *Evidence*: F010

### What's Untouched (Non-Goals)

- AgentCard serialization (already fixed — do not re-open `to_dict`). *Evidence*: F005
- OAuth2 `IntegrationsService` / provider registry / `users_integrations` +
  `user_agent_toolkits` schema (reuse as-is). *Evidence*: F002
- `VaultTokenSync`, `CredentialResolver`, the scrubber seam (reuse). *Evidence*: F001, F008, F011
- Making parrot a *standalone* Copilot/Outlook sidebar agent (separate track,
  per brainstorm §2 non-goals).

### Patterns to Follow

- `CredentialResolver.resolve → get_auth_url` link-out. *Evidence*: F001
- `IntegrationsService.start_connect` nonce + `return_origin` allowlist. *Evidence*: F002, F003
- telegram `post_auth_jira` nonce→callback→`VaultTokenSync.store_tokens`. *Evidence*: F011, F010

### Integration Risks

- **In-flight MS Agent SDK WIP** (`6d9b8b3ed`) + FEAT-259 tenant-auth — must
  coordinate to avoid divergence on the A2A server surface. *Evidence*: F011
- **`AuditLedger` is greenfield + KMS** — the single largest new build; its
  KMS-signing dependency and append-only store are non-trivial and gate the
  acceptance criteria. *Evidence*: F007
- **Two unverified externals** (work-iq OBO, fireflies MCP auth) — see §5;
  neither blocks the bridge, but both block their respective tool's completion.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `CredentialResolver` exists with `resolve`/`get_auth_url` link-out | F001 | high | direct read |
| C2 | Full OAuth2 `IntegrationsService` + jira/o365 registry + nonce + persistence exists | F002 | high | direct read |
| C3 | Parrot-owned OAuth callback web surface exists (`oauth2_routes`) | F003 | high | grep + line read |
| C4 | `SuspendedExecutionStore` exists; OAuth-callback resume trigger is new | F004 | high | direct read |
| C5 | `AgentCard.to_dict` already camelCase + omits `supportedInterfaces` — §11 superseded | F005 | high | direct read incl. decision NOTE |
| C6 | `A2AServer.process_message` has no identity/credential/suspend — the core gap | F006 | high | direct read |
| C7 | `AuditLedger` / `key_fingerprint` do not exist anywhere | F007 | high | exhaustive grep = 0 |
| C8 | Entra OBO implemented (`o365.acquire_token_on_behalf_of`), reusable for work-iq | F009 | high | grep + read |
| C9 | work-iq does not exist; fireflies is MCP-based not a native toolkit | F010 | high | 0 work-iq hits; fireflies only under `parrot/mcp` + telegram MCP |
| C10 | Copilot low-code A2A connection delivers a verifiable per-user identity | — | medium | OQ#1 confirmed YES by operator; no codebase artifact to cite yet |
| C11 | work-iq public preview supports Entra OBO with known resource id/scopes | — | low | external API unknown (OQ#5); to verify during spec |

Distribution: **9** high, **1** medium, **1** low.

> Overall confidence is **medium**, not high: the reuse story is rock-solid
> (C1–C9), but the two implementation-completing externals (C10 partially, C11)
> remain unverified, and the operator-confirmed full `AuditLedger` build is
> greenfield with a KMS dependency.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **OQ#1 — Does Copilot's low-code A2A connection deliver a verifiable
  per-user identity?** — *Resolved*: **Yes**, identity is present in the A2A
  request; vault-keying proceeds directly, no parrot-run Entra sign-in needed to
  bootstrap. *Resolves claims*: C10. *Spec note*: cite exactly where in the
  payload the identity claim lands so `process_message` extracts it
  deterministically.
- [x] **AuditLedger fate** — *Resolved*: **Build the full append-only,
  KMS-signed `AuditLedger`** as part of this feature; `key_fingerprint` per
  credentialed invocation is a hard AC. *Resolves claims*: C7.

### Unresolved (defer to spec / implementation)

- [ ] **OQ#6 — Is fireflies' MCP server static-API-key or MCP-OAuth?** —
  *Owner*: tbd. *Blocks*: C9 (fireflies completion). *Direction*: bias to
  static-key-over-MCP (reuse telegram `mcp_persistence` `vault_credential_name`)
  for v1; revisit if the server requires OAuth.
- [ ] **OQ#5 — Does work-iq (public preview) support Entra OBO? resource id +
  scopes + admin-consent?** — *Owner*: tbd. *Blocks*: C11. *Direction*: verify
  empirically; if no OBO, fall back to delegated 3LO via a new oauth2 provider
  (reusing the `IntegrationsService` registry pattern).
- [ ] **OQ#9 — AgentCard autopopulate** — *Owner*: tbd. *Note*: code fix is
  done (F005); confirm empirically via served-card dump + access-log (no code
  change expected).
- [ ] **OQ#2 — Does Copilot's A2A client support `input-required` + resume?** —
  *Owner*: tbd. *Direction*: robust default is link-in-response → user
  re-prompts after consent, regardless.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-263`** — *Rationale*: localization and the reuse story are
high-confidence (C1–C9); the new surface is a tightly-bounded **bridge over
verified primitives** rather than an architectural fork. The OQ#1 identity gate
is resolved, removing the spike-first blocker. The spec must encode two items as
first-class scope (not assumptions): the full `AuditLedger` build (U2) and the
two external verifications (work-iq OBO, fireflies MCP auth) as gated sub-tasks.

### Alternatives

- **`/sdd-brainstorm FEAT-263`** — not recommended; no architectural fork
  remains now that identity (OQ#1) is resolved.
- **`/sdd-task FEAT-263`** — premature; this is multi-component (bridge +
  work-iq + fireflies + AuditLedger), not a single localized fix.
- **Manual review** — not needed; research is complete (not truncated).

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-263/state.json` |
| Source (raw) | `sdd/state/FEAT-263/source.md` (+ `source-original.md`) |
| Research plan | `sdd/state/FEAT-263/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-263/findings/F001-*.md` … `F011-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-263/synthesis.json` |

**Budget consumed**:
- Files read: 7 / 40
- Grep calls: 11 / 25
- Git calls: 2 / 10
- Truncated: **no**

**Mode determination**: `enrichment` (rich brainstorm with a CLOSED core
decision + partial spike; research grounded/overturned its anchors rather than
exploring greenfield options).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus (via Claude Code) |
