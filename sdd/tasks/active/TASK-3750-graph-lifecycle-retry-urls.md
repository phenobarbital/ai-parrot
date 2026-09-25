# TASK-3750: GraphDriveFileManager lifecycle — connect/auth modes, adopt_client, close, retry policy, URL boundary

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3749, TASK-3748
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1** (second of six `graph.py` tasks) and design research **S1** (authenticated-client injection),
**S5** (one bounded retry policy) and **S6** (outbound URL boundary). Everything here is infrastructure the operation
tasks (3751–3754) call: `_ready()` before every operation, `_retrying()` around every request, `_map_error()` to turn
Graph failures into the documented exceptions, `_validate_graph_url()` before every raw aiohttp call. The subclasses
(TASK-3756/3757) and the tool refactor (TASK-3761..3764) depend on `connect()` / `adopt_client()` exactly as fixed here.

---

## Scope

- Append to `GraphDriveFileManager`: `connect`, `adopt_client`, `_ready`, `close`, `__aenter__`, `__aexit__`,
  `_http_session`, `_sleep`, `_status_code_of`, `_retry_after_seconds`, `_map_error`, `_retrying`, `_validate_graph_url`,
  plus the module-level `_RawHTTPError`.
- Append the tests of this task to `test_graph_filemanager.py`.

**NOT in scope**: any drive-item operation (3751+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/graph.py` | MODIFY | lifecycle, auth, injection, retry, URL boundary |
| `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` | MODIFY | append lifecycle/retry/URL tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`. `graph.py` and the test file are created by TASK-3749.

### Verified Imports
```python
import aiohttp                                           # workspace dependency (aiohttp 3.14.3)
from email.utils import parsedate_to_datetime            # stdlib (same as parrot_tools/o365/delta.py uses)
from urllib.parse import urlsplit                        # stdlib
from parrot.interfaces.o365 import O365Client            # verified: packages/ai-parrot/src/parrot/interfaces/o365.py:115 (already imported by TASK-3749)
from ._graph_fakes import FakeAPIError, FakeDrive, FakeGraphClient, make_onedrive_client, make_probe, make_sharepoint_client  # tests
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/o365.py
class O365Client(CredentialsInterface):                     # :115
    def processing_credentials(self)                        # :218 (sync) — tenant/site/tenant_id from credentials
    def set_auth_mode(self, auth_mode: Optional[str]) -> None   # :360
    def user_auth(self, username: str, password: str, scopes=None) -> Dict   # :475 (sync, ROPC)
    def acquire_token(self, scopes=None) -> Dict            # :562 (sync, client credentials)
    def acquire_token_on_behalf_of(self, user_assertion: str, scopes=None) -> Dict   # :621 (sync)
    async def interactive_login(self, scopes=None, ...) -> Dict   # :763
    async def ensure_interactive_session(self, scopes=None)       # :923
    async def close(self)                                   # :709 — shuts _executor, clears _credential/_graph_client/_access_token
    # auth-state attributes set in __init__ (:167-200): _credential, _graph_client, _access_token, auth_mode

# The exact auth branching to reproduce — packages/ai-parrot-tools/src/parrot_tools/o365/base.py:151-182:
#   client.processing_credentials(); client.set_auth_mode(auth_mode)
#   direct       -> await loop.run_in_executor(None, client.acquire_token, scopes)
#   on_behalf_of -> await loop.run_in_executor(None, client.acquire_token_on_behalf_of, user_assertion, scopes)
#   delegated    -> await client.interactive_login(scopes=scopes)   (first time; ensure_interactive_session afterwards)
#   cached       -> await client.ensure_interactive_session(scopes=scopes)
#   base.py:148 builds a PLAIN O365Client — so adopt_client must accept one (spec §7, S1)

# Retry semantics to re-implement (do NOT import) — packages/ai-parrot-tools/src/parrot_tools/o365/delta.py:
def _status_code_of(error) -> Optional[int]          # :487-496 — response_status_code, then status_code/status/code
def _retry_after_seconds(error) -> Optional[float]   # :499-539 — headers.get("Retry-After"|"retry-after"); float or HTTP-date; >=0 else None
DEFAULT_GRAPH_ORIGINS                                # :65-71 — equals GraphDriveFileManager.ALLOWED_ORIGINS (TASK-3749)
def validate_continuation_link(link, drive_id, allowed_origins=...)   # :387 — the structural-validation pattern S6 follows
```

### Does NOT Exist
- ~~`O365Client.aclose()`~~ — it is `async def close()` (`o365.py:709`).
- ~~`O365Client.connect()` (async)~~ — `connection()` (`o365.py:403`) is sync and is NOT used by the manager; the manager
  reproduces `O365Tool._get_client`'s branches instead.
- ~~importing `parrot_tools.o365.delta` from `parrot.interfaces`~~ — forbidden (core ↛ tools); copy the semantics.
- ~~an `Authorization` header on uploadUrl / monitor / downloadUrl calls~~ — those URLs are pre-authenticated (S6).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/graph.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_graph_filemanager.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/o365.py#O365Client",
    "sym:packages/ai-parrot/src/parrot/interfaces/o365.py#O365Client.acquire_token",
    "sym:packages/ai-parrot/src/parrot/interfaces/o365.py#O365Client.acquire_token_on_behalf_of",
    "sym:packages/ai-parrot/src/parrot/interfaces/o365.py#O365Client.user_auth",
    "sym:packages/ai-parrot/src/parrot/interfaces/o365.py#O365Client.interactive_login",
    "sym:packages/ai-parrot/src/parrot/interfaces/o365.py#O365Client.ensure_interactive_session",
    "sym:packages/ai-parrot/src/parrot/interfaces/o365.py#O365Client.close",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/base.py#O365Tool._get_client",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/delta.py#_status_code_of",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/delta.py#_retry_after_seconds"
  ]
}
```

---

## Implementation Notes

- **ROPC mapping (task-time decision)**: `auth_mode="direct"` with both `username` and `password` in `credentials` runs
  `client.user_auth(username, password, scopes)` in the executor instead of `acquire_token` — that is how "username/
  password via credentials" (spec §2, AC3) reaches `O365Client`; any other `direct` call uses `acquire_token`.
- **`adopt_client(client)` contract (S1)**: when `isinstance(client, self.client_class)` use it as-is. Otherwise build
  a wrapper with `self._build_client()`, call its `processing_credentials()`, and copy ONLY the auth state
  (`_credential`, `_graph_client`, `_access_token`, `auth_mode`) from `client` — never `site`/`tenant`, which the
  subclass's `_build_client` owns. Either way no token is acquired (AC3). Reset `_drive_id` so the next `_ready()`
  resolves it on the adopted client.
- **`close()` ownership**: close `self._client` iff the manager built it (`connect()` or the adopt wrapper); never
  close the adopted original — its owner (the O365 tool cache) does.
- **`_retrying(op, *, label, idempotent=True)`**: `attempts` starts at 1; on an exception whose status is in
  `RETRYABLE_STATUS`, and `idempotent`, and `attempts <= max_retries`: sleep `min(retry_after or 2 ** (attempts - 1), 60)`
  via `self._sleep` then retry; otherwise raise the original exception. Returns `(result, attempts)`. Raw aiohttp helpers
  (3752–3754) raise `_RawHTTPError(status, headers)` for non-2xx so the same policy applies.
- **`_map_error(exc, *, path)`**: 404 → `FileNotFoundError(path)`; 401/403 → `PermissionError`; 409 → `FileExistsError`;
  everything else → `GraphFileManagerError(str, status_code=...)`. Messages never contain URLs or tokens.
- **`_validate_graph_url(url, *, purpose)`**: https only; host (lower-case, no port) accepted when `f"https://{host}"`
  is in `ALLOWED_ORIGINS` or the host ends with an `ALLOWED_HOST_SUFFIXES` entry; otherwise `GraphFileManagerError`
  whose message names `purpose` but NOT the URL.
- `_http_session()` returns `aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_read=300))`; tests
  replace it per instance (`m._http_session = lambda: session`). `_sleep` wraps `asyncio.sleep` for the same reason.

### Key Constraints (all FEAT-603 tasks)
- **aiohttp only** for raw HTTP. `httpx`, `requests`, `langchain*` are banned (ruff TID251). The two legacy
  clients carry an unused `import httpx` (`interfaces/sharepoint.py:11`, `interfaces/onedrive.py:10`) — never copy
  their import blocks into new code.
- **Core never imports the tools distribution**: nothing under `packages/ai-parrot/src/parrot/` may import
  `parrot_tools` (the retry helpers of `parrot_tools/o365/delta.py` are *re-implemented*, not imported).
- Pydantic v2 models; Google-style docstrings and strict type hints on every function/class; `self.logger`
  (or a module `logger = logging.getLogger(__name__)`), never `print`; `black` line length 120; `ruff check` clean.
- **Never log** upload-session `uploadUrl`s, copy monitor URLs, `@microsoft.graph.downloadUrl`s, tokens or secrets.
- **Byte-identical files** (no edit, ever, in this feature): `packages/ai-parrot/src/parrot/interfaces/sharepoint.py`,
  `packages/ai-parrot/src/parrot/interfaces/o365.py`, `packages/ai-parrot-tools/src/parrot_tools/o365/delta.py`,
  `packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py`, `packages/ai-parrot-tools/src/parrot_tools/o365/base.py`,
  and the `Delta*Args` / `Delta*Tool` class blocks inside `parrot_tools/o365/{sharepoint,onedrive}.py` (FEAT-539).
- Tests never construct a real `O365Client` / `SharepointClient` / `OneDriveClient` (their `__init__` builds an
  aioredis client, `o365.py:198-200`) — use the fakes of TASK-3748 and `GraphDriveFileManager.adopt_client`.
- Tests are async with `asyncio_mode = auto` (`pytest.ini:3`); the `live` marker is registered (`pytest.ini:6`).
- **Worktree testing**: the shared `.venv` is editable-installed against the MAIN checkout, so run
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src timeout -s KILL 600 pytest <file> -q`.
  Never `uv sync` inside a worktree.

---

## Implementation Blueprint

### Steps (in order)
1. Add the new imports at the top of `graph.py` — *why*: the retry/URL helpers need them.
2. Append `_RawHTTPError` at module level ABOVE the class and the methods at the END of the class — *why*: later tasks
   append after these, so order must stay predictable.
3. Append the tests.

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — imports
```python
# occurrences: 1 (expected after TASK-3749; verify: grep -c '^from urllib.parse import quote$' graph.py)
# REPLACE the line `from urllib.parse import quote` with:
import asyncio
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Awaitable, Callable, Tuple
from urllib.parse import quote, urlsplit

import aiohttp
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — `_RawHTTPError`
```python
# occurrences: 1 (expected after TASK-3749; verify: grep -c '^class GraphFileManagerError(RuntimeError):$' graph.py)
# BEFORE — insert above `class GraphFileManagerError(RuntimeError):`
class _RawHTTPError(Exception):
    """Non-2xx response on a raw aiohttp call; shaped like kiota APIError so ``_retrying`` treats both alike."""

    def __init__(self, status: int, headers: Optional[Dict[str, str]] = None) -> None:
        super().__init__(f"HTTP {status}")
        self.response_status_code = status
        self.response_headers = dict(headers or {})
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — lifecycle (append at end of class)
```python
# occurrences: 1 (expected after TASK-3749; verify: grep -c '    def _make_entry(self, item: Any, \*, full_path' graph.py)
# AFTER — append at the end of the GraphDriveFileManager class body (after `_make_entry`)
    async def connect(self) -> "GraphDriveFileManager":
        """Build the client, authenticate per ``auth_mode`` and resolve the drive id. Idempotent."""
        async with self._get_lock():
            if self._client is None:
                client = self._build_client()
                client.processing_credentials()
                client.set_auth_mode(self.auth_mode)
                # FILL IN: the four branches of O365Tool._get_client (Existing Signatures) + the ROPC mapping in
                #          Implementation Notes; sync calls through asyncio.get_running_loop().run_in_executor(None, ...);
                #          unknown auth_mode -> ValueError — bounded by AC3 (exactly one token acquisition)
                self._client, self._owns_client = client, True
            if self._drive_id is None:
                self._drive_id = await self._resolve_drive_id()
        return self

    def adopt_client(self, client: O365Client) -> None:
        """Reuse an already-authenticated client instead of authenticating again (S1). See Implementation Notes."""
        # FILL IN: isinstance branch vs wrapper branch; set _client, _adopted, _owns_client; reset _drive_id

    async def _ready(self) -> str:
        """Return the drive id, connecting (owned client) or resolving it on the adopted client first."""
        if self._drive_id is None:
            if self._client is None:
                await self.connect()
            else:
                async with self._get_lock():
                    if self._drive_id is None:
                        self._drive_id = await self._resolve_drive_id()
        return self._drive_id

    def _get_lock(self) -> asyncio.Lock:
        lock = self.__dict__.get("_lock_obj")
        if lock is None:
            lock = self.__dict__["_lock_obj"] = asyncio.Lock()
        return lock

    async def close(self) -> None:
        """Close the client iff this manager built it; drop caches."""
        # FILL IN: ownership rule in Implementation Notes

    async def __aenter__(self) -> "GraphDriveFileManager":
        return await self.connect()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    def _http_session(self) -> aiohttp.ClientSession:
        """Session for pre-authenticated URLs (no auth header, no base URL); replaced per instance in tests."""
        return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_read=300))

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — retry, error map, URL boundary (append)
```python
# AFTER — append below `_sleep` (added by the previous block of this task)
    @staticmethod
    def _status_code_of(error: BaseException) -> Optional[int]:
        """HTTP status of a kiota/raw error — same semantics as parrot_tools/o365/delta.py:487."""
        # FILL IN: copy the semantics (response_status_code, then status_code / status / code)

    @staticmethod
    def _retry_after_seconds(error: BaseException) -> Optional[float]:
        """``Retry-After`` delay in seconds — same semantics as parrot_tools/o365/delta.py:499."""
        # FILL IN: copy the semantics (header lookup, float or HTTP-date via parsedate_to_datetime, >= 0 else None)

    def _map_error(self, exc: BaseException, *, path: str) -> BaseException:
        """Translate a Graph/raw failure into the documented exception type (never leaks URLs)."""
        # FILL IN: mapping in Implementation Notes; returns the exception (callers `raise ... from exc`)

    async def _retrying(
        self, op: Callable[[], Awaitable[Any]], *, label: str, idempotent: bool = True
    ) -> Tuple[Any, int]:
        """ONE bounded retry policy for SDK and raw-aiohttp calls (S5). Returns (result, attempts)."""
        attempts = 1
        while True:
            try:
                return await op(), attempts
            except Exception as exc:  # noqa: BLE001 — re-raised unless retryable
                status = self._status_code_of(exc)
                # FILL IN: retry rule in Implementation Notes; log label/status/attempt at WARNING (no URLs)
                raise

    def _validate_graph_url(self, url: str, *, purpose: str) -> str:
        """Accept only https URLs on Graph / SharePoint / OneDrive hosts (S6); return ``url`` unchanged."""
        # FILL IN: rule in Implementation Notes (urlsplit; hostname lower-case)
```
**Why this shape**: `connect`, `_ready` and `_retrying` are written out because every later task calls them and the
locking / attempt counting must not vary between tasks. The auth branches are a FILL IN bounded by an exact reference
(`base.py:151-182`), and the copy-don't-import rule for the delta helpers keeps core independent of `parrot_tools`.

### `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` (MODIFY)
```python
# AFTER — append at end of file
from ._graph_fakes import FakeAPIError, FakeDrive, FakeGraphClient, make_onedrive_client, make_sharepoint_client
from parrot.interfaces.sharepoint import SharepointClient


async def test_connect_auth_mode_branches(monkeypatch):
    # FILL IN: probe subclass whose _build_client returns make_sharepoint_client(...) with acquire_token /
    #          acquire_token_on_behalf_of / user_auth / interactive_login / ensure_interactive_session recorded;
    #          one parametrised case per mode + ROPC; each acquires exactly once; second connect() acquires nothing


async def test_adopt_client_same_class_is_used_as_is():
    # FILL IN: client_class=SharepointClient; adopt make_sharepoint_client(...); m.client is it; close() leaves it open


async def test_adopt_client_generic_builds_wrapper_and_copies_auth_state_only():
    # FILL IN: adopt a bare OneDriveClient into a SharepointClient-class probe; wrapper has the adopted _credential /
    #          _graph_client / auth_mode, its own site; no acquire_* called; close() closes the wrapper only


async def test_ready_resolves_drive_once():
    # FILL IN: _resolve_drive_id counted; two concurrent _ready() -> one resolution


async def test_retrying_honours_retry_after_and_caps_at_60():
    # FILL IN: op raising FakeAPIError(429, retry_after=90) then succeeding -> slept 60, attempts == 2


async def test_retrying_non_idempotent_never_retries():
    # FILL IN


def test_map_error_types():
    # FILL IN: 404/401/403/409/500 -> FileNotFoundError / PermissionError / PermissionError / FileExistsError /
    #          GraphFileManagerError(status_code=500)


def test_validate_graph_url_accepts_graph_and_sharepoint_hosts():
    # FILL IN: graph.microsoft.com, contoso.sharepoint.com, contoso-my.sharepoint.com, x.files.1drv.com accepted


def test_validate_graph_url_rejects_http_and_foreign_hosts():
    # FILL IN: http://contoso.sharepoint.com, https://evil.example, https://sharepoint.com.evil.example rejected;
    #          the raised message does not contain the URL
```

### FILL IN checklist
- [ ] `connect` auth branches + ROPC mapping
- [ ] `adopt_client` both branches; `close` ownership
- [ ] `_status_code_of`, `_retry_after_seconds`, `_map_error`, retry rule, `_validate_graph_url`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] All four auth modes and ROPC reach the matching `O365Client` call exactly once per manager (spec AC3).
- [ ] `adopt_client` never acquires a token; a plain `O365Client` is wrapped with auth state copied and the manager's
      own site/tenant kept; `close()` never closes an adopted client (spec §3 M1, S1).
- [ ] Retries: `{429, 503, 504}` only, `Retry-After` honoured and capped at 60 s, `max_retries` default 3,
      `idempotent=False` never retried (spec AC8, AC21, S5).
- [ ] `_validate_graph_url` accepts only https on the allowed hosts; error messages contain no URL (spec AC21, S6).
- [ ] `ruff check` clean; no `parrot_tools` import in `graph.py`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_graph_filemanager.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_connect_auth_mode_branches` | AC3 incl. ROPC, idempotence |
| `test_adopt_client_same_class_is_used_as_is` / `..._generic_builds_wrapper...` | S1 contract |
| `test_ready_resolves_drive_once` | lock |
| `test_retrying_honours_retry_after_and_caps_at_60` / `test_retrying_non_idempotent_never_retries` | S5 |
| `test_map_error_types` | error contract |
| `test_validate_graph_url_*` | S6 boundary |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** `sdd/specs/sharepoint-filemanager.spec.md` (§2, the §3 module named in Context, §6, §7).
2. **Check dependencies** — every `Depends-on` task must be `done` in `sdd/tasks/index/sharepoint-filemanager.json`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still resolves (`grep` or `read` the source).
   - Re-run the `grep -c` of every MODIFY anchor in the blueprint; a changed count means the anchor moved —
     re-locate it; a count of `0` means STOP and report drift.
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists.
4. **Update status** in `sdd/tasks/index/sharepoint-filemanager.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, and never
   change a signature, class name or file path the blueprint fixes.
6. **Verify** every acceptance criterion and run every Validation Command (plus `ruff check` on touched files).
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
