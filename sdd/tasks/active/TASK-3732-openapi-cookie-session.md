# TASK-3732: OpenAPIToolkit: cookie-session auth mode (login hook, jar, extra headers, 401 re-login, no write retries)

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3731
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1**, second half. Hooba authenticates with a `sid` session cookie set by
`POST /auth/login`; its OpenAPI document declares no security scheme. `OpenAPIToolkit`
knows only bearer/apikey/basic, and the shared transport cannot carry a session:
`HTTPService._request` creates a fresh `httpx.AsyncClient` per call (`http.py:1732`) and
`HTTPService.cookies` is never consumed. Worse, `process_response` **raises**
`ConnectionError` on any status ≥ 400 (`http.py:568`), so a 401 cannot be seen as a
return value. Design research S1 and S11 apply.

This task adds `auth_type="cookie"`: the toolkit owns a cookie jar, calls an async
`login_hook(http_service) -> dict[str, str]` lazily (lock-serialized), passes `cookies=`
and merged `extra_headers` on every request with `full_response=True`, inspects
`response.status_code`, re-logs in exactly once on 401, and runs writes with
`num_retries=0`. The existing request call for other auth modes stays byte-identical.

---

## Scope

- Add `Awaitable` to the typing import and a module-level `LoginHook` alias.
- Add keyword-only `login_hook` and `extra_headers` ctor params; `auth_type="cookie"` without `login_hook` → `ValueError`.
- Merge `extra_headers` into the headers passed to `HTTPService`; init `self._cookies: Dict[str, str] = {}` and `self._session_lock = asyncio.Lock()`.
- Add `_ensure_session(force=False)`, `set_cookies(cookies)`, `get_cookies()`, `_cookie_request(...)`.
- In the generated `operation_method`, branch on `self_ref.auth_type == "cookie"` to `_cookie_request`; leave the existing call untouched for other modes.
- Write `packages/ai-parrot/tests/tools/test_openapi_cookie_session.py`.

**NOT in scope**: anything Hooba-specific (login URL, `sid`, headers — TASK-3734/3737); changing `HTTPService`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` | MODIFY | cookie auth mode: LoginHook, ctor params, session methods, request branch |
| `packages/ai-parrot/tests/tools/test_openapi_cookie_session.py` | CREATE | unit tests with a fake HTTPService._request |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot.tools.openapitoolkit import OpenAPIToolkit   # verified: openapi_register.py:15
# inside openapitoolkit.py (after TASK-3731):
from typing import Any, Callable, Dict, List, Optional, Sequence, Union   # this task adds Awaitable
from ..interfaces.http import HTTPService                 # verified: openapitoolkit.py:40
from .abstract import ToolResult                          # verified: openapitoolkit.py:42 (occurrences: 1)
import asyncio                                            # NOT imported today — add it (stdlib)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/openapitoolkit.py
#   lines 135-137: "# Prepare credentials and headers for HTTPService" / creds = credentials or {} / headers = {}
#   line 150: "# Initialize HTTPService"   (occurrences: 1)
#   lines 151-159: self.http_service = HTTPService(accept='application/json', headers=headers, credentials=creds, ...)
#   line 758: "# Execute request via HTTPService"   (occurrences: 1)
#   lines 759-764: result, error = await self_ref.http_service._request(**request_kwargs, full_response=False,
#                                                                       use_proxy=False, raise_for_status=False)
#   lines 766-775: `if error: return ToolResult(status="error", ...).model_dump()`

# packages/ai-parrot/src/parrot/interfaces/http.py
async def _request(self, url: str, method: str = 'get', cookies=None, params=None, data=None, headers=None,
                   timeout=30.0, use_proxy=True, free_proxy=False, use_ssl=True, use_json=False,
                   follow_redirects=True, raise_for_status=True, full_response=False, ...,
                   num_retries: int = 2, **kwargs)                         # lines 1610-1631
#   full_response=True → returns (httpx.Response, None) before process_response   (lines 1754-1759)
async def process_response(self, response, url: str) -> tuple            # lines 522-687 — ≥400 → raise ConnectionError (line 568)
```

### Does NOT Exist
- ~~`auth_type="cookie"`~~, ~~`login_hook`~~, ~~`extra_headers`~~, ~~`set_cookies()`~~, ~~`get_cookies()`~~, ~~`_ensure_session()`~~ — all new here.
- ~~A persistent cookie jar in `HTTPService`~~ — `self.cookies` (`http.py:191`) is never passed by `_request`; pass cookies per call.
- ~~`process_response` returning an error tuple for 401~~ — it raises `ConnectionError`; read `status_code` first.
- ~~`import asyncio` in openapitoolkit.py~~ — absent today; add it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/openapitoolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_openapi_cookie_session.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/openapitoolkit.py#OpenAPIToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/openapitoolkit.py#OpenAPIToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/tools/openapitoolkit.py#OpenAPIToolkit._create_operation_method",
    "sym:packages/ai-parrot/src/parrot/interfaces/http.py#HTTPService._request",
    "sym:packages/ai-parrot/src/parrot/interfaces/http.py#HTTPService.process_response"
  ]
}
```

---

## Implementation Notes

- `_cookie_request` order: `await self._ensure_session()` → request with `cookies=dict(self._cookies)`,
  `headers={**header_params}` (instance headers are already merged by `HTTPService`), `full_response=True`,
  `raise_for_status=False`, `use_proxy=False`, and `num_retries=0` when the method is POST/PUT/PATCH/DELETE (S11).
  On `response.status_code == 401` and not yet retried: `await self._ensure_session(force=True)` and retry once.
  Then `result, error = await self.http_service.process_response(response, url)`; catch `ConnectionError` and return
  it as `(None, {"status": status, "message": str(exc)[:500]})`.
- `_ensure_session`: inside `async with self._session_lock:` re-check the jar (double-checked) so N concurrent first calls
  log in exactly once (S1). Store `dict(await self._login_hook(self.http_service))`.
- Never log cookie values; `get_cookies()` returns a copy.

### Key Constraints (all FEAT-602 tasks)
- async-first: no blocking I/O inside `async def` — wrap pandas/openpyxl/filesystem work in `asyncio.to_thread` (spec §7, S10).
- aiohttp only in new code: `httpx` and `requests` are banned by ruff TID251; the only httpx surface is inside the exempt `HTTPService` / `openapitoolkit.py`.
- Pydantic v2 models for every structured value; `self.logger` (or a module `logger = logging.getLogger(__name__)`), never `print`.
- Never log cookie values, passwords, IBANs or full bank rows at INFO or above.
- Google-style docstrings and strict type hints on every function and class; `black` line length 120; `ruff check` clean.
- Drafts only: no code path may call `:issue`, `:confirm`, `:cancel`, `:send*`, a DELETE, or any write outside `DRAFT_OPERATIONS` (spec G3, AC-5).
- Worktree testing: the shared `.venv` is editable-installed against the MAIN checkout. Run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-loaders/src pytest ...` so the worktree's code is imported. Never `uv sync` in a worktree.
- Fixtures are synthetic: never commit real Hooba selectors, credentials, bank exports or personal data (AC-17).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above. Business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add `import asyncio`, `Awaitable`, and `LoginHook` — *why*: the hook type is part of the public contract (spec §2).
2. Add `login_hook`/`extra_headers` to the keyword-only block TASK-3731 created; validate cookie mode — *why*: fail at construction, not at the first call.
3. Merge `extra_headers` into `headers` before `HTTPService(...)` — *why*: Hooba requires `origin`, `x-hooba-language`, `ngsw-bypass` on every call.
4. Add the session methods and `_cookie_request` — *why*: S1 (one login, lock-serialized) and S11 (no write retries).
5. Branch the generated method on cookie mode — *why*: AC-4 requires the other modes' call to stay byte-identical.
6. Write tests with a fake `_request`/`process_response` — *why*: no network in unit tests.

### `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` (MODIFY)
```python
# (a) typing import (after TASK-3731) — REPLACE with:
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Union
# and add `import asyncio` next to `import contextlib` (line 23).

# (b) occurrences: 1 (verified: grep -c 'from .abstract import ToolResult' openapitoolkit.py) — line 42
# AFTER — insert below `from .abstract import ToolResult`:


#: Async hook performing a login and returning the session cookies to send on every request.
LoginHook = Callable[[HTTPService], Awaitable[Dict[str, str]]]

# (c) in the keyword-only block added by TASK-3731, directly after `max_tools: Optional[int] = None,` add:
        login_hook: Optional[LoginHook] = None,
        extra_headers: Optional[Dict[str, str]] = None,
# and document both in Args.

# (d) occurrences: 1 (verified: grep -c '        # Initialize HTTPService' openapitoolkit.py) — line 150
# BEFORE — insert above `        # Initialize HTTPService`:
        # Cookie-session mode (FEAT-602): the toolkit owns the jar; HTTPService is stateless per call.
        if auth_type == "cookie" and login_hook is None:
            raise ValueError("auth_type='cookie' requires a login_hook")
        self._login_hook = login_hook
        self._cookies: Dict[str, str] = {}
        self._session_lock = asyncio.Lock()
        if extra_headers:
            headers.update(extra_headers)

# (e) new methods — insert directly above `    def _normalize_path_for_method_name(` (occurrences: 1):
    async def _ensure_session(self, force: bool = False) -> None:
        """Log in through ``login_hook`` when the jar is empty (or ``force``); cookie mode only.

        Lock-serialized and double-checked so concurrent first calls trigger exactly one login.
        """
        if self.auth_type != "cookie":
            return
        # FILL IN: async with self._session_lock: if force or not self._cookies:
        #          self._cookies = dict(await self._login_hook(self.http_service)) — bounded by AC-1 / S1
        raise NotImplementedError

    async def set_cookies(self, cookies: Dict[str, str]) -> None:
        """Replace the jar with externally obtained cookies (e.g. exported from a browser)."""
        async with self._session_lock:
            self._cookies = dict(cookies)

    def get_cookies(self) -> Dict[str, str]:
        """Return a copy of the cookie jar. Callers must never log the values."""
        return dict(self._cookies)

    async def _cookie_request(self, method: str, url: str, request_kwargs: Dict[str, Any]) -> tuple:
        """Send one request in cookie mode; re-login once on 401; never transport-retry writes.

        Returns:
            ``(result, error)`` like ``HTTPService._request``; ``error`` carries ``status`` on HTTP errors.
        """
        # FILL IN: see Implementation Notes — ensure session; loop at most twice; full_response=True;
        #          num_retries=0 for writes; 401 → _ensure_session(force=True) once; process_response in try/except
        #          ConnectionError → (None, {"status": ..., "message": ...}) — bounded by AC-1, AC-3 (S11)
        raise NotImplementedError

# (f) occurrences: 1 (verified: grep -c '                # Execute request via HTTPService' openapitoolkit.py) — line 758
# REPLACE the block from `# Execute request via HTTPService` through the closing `)` of the _request call (lines 758-764) WITH:
                # Execute request via HTTPService
                if self_ref.auth_type == "cookie":
                    result, error = await self_ref._cookie_request(method, url, request_kwargs)
                else:
                    result, error = await self_ref.http_service._request(
                        **request_kwargs,
                        full_response=False,
                        use_proxy=False,
                        raise_for_status=False,
                    )
```
**Why this shape**: the else-branch is the original call verbatim (AC-4). Returning `(result, error)` from
`_cookie_request` lets the existing `if error:` / success `ToolResult` code below serve both modes unchanged.

### `packages/ai-parrot/tests/tools/test_openapi_cookie_session.py` (CREATE)
```python
"""FEAT-602 TASK-3732 — OpenAPIToolkit cookie-session mode."""
import asyncio
from types import SimpleNamespace

import pytest

from parrot.tools.openapitoolkit import OpenAPIToolkit


class FakeTransport:
    """Replaces http_service._request / process_response; scripts status codes per call."""
    # FILL IN: record kwargs of every _request call; return SimpleNamespace(status_code=..., ...) responses
    #          from a script list; process_response returns ({"ok": True}, None) for 2xx and raises
    #          ConnectionError for >= 400 (mirrors http.py:568)


def test_cookie_mode_requires_login_hook():
    # FILL IN: auth_type="cookie" without login_hook → ValueError


async def test_cookie_mode_logs_in_lazily_once():
    # FILL IN: hook not called at construction; two tool calls → hook called once


async def test_cookie_mode_sends_jar_and_extra_headers():
    # FILL IN: cookies={"sid": "x"}, extra_headers present in HTTPService headers, full_response=True


async def test_cookie_mode_relogins_once_on_401():
    # FILL IN: [401, 200] → hook called twice, success; [401, 401] → ToolResult status "error"


async def test_cookie_mode_concurrent_first_use_logs_in_once():
    # FILL IN: asyncio.gather of 5 first calls → hook called exactly once (S1)


async def test_cookie_mode_no_transport_retries_on_writes():
    # FILL IN: POST → num_retries=0; GET → num_retries not forced to 0 (S11)


async def test_set_and_get_cookies_copy():
    # FILL IN


def test_non_cookie_modes_use_original_call():
    # FILL IN: bearer toolkit's generated method calls _request with full_response=False (AC-4)
```

### FILL IN checklist
- [ ] `OpenAPIToolkit._ensure_session` — double-checked lock; bounded by AC-1, S1
- [ ] `OpenAPIToolkit._cookie_request` — single retry on 401, `num_retries=0` for writes, ConnectionError → error tuple; bounded by AC-1, S11
- [ ] every test body and `FakeTransport`

---

## Acceptance Criteria

- [ ] AC-1 (spec): cookie mode calls the hook lazily, sends the jar and `extra_headers` on every request, re-logs in exactly once on 401; `set_cookies()` / `get_cookies()` work.
- [ ] AC-3 (spec, transport half): cookie-mode writes never use transport retries (`num_retries=0`).
- [ ] AC-4 (spec): bearer/apikey/basic request path unchanged; `tests/test_openapi_toolkit.py`, `tests/test_openapi.py`, `tests/tools/test_openapi_filters.py` pass.
- [ ] `ruff check` and `black --check` clean on the touched file.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot/tests/tools/test_openapi_cookie_session.py -q`
- `pytest packages/ai-parrot/tests/test_openapi_toolkit.py -q`
- `pytest packages/ai-parrot/tests/test_openapi.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_cookie_mode_requires_login_hook` | construction guard |
| `test_cookie_mode_logs_in_lazily_once` | lazy, single login |
| `test_cookie_mode_sends_jar_and_extra_headers` | per-call cookies, merged headers, `full_response=True` |
| `test_cookie_mode_relogins_once_on_401` | one re-login, second 401 is an error ToolResult |
| `test_cookie_mode_concurrent_first_use_logs_in_once` | S1 |
| `test_cookie_mode_no_transport_retries_on_writes` | S11 |
| `test_set_and_get_cookies_copy` | jar API |
| `test_non_cookie_modes_use_original_call` | AC-4 |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2, §3 module, §6, §7).
2. **Check dependencies** — verify every `Depends-on` task is done in `sdd/tasks/index/hooba-toolkit.json`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every anchor in the blueprint still has the stated occurrence count (`grep -c`)
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/hooba-toolkit.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria and run every Validation Command.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
