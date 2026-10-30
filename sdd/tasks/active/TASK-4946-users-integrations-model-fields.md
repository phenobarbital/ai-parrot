# TASK-4946: UsersIntegrationRow / IntegrationDescriptor channel-neutral fields + list_users_integrations

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4945
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models (M6 changes), U1, U2, S3, AC-12, AC-19. Rows become principal-scoped and channel-neutral:
`channel: str = "web"` is replaced by `channels: List[str]`, plus `canonical_identity`, `scopes_granted`,
`expires_at`, `updated_at`, and a `needs_reconnect` status. `IntegrationDescriptor` drops `enabled_on_agent` (U2)
and gains `channels`, `scopes_granted`, `expires_at`, `updated_at` (S-4 pre-check: a CLI detects a completed
reconnect by `status` + `updated_at`). This task is **additive** on the persistence side; removing the
`user_agent_toolkits` repository is TASK-4949 (after its readers are gone).

---

## Scope

- `UsersIntegrationRow`: replace `channel` with `channels: List[str] = []`; add `canonical_identity`, `scopes_granted`,
  `expires_at`, `updated_at`; status `Literal["active", "revoked", "needs_reconnect"]`; a `model_validator(mode="before")`
  that maps a legacy stored `channel` value into `channels` (old DocumentDB documents still carry it).
- `IntegrationDescriptor`: remove `enabled_on_agent`; add `channels`, `scopes_granted`, `expires_at`, `updated_at`.
- `persistence.py`: `list_users_integrations(user_id) -> List[UsersIntegrationRow]`.
- Unit tests for the model migration and the list function (DocumentDB mocked like the existing persistence tests).

**NOT in scope**: service changes (TASK-4947); deleting `UserAgentToolkitRow` / toolkit functions (TASK-4949).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/models.py` | MODIFY | row/descriptor fields |
| `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` | MODIFY | list_users_integrations |
| `packages/ai-parrot/tests/unit/auth/test_users_integrations_model.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.oauth2.models import IntegrationDescriptor, UsersIntegrationRow   # verified: models.py:21, :147
from parrot.auth.oauth2.persistence import get_users_integration, upsert_users_integration   # verified: persistence.py:67, :42
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/models.py  (imports: datetime; List, Literal, Optional; BaseModel, Field, model_validator)
class IntegrationDescriptor(BaseModel):   # :21 provider, display_name, icon, default_scopes, connected, status: Optional[IntegrationStatus],
                                          #     enabled_on_agent: bool = False (:47), account_id, display_account_name, email, connected_at
class UsersIntegrationRow(BaseModel):     # :147 user_id, provider, channel: str = "web" (:171 anchor),
                                          #     status: Literal["active","revoked"] = "active", account_id, display_name, email,
                                          #     scopes, cloud_id, site_url, connected_at, last_used_at
# packages/ai-parrot/src/parrot/auth/oauth2/persistence.py
USERS_INTEGRATIONS_COLLECTION = "users_integrations"                               # :33
async def upsert_users_integration(row) (:42); get_users_integration(user_id, provider) (:67); delete_users_integration (:89)
# list_user_agent_toolkits (:148) shows the DocumentDB read/iterate pattern to copy
```

### Does NOT Exist
- ~~`list_users_integrations`~~ — new.
- ~~`UsersIntegrationRow.channels` / `updated_at`~~ — new.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/persistence.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_users_integrations_model.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/models.py#UsersIntegrationRow",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/models.py#IntegrationDescriptor",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/persistence.py#get_users_integration"
  ]
}
```

---

## Implementation Notes

- `enabled_on_agent` is still written by `service.list_for_user` (service.py:145), which belongs to TASK-4947.
  Do NOT delete the field here: keep it as `Field(default=False, exclude=True)` (deprecated, hidden from output)
  so service.py keeps working; TASK-4949 deletes it once TASK-4947 stops writing it.
- `updated_at` is set by the service (TASK-4947), not by the model.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Edit `UsersIntegrationRow` at the anchor (block A) — *why*: U1/U2/S3 row shape.
2. Edit `IntegrationDescriptor` (block A) — *why*: AC-19.
3. Add `list_users_integrations` (block B) — *why*: hydration and `list_for_principal` read all rows of a principal.
4. Tests.

### `packages/ai-parrot/src/parrot/auth/oauth2/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    channel: str = "web"' oauth2/models.py → :171)
# REPLACE `    channel: str = "web"` and the status line below it WITH:
    canonical_identity: Optional[str] = None
    channels: List[str] = Field(default_factory=list)
    status: Literal["active", "revoked", "needs_reconnect"] = "active"
# AFTER `scopes: List[str]` in the same class add:
    scopes_granted: List[str] = Field(default_factory=list)
    expires_at: Optional[float] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def _legacy_channel(cls, data: Any) -> Any:
        """Old documents carry ``channel: str``; fold it into ``channels``."""
        # FILL IN: dict with "channel" and no "channels" → channels=[channel]; drop "channel"; return data

# IntegrationDescriptor (:21): add after connected_at
    channels: List[str] = Field(default_factory=list)
    scopes_granted: List[str] = Field(default_factory=list)
    expires_at: Optional[float] = None
    updated_at: Optional[datetime] = None
# and change `enabled_on_agent: bool = False` to `enabled_on_agent: bool = Field(default=False, exclude=True)`
#   (deprecated; removed by TASK-4949 once service.py stops writing it)
```

### `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def upsert_user_agent_toolkit(row: UserAgentToolkitRow) -> None:' persistence.py → :113)
# BEFORE — insert above the `# user_agent_toolkits repository` section header (:109):
async def list_users_integrations(user_id: str) -> List[UsersIntegrationRow]:
    """Every provider connection of a principal (one row per provider in v1, S3)."""
    # FILL IN: same DocumentDB access as get_users_integration but filter {"user_id": user_id} only; skip and
    #          log documents that fail validation (never raise for one bad row)
    raise NotImplementedError
```

### FILL IN checklist
- [ ] `models.py::UsersIntegrationRow._legacy_channel`
- [ ] `persistence.py::list_users_integrations`
- [ ] `Any` import in models.py if missing
- [ ] tests

---

## Acceptance Criteria

- [ ] AC-19: `UsersIntegrationRow` and `IntegrationDescriptor` carry `updated_at`; `account_id` present on both (AC-12)
- [ ] A stored document with legacy `channel: 'telegram'` validates with `channels == ['telegram']`
- [ ] `list_users_integrations(user_id)` returns every row of the principal

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_users_integrations_model.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_users_integrations_model.py
from datetime import datetime, timezone
from parrot.auth.oauth2.models import UsersIntegrationRow

def test_legacy_channel_folded_into_channels():
    row = UsersIntegrationRow.model_validate({"user_id": "1042", "provider": "jira", "channel": "telegram",
        "account_id": "a", "display_name": "J", "scopes": [], "connected_at": datetime.now(timezone.utc)})
    assert row.channels == ["telegram"] and row.updated_at is None

# FILL IN: test_list_users_integrations — patch the DocumentDB accessor used by persistence.py
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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
