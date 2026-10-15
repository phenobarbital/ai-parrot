# TASK-4351: Update stale studio BYOK test fixtures to the vault KeyRing API

**Feature**: FEAT-677 — Studio BYOK test fixtures follow the vault KeyRing API
**Spec**: `sdd/specs/studio-byok-test-fix.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §2/§3 Module 1. Resolves ledger issue:d5a7c625fbe7. The studio
BYOK tests patch `byok.load_master_keys`, which FEAT-099 replaced with the vault
`KeyRing` (`get_vault_keyring`), and `_FakeAskBot` predates the test/ask
`bot.name` / `ask(question=, user_id=, session_id=)` contract (commit 3ee6e37fc).

---

## Scope

- In both files, replace the `patch_vault_keys` fixture's `byok_module.load_master_keys`
  / `get_active_key_id` patches with `get_vault_keyring` patches returning a real
  `KeyRing(MASTER_KEYS, MASTER_KEY_ID)` on `byok_module` and `parrot.security.vault_utils`.
- In `test_byok.py`, make `test_missing_master_keys_503` patch `byok_module.get_vault_keyring`
  with a function raising `RuntimeError`.
- In `test_integration.py`, give `_FakeAskBot` a `name` attribute and an
  `ask(question, **kwargs)` signature.

**NOT in scope**: any production source change; restoring `load_master_keys`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/studio/test_integration.py` | MODIFY | vault fixture + `_FakeAskBot` |
| `packages/ai-parrot-server/tests/studio/test_byok.py` | MODIFY | vault fixture + 503 test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator_session.vault import KeyRing           # used by tests/studio/storage/test_byok_store.py
import parrot.security.vault_utils as vault_utils      # packages/ai-parrot/src/parrot/security/vault_utils.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/byok.py:25,35
from parrot.security.vault_utils import get_vault_keyring
def _vault_keyring(): return get_vault_keyring()
# packages/ai-parrot/src/parrot/security/vault_utils.py:57
def get_vault_keyring() -> Any  # raises RuntimeError when keys unconfigured
# packages/ai-parrot-server/src/parrot/handlers/studio/testing/_ask.py:37-38
async with bot.session(request=..., app=..., **ctx) as live_bot:
    response = await live_bot.ask(question=..., user_id=..., session_id=session_id)
```

### Does NOT Exist
- `parrot.handlers.studio.byok.load_master_keys`
- `parrot.handlers.studio.byok.get_active_key_id`

---

## Acceptance Criteria
- [ ] `test_integration.py`: 6 passed.
- [ ] `test_byok.py`: all pass.
- [ ] `tests/unit/test_byok_context.py` and `tests/unit/test_mcp_restore_integrity.py` still pass.

## Validation Commands
```bash
pytest packages/ai-parrot-server/tests/studio/test_integration.py packages/ai-parrot-server/tests/studio/test_byok.py packages/ai-parrot-server/tests/unit/test_byok_context.py packages/ai-parrot-server/tests/unit/test_mcp_restore_integrity.py -q
```

## Test Specification
The task modifies tests only; the validation command above is the test.

## Agent Instructions
Implement exactly the scope above, run the validation command, commit only the two files.

## Completion Note
*(Agent fills this in when done)*
