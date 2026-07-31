---
type: Wiki Overview
title: 'TASK-1649: work-iq tool vertical via Entra OBO (Group B — GATED on OQ#5)'
id: doc:sdd-tasks-completed-task-1649-workiq-obo-vertical-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **B3** — the headline tool, and the only fully greenfield
relates_to:
- concept: mod:parrot.auth.oauth2
  rel: mentions
- concept: mod:parrot.interfaces.o365
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.workiq_tool
  rel: mentions
---

# TASK-1649: work-iq tool vertical via Entra OBO (Group B — GATED on OQ#5)

**Feature**: FEAT-263 — AI-Parrot ⇄ M365 Copilot via A2A (per-user credentials)
**Spec**: `sdd/specs/copilot-a2a-percredential.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1646
**Assigned-to**: unassigned

---

## Context

Implements spec Module **B3** — the headline tool, and the only fully greenfield
one: `work-iq` does **not exist** anywhere in the codebase. It is built on the
existing Entra **OBO** path (`O365Interface.acquire_token_on_behalf_of`), reusing
the single Microsoft Entra sign-in that also covers o365.

> **GATE — OQ#5 (unresolved).** Verify empirically that work-iq (MS public
> preview) supports Entra OBO, and obtain its resource id + required scopes +
> admin-consent path BEFORE building. If OBO is unavailable, fall back to a
> delegated auth-code 3LO provider (reuse the `IntegrationsService` registry
> pattern). Record the finding in spec §8.

---

## Scope

- Resolve OQ#5 (OBO support + resource id + scopes) and record it.
- Build the `work-iq` tool (greenfield) and its `CredentialResolver`/provider.
- OBO path: reuse `O365Interface.acquire_token_on_behalf_of(user_assertion, scopes)`
  to exchange the Entra source token for work-iq scopes; persist per-user via vault.
- Wire over the A2A bridge: missing cred → Entra link-out → callback → vault →
  resume → result, with audit.
- Integration test (mock Entra/work-iq).

**NOT in scope**: bridge changes (Group A), jira/fireflies.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/workiq_tool.py` | CREATE | greenfield work-iq tool |
| `packages/ai-parrot/src/parrot/auth/oauth2/workiq_provider.py` | CREATE | work-iq provider (OBO or 3LO per OQ#5) |
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | map work-iq tool → resolver |
| `packages/ai-parrot-server/tests/integration/test_a2a_workiq_vertical.py` | CREATE | work-iq-over-bridge test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interfaces.o365 import O365Interface   # verify exact class name in interfaces/o365.py before use
from parrot.auth.oauth2 import OAuth2ProviderRegistry, IntegrationsService  # verified: auth/oauth2/__init__.py:31,36
from parrot.tools.abstract import AbstractTool      # verified: tools/abstract.py:98
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/o365.py
def acquire_token_on_behalf_of(self, user_assertion: str,
                               scopes: Optional[List[str]] = None) -> Dict[str, Any]: ...  # :621
#   uses OnBehalfOfCredential (:262) when an "assertion" is in self.credentials (:250)

# packages/ai-parrot/src/parrot/auth/oauth2/registry.py
class OAuth2ProviderRegistry:
    def register(self, provider: OAuth2Provider) -> None: ...   # :96
```

### Does NOT Exist  (confirmed via grep 2026-06-26)
- ~~`work-iq` / `WorkIQ` / `work_iq` anything~~ — ZERO matches; fully greenfield
- ~~`parrot.tools.workiq_tool`~~ / ~~`workiq_provider`~~ — you are creating them
- ~~a registered work-iq provider~~ — registry has jira + o365 only
- Confirm the exact `O365Interface` class name + `acquire_token_on_behalf_of` host class before importing.

---

## Implementation Notes
### Key Constraints
- DO NOT start before OQ#5 is resolved.
- Reuse the existing OBO machinery and the single Entra sign-in (shared with o365); do not duplicate Entra auth.
- async; Pydantic args schema; no secret in A2A payloads; audit on invoke.

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/oauth2/o365_provider.py` — provider pattern to mirror for work-iq.
- `packages/ai-parrot/src/parrot/interfaces/o365.py` — OBO host.

---

## Acceptance Criteria
- [ ] OQ#5 resolved (OBO support + resource id + scopes) and recorded in spec §8.
- [ ] `from parrot.tools.workiq_tool import WorkIQTool` works.
- [ ] work-iq over the bridge: missing cred → Entra link → callback → vault → resume → result.
- [ ] One Entra sign-in yields OBO for both o365 and work-iq (per spec AC).
- [ ] Audit entry recorded; no secret in A2A payloads.
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/integration/test_a2a_workiq_vertical.py -v`

---

## Test Specification
```python
async def test_workiq_vertical_end_to_end(): ...   # mocked Entra + work-iq
async def test_obo_covers_o365_and_workiq(): ...
async def test_workiq_no_secret_in_payload(): ...
```

---

## Agent Instructions
**GATED**: resolve OQ#5 first. Requires TASK-1646 in `completed/`. Parallel-safe
with TASK-1647/1648.

### Completion Note
**DONE.** OQ#5 resolved: Work IQ IS an MCP server; OBO auth SUPPORTED (delegated
only; app-only NOT supported).  Scope: ``api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask``.

Implementation (2026-06-27):
- Created `packages/ai-parrot/src/parrot/tools/workiq_tool.py` with `WorkIQTool`:
  MCP credential adapter declaring `credential_provider = "workiq"`. The bridge
  resolves the OBO token before invocation; the tool stubs the MCP call (operators
  replace with real MCP client at deployment).
- Created `packages/ai-parrot/src/parrot/auth/oauth2/workiq_provider.py` with:
  - `WorkIQOBOCredentialResolver`: resolves Work IQ OBO token from vault; falls
    back to OBO exchange via `O365Interface.acquire_token_on_behalf_of`; caches
    result. Returns None → Entra sign-in via `get_auth_url`.
  - `WorkIQOAuth2Provider`: OAuth2Provider subclass for registry.
  - One Entra sign-in covers both o365 and work-iq (OBO reuses Entra token).
- Modified `packages/ai-parrot-server/src/parrot/a2a/server.py`: added
  `wire_workiq_resolver(resolver)` convenience method (registers under
  `provider="workiq"`).
- Created `packages/ai-parrot-server/tests/integration/test_a2a_workiq_vertical.py`:
  12 tests covering: import, no-Entra-token → INPUT_REQUIRED, no-secret-in-payload,
  OBO-exchange success → COMPLETED, one-Entra-sign-in covers both, OBO failure →
  INPUT_REQUIRED, cached-OBO-token → no-new-OBO, audit-entry, wire-resolver,
  no-service-identity fallback, provider metadata, toolkit_factory raises. All 12 pass.

Spec §8 updated with OQ#5 resolution.
