# TASK-5499: `AgentTalk` MCP restore reads secrets through `retrieve_vault_credential`

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Vault access is centralised", §3 Module 4, decision `vault-access-through-vault-utils`.
`AgentTalk._restore_user_mcp_servers` opens DocumentDB itself to read `user_credentials`, ignoring
`VAULT_STORE`. `agent.py` already imports `retrieve_vault_credential` (line 56); this task uses it, so the
restore honours whatever backend `vault_utils` resolves (Redis by default once TASK-5497 lands — this task
does not need TASK-5497: it only calls an existing function).

---

## Scope

- Replace the `async with DocumentDb() as db:` block (agent.py:1217-1236) with
  `secret_params = await retrieve_vault_credential(user_id, config.vault_credential_name)`.
  `KeyError` → the existing "Vault credential '%s' missing for server '%s', skipping" warning + `continue`;
  any other exception → the existing "failed to decrypt Vault credential" warning + `continue`.
- Keep the early keyring check (`get_vault_keyring()`, "vault unavailable, skipping restore") unchanged.
- Remove imports that become unused: `DocumentDb` (line 43, its only use), the local
  `from parrot.security.credentials_utils import credential_context` (line 1195), and
  `_decrypt_credential` (line 49) if no other use remains.
- Update `test_mcp_restore_hook.py` to patch `parrot.handlers.agent.retrieve_vault_credential`.

**NOT in scope**: `MCPPersistenceService` (TASK-5504), `CredentialsHandler` (TASK-5498).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | secret lookup via `retrieve_vault_credential`; drop unused imports |
| `packages/ai-parrot/tests/unit/test_mcp_restore_hook.py` | MODIFY | patch `retrieve_vault_credential` instead of `DocumentDb` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.security.vault_utils import retrieve_vault_credential   # verified: agent.py:56 (already imported)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py
from ..interfaces.documentdb import DocumentDb                       # line 43 — only use is line 1217
from .credentials_utils import decrypt_credential as _decrypt_credential  # line 49 — `grep -c _decrypt_credential` = 2 (import + line 1232)
from parrot.security.vault_utils import retrieve_vault_credential   # line 56
class AgentTalk(BaseView):                                           # line 133
    async def _restore_user_mcp_servers(...)                         # line 1127
        # line 1195: from parrot.security.credentials_utils import credential_context   (only used at 1234)
        # line 1196-1198: get_vault_keyring() early check — KEEP
        # lines 1217-1236: async with DocumentDb() as db: … doc = await db.read_one("user_credentials", {...}) …
        #                  secret_params = _decrypt_credential(doc["credential"], credential_context(...), keyring)

# packages/ai-parrot/src/parrot/security/vault_utils.py:145
async def retrieve_vault_credential(user_id: str, vault_name: str) -> Dict[str, Any]:  # KeyError when absent

# packages/ai-parrot/tests/unit/test_mcp_restore_hook.py
#   line 193 test_logs_warning_when_vault_credential_missing patches "parrot.interfaces.documentdb.DocumentDb" (line 210)
```

### Does NOT Exist
- ~~`DocumentDb` in `parrot.handlers.agent` after this task~~ — tests must not patch it.
- ~~`retrieve_vault_credential(..., keyring=...)`~~ — no keyring parameter; it loads the keyring itself.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/agent.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_mcp_restore_hook.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk._restore_user_mcp_servers",
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#retrieve_vault_credential"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Replace the DocumentDB block — *why*: the restore must honour `VAULT_STORE` (AC5, AC8).
2. Remove the imports that became unused — *why*: ruff F401; `DocumentDb` must disappear from `agent.py` (AC5 grep in TASK-5512).
3. Update the missing-credential test and run the module.

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async with DocumentDb() as db:' packages/ai-parrot-server/src/parrot/handlers/agent.py)
# REPLACE lines 1216-1236 (the `try:` that opens `async with DocumentDb() as db:` through the `_decrypt_credential(...)`
#   assignment) with:
                    try:
                        secret_params = await retrieve_vault_credential(user_id, config.vault_credential_name)
                    except KeyError:
                        self.logger.warning(
                            "MCP restore: Vault credential '%s' missing " "for server '%s', skipping",
                            config.vault_credential_name,
                            config.server_name,
                        )
                        continue
# keep the existing `except Exception as exc:` "failed to decrypt Vault credential" branch that follows.
# FILL IN: make the indentation/try structure match the surrounding loop exactly; keep the outer `except Exception`.
```
**Why**: identical log lines and control flow; only the source of the secret changes.

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY — imports)
```python
# occurrences: 1 (verified: grep -c 'from ..interfaces.documentdb import DocumentDb' .../handlers/agent.py) — DELETE line 43
# occurrences: 1 (verified: grep -c 'from parrot.security.credentials_utils import credential_context' .../agent.py) — DELETE line 1195
# FILL IN: delete `from .credentials_utils import decrypt_credential as _decrypt_credential` (line 49) only if
#   `grep -c _decrypt_credential` is 1 after the edit; keep `get_vault_keyring` (still used at 1196-1198).
```

### `packages/ai-parrot/tests/unit/test_mcp_restore_hook.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'patch("parrot.interfaces.documentdb.DocumentDb", return_value=mock_db_cm)' ...)
# In test_logs_warning_when_vault_credential_missing (line 193): replace the DocumentDb patch (line 210) with
#   patch("parrot.handlers.agent.retrieve_vault_credential", side_effect=KeyError("missing")),
# and drop the now-unused mock_db_cm setup.
# FILL IN: add one test that a stored secret is merged into the factory kwargs
#   (patch retrieve_vault_credential with AsyncMock(return_value={"api_key": "k"})).
```

### FILL IN checklist
- [ ] try/except structure matches the loop
- [ ] `_decrypt_credential` import removed only if unused
- [ ] new "secret merged" test

---

## Acceptance Criteria

- [ ] `agent.py` has no `DocumentDb` reference (AC5)
- [ ] Missing credential → warning + server skipped; present → secret merged into factory kwargs
- [ ] `test_mcp_restore_hook.py` passes
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/agent.py` clean

---

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/test_mcp_restore_hook.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_mcp_restore_hook.py — added test
async def test_restore_merges_vault_secret(self) -> None:
    # FILL IN: mirror test_restores_server_without_vault_needed (line 257) with vault_credential_name set and
    #   patch("parrot.handlers.agent.retrieve_vault_credential", new=AsyncMock(return_value={"api_key": "k"}));
    #   assert the factory received api_key="k".
    ...
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§2 Vault access is centralised, §3 M4)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** (re-run each `grep -c`)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5499 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
