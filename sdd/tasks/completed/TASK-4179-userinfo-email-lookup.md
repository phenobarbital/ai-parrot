# TASK-4179: UserInfoService email lookup

**Feature**: FEAT-647 — Chat-driven document upload into Bookstore / LLM Wiki
**Spec**: `sdd/specs/teams-telegram-uploader-bookstore.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-647 lets authorized users upload documents into the Bookstore / LLM wiki
from Telegram, MS Teams and Slack. Teams and Slack have no navigator-auth
login: the platform user is mapped to a navigator user **by email** and looked
up in `auth.vw_users` to get `username` + `groups` for the allow-list check
(spec §2 "Identity", §3 Module 2). `UserInfoService` today only looks up by
`user_id`.

---

## Scope

- Add `UserInfoService.get_profile_by_email(email: str) -> EmployeeProfile | None`.
- Case-insensitive match on `auth.vw_users.email`.
- Return `None` when no row matches **or when more than one row matches**
  (ambiguous identities are never authorized — spec §3 Module 2).
- On exactly one match, delegate to the existing `get_profile(user_id)` so the
  profile construction and its TTL cache are reused.
- Blank / whitespace-only email → `None` without touching the database.
- Write unit tests with a fake asyncdb connection.

**Decision (recorded here, binding)**: no separate `email:<lower>` cache entry.
Only the resolved profile is cached (by `get_profile`, keyed by `user_id`). The
email → user_id query runs on every call — it is one indexed `LIMIT 2` query,
and not caching it means a newly-duplicated email is detected as ambiguous
immediately instead of after the TTL.

**NOT in scope**: lookup by username; any caller (the knowledge-upload policy
is TASK-4182); changes to `get_profile`, `EmployeeProfile` or `_fetch_manager`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/userinfo.py` | MODIFY | add `get_profile_by_email` after `get_profile` |
| `packages/ai-parrot/tests/auth/test_userinfo_by_email.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.userinfo import EmployeeProfile, UserInfoService  # verified: packages/ai-parrot/src/parrot/auth/userinfo.py (EmployeeProfile :42, UserInfoService :77)
```
`userinfo.py` already imports `logging`, `Any` (`typing`), `AsyncDB` (`asyncdb`),
`BaseModel`; no new import is needed.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/userinfo.py
class EmployeeProfile(BaseModel):     # :42
    user_id: int | str                 # :64
    username: str | None = None
    email: str | None = None
    groups: list[str] = []             # :71

class UserInfoService:                                                   # :77
    def __init__(self, dsn: str | None = None, cache_ttl: int = 600,
                 cache_max_size: int = 500) -> None:                     # :88
    self._db: AsyncDB | None = None                                      # :105
    self._cache = TTLCache(max_size=cache_max_size, default_ttl=cache_ttl)
    self.logger = logging.getLogger(__name__)
    def _get_db(self) -> AsyncDB:                                        # :109
    async def get_profile(self, user_id: Any) -> EmployeeProfile | None: # :148
        # pattern used inside:
        #   db = self._get_db()
        #   async with await db.connection() as conn:  # pylint: disable=E1101
        #       row = await conn.fetch_one("""SELECT ... FROM auth.vw_users WHERE user_id = $1""", user_id)
        # ends with:
        #   await self._cache.set(cache_key, profile)   # :193
        #   return profile                               # :194 (last line of file)
```
```python
# asyncdb multi-row fetch, positional params — verified usage:
# packages/ai-parrot/src/parrot/interfaces/database.py:445
result = await conn.fetch_all(sql, *values)
```
```python
# Test pattern to copy: packages/ai-parrot/tests/auth/test_userinfo_service.py
#   _vw_users_row(**overrides), _FakeConnection(rows) with fetch_one + __aenter__/__aexit__,
#   _FakeConnectionCtx (awaitable returning conn), _FakeDB.connection(),
#   _make_service(rows) sets service._db = _FakeDB(conn)
```

### Does NOT Exist
- ~~`UserInfoService.get_profile_by_email`~~ — this task creates it
- ~~`UserInfoService.get_profile_by_username`~~ — not part of this feature
- ~~a shared conftest with the fake asyncdb classes~~ — the fakes live inside `test_userinfo_service.py`; copy them, do not import from another test module
- ~~`conn.fetch(...)` on the asyncdb pg connection in this module~~ — use `fetch_all` (verified usage above)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/userinfo.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/auth/test_userinfo_by_email.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/userinfo.py#UserInfoService",
    "sym:packages/ai-parrot/src/parrot/auth/userinfo.py#UserInfoService.get_profile",
    "sym:packages/ai-parrot/src/parrot/auth/userinfo.py#UserInfoService._get_db",
    "sym:packages/ai-parrot/src/parrot/auth/userinfo.py#EmployeeProfile"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async only; never block.
- Never raise for "not found" or "ambiguous" — return `None` (same contract as `get_profile`).
- Log ambiguity at `warning` without echoing the full email list (log the count).

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/userinfo.py:148` — `get_profile`, the pattern to follow
- `packages/ai-parrot/tests/auth/test_userinfo_service.py` — fake asyncdb pattern

---

## Implementation Blueprint

### Steps (in order)
1. Append `get_profile_by_email` to `UserInfoService` after `get_profile` — *why*: keeps the email path a thin resolver on top of the cached `get_profile`.
2. Query `SELECT user_id FROM auth.vw_users WHERE lower(email) = lower($1) LIMIT 2` with `fetch_all` — *why*: `LIMIT 2` is the cheapest way to detect ambiguity.
3. Return `None` for 0 or 2 rows; otherwise `await self.get_profile(rows[0]["user_id"])` — *why*: ambiguous identities must never be authorized (spec §3 Module 2).
4. Write tests copying the fake classes and adding `fetch_all` — *why*: no real database in unit tests.

### `packages/ai-parrot/src/parrot/auth/userinfo.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        return profile' packages/ai-parrot/src/parrot/auth/userinfo.py → 1)
# AFTER — append below `        return profile` (verified: userinfo.py:194, last line of get_profile and of the file)

    async def get_profile_by_email(self, email: str) -> EmployeeProfile | None:
        """Fetch the curated `EmployeeProfile` whose email matches `email`.

        The match is case-insensitive. Used by chat integrations (MS Teams,
        Slack) that know the user's email but not their navigator user id.

        Args:
            email: The email address to look up.

        Returns:
            The `EmployeeProfile` when exactly one `auth.vw_users` row matches;
            `None` when the email is blank, when no row matches, or when more
            than one row matches (an ambiguous identity is never resolved).
        """
        normalized = (email or "").strip()
        if not normalized:
            return None

        db = self._get_db()
        async with await db.connection() as conn:  # pylint: disable=E1101
            rows = await conn.fetch_all(
                """
                SELECT user_id
                FROM auth.vw_users WHERE lower(email) = lower($1)
                LIMIT 2
                """,
                normalized,
            )

        rows = [dict(r) for r in (rows or [])]
        # FILL IN: return None when len(rows) == 0; when len(rows) > 1 log
        #   self.logger.warning("get_profile_by_email: ambiguous email (%d rows)", len(rows))
        #   and return None — bounded by spec §3 Module 2 (ambiguous → None)
        return await self.get_profile(rows[0]["user_id"])
```
**Why this shape**: the email query only resolves the `user_id`; profile
construction, manager lookup and caching stay in `get_profile`, so both paths
return identical profiles. No email-keyed cache (see Scope decision).

### `packages/ai-parrot/tests/auth/test_userinfo_by_email.py` (CREATE)
```python
"""Unit tests for `UserInfoService.get_profile_by_email` (FEAT-647 / TASK-4179)."""
import pytest

from parrot.auth.userinfo import UserInfoService


def _vw_users_row(**overrides):
    row = {
        "user_id": 42, "username": "jlara", "display_name": "Jesus Lara",
        "email": "jlara@example.com", "job_code": "ENG-3", "title": "Sr Engineer",
        "department_code": "TECH", "worker_type": "FTE", "manager_id": None,
        "groups": ["curators"], "programs": [],
    }
    row.update(overrides)
    return row


class _FakeConnection:
    """fetch_all returns `all_rows`; fetch_one pops from `one_rows`."""

    def __init__(self, all_rows: list, one_rows: list):
        self._all_rows = list(all_rows)
        self._one_rows = list(one_rows)
        self.fetch_all_calls: list = []
        self.fetch_one_calls: list = []

    async def fetch_all(self, query, *params):
        self.fetch_all_calls.append((query, params))
        return list(self._all_rows)

    async def fetch_one(self, query, *params):
        self.fetch_one_calls.append((query, params))
        return self._one_rows.pop(0) if self._one_rows else None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeConnectionCtx:
    def __init__(self, conn):
        self._conn = conn

    def __await__(self):
        async def _inner():
            return self._conn
        return _inner().__await__()


class _FakeDB:
    def __init__(self, conn):
        self._conn = conn

    def connection(self):
        return _FakeConnectionCtx(self._conn)


def _make_service(all_rows, one_rows):
    service = UserInfoService()
    conn = _FakeConnection(all_rows, one_rows)
    service._db = _FakeDB(conn)
    return service, conn


# FILL IN: tests listed in the Test Specification — bounded by AC-1..AC-5
```
**Why**: the fakes are copied (not imported) because test modules are not a
shared API; `fetch_all` is the only addition.

### FILL IN checklist
- [ ] `userinfo.py::UserInfoService.get_profile_by_email` — 0 rows / >1 rows → `None` with warning on ambiguity; bounded by spec §3 Module 2
- [ ] `test_userinfo_by_email.py` — the five tests of the Test Specification

---

## Acceptance Criteria

- [ ] AC-1: exactly one matching row → the same `EmployeeProfile` `get_profile(user_id)` returns (username, groups).
- [ ] AC-2: the SQL compares `lower(email) = lower($1)` and passes the stripped email as the only parameter.
- [ ] AC-3: zero rows → `None`; two rows → `None` and `get_profile` is not called.
- [ ] AC-4: `""` / `"   "` / `None`-ish input → `None` without opening a connection.
- [ ] AC-5: a second call for the same email reuses the cached profile (one `fetch_one` for the profile across both calls).
- [ ] No linting errors.

- [ ] Lint clean: `ruff check packages/ai-parrot/src/parrot/auth/userinfo.py packages/ai-parrot/tests/auth/test_userinfo_by_email.py`
---

## Validation Commands

- `pytest packages/ai-parrot/tests/auth/test_userinfo_by_email.py -q`
- `pytest packages/ai-parrot/tests/auth/test_userinfo_service.py -q`

---

## Test Specification

```python
class TestGetProfileByEmail:
    async def test_single_match_returns_profile(self):
        service, conn = _make_service([{"user_id": 42}], [_vw_users_row()])
        profile = await service.get_profile_by_email("JLara@Example.com")
        assert profile is not None and profile.username == "jlara"
        assert "lower(email) = lower($1)" in conn.fetch_all_calls[0][0]
        assert conn.fetch_all_calls[0][1] == ("JLara@Example.com",)

    async def test_no_match_returns_none(self):
        service, _ = _make_service([], [])
        assert await service.get_profile_by_email("nobody@example.com") is None

    async def test_ambiguous_returns_none(self):
        service, conn = _make_service([{"user_id": 1}, {"user_id": 2}], [_vw_users_row()])
        assert await service.get_profile_by_email("dup@example.com") is None
        assert conn.fetch_one_calls == []

    @pytest.mark.parametrize("email", ["", "   "])
    async def test_blank_email_skips_db(self, email):
        service, conn = _make_service([{"user_id": 42}], [_vw_users_row()])
        assert await service.get_profile_by_email(email) is None
        assert conn.fetch_all_calls == []

    async def test_profile_cache_reused(self):
        service, conn = _make_service([{"user_id": 42}], [_vw_users_row()])
        await service.get_profile_by_email("jlara@example.com")
        await service.get_profile_by_email("jlara@example.com")
        assert len(conn.fetch_one_calls) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug teams-telegram-uploader-bookstore --feature-id FEAT-647`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/teams-telegram-uploader-bookstore.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/teams-telegram-uploader-bookstore.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4179 teams-telegram-uploader-bookstore verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

## Completion Note

Implemented by engine seat; merged. Tests run via PYTHONPATH with main-checkout .so files (merge-tier validation failed on a worktree import env issue, not code). Pre-existing unrelated failures: pageindex test_adapter x2, test_okf_ontology.
