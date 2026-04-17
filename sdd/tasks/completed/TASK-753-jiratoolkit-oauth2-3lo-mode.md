# TASK-753: JiraToolkit — OAuth2 3LO Mode

**Feature**: FEAT-107 — Jira OAuth 2.0 (3LO) Per-User Authentication
**Spec**: `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-747, TASK-748, TASK-749, TASK-750
**Assigned-to**: unassigned

---

## Context

Module 7 of the spec. This is the integration point that ties the framework hooks, exception, credential resolver, and OAuth manager together inside `JiraToolkit`. When `auth_type="oauth2_3lo"`, the toolkit skips client creation in `__init__` and instead resolves credentials per-call via `_pre_execute()`.

---

## Scope

- Add `auth_type="oauth2_3lo"` as a supported value in `JiraToolkit`.
- Accept optional `credential_resolver: CredentialResolver` parameter in `__init__`.
- When `oauth2_3lo` mode: skip `_set_jira_client()` in `__init__`, defer client creation.
- Override `_pre_execute()` to:
  1. Extract `user_id` and `channel` from `permission_context` in kwargs.
  2. Call `credential_resolver.resolve(channel, user_id)`.
  3. If no credentials: raise `AuthorizationRequired` with auth URL.
  4. If credentials: create or reuse cached JIRA client for that user.
- Implement JIRA client caching: `Dict[str, tuple[JIRA, str]]` keyed by `"{channel}:{user_id}"`, invalidated when token hash changes.
- Ensure legacy modes (`basic_auth`, `token_auth`, `oauth`) are completely unchanged.
- Write unit tests.

**NOT in scope**: OAuth callback routes (TASK-752), Telegram commands (TASK-754), AgenTalk integration (TASK-755).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | Add oauth2_3lo support, _pre_execute override, client caching |
| `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py` | CREATE | Unit tests for OAuth mode |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.jiratoolkit import JiraToolkit, JiraInput, CreateIssueInput  # verified: packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:561,137,312
from parrot.tools.toolkit import AbstractToolkit  # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:140
from parrot.auth.exceptions import AuthorizationRequired  # created by TASK-748
from parrot.auth.credentials import CredentialResolver, OAuthCredentialResolver  # created by TASK-750
from parrot.auth.jira_oauth import JiraTokenSet  # created by TASK-751
from jira import JIRA  # verified: packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:46
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:561-739
class JiraToolkit(AbstractToolkit):
    input_class = JiraInput  # line 616
    _tool_manager: Optional[ToolManager] = None  # line 617

    def __init__(
        self,
        server_url: Optional[str] = None,  # line 621
        auth_type: Optional[str] = None,  # line 622
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        oauth_consumer_key: Optional[str] = None,
        oauth_key_cert: Optional[str] = None,
        oauth_access_token: Optional[str] = None,
        oauth_access_token_secret: Optional[str] = None,
        default_project: Optional[str] = None,
        **kwargs,
    ):
        # line 643: self.server_url = server_url or _cfg("JIRA_INSTANCE") or ""
        # line 644-646: raises ValueError if not self.server_url
        # line 680-681: self._set_jira_client()  ← MUST be skipped in oauth2_3lo mode

    def _set_jira_client(self):  # line 683
        self.jira = self._init_jira_client()

    def _init_jira_client(self) -> JIRA:  # line 690
        # Supports basic_auth, token_auth, oauth (OAuth1)
        # oauth2_3lo is NOT supported here — this task adds per-user client creation
```

### Does NOT Exist
- ~~`JiraToolkit.credential_resolver`~~ — does NOT exist yet (this task adds it)
- ~~`JiraToolkit._pre_execute()`~~ — not overridden yet (this task adds it)
- ~~`JiraToolkit._client_cache`~~ — does NOT exist yet (this task adds it)
- ~~`JiraToolkit.auth_type = "oauth2_3lo"`~~ — not a supported value yet (this task adds it)

---

## Implementation Notes

### __init__ Changes
```python
def __init__(self, ..., credential_resolver=None, **kwargs):
    # ... existing code ...

    # NEW: accept credential_resolver for OAuth2 3LO
    self.credential_resolver = credential_resolver

    if self.auth_type == "oauth2_3lo":
        # Defer client creation — resolved per-call in _pre_execute
        self.jira = None
        self._client_cache: Dict[str, tuple] = {}  # {user_key: (JIRA, token_hash)}
        if not self.credential_resolver:
            raise ValueError("oauth2_3lo requires a credential_resolver")
    else:
        # Legacy: create client immediately
        self._set_jira_client()
```

### _pre_execute Override
```python
async def _pre_execute(self, tool_name: str, **kwargs) -> None:
    if self.auth_type != "oauth2_3lo":
        return  # legacy modes skip this entirely

    perm_ctx = kwargs.get("_permission_context")
    if not perm_ctx:
        raise AuthorizationRequired(
            tool_name=tool_name,
            message="Permission context required for OAuth2 3LO",
            provider="jira",
        )

    user_id = perm_ctx.user_id
    channel = getattr(perm_ctx, "channel", None) or "unknown"
    user_key = f"{channel}:{user_id}"

    token_set = await self.credential_resolver.resolve(channel, user_id)
    if not token_set:
        auth_url = await self.credential_resolver.get_auth_url(channel, user_id)
        raise AuthorizationRequired(
            tool_name=tool_name,
            message="Please authorize your Jira account to use this tool.",
            auth_url=auth_url,
            provider="jira",
            scopes=["read:jira-work", "write:jira-work", "offline_access"],
        )

    # Client caching: reuse if token hasn't changed
    token_hash = hash(token_set.access_token)
    cached = self._client_cache.get(user_key)
    if cached and cached[1] == token_hash:
        self.jira = cached[0]
        return

    # Create new client with Bearer auth
    client = JIRA(
        options={"server": token_set.api_base_url, "verify": False,
                 "headers": {"Authorization": f"Bearer {token_set.access_token}"}},
    )
    self._client_cache[user_key] = (client, token_hash)
    self.jira = client
```

### Key Constraints
- `server_url` validation must be relaxed for `oauth2_3lo` mode (server URL is resolved at runtime).
- All existing tool methods (`jira_get_issue`, `jira_search_issues`, etc.) use `self.jira` — the `_pre_execute` hook sets `self.jira` to the correct per-user client before any method runs.
- The `_permission_context` kwarg is injected by `ToolManager.execute_tool()` — it's already passed through.
- Client cache should have a max size (e.g., 100 entries) with LRU eviction.
- pycontribs/jira `JIRA()` with `options.headers` for Bearer auth — verify this works during implementation.

---

## Acceptance Criteria

- [ ] `JiraToolkit(auth_type="oauth2_3lo", credential_resolver=...)` instantiates without creating JIRA client
- [ ] `_pre_execute()` resolves credentials and sets `self.jira` per user
- [ ] No credentials → `AuthorizationRequired` with auth URL
- [ ] JIRA client is cached and reused when token unchanged
- [ ] Client cache invalidated when token hash changes (after refresh)
- [ ] `auth_type="basic_auth"` / `"token_auth"` completely unaffected (zero regression)
- [ ] Missing `credential_resolver` with `oauth2_3lo` raises `ValueError`
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py -v`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.auth.exceptions import AuthorizationRequired


class TestJiraToolkitOAuth:
    def test_oauth2_3lo_requires_resolver(self):
        with pytest.raises(ValueError, match="credential_resolver"):
            JiraToolkit(auth_type="oauth2_3lo")

    def test_oauth2_3lo_no_client_in_init(self):
        resolver = MagicMock()
        with patch.object(JiraToolkit, '_set_jira_client'):
            tk = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=resolver)
        assert tk.jira is None

    @pytest.mark.asyncio
    async def test_pre_execute_raises_when_no_creds(self):
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=None)
        resolver.get_auth_url = AsyncMock(return_value="https://auth.url")
        # ... construct toolkit ...
        with pytest.raises(AuthorizationRequired) as exc_info:
            await tk._pre_execute("jira_get_issue", _permission_context=ctx)
        assert exc_info.value.auth_url == "https://auth.url"

    @pytest.mark.asyncio
    async def test_pre_execute_sets_jira_client(self):
        # ... mock resolver returning valid token_set ...
        await tk._pre_execute("jira_get_issue", _permission_context=ctx)
        assert tk.jira is not None

    @pytest.mark.asyncio
    async def test_client_cached_on_second_call(self):
        # ... two calls with same token ...
        await tk._pre_execute("tool1", _permission_context=ctx)
        client1 = tk.jira
        await tk._pre_execute("tool2", _permission_context=ctx)
        assert tk.jira is client1  # reused

    def test_legacy_basic_auth_unaffected(self):
        # ... basic_auth mode still works as before ...
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md` Sections 2, 6, 7
2. **Check dependencies** — verify TASK-747, TASK-748, TASK-749, TASK-750 are in `tasks/completed/`
3. **Verify the Codebase Contract** — read `jiratoolkit.py` lines 619-739 for current __init__ and _init_jira_client
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Test pycontribs/jira Bearer auth** — verify `JIRA(options={"headers": {"Authorization": "Bearer ..."}})` works
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-753-jiratoolkit-oauth2-3lo-mode.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus)
**Date**: 2026-04-17
**Notes**:
- Extended ``JiraToolkit.__init__`` with a ``credential_resolver`` kwarg and
  ``auth_type='oauth2_3lo'`` mode.  In OAuth2 3LO mode:
    * ``credential_resolver`` is mandatory (ValueError otherwise).
    * ``server_url`` becomes optional (resolved per-user from
      ``JiraTokenSet.api_base_url`` at runtime).
    * ``self.jira`` starts as ``None`` and the legacy ``_set_jira_client``
      is NOT called.
- Added ``_pre_execute`` override that reads ``_permission_context`` from
  kwargs, resolves credentials via the resolver, and raises
  ``AuthorizationRequired`` (with ``auth_url``) when tokens are missing.
- Added ``_init_jira_client_from_token`` which configures a JIRA client
  using Bearer auth via ``options['headers']['Authorization']``.
- JIRA client cache is keyed by ``{channel}:{user_id}`` and invalidated
  when ``hash(access_token)`` changes, with a simple eviction cap of 100
  entries.
- Legacy ``basic_auth`` / ``token_auth`` / ``oauth`` paths are completely
  unchanged.
- Tests: ``packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py``
  — 11 passing covering init guards, legacy no-op, missing context/user,
  auth URL propagation, per-user cache, cache invalidation on token
  rotation, and multi-user isolation.

**Deviations from spec**: none.  The spec's sketch placed the
``_client_cache`` initialisation inside the ``if self.auth_type == "oauth2_3lo"``
branch of ``__init__`` — implemented exactly that way.
