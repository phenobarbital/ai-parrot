---
type: Wiki Overview
title: 'TASK-1670: AgentDefinition credential config + broker build + in-package manifest
  loader'
id: doc:sdd-tasks-completed-task-1670-agent-config-and-manifest-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 4 + resolved questions (config source = per-agent + in-package
  manifest).
relates_to:
- concept: mod:parrot.auth.broker
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
---

# TASK-1670: AgentDefinition credential config + broker build + in-package manifest loader

**Feature**: FEAT-264 — Unified Credential Broker
**Spec**: `sdd/specs/unified-credential-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1667, TASK-1669
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 + resolved questions (config source = per-agent + in-package manifest).
Lets each agent declare its credentialed providers and have the broker built at
`configure()` and handed to the `ToolManager`.

---

## Scope

- Add a `credentials: list[ProviderCredentialConfig]` config field to `AbstractBot`
  (accept via `__init__`/`**kwargs`; default empty).
- In `AbstractBot.configure()` (:1241), build a `CredentialBroker.from_config(...)` with
  injected deps (vault, o365 interface/manager, audit ledger) and hand it to the
  `ToolManager` so the seam (TASK-1669) can use it.
- Implement an **in-package** YAML manifest loader
  (`parrot/auth/manifest.py`) that parses a `credentials:` block (shape analogous to
  `env/integrations_bots.yaml`) into `list[ProviderCredentialConfig]`, with env-var
  fallback for secrets.
- Unit tests: agent builds a broker from declarative config; manifest loader parses a
  representative YAML.

**NOT in scope**: the broker/factory (1667), the seam (1669), surface wiring (1672–1674).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `credentials` field; build broker in `configure()`; pass to `ToolManager` |
| `packages/ai-parrot/src/parrot/auth/manifest.py` | CREATE | in-package YAML → `ProviderCredentialConfig` loader |
| `packages/ai-parrot/tests/unit/test_credential_manifest.py` | CREATE | loader + agent-build tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.broker import CredentialBroker                 # TASK-1667
from parrot.auth.credentials import ProviderCredentialConfig    # TASK-1667
```

### Existing Signatures to Use
```python
# parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, ToolInterface, ...):          # :156
    def __init__(self, name='Nav', system_prompt=None, llm=None, tools=None, ..., **kwargs)  # :248
    # :342 self.tool_manager = ToolManager(logger=..., debug=..., include_search_tool=...)
    async def configure(self, app=None) -> None                  # :1241  (build broker HERE)
```

### Does NOT Exist
- ~~`credentials` / `oauth_connections` / `obo_scopes` on `AbstractBot`~~ — none today (only on `MSAgentSDKConfig`).
- ~~an in-package loader for `env/integrations_bots.yaml`~~ — it is parsed by the external Navigator layer; create the in-package loader here.

---

## Implementation Notes
- Secrets resolved by navconfig env-vars (per project rules); the manifest stores
  references/keys, not raw secrets. Reuse the `MSAgentSDKConfig.__post_init__` env-JSON
  pattern as precedent (do not import it — it lives in the satellite).
- Build the broker only when `credentials` is non-empty; otherwise leave the `ToolManager`
  broker-less (no behavior change for agents without credentialed tools).

## Acceptance Criteria
- [ ] An agent with a `credentials` config builds a `CredentialBroker` at `configure()` and the seam can use it.
- [ ] The in-package manifest loader parses a `credentials:` YAML block into configs.
- [ ] Agents without credential config are unaffected.
- [ ] `pytest packages/ai-parrot/tests/unit/test_credential_manifest.py -v` passes; `ruff` clean.

## Agent Instructions
Standard SDD flow.

## Completion Note
*(Agent fills this in when done)*
