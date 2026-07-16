---
type: Wiki Overview
title: 'TASK-1647: jira tool vertical over the A2A credential bridge (Group B)'
id: doc:sdd-tasks-completed-task-1647-jira-vertical-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **B1** — the first real tool vertical. jira is the
  most
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.oauth2
  rel: mentions
---

# TASK-1647: jira tool vertical over the A2A credential bridge (Group B)

**Feature**: FEAT-263 — AI-Parrot ⇄ M365 Copilot via A2A (per-user credentials)
**Spec**: `sdd/specs/copilot-a2a-percredential.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1646
**Assigned-to**: unassigned

---

## Context

Implements spec Module **B1** — the first real tool vertical. jira is the most
reuse-ready: a native `jira_provider` is already registered in
`OAuth2ProviderRegistry`, with `jira_oauth` + `jira_connect_tool` present. This
task wires the jira tool through the v1 bridge (TASK-1642/1644/1645) so a Copilot
user can authorize jira OOB and get results. NOT part of v1 acceptance.

---

## Scope

- Register/confirm a `CredentialResolver` for `provider="jira"` that the A2A
  bridge uses (the `OAuthCredentialResolver` delegating to the jira OAuth manager).
- Ensure the jira tool runs over the bridge: missing cred → Atlassian 3LO
  link-out → callback → vault → resume → result, with audit.
- Integration test against the bridge using the jira provider (mock Atlassian).

**NOT in scope**: bridge changes (done in Group A), fireflies/work-iq.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | map jira tool → jira CredentialResolver/provider |
| `packages/ai-parrot-server/tests/integration/test_a2a_jira_vertical.py` | CREATE | jira-over-bridge test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import OAuthCredentialResolver   # verified: auth/__init__.py:47
from parrot.auth.oauth2 import OAuth2ProviderRegistry          # verified: auth/oauth2/__init__.py:31
# jira specifics — verify exact symbols before use:
#   packages/ai-parrot/src/parrot/auth/jira_oauth.py
#   packages/ai-parrot/src/parrot/auth/oauth2/jira_provider.py
#   packages/ai-parrot/src/parrot/tools/jira_connect_tool.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/registry.py
class OAuth2ProviderRegistry:
    def get(self, provider_id: str) -> Optional[OAuth2Provider]: ...  # :106  (get("jira"))

# packages/ai-parrot/src/parrot/auth/credentials.py
class OAuthCredentialResolver(CredentialResolver):   # :49
    def __init__(self, oauth_manager): ...           # delegates get_valid_token / create_authorization_url
```

### Does NOT Exist  (verify before assuming)
- ~~a jira tool already wired to the A2A bridge~~ — bridge is provider-agnostic; YOU map it
- Confirm the exact `JiraOAuthManager` class name + methods in `jira_oauth.py` before importing.

---

## Implementation Notes
### Key Constraints
- Reuse the registered jira provider; do not add a parallel jira OAuth flow.
- async; `self.logger`; no secret in A2A payloads.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/jira_specialist.py` — uses `CredentialResolver` with jira.
- `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md` — jira 3LO background.

---

## Acceptance Criteria
- [ ] jira tool over the bridge: missing cred → 3LO link → callback → vault → resume → result.
- [ ] Audit entry recorded for the jira invocation.
- [ ] No secret in any A2A payload.
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/integration/test_a2a_jira_vertical.py -v`

---

## Test Specification
```python
async def test_jira_vertical_end_to_end(): ...   # mocked Atlassian
async def test_jira_no_secret_in_payload(): ...
```

---

## Agent Instructions
Standard SDD flow. Requires TASK-1646 (v1 bridge) in `completed/`. Parallel-safe
with TASK-1648/1649 (different provider files).

### Completion Note
Implemented the Jira vertical (FEAT-260 / TASK-1647):
- Added `A2AServer.wire_jira_resolver(jira_oauth_manager)` to `server.py`: creates an
  `OAuthCredentialResolver` backed by the given `JiraOAuthManager` and registers it
  under `provider="jira"`.
- 6/6 integration tests pass: missing-credential suspend, no-secret payload, resolved
  credential runs tool, audit entry written, resolver registration, no-service-identity
  fallback. Ruff clean.
