# FEAT-107 Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all issues identified in the FEAT-107 (Jira OAuth 2.0 3LO) code review, including a production-breaking `_permission_context` routing bug, debug print statements, an `httpx` violation, a distributed lock fallback gap, an unwired Telegram notifier, and several minor quality issues.

**Architecture:** All fixes apply to the feat-107-jira-oauth2-3lo worktree. Critical fix (Task 2) threads the `_permission_context` through `AbstractTool.execute()` → `ToolkitTool._execute()` → `AbstractToolkit._pre_execute()` via a short-lived instance variable `_current_pctx`. The aiohttp migration (Task 3) rewrites all HTTP calls in `JiraOAuthManager` using `aiohttp.ClientSession` async context managers. The notifier wiring (Task 4) changes `handle_callback` to return `(JiraTokenSet, state_payload)` so the route can extract `chat_id` and fire-and-forget a Telegram notification.

**Tech Stack:** Python 3.11, aiohttp, pydantic v2, redis-py async, aiogram, pytest-asyncio

**Worktree:** `/home/jesuslara/proyectos/ai-parrot/.claude/worktrees/feat-107-jira-oauth2-3lo`

---

## File Map

| File | Tasks |
|---|---|
| `packages/ai-parrot/src/parrot/tools/abstract.py` | 1, 2 |
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | 2 |
| `packages/ai-parrot/tests/unit/test_toolkit_hooks.py` | 2 |
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | 3, 4 |
| `packages/ai-parrot/tests/unit/test_jira_oauth_manager.py` | 3, 4 |
| `packages/ai-parrot/src/parrot/auth/routes.py` | 4 |
| `packages/ai-parrot/tests/unit/test_oauth_callback_routes.py` | 4 |
| `packages/ai-parrot/src/parrot/tools/jira_connect_tool.py` | 5 |
| `packages/ai-parrot/src/parrot/tools/manager.py` | 5 |
| `packages/ai-parrot/src/parrot/integrations/telegram/jira_commands.py` | 5 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | 5 |

---

## Task 1: Fix debug `print()` calls and logger f-strings in `abstract.py`

**Files:**
- Modify: `packages/ai-parrot/src/parrot/tools/abstract.py`

### Context

`AbstractTool.execute()` contains two `print()` statements at lines 466-467 that fire on every non-`AuthorizationRequired` exception (e.g., every Jira API error, every validation error). There is also a commented-out print at line 446 and several `f"..."` strings inside `self.logger.*` calls (should use `%s` lazy interpolation).

- [ ] **Step 1: Run baseline tests**

```bash
cd /home/jesuslara/proyectos/ai-parrot/.claude/worktrees/feat-107-jira-oauth2-3lo
source .venv/bin/activate
pytest packages/ai-parrot/tests/unit/test_toolkit_hooks.py packages/ai-parrot/tests/unit/test_auth_required.py -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 2: Remove debug prints and fix logger calls**

Open `packages/ai-parrot/src/parrot/tools/abstract.py`.

Replace the entire `except Exception as e:` block (lines 457–480) with:

```python
        except Exception as e:
            # Let ``AuthorizationRequired`` bubble up to ``ToolManager`` so it
            # can be converted into a structured ``authorization_required``
            # ToolResult (FEAT-107, TASK-748).  Imported lazily to avoid a
            # circular import with ``parrot.auth``.
            from ..auth.exceptions import AuthorizationRequired
            if isinstance(e, AuthorizationRequired):
                raise

            error_msg = f"Error in {self.name}: {str(e)}"
            self.logger.error("Tool %s raised: %s", self.name, e)
            self.logger.debug("%s", traceback.format_exc())

            return ToolResult(
                status="error",
                result=None,
                error=error_msg,
                metadata={
                    "tool_name": self.name,
                    "error_type": type(e).__name__
                }
            )
```

Also in the same file, replace these individual lines:

Line 413:
```python
            self.logger.info(f"Executing tool: {self.name}")
```
→
```python
            self.logger.info("Executing tool: %s", self.name)
```

Lines 431–437 (inside the `elif isinstance(result, dict)` branch):
```python
                    self.logger.error(f"Error creating ToolResult from dict: {e}")
```
→
```python
                    self.logger.error("Error creating ToolResult from dict: %s", e)
```

Lines 443–445:
```python
            self.logger.info(
                f"Tool {self.name} executed successfully"
            )
```
→
```python
            self.logger.info("Tool %s executed successfully", self.name)
```

Line 446 — delete the entire commented-out print line:
```python
            # print('TYPE > ', type(result), ' RESULT > ', result)
```

Lines 395–398 (permission denied warning):
```python
                self.logger.warning(
                    f"Permission denied: user={pctx.user_id} "
                    f"tool={self.name} required={required}"
                )
```
→
```python
                self.logger.warning(
                    "Permission denied: user=%s tool=%s required=%s",
                    pctx.user_id, self.name, required,
                )
```

Line 362 (in `validate_args`):
```python
            self.logger.error(f"Validation error in {self.name}: {e}")
```
→
```python
            self.logger.error("Validation error in %s: %s", self.name, e)
```

- [ ] **Step 3: Run tests again**

```bash
pytest packages/ai-parrot/tests/unit/test_toolkit_hooks.py packages/ai-parrot/tests/unit/test_auth_required.py -v 2>&1 | tail -20
```

Expected: all tests still pass (no change in behavior).

- [ ] **Step 4: Commit**

```bash
cd /home/jesuslara/proyectos/ai-parrot/.claude/worktrees/feat-107-jira-oauth2-3lo
git add packages/ai-parrot/src/parrot/tools/abstract.py
git commit -m "fix(tools): remove debug print()s and fix logger f-strings in AbstractTool.execute"
```

---

## Task 2: Thread `_permission_context` through to `_pre_execute` (CRITICAL)

**Files:**
- Modify: `packages/ai-parrot/src/parrot/tools/abstract.py`
- Modify: `packages/ai-parrot/src/parrot/tools/toolkit.py`
- Modify: `packages/ai-parrot/tests/unit/test_toolkit_hooks.py`

### Context

`AbstractTool.execute()` pops `_permission_context` from kwargs at line 388, then calls `self._execute(**validated_args.model_dump())` — which does NOT include `_permission_context`. When `ToolkitTool._execute()` calls `toolkit._pre_execute(self.name, **kwargs)`, `_permission_context` is never in those kwargs. `JiraToolkit._pre_execute()` therefore **always** gets `perm_ctx = None` and **always** raises "Permission context required", making `oauth2_3lo` mode completely broken in production.

Fix: store the popped `pctx` in `self._current_pctx` (a short-lived instance variable on the `ToolkitTool`) and clean it up in a `finally` block. `ToolkitTool._execute()` reads it back and injects it into the `_pre_execute` call.

- [ ] **Step 1: Write the failing integration test first**

Add to `packages/ai-parrot/tests/unit/test_toolkit_hooks.py`:

```python
class TestPermissionContextForwarding:
    """Verify _permission_context is available inside _pre_execute when routed through ToolManager."""

    @pytest.mark.asyncio
    async def test_permission_context_forwarded_to_pre_execute(self) -> None:
        """Full chain: execute_tool → execute → _execute → _pre_execute gets pctx."""
        from parrot.tools.manager import ToolManager
        from parrot.auth.permission import PermissionContext, UserSession

        received: dict = {}

        class ObservingToolkit(AbstractToolkit):
            async def _pre_execute(self, tool_name: str, **kwargs) -> None:
                received["pctx"] = kwargs.get("_permission_context")

            async def observe(self) -> str:
                """Return a fixed string."""
                return "ok"

        session = UserSession(user_id="u-test", tenant_id="t-test", roles=frozenset())
        ctx = PermissionContext(session=session)

        tk = ObservingToolkit()
        manager = ToolManager()
        manager.register_toolkit(tk)

        await manager.execute_tool("observe", {}, permission_context=ctx)

        assert received.get("pctx") is ctx, (
            "_permission_context was not forwarded to _pre_execute; "
            f"received: {received.get('pctx')!r}"
        )

    @pytest.mark.asyncio
    async def test_permission_context_none_when_not_provided(self) -> None:
        """_permission_context kwarg is None (not missing) in _pre_execute when not set."""
        received: dict = {}

        class NullContextToolkit(AbstractToolkit):
            async def _pre_execute(self, tool_name: str, **kwargs) -> None:
                received["pctx"] = kwargs.get("_permission_context", "MISSING")

            async def act(self) -> str:
                """Do something."""
                return "done"

        tk = NullContextToolkit()
        from parrot.tools.manager import ToolManager
        manager = ToolManager()
        manager.register_toolkit(tk)

        await manager.execute_tool("act", {})  # no permission_context

        # Should be None (not the "MISSING" sentinel) because _current_pctx is always set
        assert received["pctx"] is None
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /home/jesuslara/proyectos/ai-parrot/.claude/worktrees/feat-107-jira-oauth2-3lo
source .venv/bin/activate
pytest packages/ai-parrot/tests/unit/test_toolkit_hooks.py::TestPermissionContextForwarding -v 2>&1 | tail -20
```

Expected: `FAILED — AssertionError: _permission_context was not forwarded to _pre_execute`

- [ ] **Step 3: Fix `AbstractTool.execute()` — store pctx before `_execute`, clear in `finally`**

In `packages/ai-parrot/src/parrot/tools/abstract.py`, replace the `execute` method body.

The section starting at line 387 (after the docstring) currently reads:
```python
        # ── Permission check (Layer 2 safety net) ────────────────────────────
        pctx = kwargs.pop('_permission_context', None)
        resolver = kwargs.pop('_resolver', None)

        if pctx is not None and resolver is not None:
            ...
            
        # ── Normal execution ─────────────────────────────────────────────────
        try:
            ...
        except Exception as e:
            ...
            return ToolResult(...)
```

Replace (from "# ── Permission check" through the end of the existing `except` block) with:

```python
        # ── Permission check (Layer 2 safety net) ────────────────────────────
        pctx = kwargs.pop('_permission_context', None)
        resolver = kwargs.pop('_resolver', None)

        # Store for lifecycle hooks.  ToolkitTool._execute reads ``_current_pctx``
        # and injects it back into the ``_pre_execute`` / ``_post_execute`` calls
        # so toolkits can access the request context (FEAT-107 oauth2_3lo mode).
        # Safe for single-agent sessions; do not share one ToolkitTool instance
        # across concurrent tasks.
        self._current_pctx = pctx

        if pctx is not None and resolver is not None:
            required = getattr(self, '_required_permissions', set())
            allowed = await resolver.can_execute(pctx, self.name, required)
            if not allowed:
                self.logger.warning(
                    "Permission denied: user=%s tool=%s required=%s",
                    pctx.user_id, self.name, required,
                )
                self._current_pctx = None
                return ToolResult(
                    success=False,
                    status='forbidden',
                    result=None,
                    error=f"Permission denied: '{self.name}' requires {required}",
                    metadata={
                        "tool_name": self.name,
                        "user_id": pctx.user_id,
                        "required_permissions": list(required),
                    }
                )

        # ── Normal execution ─────────────────────────────────────────────────
        try:
            self.logger.info("Executing tool: %s", self.name)

            # Validate arguments
            validated_args = self.validate_args(**kwargs)

            # Execute the tool
            if hasattr(validated_args, 'model_dump'):
                result = await self._execute(*args, **validated_args.model_dump())
            else:
                result = await self._execute(*args, **kwargs)

            # if is an toolResult, return it directly
            if isinstance(result, ToolResult):
                return result
            elif isinstance(result, dict) and 'status' in result and 'result' in result:
                try:
                    return ToolResult(**result)
                except Exception as e:
                    self.logger.error("Error creating ToolResult from dict: %s", e)
                    return ToolResult(
                        status="done_with_errors",
                        result=result.get('result', []),
                        error=f"Error creating ToolResult: {e}",
                        metadata=result.get('metadata', {})
                    )
            if result is None:
                raise ValueError(
                    "Tool execution returned None, expected a result."
                )

            self.logger.info("Tool %s executed successfully", self.name)

            return ToolResult(
                status="success",
                result=result,
                metadata={
                    "tool_name": self.name,
                    "execution_time": datetime.now().isoformat()
                }
            )

        except Exception as e:
            # Let ``AuthorizationRequired`` bubble up to ``ToolManager`` so it
            # can be converted into a structured ``authorization_required``
            # ToolResult (FEAT-107, TASK-748).  Imported lazily to avoid a
            # circular import with ``parrot.auth``.
            from ..auth.exceptions import AuthorizationRequired
            if isinstance(e, AuthorizationRequired):
                raise

            error_msg = f"Error in {self.name}: {str(e)}"
            self.logger.error("Tool %s raised: %s", self.name, e)
            self.logger.debug("%s", traceback.format_exc())

            return ToolResult(
                status="error",
                result=None,
                error=error_msg,
                metadata={
                    "tool_name": self.name,
                    "error_type": type(e).__name__
                }
            )
        finally:
            # Always clear the per-call context so stale references don't linger.
            self._current_pctx = None
```

- [ ] **Step 4: Fix `ToolkitTool._execute()` — forward `_current_pctx` to hooks**

In `packages/ai-parrot/src/parrot/tools/toolkit.py`, replace the `_execute` method body (lines 127–150):

```python
    async def _execute(self, **kwargs) -> Any:
        """
        Execute the toolkit method.

        Invokes the parent toolkit's ``_pre_execute`` lifecycle hook before
        calling the bound method and its ``_post_execute`` hook after. This
        lets toolkits resolve credentials, emit metrics, or transform results
        transparently for every tool call.

        The ``_permission_context`` that was stripped by
        :meth:`AbstractTool.execute` is re-injected here via the
        ``_current_pctx`` instance variable so that lifecycle hooks (e.g.,
        ``JiraToolkit._pre_execute``) can access the request context.

        Args:
            **kwargs: Method arguments (validated tool parameters only).

        Returns:
            Method result (possibly transformed by ``_post_execute``).
        """
        toolkit = getattr(self.bound_method, "__self__", None)
        if isinstance(toolkit, AbstractToolkit):
            # Rebuild hook_kwargs: tool params + the permission context that
            # AbstractTool.execute() popped from kwargs before validation.
            pctx = getattr(self, "_current_pctx", None)
            hook_kwargs = dict(kwargs)
            if pctx is not None:
                hook_kwargs["_permission_context"] = pctx
            await toolkit._pre_execute(self.name, **hook_kwargs)

        result = await self.bound_method(**kwargs)

        if isinstance(toolkit, AbstractToolkit):
            result = await toolkit._post_execute(self.name, result, **kwargs)
        return result
```

- [ ] **Step 5: Run the new integration tests**

```bash
pytest packages/ai-parrot/tests/unit/test_toolkit_hooks.py -v 2>&1 | tail -30
```

Expected: all tests pass including the two new `TestPermissionContextForwarding` tests.

- [ ] **Step 6: Run the full unit test suite**

```bash
pytest packages/ai-parrot/tests/unit/ -v 2>&1 | tail -30
```

Expected: all tests pass (zero regressions).

- [ ] **Step 7: Commit**

```bash
git add packages/ai-parrot/src/parrot/tools/abstract.py \
        packages/ai-parrot/src/parrot/tools/toolkit.py \
        packages/ai-parrot/tests/unit/test_toolkit_hooks.py
git commit -m "fix(tools): thread _permission_context through to AbstractToolkit._pre_execute

AbstractTool.execute() pops _permission_context before calling _execute(),
so lifecycle hooks never received it.  Fix: store as self._current_pctx
before _execute(), cleared in finally.  ToolkitTool._execute() reads it
back and injects into _pre_execute() as _permission_context kwarg.

This unblocks JiraToolkit oauth2_3lo mode which was always raising
AuthorizationRequired with 'Permission context required' even for
authenticated users (FEAT-107 review finding)."
```

---

## Task 3: Replace `httpx` with `aiohttp` in `JiraOAuthManager` + fix lock fallback

**Files:**
- Modify: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`
- Modify: `packages/ai-parrot/tests/unit/test_jira_oauth_manager.py`

### Context

`jira_oauth.py` imports and uses `httpx.AsyncClient` in violation of AI-Parrot's CONTEXT.md rule ("Never use `requests` or `httpx` — use `aiohttp`"). Additionally, `_refresh_tokens` calls `lock.acquire()` but does not handle the case where `acquire()` returns `False` (blocking timeout elapsed), allowing the refresh to proceed without the lock and exposing a race condition on Atlassian's rotating refresh tokens.

Both issues are fixed in this task since they both touch `jira_oauth.py`.

- [ ] **Step 1: Add aiohttp helper + update `__init__` and `aclose`**

In `packages/ai-parrot/src/parrot/auth/jira_oauth.py`:

Replace the `import httpx` at line 26 with:

```python
import aiohttp
```

Replace `__init__` signature and body (the `self._http` line specifically). Current:
```python
        self._http = http_client or httpx.AsyncClient(timeout=30.0)
```

Replace the entire `__init__` parameter `http_client: Optional[httpx.AsyncClient] = None` and its assignment with:

```python
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        redis_client: Any,
        scopes: Optional[List[str]] = None,
        http_session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.redis = redis_client
        self.scopes: List[str] = list(scopes) if scopes else list(DEFAULT_SCOPES)
        self._http: Optional[aiohttp.ClientSession] = http_session
        self._http_owned: bool = http_session is None  # True if we must close it
        self.logger = logger
```

Add this helper method right after `_lock_key`:

```python
    async def _get_session(self) -> aiohttp.ClientSession:
        """Return the shared aiohttp session, creating it lazily if needed."""
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
            )
            self._http_owned = True
        return self._http
```

Replace the `aclose` method:

```python
    async def aclose(self) -> None:
        """Close the underlying aiohttp session if this manager owns it."""
        if self._http_owned and self._http and not self._http.closed:
            await self._http.close()
        self._http = None
```

- [ ] **Step 2: Rewrite `_exchange_code` with aiohttp**

Replace:
```python
    async def _exchange_code(self, code: str) -> Dict[str, Any]:
        response = await self._http.post(
            self.token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
        )
        if response.status_code != 200:
            raise ValueError(
                f"Token exchange failed with status {response.status_code}: "
                f"{response.text}"
            )
        return response.json()
```

With:
```python
    async def _exchange_code(self, code: str) -> Dict[str, Any]:
        session = await self._get_session()
        async with session.post(
            self.token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise ValueError(
                    f"Token exchange failed with status {response.status}: {text}"
                )
            return await response.json()
```

- [ ] **Step 3: Rewrite `_fetch_accessible_resources` with aiohttp**

Replace:
```python
    async def _fetch_accessible_resources(self, access_token: str) -> List[Dict[str, Any]]:
        response = await self._http.get(
            self.accessible_resources_url,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        if response.status_code != 200:
            raise ValueError(
                f"accessible-resources failed with status {response.status_code}: "
                f"{response.text}"
            )
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("accessible-resources returned a non-list payload.")
        return data
```

With:
```python
    async def _fetch_accessible_resources(self, access_token: str) -> List[Dict[str, Any]]:
        session = await self._get_session()
        async with session.get(
            self.accessible_resources_url,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise ValueError(
                    f"accessible-resources failed with status {response.status}: {text}"
                )
            data = await response.json()
            if not isinstance(data, list):
                raise ValueError("accessible-resources returned a non-list payload.")
            return data
```

- [ ] **Step 4: Rewrite `_fetch_myself` with aiohttp**

Replace:
```python
    async def _fetch_myself(self, access_token: str, cloud_id: str) -> Dict[str, Any]:
        url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/myself"
        response = await self._http.get(
            url,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        if response.status_code != 200:
            raise ValueError(
                f"/myself failed with status {response.status_code}: {response.text}"
            )
        return response.json()
```

With:
```python
    async def _fetch_myself(self, access_token: str, cloud_id: str) -> Dict[str, Any]:
        url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/myself"
        session = await self._get_session()
        async with session.get(
            url,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise ValueError(
                    f"/myself failed with status {response.status}: {text}"
                )
            return await response.json()
```

- [ ] **Step 5: Rewrite `_refresh_tokens` with aiohttp + fix lock fallback**

Replace the entire `_refresh_tokens` method:

```python
    async def _refresh_tokens(
        self, channel: str, user_id: str, token_set: JiraTokenSet
    ) -> JiraTokenSet:
        """Refresh a user's tokens using the rotating refresh token.

        Uses a Redis distributed lock so that concurrent refresh requests
        do not both consume the old refresh token (Atlassian rotates it on
        each successful refresh; the second request would otherwise be
        rejected).

        If the lock cannot be acquired within ``_REFRESH_LOCK_BLOCKING_TIMEOUT``
        seconds, the method re-reads the token (another process may have
        refreshed already) and returns it if still valid, or raises
        ``PermissionError`` so the caller can surface the issue rather than
        silently proceeding without lock protection.
        """
        key = self._token_key(channel, user_id)
        lock_name = self._lock_key(channel, user_id)
        lock = self.redis.lock(
            lock_name,
            timeout=_REFRESH_LOCK_TIMEOUT,
            blocking_timeout=_REFRESH_LOCK_BLOCKING_TIMEOUT,
        )
        acquired = await lock.acquire()
        if not acquired:
            # Another process is holding the lock.  Re-read — it may have
            # just finished refreshing and stored a fresh token.
            self.logger.warning(
                "Could not acquire refresh lock for %s:%s within %ss; re-reading",
                channel, user_id, _REFRESH_LOCK_BLOCKING_TIMEOUT,
            )
            fresh = await self._read_token(key)
            if fresh and not fresh.is_expired:
                return fresh
            raise PermissionError(
                f"Jira token refresh lock unavailable for {channel}:{user_id}. "
                "Another refresh may be in progress — retry after a moment."
            )

        try:
            # Another request may have refreshed already while we waited.
            fresh = await self._read_token(key)
            if fresh and not fresh.is_expired:
                return fresh

            current = fresh or token_set
            try:
                session = await self._get_session()
                async with session.post(
                    self.token_url,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": current.refresh_token,
                    },
                ) as response:
                    if response.status == 401:
                        # Atlassian rejected the refresh token — revoke locally.
                        await self.revoke(channel, user_id)
                        raise PermissionError(
                            "Jira refresh token rejected (401); user must re-authorize."
                        )
                    if response.status != 200:
                        text = await response.text()
                        raise PermissionError(
                            f"Jira token refresh failed with status {response.status}: {text}"
                        )
                    payload = await response.json()

            except aiohttp.ClientError as exc:
                raise PermissionError(
                    f"Jira token refresh network error: {exc}"
                ) from exc

            now = time.time()
            refreshed = token_set.model_copy(update={
                "access_token": payload["access_token"],
                "refresh_token": payload.get("refresh_token", token_set.refresh_token),
                "expires_at": now + int(payload.get("expires_in", 3600)),
                "last_refreshed_at": now,
            })
            await self._write_token(key, refreshed)
            return refreshed
        finally:
            try:
                await lock.release()
            except Exception:  # pragma: no cover - lock already released
                pass
```

- [ ] **Step 6: Update tests to use aiohttp mock helpers**

In `packages/ai-parrot/tests/unit/test_jira_oauth_manager.py`, add this helper at the top of the file (after the imports):

```python
def _mock_response(
    status: int,
    json_data: Any = None,
    text_data: str = "",
) -> MagicMock:
    """Build a mock aiohttp response that works as an async context manager."""
    from unittest.mock import AsyncMock, MagicMock
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data if json_data is not None else {})
    resp.text = AsyncMock(return_value=text_data)
    # Support ``async with session.post(...) as response:``
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _mock_session(*responses: MagicMock) -> MagicMock:
    """Return a mock aiohttp.ClientSession where post/get return successive responses."""
    session = MagicMock()
    session.closed = False  # prevents _get_session() from recreating it
    it = iter(responses)

    def _next_response(*args, **kwargs):
        try:
            return next(it)
        except StopIteration:
            return responses[-1]  # repeat last

    session.post.side_effect = _next_response
    session.get.side_effect = _next_response
    return session
```

Also add `from typing import Any` to the imports if not already there.

Update `TestHandleCallback.test_full_exchange_stores_token` — replace the mock setup and assertion:

```python
    @pytest.mark.asyncio
    async def test_full_exchange_stores_token(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        # Seed a valid nonce first.
        _, nonce = await manager.create_authorization_url("telegram", "user-7")
        fake_redis.set_calls.clear()

        exchange = _mock_response(200, json_data={
            "access_token": "at_123",
            "refresh_token": "rt_456",
            "expires_in": 3600,
            "scope": "read:jira-work write:jira-work offline_access",
        })
        resources = _mock_response(200, json_data=[
            {
                "id": "cloud-uuid-1",
                "name": "mysite",
                "url": "https://mysite.atlassian.net",
                "scopes": ["read:jira-work"],
            }
        ])
        myself = _mock_response(200, json_data={
            "accountId": "acc-123",
            "displayName": "Jesus Garcia",
            "emailAddress": "jesus@example.com",
        })

        manager._http = _mock_session(exchange, resources, myself)

        token, state_payload = await manager.handle_callback(code="auth-code", state=nonce)

        assert isinstance(token, JiraTokenSet)
        assert token.access_token == "at_123"
        assert token.refresh_token == "rt_456"
        assert token.cloud_id == "cloud-uuid-1"
        assert token.site_url == "https://mysite.atlassian.net"
        assert token.display_name == "Jesus Garcia"
        assert token.email == "jesus@example.com"
        assert "offline_access" in token.scopes
        assert state_payload["channel"] == "telegram"
        assert state_payload["user_id"] == "user-7"

        # Nonce deleted after use.
        assert f"jira:nonce:{nonce}" in fake_redis.deleted
        # Token persisted under the per-user key with 90-day TTL.
        assert fake_redis.set_calls, "Expected token set in Redis"
        key, _, ttl = fake_redis.set_calls[-1]
        assert key == "jira:oauth:telegram:user-7"
        assert ttl == 90 * 24 * 60 * 60
```

Update `TestGetValidToken.test_refresh_on_expired_token`:

```python
    @pytest.mark.asyncio
    async def test_refresh_on_expired_token(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        expired = JiraTokenSet(
            access_token="old",
            refresh_token="rt_old",
            expires_at=time.time() - 10,
            cloud_id="c",
            site_url="https://x.atlassian.net",
            account_id="a",
            display_name="Test",
        )
        fake_redis.store["jira:oauth:tg:u1"] = expired.model_dump_json()

        refresh_resp = _mock_response(200, json_data={
            "access_token": "new",
            "refresh_token": "rt_new",
            "expires_in": 3600,
        })
        manager._http = _mock_session(refresh_resp)

        refreshed = await manager.get_valid_token("tg", "u1")
        assert refreshed is not None
        assert refreshed.access_token == "new"
        assert refreshed.refresh_token == "rt_new"
        # Rotating refresh token must be persisted in Redis.
        stored = JiraTokenSet.model_validate_json(
            fake_redis.store["jira:oauth:tg:u1"]
        )
        assert stored.refresh_token == "rt_new"
```

Update `TestGetValidToken.test_refresh_401_revokes_and_raises`:

```python
    @pytest.mark.asyncio
    async def test_refresh_401_revokes_and_raises(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        expired = JiraTokenSet(
            access_token="old",
            refresh_token="rt_old",
            expires_at=time.time() - 10,
            cloud_id="c",
            site_url="https://x.atlassian.net",
            account_id="a",
            display_name="Test",
        )
        fake_redis.store["jira:oauth:tg:u1"] = expired.model_dump_json()

        bad = _mock_response(401, text_data="refresh token rejected")
        manager._http = _mock_session(bad)

        with pytest.raises(PermissionError, match="re-authorize"):
            await manager.get_valid_token("tg", "u1")

        assert "jira:oauth:tg:u1" not in fake_redis.store
```

Add a new test for the lock fallback at the end of `TestGetValidToken`:

```python
    @pytest.mark.asyncio
    async def test_refresh_lock_not_acquired_re_reads_fresh_token(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        """When lock.acquire() returns False, the manager re-reads the token."""
        import time as _time

        expired = JiraTokenSet(
            access_token="old",
            refresh_token="rt_old",
            expires_at=_time.time() - 10,
            cloud_id="c",
            site_url="https://x.atlassian.net",
            account_id="a",
            display_name="Test",
        )
        fake_redis.store["jira:oauth:tg:u1"] = expired.model_dump_json()

        # Simulate a lock that cannot be acquired (returns False)
        non_blocking_lock = MagicMock()
        non_blocking_lock.acquire = AsyncMock(return_value=False)
        non_blocking_lock.release = AsyncMock()

        original_lock = fake_redis.lock

        def patched_lock(name, **kwargs):
            lock = original_lock(name, **kwargs)
            lock.acquire = AsyncMock(return_value=False)
            return lock

        fake_redis.lock = patched_lock

        # Simulate another process having refreshed the token in Redis
        fresh = expired.model_copy(update={
            "access_token": "refreshed_by_other",
            "expires_at": _time.time() + 3600,
        })
        fake_redis.store["jira:oauth:tg:u1"] = fresh.model_dump_json()

        result = await manager.get_valid_token("tg", "u1")
        assert result is not None
        assert result.access_token == "refreshed_by_other"

    @pytest.mark.asyncio
    async def test_refresh_lock_not_acquired_raises_when_still_expired(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        """Lock not acquired + token still expired → PermissionError."""
        import time as _time

        expired = JiraTokenSet(
            access_token="old",
            refresh_token="rt_old",
            expires_at=_time.time() - 10,
            cloud_id="c",
            site_url="https://x.atlassian.net",
            account_id="a",
            display_name="Test",
        )
        fake_redis.store["jira:oauth:tg:u1"] = expired.model_dump_json()

        def patched_lock(name, **kwargs):
            lock = MagicMock()
            lock.acquire = AsyncMock(return_value=False)
            return lock

        fake_redis.lock = patched_lock

        with pytest.raises(PermissionError, match="lock unavailable"):
            await manager.get_valid_token("tg", "u1")
```

- [ ] **Step 7: Update `handle_callback` return type**

In `packages/ai-parrot/src/parrot/auth/jira_oauth.py`, update the `handle_callback` signature and its `return` statement.

Change the signature from:
```python
    async def handle_callback(self, code: str, state: str) -> JiraTokenSet:
```
To:
```python
    async def handle_callback(self, code: str, state: str) -> Tuple[JiraTokenSet, Dict[str, Any]]:
```

Change the final `return token` to:
```python
        return token, state_payload
```

(Keep all the rest of `handle_callback` unchanged.)

- [ ] **Step 8: Run tests**

```bash
cd /home/jesuslara/proyectos/ai-parrot/.claude/worktrees/feat-107-jira-oauth2-3lo
source .venv/bin/activate
pytest packages/ai-parrot/tests/unit/test_jira_oauth_manager.py -v 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add packages/ai-parrot/src/parrot/auth/jira_oauth.py \
        packages/ai-parrot/tests/unit/test_jira_oauth_manager.py
git commit -m "fix(auth): replace httpx with aiohttp in JiraOAuthManager + fix lock fallback

- Replace httpx.AsyncClient with aiohttp.ClientSession (lazy-created, owned
  by manager, closed in aclose()).  All HTTP methods use async context
  managers as per AI-Parrot CONTEXT.md convention.
- _refresh_tokens now checks lock.acquire() return value: if False, re-reads
  the token (another process may have refreshed) and raises PermissionError
  if still expired rather than proceeding without the lock.
- handle_callback now returns (JiraTokenSet, state_payload) so callers can
  extract extra.chat_id for post-callback Telegram notifications."
```

---

## Task 4: Wire `TelegramOAuthNotifier` into the callback route

**Files:**
- Modify: `packages/ai-parrot/src/parrot/auth/routes.py`
- Modify: `packages/ai-parrot/tests/unit/test_oauth_callback_routes.py`

### Context

`jira_commands.py` stores `{"chat_id": message.chat.id}` in `extra_state` when generating the authorization URL so the callback can notify the user. The `TelegramOAuthNotifier` class exists and is correctly implemented. However, `routes.py` never calls it — the user gets the HTML success page in their browser but no Telegram confirmation message. This task wires the notifier in as a fire-and-forget task.

- [ ] **Step 1: Update `routes.py` to unpack the tuple and call the notifier**

Replace the entire `routes.py` with:

```python
"""HTTP routes for OAuth callbacks.

This module exposes the aiohttp route that Atlassian's consent page
redirects to after a user authorizes their Jira account:

- ``GET /api/auth/jira/callback?code=...&state=...``

The handler validates the CSRF state nonce, exchanges the code for
tokens via :class:`JiraOAuthManager`, and renders a browser-friendly
HTML success/error page.  The manager must be stored on
``app['jira_oauth_manager']`` at application startup.

Optionally, a :class:`TelegramOAuthNotifier` stored on
``app['jira_oauth_notifier']`` receives a fire-and-forget notification
after successful callbacks that originated from Telegram (i.e. the
authorization URL included ``extra_state={"chat_id": ...}``).
"""
from __future__ import annotations

import asyncio
import html
import logging
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:  # pragma: no cover - type-checking only
    from .jira_oauth import JiraOAuthManager
    from parrot.integrations.telegram.jira_commands import TelegramOAuthNotifier


logger = logging.getLogger(__name__)


_SUCCESS_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Jira Connected</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f5f5f5}}
.container{{text-align:center;padding:2rem}}.check{{font-size:3rem;color:#36b37e}}</style>
</head><body><div class="container">
<div class="check">&#10003;</div>
<h2>Jira Connected</h2>
<p>Hi {display_name}! Your Jira account ({site_url}) is now linked.</p>
<p>You can close this window and return to your chat.</p>
</div></body></html>"""


_ERROR_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Authorization Failed</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f5f5f5}}
.container{{text-align:center;padding:2rem}}.x{{font-size:3rem;color:#de350b}}</style>
</head><body><div class="container">
<div class="x">&#10007;</div>
<h2>Authorization Failed</h2>
<p>{error}</p>
</div></body></html>"""


def _error_response(message: str, status: int = 400) -> web.Response:
    return web.Response(
        text=_ERROR_HTML.format(error=html.escape(message)),
        content_type="text/html",
        status=status,
    )


async def jira_oauth_callback(request: web.Request) -> web.Response:
    """Handle ``GET /api/auth/jira/callback``.

    Validates required query parameters, delegates the exchange to
    :class:`JiraOAuthManager`, and renders an HTML page for the browser.
    After a successful exchange, optionally fires a Telegram notification
    via the :class:`TelegramOAuthNotifier` stored on ``app['jira_oauth_notifier']``.
    """
    code = request.query.get("code")
    state = request.query.get("state")

    if not code or not state:
        return _error_response("Missing code or state parameter.", status=400)

    manager: "JiraOAuthManager | None" = request.app.get("jira_oauth_manager")
    if manager is None:
        logger.error("jira_oauth_manager not registered on the aiohttp app")
        return _error_response(
            "OAuth manager not configured on the server.", status=500,
        )

    try:
        token_set, state_payload = await manager.handle_callback(code, state)
    except ValueError as exc:
        return _error_response(str(exc), status=400)
    except Exception:  # noqa: BLE001
        logger.exception("OAuth callback error")
        return _error_response(
            "An unexpected error occurred while exchanging the authorization code.",
            status=500,
        )

    # Fire-and-forget Telegram notification (does not block the browser response).
    notifier: "TelegramOAuthNotifier | None" = request.app.get("jira_oauth_notifier")
    if notifier is not None:
        extra = (state_payload.get("extra") or {})
        chat_id = extra.get("chat_id")
        if chat_id:
            asyncio.get_running_loop().create_task(
                notifier.notify_connected(
                    int(chat_id),
                    token_set.display_name or "",
                    token_set.site_url or "",
                )
            )

    return web.Response(
        text=_SUCCESS_HTML.format(
            display_name=html.escape(token_set.display_name or ""),
            site_url=html.escape(token_set.site_url or ""),
        ),
        content_type="text/html",
    )


def setup_jira_oauth_routes(app: web.Application) -> None:
    """Attach the Jira OAuth callback route to *app*.

    Call this once at application startup, after the
    :class:`JiraOAuthManager` has been stored at ``app['jira_oauth_manager']``.
    Optionally store a :class:`TelegramOAuthNotifier` at
    ``app['jira_oauth_notifier']`` to enable post-callback Telegram messages.
    """
    app.router.add_get("/api/auth/jira/callback", jira_oauth_callback)

    # Ensure the route is not subjected to the auth middleware — it IS the
    # authorization callback itself.
    try:  # pragma: no cover - navigator_auth is optional in tests
        from navigator_auth.conf import exclude_list  # type: ignore

        if "/api/auth/jira/callback" not in exclude_list:
            exclude_list.append("/api/auth/jira/callback")
    except ImportError:
        pass
```

- [ ] **Step 2: Update existing route tests**

In `packages/ai-parrot/tests/unit/test_oauth_callback_routes.py`, update all tests that mock `handle_callback` to return a tuple:

Find every occurrence of:
```python
mock_manager.handle_callback = AsyncMock(return_value=token)
```
Replace with:
```python
mock_manager.handle_callback = AsyncMock(
    return_value=(token, {"channel": "telegram", "user_id": "u1", "extra": {}})
)
```

Add a new test for the notifier at the end of the class:

```python
    @pytest.mark.asyncio
    async def test_notifier_called_when_chat_id_present(self, aiohttp_client):
        from parrot.auth.routes import setup_jira_oauth_routes
        from parrot.auth.jira_oauth import JiraTokenSet
        from unittest.mock import AsyncMock, MagicMock

        token = JiraTokenSet(
            access_token="at", refresh_token="rt", expires_at=9999999999,
            cloud_id="c", site_url="https://test.atlassian.net",
            account_id="a", display_name="Test User",
        )
        state_payload = {
            "channel": "telegram",
            "user_id": "12345",
            "extra": {"chat_id": 99887766},
        }

        mock_manager = MagicMock()
        mock_manager.handle_callback = AsyncMock(return_value=(token, state_payload))

        mock_notifier = MagicMock()
        mock_notifier.notify_connected = AsyncMock()

        app = web.Application()
        app["jira_oauth_manager"] = mock_manager
        app["jira_oauth_notifier"] = mock_notifier
        setup_jira_oauth_routes(app)

        client = await aiohttp_client(app)
        resp = await client.get("/api/auth/jira/callback?code=x&state=y")

        assert resp.status == 200
        # Give the fire-and-forget task a chance to run
        import asyncio
        await asyncio.sleep(0)
        mock_notifier.notify_connected.assert_awaited_once_with(
            99887766, "Test User", "https://test.atlassian.net"
        )

    @pytest.mark.asyncio
    async def test_notifier_not_called_when_no_chat_id(self, aiohttp_client):
        from parrot.auth.routes import setup_jira_oauth_routes
        from parrot.auth.jira_oauth import JiraTokenSet
        from unittest.mock import AsyncMock, MagicMock

        token = JiraTokenSet(
            access_token="at", refresh_token="rt", expires_at=9999999999,
            cloud_id="c", site_url="https://test.atlassian.net",
            account_id="a", display_name="Test User",
        )
        # extra has no chat_id (e.g., web UI flow)
        state_payload = {"channel": "api", "user_id": "u1", "extra": {}}

        mock_manager = MagicMock()
        mock_manager.handle_callback = AsyncMock(return_value=(token, state_payload))
        mock_notifier = MagicMock()
        mock_notifier.notify_connected = AsyncMock()

        app = web.Application()
        app["jira_oauth_manager"] = mock_manager
        app["jira_oauth_notifier"] = mock_notifier
        setup_jira_oauth_routes(app)

        client = await aiohttp_client(app)
        resp = await client.get("/api/auth/jira/callback?code=x&state=y")

        assert resp.status == 200
        import asyncio
        await asyncio.sleep(0)
        mock_notifier.notify_connected.assert_not_awaited()
```

- [ ] **Step 3: Run tests**

```bash
pytest packages/ai-parrot/tests/unit/test_oauth_callback_routes.py -v 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add packages/ai-parrot/src/parrot/auth/routes.py \
        packages/ai-parrot/tests/unit/test_oauth_callback_routes.py
git commit -m "fix(auth): wire TelegramOAuthNotifier into OAuth callback route

After a successful Jira OAuth exchange, the route now fires a
fire-and-forget Telegram notification when state_payload['extra']['chat_id']
is present.  The notifier is opt-in via app['jira_oauth_notifier'] so
non-Telegram deployments are unaffected."
```

---

## Task 5: Fix remaining minor issues

**Files:**
- Modify: `packages/ai-parrot/src/parrot/tools/jira_connect_tool.py`
- Modify: `packages/ai-parrot/src/parrot/tools/manager.py`
- Modify: `packages/ai-parrot/src/parrot/integrations/telegram/jira_commands.py`
- Modify: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`

### Context

Four remaining issues:

1. **`jira_connect_tool.py:173`** — `hotswap_to_full_toolkit` accesses the private `tool_manager._tools` dict directly. `ToolManager.remove_tool()` already exists — just use it.
2. **`manager.py:884` and others** — f-strings in logger calls inside `ToolManager` and `toolkit.py`.
3. **`jira_commands.py:76`** — `disconnect_jira_handler` silently returns (no reply) when `message.from_user is None`.
4. **`jiratoolkit.py:695`** — `_client_cache` typed as `Dict[str, tuple]` (too generic); and `hash(token_set.access_token)` uses Python's non-deterministic built-in hash.

- [ ] **Step 1: Fix `hotswap_to_full_toolkit` to use `tool_manager.remove_tool()`**

In `packages/ai-parrot/src/parrot/tools/jira_connect_tool.py`, replace lines 172–175:

```python
    # Remove the placeholder if present.  ToolManager stores registered
    # tools on ``_tools``; we pop directly to avoid depending on any
    # particular removal API.
    tools_map = getattr(tool_manager, "_tools", None)
    if isinstance(tools_map, dict):
        tools_map.pop("connect_jira", None)
```

With:

```python
    # Remove the placeholder via the public API.
    tool_manager.remove_tool("connect_jira")
```

- [ ] **Step 2: Fix f-strings in `manager.py` logger calls**

In `packages/ai-parrot/src/parrot/tools/manager.py`:

Line 1163:
```python
                self.logger.debug(
                    f"Executed tool '{tool_name}' with parameters: {parameters}"
                )
```
→
```python
                self.logger.debug(
                    "Executed tool %r with parameters: %s", tool_name, parameters
                )
```

Line 1217:
```python
            self.logger.error(
                f"Error executing tool {tool_name}: {e}"
            )
```
→
```python
            self.logger.error("Error executing tool %s: %s", tool_name, e)
```

Line 884 (in `remove_tool`):
```python
            self.logger.debug(
                f"Removed tool: {tool_name}"
            )
```
→
```python
            self.logger.debug("Removed tool: %s", tool_name)
```

Line 888:
```python
            self.logger.warning(f"Tool not found: {tool_name}")
```
→
```python
            self.logger.warning("Tool not found: %s", tool_name)
```

Also fix in `packages/ai-parrot/src/parrot/tools/toolkit.py` line 124:
```python
            self.logger.warning(f"Could not generate schema for {self.name}: {e}")
```
→
```python
            self.logger.warning("Could not generate schema for %s: %s", self.name, e)
```

- [ ] **Step 3: Fix silent return in `disconnect_jira_handler`**

In `packages/ai-parrot/src/parrot/integrations/telegram/jira_commands.py`, replace the `disconnect_jira_handler` body:

```python
async def disconnect_jira_handler(
    message: Message, oauth_manager: "JiraOAuthManager"
) -> None:
    """Handle ``/disconnect_jira`` — revoke any stored tokens."""
    if message.from_user is None:
        await message.reply(
            "I can only manage Jira connections for a real Telegram user."
        )
        return
    user_id = str(message.from_user.id)
    await oauth_manager.revoke(_TELEGRAM_CHANNEL, user_id)
    await message.reply("Your Jira account has been disconnected.")
```

- [ ] **Step 4: Fix `_client_cache` type hint and use token fingerprint in `jiratoolkit.py`**

In `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`:

Find the `_client_cache` declaration:
```python
            self._client_cache: Dict[str, tuple] = {}
```
Replace with:
```python
            self._client_cache: Dict[str, tuple] = {}  # {user_key: (JIRA, str)}
```

Find the token hash line:
```python
        token_hash = hash(getattr(token_set, "access_token", ""))
```
Replace with (use a stable fingerprint instead of Python's non-deterministic `hash()`):
```python
        _at = getattr(token_set, "access_token", "")
        # Use a deterministic fingerprint: first 16 + last 8 chars is cheap
        # and stable across process restarts (unlike Python's hash()).
        token_hash = (_at[:16] + _at[-8:]) if len(_at) > 24 else _at
```

Update the cache comparison accordingly:
```python
        cached = self._client_cache.get(user_key)
        if cached is not None and cached[1] == token_hash:
```
This line is unchanged (already compares `cached[1]` to `token_hash`).

- [ ] **Step 5: Run the full test suite**

```bash
cd /home/jesuslara/proyectos/ai-parrot/.claude/worktrees/feat-107-jira-oauth2-3lo
source .venv/bin/activate
pytest packages/ai-parrot/tests/unit/ packages/ai-parrot-tools/tests/unit/ -v 2>&1 | tail -40
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/ai-parrot/src/parrot/tools/jira_connect_tool.py \
        packages/ai-parrot/src/parrot/tools/manager.py \
        packages/ai-parrot/src/parrot/tools/toolkit.py \
        packages/ai-parrot/src/parrot/integrations/telegram/jira_commands.py \
        packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
git commit -m "fix(misc): hotswap uses remove_tool, fix logger f-strings, disconnect reply, token fingerprint

- jira_connect_tool: hotswap_to_full_toolkit uses tool_manager.remove_tool()
  instead of accessing private _tools dict
- manager.py / toolkit.py: replace f-strings in self.logger.* calls with
  %s lazy interpolation per AI-Parrot convention
- jira_commands: disconnect_jira_handler now replies when from_user is None
  instead of silently returning with no user feedback
- jiratoolkit: replace hash(access_token) with a stable string fingerprint
  to avoid PYTHONHASHSEED non-determinism"
```

---

## Self-Review

### Spec coverage

| Issue from review | Task | Status |
|---|---|---|
| 🔴 Debug print() in abstract.py | Task 1 | ✅ covered |
| 🔴 _permission_context never reaches _pre_execute | Task 2 | ✅ covered |
| 🟠 httpx violation | Task 3 | ✅ covered |
| 🟠 Lock acquisition fallback missing | Task 3 | ✅ covered |
| 🟠 TelegramOAuthNotifier unwired | Task 4 | ✅ covered |
| 🟠 handle_callback return type for notifier | Task 3+4 | ✅ covered |
| 🟡 hash() non-deterministic | Task 5 | ✅ covered |
| 🟡 Private _tools access in hotswap | Task 5 | ✅ covered |
| 🟡 Silent disconnect return | Task 5 | ✅ covered |
| 🟡 Logger f-strings manager.py/toolkit.py | Task 5 | ✅ covered |
| 💡 Commented-out print in abstract.py | Task 1 | ✅ covered |
| 💡 Untyped _client_cache tuple | Task 5 | ✅ covered |

### Placeholder scan

No TBD or "similar to" placeholders — all steps contain complete code.

### Type consistency

- `handle_callback` returns `Tuple[JiraTokenSet, Dict[str, Any]]` — updated in Task 3 (signature), Task 3 tests, and Task 4 route handler.
- `_current_pctx` is `None | PermissionContext` — set in Task 2 `abstract.py`, read in Task 2 `toolkit.py`.
- `token_hash` type changed from `int` (hash result) to `str` (fingerprint) in Task 5 — the cache comparison `cached[1] == token_hash` works for both (string == string).
