# TASK-5510: Redis vault rotation targets (`redis:user_credentials`, `redis:user_llm_keys`)

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5496
**Assigned-to**: unassigned

---

## Context

Spec §2 "Rotation", §3 Module 13, AC12. `navigator-vault` keyring rotation and v1→v2 migration discover
protected targets through the `navigator_session.vault_targets` entry-point group. Sealed credentials and
BYOK keys stored in Redis must be covered, or a rotation would leave them on a retired key. This task adds
`RedisDocumentTarget` (a `DocumentDbTarget` whose I/O goes through `RedisDocumentStore`), two concrete
targets, two factories and their entry points.

---

## Scope

- Add `RedisDocumentTarget`, `RedisUserCredentialsTarget`, `RedisUserLlmKeysTarget`,
  `redis_user_credentials_factory`, `redis_user_llm_keys_factory` to `parrot/vault_targets.py`.
- Register two entry points in `packages/ai-parrot/pyproject.toml`.
- Tests calling the factories directly (entry-point discovery needs a metadata reinstall — operator step).

**NOT in scope**: DocumentDB targets (unchanged), Studio Postgres targets (unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/vault_targets.py` | MODIFY | Redis target classes + factories |
| `packages/ai-parrot/pyproject.toml` | MODIFY | two `navigator_session.vault_targets` entry points |
| `packages/ai-parrot/tests/security/test_vault_targets_redis.py` | CREATE | rotation cycle + factory tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator_session.vault.registry import BackupSink, BackupSource, VaultRow   # verified: vault_targets.py:32
from parrot.userstore import RedisDocumentStore, resolve_store_backend            # TASK-5495/5496
from parrot.userstore.collections import CollectionSpec, USER_CREDENTIALS, USER_LLM_KEYS  # TASK-5496
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/vault_targets.py
QUARANTINE_SUFFIX = "_quarantine"                                       # line 43
class DocumentDbTarget:                                                 # line 46
    name: str; collection: str; purpose: str; identity_fields: tuple[str, ...]; encrypted_field: str
    def __init__(self, docdb_factory: Callable[[], Any]) -> None:       # sets self._docdb
    encrypted_fields (property); context_for(row, field); ref_for(identity)
    async def iter_batches(self, batch_size: int) -> AsyncIterator[list[VaultRow]]:  # reads all docs, sorts by identity, yields self._row(doc) batches
    async def transaction(self) -> AsyncIterator[None]:                 # no-op context manager
    async def write(self, row, blobs: Mapping[str, Optional[bytes]], key_version: int) -> None:  # base64-encodes blob; $set {field, key_version, updated_at}; LookupError when gone
    async def quarantine(self, row, reason: str, run_id: str) -> None:  # copy doc (+quarantined_at, reason, run_id) to <collection>_quarantine, delete original
    async def export_raw(self, sink: BackupSink) -> int:               # via iter_batches — inherit
    async def restore_raw(self, source: BackupSource) -> int:          # replace doc from record["document"], drop quarantine copy
    def to_backup_record(self, row: VaultRow) -> dict:                  # inherit
    def _row(self, document: Mapping[str, Any]) -> VaultRow:           # inherit
class UserCredentialsTarget(DocumentDbTarget):                          # line 209 — purpose CREDENTIAL_PURPOSE, identity (user_id, name), field CREDENTIAL_FIELD, _context=credential_context
class UserLlmKeysTarget(DocumentDbTarget):                              # line 222 — LLM_KEY_PURPOSE, (user_id, provider), LLM_KEY_FIELD, _context=llm_key_context
def user_llm_keys_factory(resources: Mapping[str, Any]) -> Optional[UserLlmKeysTarget]:   # line 260 (last function in file)

# packages/ai-parrot/pyproject.toml
# [project.entry-points."navigator_session.vault_targets"]                    # line 956
# parrot_user_credentials = "parrot.vault_targets:user_credentials_factory"   # line 957
# parrot_user_llm_keys = "parrot.vault_targets:user_llm_keys_factory"         # line 958
```

### Does NOT Exist
- ~~`RedisDocumentTarget` and the two factories~~ — created by this task.
- ~~Automatic entry-point discovery in an existing editable install~~ — needs a metadata refresh; tests call the factories directly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/vault_targets.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/security/test_vault_targets_redis.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/vault_targets.py#DocumentDbTarget",
    "sym:packages/ai-parrot/src/parrot/vault_targets.py#UserCredentialsTarget",
    "sym:packages/ai-parrot/src/parrot/vault_targets.py#UserLlmKeysTarget",
    "sym:packages/ai-parrot/src/parrot/vault_targets.py#user_llm_keys_factory"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Same `ProtectedTarget` contract as the DocumentDB targets: refs, backup records and AAD contexts must be
  identical in shape (only `name` differs: `redis:user_credentials`, `redis:user_llm_keys`).
- A factory returns a target only when its switch resolves to `redis` (`VAULT_STORE` / `BYOK_STORE`);
  misconfiguration → `None` (never raise inside entry-point discovery).
- Quarantine store: `CollectionSpec(collection + QUARANTINE_SUFFIX, same key_fields, same index_fields)` —
  quarantining the same identity twice keeps only the latest copy (spec §7).
- This task edits `pyproject.toml` → exclusive (`parallel: false`).

---

## Implementation Blueprint

### Steps (in order)
1. Add `RedisDocumentTarget` overriding the four I/O methods — *why*: reuse every non-I/O behaviour of `DocumentDbTarget`.
2. Add the two concrete targets reusing the DocumentDB targets' class attributes — *why*: identical purpose/identity/context.
3. Add the factories and entry points; write tests.

### `packages/ai-parrot/src/parrot/vault_targets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def user_llm_keys_factory(resources: Mapping[str, Any]) -> Optional[UserLlmKeysTarget]:' .../vault_targets.py)
# AFTER the body of user_llm_keys_factory (verified: vault_targets.py:260, end of file) append:


class RedisDocumentTarget(DocumentDbTarget):
    """DocumentDbTarget whose I/O goes through RedisDocumentStore (FEAT-878). Same refs, records and contexts."""

    def __init__(self, documents: Any, quarantine: Any) -> None:  # RedisDocumentStore instances
        self._documents = documents
        self._quarantine = quarantine

    async def iter_batches(self, batch_size: int) -> AsyncIterator[list[VaultRow]]:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        documents = [doc async for doc in self._documents.scan()]
        documents.sort(key=lambda doc: tuple(str(doc.get(name)) for name in self.identity_fields))
        for start in range(0, len(documents), batch_size):
            yield [self._row(doc) for doc in documents[start:start + batch_size]]

    async def write(self, row: Any, blobs: Mapping[str, Optional[bytes]], key_version: int) -> None:
        """Replace the sealed field and record key_version. LookupError when the document is gone."""
        # FILL IN: same validation as DocumentDbTarget.write; documents.update(identity, {field: b64, key_version,
        #   updated_at}) → raise LookupError(f"{row.ref} not found") when it returns False.
        raise NotImplementedError

    async def quarantine(self, row: Any, reason: str, run_id: str) -> None:
        # FILL IN: get original (LookupError when gone); quarantine.put({**doc, quarantined_at, reason, run_id}); documents.delete(identity)
        raise NotImplementedError

    async def restore_raw(self, source: BackupSource) -> int:
        # FILL IN: for each record in source.read(self.name): documents.put(record["document"]); quarantine.delete(identity); count
        raise NotImplementedError


class RedisUserCredentialsTarget(RedisDocumentTarget):
    name = "redis:user_credentials"
    collection = UserCredentialsTarget.collection
    purpose = UserCredentialsTarget.purpose
    identity_fields = UserCredentialsTarget.identity_fields
    encrypted_field = UserCredentialsTarget.encrypted_field
    _context = UserCredentialsTarget._context


class RedisUserLlmKeysTarget(RedisDocumentTarget):
    name = "redis:user_llm_keys"
    collection = UserLlmKeysTarget.collection
    purpose = UserLlmKeysTarget.purpose
    identity_fields = UserLlmKeysTarget.identity_fields
    encrypted_field = UserLlmKeysTarget.encrypted_field
    _context = UserLlmKeysTarget._context


def _redis_target(switch: str, cls: type, spec_name: str) -> Optional[RedisDocumentTarget]:
    """Target over Redis when ``switch`` resolves to redis, else None (never raises during discovery)."""
    # FILL IN: lazy imports of parrot.userstore; try resolve_store_backend(switch) except Exception → None;
    #   spec = USER_STORE_COLLECTIONS[spec_name]; quarantine spec = CollectionSpec(spec.name + QUARANTINE_SUFFIX,
    #   spec.key_fields, spec.index_fields); return cls(RedisDocumentStore(spec), RedisDocumentStore(qspec)).
    raise NotImplementedError


def redis_user_credentials_factory(resources: Mapping[str, Any]) -> Optional[RedisUserCredentialsTarget]:
    """Entry-point factory for ``user_credentials`` in Redis (VAULT_STORE=redis)."""
    return _redis_target("VAULT_STORE", RedisUserCredentialsTarget, "user_credentials")


def redis_user_llm_keys_factory(resources: Mapping[str, Any]) -> Optional[RedisUserLlmKeysTarget]:
    """Entry-point factory for ``user_llm_keys`` in Redis (BYOK_STORE=redis)."""
    return _redis_target("BYOK_STORE", RedisUserLlmKeysTarget, "user_llm_keys")
```
**Why**: subclassing keeps `context_for`, `ref_for`, `to_backup_record`, `_row`, `export_raw` and `transaction`
identical to the DocumentDB targets, so navigator-vault treats both backends the same.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c 'parrot_user_llm_keys = "parrot.vault_targets:user_llm_keys_factory"' packages/ai-parrot/pyproject.toml)
# AFTER `parrot_user_llm_keys = "parrot.vault_targets:user_llm_keys_factory"` (verified: pyproject.toml:958) add:
parrot_redis_user_credentials = "parrot.vault_targets:redis_user_credentials_factory"
parrot_redis_user_llm_keys = "parrot.vault_targets:redis_user_llm_keys_factory"
```

### FILL IN checklist
- [ ] `write`, `quarantine`, `restore_raw`
- [ ] `_redis_target`
- [ ] tests

---

## Acceptance Criteria

- [ ] Rotation cycle on Redis: iter_batches → write with a new key_version → value still decrypts; quarantine → restore_raw round-trips (AC12)
- [ ] Factories return `None` unless the switch resolves to `redis`; misconfiguration → `None`
- [ ] Existing `test_vault_targets.py` passes unchanged
- [ ] `ruff check packages/ai-parrot/src/parrot/vault_targets.py` clean

---

## Validation Commands
- `pytest packages/ai-parrot/tests/security/test_vault_targets_redis.py -q`
- `pytest packages/ai-parrot/tests/security/test_vault_targets.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/security/test_vault_targets_redis.py
import pytest

from parrot import vault_targets
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def redis_env(monkeypatch):
    monkeypatch.delenv("VAULT_STORE", raising=False)
    monkeypatch.delenv("BYOK_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    async with redis_test_settings(monkeypatch):
        yield


async def test_redis_target_rotation_cycle(redis_env): ...
    # FILL IN: seed a credential via RedisVaultCredentialStore (test keyring), iterate the target, write a re-sealed blob
    #   with key_version 2, read back through vault_utils; quarantine then restore_raw from an in-memory BackupSource
def test_redis_target_factories(monkeypatch): ...   # VAULT_STORE=documentdb → None; unset → target; bogus → None
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§2 Rotation, §3 M13, AC12)
3. **Check dependencies** — TASK-5496 must be `done`
4. **Verify the Codebase Contract** (re-run each `grep -c`)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`; do NOT reinstall the package to test entry points
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5510 redis-user-stores verified`
10. **Fill in the Completion Note** (mention that entry-point discovery needs a metadata refresh by the operator), commit the staged SDD state

---

## Completion Note


- Task: TASK-5510
- Feature: redis-user-stores
- Implementation SHA: e3538dbd271c8aa5f77256b1fe1b459c2d5be54f
- Closed at (UTC): 2026-11-11T01:14:36+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 296s · Tokens: n/a |
