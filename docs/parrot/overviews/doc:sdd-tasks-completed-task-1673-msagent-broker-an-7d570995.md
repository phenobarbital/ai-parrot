---
type: Wiki Overview
title: 'TASK-1673: MSAgentSDK — consume broker + render Adaptive/OAuth cards'
id: doc:sdd-tasks-completed-task-1673-msagent-broker-and-cards-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 7 (part 1). Cables the MSAgentSDK chat path to the broker
  and renders the
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.identity
  rel: mentions
---

# TASK-1673: MSAgentSDK — consume broker + render Adaptive/OAuth cards

**Feature**: FEAT-264 — Unified Credential Broker
**Spec**: `sdd/specs/unified-credential-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1667, TASK-1669, TASK-1671
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (part 1). Cables the MSAgentSDK chat path to the broker and renders the
single `CredentialRequired` signal as the right card: Adaptive Card (static key) or
OAuthCard (OAuth/OBO). Retires the dead `_resolver_var` and the stub OBO.

---

## Scope

- In `_handle_message`, feed identity through `CanonicalIdentityMapper` and make the
  broker reachable by the tool-loop seam (TASK-1669) during `agent.ask()`.
- Catch the canonical `CredentialRequired(provider, auth_url, auth_kind)` and render:
  - `auth_kind in {oauth2, obo}` → OAuthCard (existing `_emit_oauth_card` precedent).
  - `auth_kind == static_key` → Adaptive Card containing the OOB capture link; plain-text
    link fallback for channels that cannot render cards.
- Remove the dead `_resolver_var` plumbing and the stub `_obo_exchange`; OBO now flows
  through the broker's `obo` strategy (O365 + vault).
- Unit tests: static-key miss → Adaptive Card; OBO miss → OAuthCard; no dead resolver var.

**NOT in scope**: suspend/resume + proactive delivery (TASK-1674); the broker (1667); the
seam (1669).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py` | MODIFY | identity → mapper; catch `CredentialRequired`; render card by `auth_kind` |
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/auth.py` | MODIFY | retire `_resolver_var` + stub `_obo_exchange`; unify on core `CredentialRequired` |
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py` | MODIFY | wire broker into the bridge agent / app |
| `packages/ai-parrot-integrations/tests/unit/test_msagent_cards.py` | CREATE | card-by-auth_kind tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import CredentialRequired          # TASK-1667 (canonical)
from parrot.auth.identity import CanonicalIdentityMapper        # TASK-1671
```

### Existing Signatures to Use
```python
# integrations/msagentsdk/agent.py
class ParrotM365Agent:
    async def _handle_message(self, context)                     # :167  sets _pctx_var + _resolver_var (dead), calls parrot_agent.ask(...)
    def _extract_user_id(self, activity) -> str                  # :108  aad_object_id preferred
    async def _emit_oauth_card(self, context, connection_name, tool)  # :338  OAuthCard precedent
    async def _handle_signin_verify(self, context)               # :263  signin/verifyState
    async def _handle_signin_exchange(self, context)             # :288  signin/tokenExchange

# integrations/msagentsdk/auth.py
_resolver_var: ContextVar = ...                                  # :38  SET in agent.py, NEVER READ → remove
class CredentialRequired(Exception): __init__(self, tool, connection_name)  # :41  msagentsdk-local → migrate to core
class BFTokenServiceResolver(CredentialResolver): ... _obo_exchange(...)  # :68/:319  stub OBO → remove
```

### Does NOT Exist
- ~~a reader of `_resolver_var`~~ — it is dead; this task removes it.
- ~~a working BF Token Service OBO~~ — `_obo_exchange` returns the original token; replaced by broker `obo` strategy.

---

## Implementation Notes
- Use one `CredentialRequired` (the core one from TASK-1667); migrate the msagentsdk-local
  exception and its handler.
- Adaptive Card content type: `application/vnd.microsoft.card.adaptive`; embed the
  capture URL from `NeedsAuth.auth_url`. OAuthCard stays
  `application/vnd.microsoft.card.oauth`.

## Acceptance Criteria
- [ ] Static-key miss renders an Adaptive Card with the capture link; OBO/OAuth miss renders an OAuthCard.
- [ ] `_resolver_var` and `_obo_exchange` stub removed; OBO resolves via the broker.
- [ ] Identity flows through the canonical mapper.
- [ ] `pytest packages/ai-parrot-integrations/tests/unit/test_msagent_cards.py -v` passes; `ruff` clean.

## Agent Instructions
Standard SDD flow.

## Completion Note
*(Agent fills this in when done)*
