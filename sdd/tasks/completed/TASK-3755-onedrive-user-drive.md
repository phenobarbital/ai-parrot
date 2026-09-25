# TASK-3755: OneDriveClient._resolve_user_drive — cache-safe port from flowtask (me / UPN / object id)

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 2**, AC4 and AC24, design research **S9**. `OneDriveClient._resolve_drive()` only targets the
signed-in user (`me/drive`). flowtask's `SharepointClient._resolve_user_drive` (user-provided reference below) can target
any user, but it writes the single-slot `_drive_id` / `_user_drive_info` caches — reusing one client for two users would
return the first user's drive. This task ports it into `OneDriveClient` as an **additive**, **per-user-cached** method
that never touches `_drive_id` / `_drive_info` (those remain owned by the legacy `_resolve_drive`).
`OneDriveFileManager` (TASK-3757) calls it.

**Spec correction (verified):** `O365Client.is_app_only` is a **property** (`o365.py:364-370`), not a method — the spec's
skeleton writes `self.is_app_only()`. Use `self.is_app_only` (no call).

---

## Scope

- Add `self._user_drives: Dict[str, DriveItem] = {}` in `OneDriveClient.__init__`.
- Add `async def _resolve_user_drive(self, user: str) -> DriveItem` right after `_resolve_drive`.
- Create `packages/ai-parrot/tests/interfaces/test_onedrive_client_user_drive.py`.

**NOT in scope**: `SharepointClient` (no edit — the flowtask `drive.type` shim is NOT ported, spec G3); the manager.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/onedrive.py` | MODIFY | per-user drive cache + `_resolve_user_drive` |
| `packages/ai-parrot/tests/interfaces/test_onedrive_client_user_drive.py` | CREATE | unit tests (self-contained fakes) |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`.

### Verified Imports
```python
# onedrive.py already imports everything needed:
from typing import List, Optional, Union, Dict, Any                 # verified: interfaces/onedrive.py:2
from msgraph.generated.models.drive_item import DriveItem          # verified: interfaces/onedrive.py:14
from parrot.interfaces.onedrive import OneDriveClient              # tests; verified: interfaces/onedrive.py:25
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/onedrive.py
class OneDriveClient(O365Client):                    # :25
    def __init__(self, *args, **kwargs):             # :48 — ends with `self._drive_info: Optional[DriveItem] = None` (:62)
    async def _resolve_drive(self) -> DriveItem:     # :88-106 — graph_client.me.drive.get(); sets _drive_id/_drive_info
# packages/ai-parrot/src/parrot/interfaces/o365.py
    @property
    def is_app_only(self) -> bool:                   # :364-370 — (auth_mode or "") == "direct" and not
                                                     #   (credentials.get("username") or credentials.get("assertion"))
    @property
    def graph_client(self)                           # :339 — returns _graph_client when set
# msgraph: graph_client.me.drive.get() ; graph_client.users.by_user_id(user).drive.get()
```

### User-Provided Code (reference, NOT in this repo)
```python
# Source: /home/jesuslara/proyectos/flowtask/flowtask/interfaces/Sharepoint.py:145-188 (abridged)
    async def _resolve_user_drive(self) -> DriveItem:
        if self._user_drive_info:
            return self._user_drive_info
        self._ensure_drive_config()
        try:
            if str(self.onedrive_user).strip().lower() == "me":
                drive = await self.graph_client.me.drive.get()
            else:
                drive = await self.graph_client.users.by_user_id(self.onedrive_user).drive.get()
        except Exception as e:
            raise RuntimeError(
                f"Failed to resolve OneDrive for '{self.onedrive_user}': {e}. "
                "For app-only auth this requires the application permission "
                "'Files.ReadWrite.All' (admin-consented)."
            ) from e
        if not drive or not getattr(drive, "id", None):
            raise RuntimeError(f"Could not resolve OneDrive for user '{self.onedrive_user}'")
        self._user_drive_info = drive
        self._drive_id = drive.id          # <- NOT ported (S9)
        return drive
```

### Does NOT Exist
- ~~`OneDriveClient.onedrive_user`~~, ~~`OneDriveClient._user_drive_info`~~, ~~`OneDriveClient._ensure_drive_config`~~ — not
  added; the user is an explicit argument and the cache is `_user_drives` (S9).
- ~~`O365Client.is_app_only()`~~ — it is a property; calling it raises `TypeError: 'bool' object is not callable`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/onedrive.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_onedrive_client_user_drive.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/onedrive.py#OneDriveClient",
    "sym:packages/ai-parrot/src/parrot/interfaces/onedrive.py#OneDriveClient._resolve_drive",
    "sym:packages/ai-parrot/src/parrot/interfaces/o365.py#O365Client.is_app_only"
  ]
}
```

---

## Implementation Notes

- Cache key: `user.strip().lower()`; a cached hit returns immediately without a Graph call.
- `"me"` under app-only auth (`self.is_app_only` is True) → `RuntimeError("OneDrive user 'me' requires delegated
  authentication; pass a UPN or object id for app-only access")` BEFORE any Graph call.
- Keep flowtask's error wording (the `Files.ReadWrite.All` hint) for Graph failures and the "Could not resolve" message
  for an empty result.
- The method must be safe to call concurrently for different users on the same client: it only reads/writes
  `self._user_drives[key]`.
- Tests are self-contained (no dependency on TASK-3748): build the client with `OneDriveClient.__new__(OneDriveClient)`,
  set `credentials`, `auth_mode`, `_graph_client` (a `SimpleNamespace` exposing `me.drive.get` / `users.by_user_id(u)
  .drive.get` as `AsyncMock`s), `_user_drives = {}`, `_drive_id = None`, `_drive_info = None`, `logger`.

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
1. Add the cache attribute in `__init__` — *why*: per-user cache (S9).
2. Add `_resolve_user_drive` after `_resolve_drive` — *why*: keeps the drive-resolution methods together.
3. Write the tests.

### `packages/ai-parrot/src/parrot/interfaces/onedrive.py` (MODIFY) — `__init__`
```python
# occurrences: 1 (verified: grep -c '        self._drive_info: Optional\[DriveItem\] = None' interfaces/onedrive.py)
# AFTER — insert below `        self._drive_info: Optional[DriveItem] = None` (verified: interfaces/onedrive.py:62)
        # Per-user OneDrive cache for _resolve_user_drive (FEAT-603, S9) — never shares _drive_id/_drive_info.
        self._user_drives: Dict[str, DriveItem] = {}
```

### `packages/ai-parrot/src/parrot/interfaces/onedrive.py` (MODIFY) — `_resolve_user_drive`
```python
# occurrences: 1 (verified: grep -c '    async def _ensure_folder(self, folder_path: str, create: bool = True) -> DriveItem:' interfaces/onedrive.py)
# BEFORE — insert above `    async def _ensure_folder(self, folder_path: str, create: bool = True) -> DriveItem:` (verified: :108),
#          i.e. directly after the end of `_resolve_drive` (:88-106)
    async def _resolve_user_drive(self, user: str) -> DriveItem:
        """Resolve a user's personal OneDrive, cached per user (FEAT-603; ported from flowtask).

        Never touches ``_drive_id`` / ``_drive_info`` (owned by :meth:`_resolve_drive`), so one client can resolve
        several users safely.

        Args:
            user: UPN, Entra object id, or the literal ``"me"`` (delegated authentication only).

        Returns:
            The user's OneDrive ``DriveItem``.

        Raises:
            RuntimeError: ``"me"`` under app-only auth; Graph failure (hint: ``Files.ReadWrite.All``); empty result.
        """
        key = (user or "").strip().lower()
        if not key:
            raise RuntimeError("OneDrive user is required (UPN, object id, or 'me')")
        cached = self._user_drives.get(key)
        if cached is not None:
            return cached
        # FILL IN: 'me' + app-only guard (property, no call); Graph call per flowtask reference; error wording kept;
        #          empty-result check; store in self._user_drives[key]; self.logger.info(...) without secrets — bounded by AC4/AC24
```
**Why**: the cache-first preamble is written out because it is the S9 fix; the Graph branch is a verbatim adaptation of
the user-provided flowtask code with the `_drive_id` write removed.

### `packages/ai-parrot/tests/interfaces/test_onedrive_client_user_drive.py` (CREATE)
```python
"""FEAT-603 TASK-3755 — OneDriveClient._resolve_user_drive."""
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.interfaces.onedrive import OneDriveClient


def _client(*, auth_mode: str = "direct", credentials: dict | None = None) -> OneDriveClient:
    c = OneDriveClient.__new__(OneDriveClient)
    me = SimpleNamespace(drive=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id="me-drive", name="OneDrive"))))
    users = SimpleNamespace(by_user_id=lambda u: SimpleNamespace(drive=SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(id=f"drive-{u}", name="OneDrive")))))
    c.__dict__.update(credentials=credentials or {}, auth_mode=auth_mode, _graph_client=SimpleNamespace(me=me, users=users),
                      _user_drives={}, _drive_id=None, _drive_info=None, logger=logging.getLogger("t"))
    return c


async def test_resolve_user_drive_me_and_upn():
    # FILL IN: delegated client -> "me" returns me-drive; "A@T.com" returns drive-A@T.com


async def test_resolve_user_drive_app_only_me_rejected():
    # FILL IN: auth_mode="direct", no username/assertion -> RuntimeError, no Graph call


async def test_resolve_user_drive_error_names_permission():
    # FILL IN: users...get raises -> RuntimeError whose message contains "Files.ReadWrite.All"


async def test_resolve_user_drive_cache_per_user_and_leaves_drive_id_alone():
    # FILL IN: two users -> two different ids; second call for the same user makes no Graph call;
    #          _drive_id and _drive_info are still None


async def test_resolve_drive_unchanged():
    # FILL IN: legacy _resolve_drive() still returns me-drive and sets _drive_id
```

### FILL IN checklist
- [ ] the Graph branch of `_resolve_user_drive`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `me/drive` under delegated auth, `users/{id}/drive` otherwise; `me` under app-only → `RuntimeError` before any
      Graph call; failure message names `Files.ReadWrite.All` (spec AC4).
- [ ] Per-user cache; `_drive_id` / `_drive_info` untouched; legacy `_resolve_drive()` unchanged (spec AC4, AC24).
- [ ] `interfaces/sharepoint.py` is unchanged (`git diff --stat` empty for it).
- [ ] `ruff check packages/ai-parrot/src/parrot/interfaces/onedrive.py` reports no NEW findings in the added lines.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_onedrive_client_user_drive.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_resolve_user_drive_me_and_upn` | both Graph paths |
| `test_resolve_user_drive_app_only_me_rejected` | guard, property semantics |
| `test_resolve_user_drive_error_names_permission` | error wording |
| `test_resolve_user_drive_cache_per_user_and_leaves_drive_id_alone` | S9 |
| `test_resolve_drive_unchanged` | backwards compatibility |

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


- Task: TASK-3755
- Feature: sharepoint-filemanager
- Implementation SHA: 2c2c5433bc481eab951a8d610651f4670cac0ab5
- Closed at (UTC): 2026-09-25T18:48:23+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| merge_tier_gate_note | Full ai-parrot distribution escalation (core-path rule, tracked as FEAT-604 draft) collects 18 test files that fail to import for reasons unrelated to this task (existing on origin/dev prior to this feature). This task's own declared test file is the acceptance evidence above. |
| real_code_commits | 091374b3bd58569054c5d9a3babbff092f705b02 (feat) and 27e6c4d7c52aa781766bd8752f58a5cf322098ea (lint autofix); implementation_sha above is an empty anchor commit because HEAD advanced past this task's own merge before finalize_task ran for it. |
| scoped_test_result | packages/ai-parrot/tests/interfaces/test_onedrive_client_user_drive.py: 5 passed, 0 failed (run directly, 2026-09-25T18:30 UTC) |
| seat_summary | Seat: sonnet(native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a |
