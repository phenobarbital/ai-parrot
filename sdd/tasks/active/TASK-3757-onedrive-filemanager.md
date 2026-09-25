# TASK-3757: OneDriveFileManager — user / "me" targeting over OneDriveClient

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3750, TASK-3755, TASK-3748
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 4**, AC2 (same allowed-member rule as TASK-3756, including the `client_class` attribute) and AC24.
Drive resolution delegates to `OneDriveClient._resolve_user_drive(user)` (TASK-3755), which caches per user, so two
managers adopting one client for different users get different drives.

**Spec correction (verified):** `O365Client.is_app_only` is a **property** (`o365.py:364-370`); the spec skeleton's
`client.is_app_only()` must be written `client.is_app_only`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/interfaces/file/onedrive.py` with `OneDriveFileManager`.
- Create `packages/ai-parrot/tests/interfaces/test_onedrive_filemanager.py`.

**NOT in scope**: registration (TASK-3758); the O365 tool refactor (TASK-3763/3764).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/onedrive.py` | CREATE | `OneDriveFileManager` |
| `packages/ai-parrot/tests/interfaces/test_onedrive_filemanager.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`.

### Verified Imports
```python
from parrot.interfaces.onedrive import OneDriveClient                 # verified: packages/ai-parrot/src/parrot/interfaces/onedrive.py:25
from .graph import GraphDriveFileManager, GraphFileManagerError        # TASK-3749/3750
from ._graph_fakes import FakeDrive, FakeGraphClient, make_onedrive_client   # tests (TASK-3748)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/onedrive.py
class OneDriveClient(O365Client):                                  # :25
    async def _resolve_user_drive(self, user: str) -> DriveItem    # added by TASK-3755 (after _resolve_drive :88-106)
# packages/ai-parrot/src/parrot/interfaces/o365.py
    @property
    def is_app_only(self) -> bool                                  # :364-370 (property!)
# O365Client.__init__ defaults: _default_client_id/secret/tenant from O365_CLIENT_ID / O365_CLIENT_SECRET / O365_TENANT_ID (:188-191)
```

### Does NOT Exist
- ~~`OneDriveClient(user=...)`~~ — the user is passed to `_resolve_user_drive`, not the constructor.
- ~~`O365Client.is_app_only()`~~ — property.
- ~~`parrot.interfaces.file.onedrive`~~ — created by this task (distinct from `parrot.interfaces.onedrive`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/onedrive.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interfaces/test_onedrive_filemanager.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/onedrive.py#OneDriveClient",
    "sym:packages/ai-parrot/src/parrot/interfaces/o365.py#O365Client.is_app_only"
  ]
}
```

---

## Implementation Notes

- `_build_client()` → `OneDriveClient(credentials=dict(self.credentials))`; no authentication here.
- `_resolve_drive_id()`: if `self.user.strip().lower() == "me"` and `self.client.is_app_only` → `RuntimeError("OneDrive
  user 'me' requires delegated, cached or on_behalf_of authentication")`; else `drive = await
  self.client._resolve_user_drive(self.user)`; return `drive.id` (missing → `GraphFileManagerError`).
- The same guard lives in `_resolve_user_drive` (TASK-3755); checking in the manager too gives a manager-level message
  and keeps the rule testable without the client.

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
1. Write the module.
2. Write the tests.

### `packages/ai-parrot/src/parrot/interfaces/file/onedrive.py` (CREATE)
```python
"""OneDrive FileManager (FEAT-603)."""
from __future__ import annotations

from typing import Any

from parrot.interfaces.onedrive import OneDriveClient

from .graph import GraphDriveFileManager, GraphFileManagerError


class OneDriveFileManager(GraphDriveFileManager):
    """FileManagerInterface over a user's OneDrive.

    ``user="me"`` requires delegated / cached / on_behalf_of auth; under app-only (direct) auth ``user`` must be a UPN or
    object id and the app needs the ``Files.ReadWrite.All`` application permission. Credentials default to
    O365_CLIENT_ID / O365_CLIENT_SECRET / O365_TENANT_ID.
    """

    manager_name: str = "onedrivefile"
    client_class: type = OneDriveClient

    def __init__(self, user: str = "me", **kwargs: Any) -> None:
        """Args:
            user: UPN, Entra object id, or ``"me"``.
            **kwargs: Forwarded to :class:`GraphDriveFileManager` (prefix, credentials, auth_mode, ...).
        """
        super().__init__(**kwargs)
        if not user or not str(user).strip():
            raise ValueError("OneDriveFileManager requires a user (UPN, object id, or 'me')")
        self.user = str(user).strip()

    def _build_client(self) -> OneDriveClient:
        """A not-yet-authenticated OneDriveClient."""
        return OneDriveClient(credentials=dict(self.credentials or {}))

    async def _resolve_drive_id(self) -> str:
        """Resolve the user's drive through ``OneDriveClient._resolve_user_drive`` (per-user cache, S9)."""
        # FILL IN: rule in Implementation Notes
```

### `packages/ai-parrot/tests/interfaces/test_onedrive_filemanager.py` (CREATE)
```python
"""FEAT-603 TASK-3757 — OneDriveFileManager."""
import pytest

from parrot.interfaces.file.onedrive import OneDriveFileManager
from ._graph_fakes import FakeDrive, FakeGraphClient, make_onedrive_client


@pytest.fixture
def fake():
    return FakeGraphClient({"drive-me": FakeDrive("drive-me"), "drive-u": FakeDrive("drive-u")},
                           me_drive_id="drive-me", user_drives={"u@t.com": "drive-u"})


async def test_onedrive_manager_me_requires_delegated(fake):
    # FILL IN: user="me" + adopt make_onedrive_client(fake, app_only=True) -> RuntimeError on _ready();
    #          app_only=False -> "drive-me"


async def test_onedrive_manager_user_drive(fake):
    # FILL IN: user="u@t.com" app-only -> "drive-u"


async def test_two_managers_one_client_different_users(fake):
    # FILL IN: AC24 — same adopted client, users "me" (delegated) and "u@t.com" resolve to different drive ids


def test_constructor_rejects_empty_user():
    with pytest.raises(ValueError):
        OneDriveFileManager(user="  ")


def test_subclass_overrides_only_allowed_members():
    allowed = {"manager_name", "client_class", "__init__", "_build_client", "_resolve_drive_id", "__doc__", "__module__",
               "__qualname__", "__abstractmethods__", "_abc_impl", "__firstlineno__", "__static_attributes__"}
    assert set(vars(OneDriveFileManager)) - allowed == set()
```

### FILL IN checklist
- [ ] `_resolve_drive_id`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `OneDriveFileManager(user="me", **kwargs)` with `manager_name = "onedrivefile"`; only allowed members overridden
      (spec AC2).
- [ ] `me` under app-only auth is rejected; UPN/id resolves via `_resolve_user_drive`; two managers on one client get
      different drive ids (spec AC4, AC24).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_onedrive_filemanager.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_onedrive_manager_me_requires_delegated` / `test_onedrive_manager_user_drive` | resolution rules |
| `test_two_managers_one_client_different_users` | AC24 |
| `test_constructor_rejects_empty_user` / `test_subclass_overrides_only_allowed_members` | API / AC2 |

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
