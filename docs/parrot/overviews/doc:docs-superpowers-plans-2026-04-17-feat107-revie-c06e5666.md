---
type: Wiki Overview
title: FEAT-107 Review Fixes Implementation Plan
id: doc:docs-superpowers-plans-2026-04-17-feat107-review-fixes-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: cd /home/jesuslara/proyectos/ai-parrot/.claude/worktrees/feat-107-jira-oauth2-3lo
relates_to:
- concept: mod:parrot.auth
  rel: mentions
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.auth.routes
  rel: mentions
- concept: mod:parrot.integrations.telegram.jira_commands
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
---

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

…(truncated)…
