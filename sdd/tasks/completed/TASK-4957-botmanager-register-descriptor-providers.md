# TASK-4957: BotManager registers descriptor providers and the principal resolver

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4948, TASK-4943, TASK-4952, TASK-4950
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (BotManager). `_register_oauth2_providers` only registers Jira. It must also load every descriptor
from `OAUTH2_PROVIDERS_FILE` and register it via `register_descriptor_providers` (store = Identity Vault, publisher =
the shared one), and register `IdentityPrincipalResolver(app['authdb'])` as the process-wide principal resolver.

---

## Scope

- In `_register_oauth2_providers`: keep the Jira branch; `set_principal_resolver(IdentityPrincipalResolver(app["authdb"]))`
  when `authdb` exists; if `OAUTH2_PROVIDERS_FILE` is set, `load_provider_descriptors(path)` →
  `register_descriptor_providers(descriptors, app=app, credential_store=IdentityVaultCredentialStore(authdb) or None,
  event_publisher=app.get("connection_event_publisher"))`; failures logged, never fatal (as today).
- Test `test_register_oauth2_providers_from_descriptors`.

**NOT in scope**: the descriptor YAML content for real providers (ops); Jira provider class.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | descriptor + resolver registration |
| `packages/ai-parrot-server/tests/unit/test_register_oauth2_providers.py` | CREATE | unit test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.oauth2.descriptor import load_provider_descriptors, register_descriptor_providers   # TASK-4939/4943
from parrot.auth.principal import set_principal_resolver                                             # TASK-4937
from parrot.services.identity_principal import IdentityPrincipalResolver                             # TASK-4952
from parrot.services.identity_credential_sink import IdentityVaultCredentialStore                    # TASK-4950
from parrot.conf import OAUTH2_PROVIDERS_FILE                                                        # TASK-4941
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
self.app.on_startup.append(self._register_oauth2_providers)               # :2388
async def _register_oauth2_providers(self, app: web.Application) -> None: # :2789 anchor — lazy imports inside try;
    # jira_manager = app.get("jira_oauth_manager") → register_oauth2_provider(JiraOAuth2Provider(manager=…)); except → logger.exception
```

### Does NOT Exist
- ~~a descriptor for O365~~ — O365 keeps its hand-written subclass; do not add it to the file.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_register_oauth2_providers.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._register_oauth2_providers"
  ]
}
```

---

## Implementation Notes

- `manager.setup()` inside `register_descriptor_providers` mounts routes; this runs in `on_startup`, after the router
  may be frozen — FILL IN: verify aiohttp allows `add_get` at that point in this app (the Jira manager is set up
  earlier); if not, move descriptor registration to the same phase where `JiraOAuthManager.setup()` runs and say so in the Completion Note.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Extend `_register_oauth2_providers` (block) — *why*: G3/G4 at runtime.
2. Verify the router-freeze question (notes) before relying on on_startup.
3. Test with a temp YAML + patched config.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _register_oauth2_providers(self, app: web.Application) -> None:' manager.py → :2789)
# INSIDE the existing try-block, after the Jira branch:
            authdb = app.get("authdb")
            if authdb is not None:
                from parrot.auth.principal import set_principal_resolver
                from parrot.services.identity_principal import IdentityPrincipalResolver
                set_principal_resolver(IdentityPrincipalResolver(authdb))
            from parrot.conf import OAUTH2_PROVIDERS_FILE
            if OAUTH2_PROVIDERS_FILE:
                # FILL IN: load_provider_descriptors(OAUTH2_PROVIDERS_FILE); store = IdentityVaultCredentialStore(authdb)
                #          if authdb else None; providers = register_descriptor_providers(descriptors, app=app,
                #          credential_store=store, event_publisher=app.get("connection_event_publisher"));
                #          self.logger.info("Registered %d descriptor OAuth2 providers", len(providers))
                pass
```

### FILL IN checklist
- [ ] descriptor registration body
- [ ] router-freeze verification
- [ ] `test_register_oauth2_providers_from_descriptors`

---

## Acceptance Criteria

- [ ] Descriptor providers from `OAUTH2_PROVIDERS_FILE` are in `OAuth2ProviderRegistry` after startup; the principal resolver is the Identity resolver when `authdb` exists
- [ ] A bad descriptor file is logged and does not break startup

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_register_oauth2_providers.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_register_oauth2_providers.py
@pytest.mark.asyncio
async def test_register_oauth2_providers_from_descriptors(tmp_path, monkeypatch): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-luna (codex)
**Date**: 2026-10-30
**Notes**: Implemented per task; merged, engine lint clean. Merge-tier validation: only reds are legacy tests/integration/oauth2/test_e2e_*.py owned by TASK-4964. Orchestrator also broke an oauth2_base <-> oauth2 package import cycle (separate fix commit).
