---
type: feature
base_branch: dev
feature_id: FEAT-677
projects: [ai-parrot-server]
tags: [studio, byok, tests]
---

# Feature Specification: Studio BYOK test fixtures follow the vault KeyRing API

**Feature ID**: FEAT-677
**Date**: 2026-10-15
**Author**: Claude (sdd-fix lane)
**Status**: approved
**Target version**: next

Resolves ledger issue:d5a7c625fbe7 (discovered from spec:FEAT-644).

---

## 1. Motivation & Business Requirements

### Problem Statement

`packages/ai-parrot-server/tests/studio/test_integration.py` and
`packages/ai-parrot-server/tests/studio/test_byok.py` fail against `dev`:

1. Their autouse `patch_vault_keys` fixtures monkeypatch
   `parrot.handlers.studio.byok.load_master_keys` / `get_active_key_id`.
   Those names no longer exist: FEAT-099 moved BYOK onto the process-wide
   vault `KeyRing` (`byok._vault_keyring()` → `parrot.security.vault_utils.get_vault_keyring()`),
   and `tests/unit/test_byok_context.py` / `test_mcp_restore_integrity.py`
   *assert* that `load_master_keys` stays out of the source. `test_byok.py`
   errors on all 10 tests (`AttributeError ... no attribute 'load_master_keys'`);
   `test_integration.py` was papered over with `raising=False`, which makes
   the patch a silent no-op.
2. `test_integration.py`'s `_FakeAskBot` predates commit 3ee6e37fc, which made
   test/ask call `bot.name` (session id) and `live_bot.ask(question=, user_id=, session_id=)`.
   `TestStudioFullLoop::test_studio_full_loop` and
   `TestDraftToLive::test_draft_to_live` fail with
   `AttributeError: '_FakeAskBot' object has no attribute 'name'`.

The production code is correct; the tests are stale.

### Goals
- Both test modules pass against the current key-loading API.
- The vault patch targets `get_vault_keyring` (the real seam), using a real
  `navigator_session.vault.KeyRing` — the pattern already used by
  `tests/studio/storage/test_byok_store.py`.
- `_FakeAskBot` matches the current test/ask call contract.

### Non-Goals (explicitly out of scope)
- No change to `parrot/handlers/studio/byok.py` or any production code.
- Restoring `load_master_keys` (explicitly forbidden by the unit tests above).

---

## 2. Architectural Design

### Overview
Test-only change. Replace the stale monkeypatches with
`monkeypatch.setattr(byok_module, "get_vault_keyring", lambda: KEYRING)` (plus
`parrot.security.vault_utils.get_vault_keyring`, which other resolvers import),
where `KEYRING = KeyRing(MASTER_KEYS, MASTER_KEY_ID)`. The "vault not
configured → 503" test patches `get_vault_keyring` with a function raising
`RuntimeError`, which is exactly what `get_vault_keyring()` raises when keys are
absent. `_FakeAskBot` gains `name` and an `ask(question, **kwargs)` signature.

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.handlers.studio.byok._vault_keyring` | test seam | calls module-level `get_vault_keyring` |
| `parrot.security.vault_utils.get_vault_keyring` | test seam | raises `RuntimeError` when unconfigured |
| `parrot.handlers.studio.testing._ask._ask_response` | contract | `bot.session(...)` then `ask(question=, user_id=, session_id=)` |

---

## 3. Module Breakdown

### Module 1: Stale studio BYOK test fixtures
- **Path**: `packages/ai-parrot-server/tests/studio/test_integration.py`, `packages/ai-parrot-server/tests/studio/test_byok.py`
- **Responsibility**: patch the vault KeyRing seam; update `_FakeAskBot`.

---

## 4. Test Specification

`pytest packages/ai-parrot-server/tests/studio/test_integration.py packages/ai-parrot-server/tests/studio/test_byok.py`
passes; `packages/ai-parrot-server/tests/unit/test_byok_context.py` and
`test_mcp_restore_integrity.py` still pass.

---

## 5. Acceptance Criteria
- [ ] `tests/studio/test_integration.py` — 6 passed.
- [ ] `tests/studio/test_byok.py` — all pass (previously 10 errors).
- [ ] No reference to `load_master_keys` remains on `byok_module` in either file.
- [ ] No production source changed.

---

## 6. Codebase Contract
- `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py:25` — `from parrot.security.vault_utils import get_vault_keyring`
- `packages/ai-parrot/src/parrot/security/vault_utils.py:57` — `def get_vault_keyring() -> Any` (raises `RuntimeError` when unconfigured)
- `navigator_session.vault.KeyRing(master_keys: Mapping[int, bytes], active_key_id: int)`
- Does NOT exist: `parrot.handlers.studio.byok.load_master_keys`, `byok.get_active_key_id`.

## 7. Open Questions
None.
