# TASK-3807: `DriveClient` + `get_drive_client()` promotion in `google.py`

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (goal G2). `GoogleClient.execute_api_call` opens a fresh `Aiogoogle` and
re-runs discovery on every call (`google.py:704-769`) — prohibitive for paginated listings
and chunked uploads. Add a long-lived `DriveClient` (one session + one discovered `drive`
v3 API per manager), promote `get_drive_client()` to return it (FEAT-453 did the same for
`CalendarClient`; the dict return has no callers), and add the read-only helper
`aiogoogle_credentials()` so `DriveClient` never touches private creds.

---

## Scope

- Add `class DriveClient` after `CalendarClient`'s body (before the `# Google Client`
  banner / `class GoogleClient`).
- Add `GoogleClient.aiogoogle_credentials()` immediately before `using_service_account`.
- Replace `get_drive_client()` (dict return) with a version returning `DriveClient(self, version=version)`.
- Unit tests in `test_drive_client.py` (fake `Aiogoogle` monkeypatched into `parrot.interfaces.google`).

**NOT in scope**: any change to `initialize`, `interactive_login`, caches, `execute_api_call`,
`CalendarClient` or other `get_*_client` methods (spec Non-Goals); the file manager.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/google.py` | MODIFY | `DriveClient`, `aiogoogle_credentials`, promoted `get_drive_client` |
| `packages/ai-parrot/tests/interfaces/test_drive_client.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiogoogle import Aiogoogle                       # verified: google.py:29 (already imported)
from aiogoogle.models import Request                  # verified: .venv/.../aiogoogle/models.py:141 — NEW import in google.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/google.py
class CalendarClient:                                                   # :160 (body ends :218)
    def __init__(self, google_client: "GoogleClient", version: str = "v3") -> None   # :172
class GoogleClient(CredentialsInterface, ABC):                          # :226
    self._service_account_creds: Optional[ServiceAccountCreds]          # :311
    self._user_creds: Optional[UserCreds]                               # :312
    self._authenticated = False                                         # :315
    def using_service_account(self) -> bool                             # :642
    async def get_drive_client(self, version: str = "v3") -> Dict[str, Any]   # :771-773 ← replaced
    async def get_calendar_client(self, version: str = "v3") -> "CalendarClient"   # :783 (pattern)

# aiogoogle 5.19.0
Aiogoogle.__init__(session_factory=..., api_key=None, user_creds=None, client_creds=None, service_account_creds=None, ...)   # client.py:60
async def discover(self, api_name, api_version=None, validate=False, *, disco_doc_ver=None)   # client.py:157
async def as_user(self, *requests, timeout=None, full_res=False, user_creds=None, raise_for_status=True)   # client.py:223
async def as_service_account(self, *requests, timeout=None, full_res=False, service_account_creds=None, raise_for_status=True)   # client.py:278
async def __aenter__ / __aexit__                                                    # client.py:425, :433
Method.__call__(..., upload_file=None, pipe_from=None, download_file=None, pipe_to=None, ...)   # resource.py:394-397
```

### Does NOT Exist
- ~~`GoogleClient.aiogoogle_credentials()`~~ — added here.
- ~~`GoogleClient.drive`~~, ~~`list_drive_files()`~~, ~~`upload_to_drive()`~~ — never add them.
- ~~aiogoogle resumable protocol~~ — `send_raw` only sends one hand-built `Request`; the chunk loop lives in TASK-3812.
- ~~`GoogleClient.close()` closing sessions~~ — it only flips `_authenticated` (:1051-1054).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/google.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_drive_client.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/google.py#CalendarClient",
    "sym:packages/ai-parrot/src/parrot/interfaces/google.py#GoogleClient",
    "sym:packages/ai-parrot/src/parrot/interfaces/google.py#GoogleClient.using_service_account",
    "sym:packages/ai-parrot/src/parrot/interfaces/google.py#GoogleClient.get_drive_client"
  ]
}
```

---

## Implementation Notes

- Every typed wrapper passes `supportsAllDrives=True` when `self.supports_all_drives` and
  forwards any extra `**params` (the manager's `_list_params()` adds shared-drive flags) — spec §7 "Shared-drive flags".
- `files_list` maps snake_case kwargs to Drive params: `pageSize`, `pageToken`, `orderBy`, `driveId`.
- `files_update` maps `add_parents` → `addParents`, `remove_parents` → `removeParents`;
  metadata goes in `json=` (aiogoogle body kwarg), upload via `upload_file=` / `pipe_from=` +
  `upload_file_content_type=`.
- `permissions_create` passes `sendNotificationEmail=send_notification_email` and `json=body`.
- `files_download` → `self.api.files.get(fileId=…, alt="media", download_file=… | pipe_to=…)`.
- Tests: monkeypatch `parrot.interfaces.google.Aiogoogle` with a recording fake; build the
  `GoogleClient` via `GoogleClient.__new__` (no Redis). The test module needs no
  `parrot.interfaces.file` stub pop (it does not import that package).

---

## Implementation Blueprint

### Steps (in order)
1. Add `from aiogoogle.models import Request` next to the existing aiogoogle imports — *why*: `send_raw` is typed on it.
2. Insert `DriveClient` after `CalendarClient` — *why*: FEAT-453 precedent placement.
3. Insert `aiogoogle_credentials()` before `using_service_account` — *why*: public read-only access to creds.
4. Replace `get_drive_client` — *why*: G2 promotion; hard cut, no callers.
5. Write the tests.

### `packages/ai-parrot/src/parrot/interfaces/google.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c 'from aiogoogle.auth.creds import ServiceAccountCreds, UserCreds' google.py)
# AFTER — insert below `from aiogoogle.auth.creds import ServiceAccountCreds, UserCreds` (verified: google.py:30)
from aiogoogle.models import Request
```

### `google.py` (MODIFY — DriveClient)
```python
# occurrences: 1 (verified: grep -c 'class CalendarClient:' google.py)
# AFTER — insert after CalendarClient.patch_event's body (ends google.py:218), BEFORE the
#         "# Google Client" banner that precedes `class GoogleClient(CredentialsInterface, ABC):` (:226)
class DriveClient:
    """A live Google Drive v3 client over one ``Aiogoogle`` session (FEAT-608).

    Unlike :class:`CalendarClient` it keeps the session and the discovered API open between
    calls: ``open()`` once, then every method is one authorised request; ``close()`` releases it.
    """

    def __init__(self, google_client: "GoogleClient", version: str = "v3", *, supports_all_drives: bool = True) -> None:
        self._client = google_client
        self.version = version
        self.supports_all_drives = supports_all_drives
        self._aiogoogle: Optional[Aiogoogle] = None
        self._api: Any = None
        self.logger = logging.getLogger(__name__)

    async def open(self) -> "DriveClient":
        """``Aiogoogle(**google_client.aiogoogle_credentials())`` + ``discover("drive", version)``; idempotent."""
        if self._api is not None:
            return self
        self._aiogoogle = Aiogoogle(**self._client.aiogoogle_credentials())
        await self._aiogoogle.__aenter__()
        self._api = await self._aiogoogle.discover("drive", self.version)
        return self

    async def close(self) -> None:
        # FILL IN: __aexit__(None, None, None) on the session if open; reset _aiogoogle/_api; idempotent
        ...

    async def __aenter__(self) -> "DriveClient":
        return await self.open()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    @property
    def api(self) -> Any:
        """The discovered GoogleAPI (raises RuntimeError before ``open()``)."""
        if self._api is None:
            raise RuntimeError("DriveClient is not open; call open() first")
        return self._api

    async def execute(self, request: Any, *, full_res: bool = False, raise_for_status: bool = True) -> Any:
        """``as_service_account`` when ``google_client.using_service_account()`` else ``as_user``."""
        send = self._aiogoogle.as_service_account if self._client.using_service_account() else self._aiogoogle.as_user
        return await send(request, full_res=full_res, raise_for_status=raise_for_status)

    async def send_raw(self, request: Request, *, full_res: bool = True, raise_for_status: bool = True) -> Any:
        """Authorise and send a hand-built ``aiogoogle.models.Request`` (resumable session + chunk PUTs)."""
        return await self.execute(request, full_res=full_res, raise_for_status=raise_for_status)

    def _drive_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # FILL IN: add supportsAllDrives=True when self.supports_all_drives; drop None values
        raise NotImplementedError

    # FILL IN: typed wrappers files_list / files_get / files_create / files_update / files_copy /
    #          files_delete / files_download / permissions_create with EXACTLY the spec §3 M1 signatures,
    #          each `return await self.execute(self.api.files.<m>(**self._drive_params({...})))` —
    #          bounded by Implementation Notes (param-name mapping); every wrapper accepts **params
```
**Why this shape**: spec §3 M1 fixes the constructor, `open/close/api/execute/send_raw` and the
eight wrapper signatures; the dispatch rule mirrors `execute_api_call` (:763-766) but uses
`using_service_account()` as AC4 requires.

### `google.py` (MODIFY — aiogoogle_credentials)
```python
# occurrences: 1 (verified: grep -c '    def using_service_account(self) -> bool:' google.py)
# BEFORE — insert above `    def using_service_account(self) -> bool:` (verified: google.py:642)
    def aiogoogle_credentials(self) -> Dict[str, Any]:
        """Return ``{"service_account_creds": ..., "user_creds": ...}`` for ``Aiogoogle(...)`` (FEAT-608).

        Raises:
            RuntimeError: when the client has not been initialised.
        """
        if not self._authenticated:
            raise RuntimeError("GoogleClient is not initialised; call initialize() first")
        return {"service_account_creds": self._service_account_creds, "user_creds": self._user_creds}
```

### `google.py` (MODIFY — get_drive_client)
```python
# occurrences: 1 (verified: grep -c '    async def get_drive_client(self, version: str = "v3") -> Dict[str, Any]:' google.py)
# REPLACE the 3-line method at google.py:771-773 with:
    async def get_drive_client(self, version: str = "v3") -> "DriveClient":
        """Return a not-yet-opened :class:`DriveClient` bound to this client (FEAT-608; was a config dict).

        Args:
            version: Drive API version (default ``'v3'``).
        """
        return DriveClient(self, version=version)
```

### `packages/ai-parrot/tests/interfaces/test_drive_client.py` (CREATE)
```python
"""FEAT-608 TASK-3807 — DriveClient + get_drive_client promotion."""
import pytest

import parrot.interfaces.google as google_mod
from parrot.interfaces.google import DriveClient, GoogleClient


class _FakeAiogoogle:
    instances: list = []
    # FILL IN: record __init__ kwargs, discover() calls, as_service_account/as_user calls;
    #          discover returns an object whose .files.<m>(**kw) returns ("files", m, kw)


def _client(auth_type: str = "service_account") -> GoogleClient:
    c = GoogleClient.__new__(GoogleClient)
    # FILL IN: _authenticated=True, auth_type, _service_account_creds / _user_creds sentinels
    return c


async def test_drive_client_open_is_idempotent_and_discovers_once(monkeypatch): ...
async def test_drive_client_dispatches_service_account_vs_user(monkeypatch): ...
async def test_drive_client_send_raw_authorises_request(monkeypatch): ...
async def test_get_drive_client_returns_drive_client(): ...
def test_aiogoogle_credentials_requires_initialised(): ...
async def test_files_list_maps_params_and_supports_all_drives(monkeypatch): ...
```

### FILL IN checklist
- [ ] `DriveClient.close` — idempotent session release.
- [ ] `DriveClient._drive_params` + 8 typed wrappers — param mapping; AC4/AC5.
- [ ] Six tests.

---

## Acceptance Criteria

- [ ] AC4: one `Aiogoogle` + one `discover("drive","v3")` per `DriveClient` lifetime; dispatch by `using_service_account()`; `get_drive_client()` returns `DriveClient`.
- [ ] No other `GoogleClient` public signature changed.
- [ ] `ruff check packages/ai-parrot/src/parrot/interfaces/google.py` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/interfaces/test_drive_client.py -q`

---

## Agent Instructions
Standard. Run tests with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` inside the worktree.

---

## Completion Note

*(Agent fills this in when done)*
