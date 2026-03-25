# TASK-438: Credential Encryption Helpers

**Feature**: user-based-credentials
**Spec**: `sdd/specs/user-based-credentials.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-437
**Assigned-to**: unassigned

---

## Context

> This task implements the encryption/decryption layer for credentials stored in DocumentDB.
> Implements Module 2 from the spec (Section 3).
> Uses navigator-session's `encrypt_for_db` / `decrypt_for_db` from `navigator_session.vault.crypto`.

---

## Scope

- Implement `encrypt_credential(credential_dict, master_key) -> str` — serializes a credential dict (driver + params) to JSON bytes, encrypts with `encrypt_for_db`, returns base64 string
- Implement `decrypt_credential(encrypted_str, master_keys) -> dict` — decodes base64, decrypts with `decrypt_for_db`, deserializes JSON back to dict
- Handle master key retrieval pattern (from app config or environment)
- Write unit tests for encryption round-trip, special characters in passwords, empty params

**NOT in scope**: handler logic, DocumentDB operations, route registration

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/credentials_utils.py` | CREATE | Encryption/decryption helper functions |
| `tests/handlers/test_credential_encryption.py` | CREATE | Unit tests for encryption helpers |

---

## Implementation Notes

### Pattern to Follow
```python
import base64
import orjson
from navigator_session.vault.crypto import encrypt_for_db, decrypt_for_db


def encrypt_credential(
    credential: dict,
    key_id: int,
    master_key: bytes
) -> str:
    """Encrypt a credential dict for DocumentDB storage.

    Args:
        credential: asyncdb-syntax dict with driver and params.
        key_id: Key version identifier.
        master_key: Master encryption key bytes.

    Returns:
        Base64-encoded encrypted string.
    """
    plaintext = orjson.dumps(credential)
    ciphertext = encrypt_for_db(plaintext, key_id, master_key)
    return base64.b64encode(ciphertext).decode("ascii")


def decrypt_credential(
    encrypted: str,
    master_keys: dict[int, bytes]
) -> dict:
    """Decrypt a credential string from DocumentDB.

    Args:
        encrypted: Base64-encoded encrypted string.
        master_keys: Dict mapping key_id -> master_key bytes.

    Returns:
        Original credential dict.
    """
    ciphertext = base64.b64decode(encrypted)
    plaintext = decrypt_for_db(ciphertext, master_keys)
    return orjson.loads(plaintext)
```

### Key Constraints
- Use `orjson` for JSON serialization (consistent with navigator-session internals)
- Use `base64` encoding for storing encrypted bytes as strings in DocumentDB
- Must handle credential dicts with special characters in passwords (unicode, symbols)
- Must handle empty params dict
- Add Google-style docstrings with type hints

### References in Codebase
- `navigator_session.vault.crypto` — `encrypt_for_db()` / `decrypt_for_db()` functions
- Format: `[key_id 2B][nonce 12B][payload+tag]` for database encryption

---

## Acceptance Criteria

- [ ] `encrypt_credential` converts dict -> encrypted base64 string
- [ ] `decrypt_credential` converts encrypted string -> original dict
- [ ] Round-trip: `decrypt(encrypt(data)) == data` for various credential formats
- [ ] Handles passwords with special characters (unicode, `$`, `@`, `!`, spaces)
- [ ] Handles empty params dict
- [ ] All tests pass: `pytest tests/handlers/test_credential_encryption.py -v`
- [ ] Import works: `from parrot.handlers.credentials_utils import encrypt_credential, decrypt_credential`

---

## Test Specification

```python
# tests/handlers/test_credential_encryption.py
import pytest
from parrot.handlers.credentials_utils import encrypt_credential, decrypt_credential


@pytest.fixture
def master_key():
    """Generate a test master key."""
    import os
    return os.urandom(32)


@pytest.fixture
def master_keys(master_key):
    return {1: master_key}


class TestCredentialEncryption:
    def test_roundtrip_basic(self, master_key, master_keys):
        cred = {"driver": "pg", "host": "localhost", "port": 5432, "user": "admin", "password": "secret"}
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        assert isinstance(encrypted, str)
        decrypted = decrypt_credential(encrypted, master_keys)
        assert decrypted == cred

    def test_roundtrip_special_chars(self, master_key, master_keys):
        cred = {"driver": "mysql", "password": "p@$$w0rd!#&*()_+{}|:<>?"}
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        decrypted = decrypt_credential(encrypted, master_keys)
        assert decrypted == cred

    def test_roundtrip_unicode(self, master_key, master_keys):
        cred = {"driver": "pg", "password": "contraseña_日本語_пароль"}
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        decrypted = decrypt_credential(encrypted, master_keys)
        assert decrypted == cred

    def test_roundtrip_empty_params(self, master_key, master_keys):
        cred = {"driver": "pg"}
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        decrypted = decrypt_credential(encrypted, master_keys)
        assert decrypted == cred

    def test_encrypted_is_different_from_plaintext(self, master_key):
        cred = {"driver": "pg", "password": "secret"}
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        assert "secret" not in encrypted
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/user-based-credentials.spec.md` for full context
2. **Check dependencies** — verify TASK-437 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-438-credential-encryption-helpers.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-25
**Notes**: Created `parrot/handlers/credentials_utils.py` with `encrypt_credential` and `decrypt_credential`. Uses `orjson` for serialization and base64 encoding. All 11 unit tests pass including round-trips with special chars, unicode, nested dicts (BigQuery), and error cases.

**Deviations from spec**: none
