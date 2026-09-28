# TASK-3813: `gdrive.py` copy / delete / folders / rename-move / sharing links

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3812
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (mutation + sharing half; AC10, AC11; goal G5). `get_file_url` returns
`webViewLink` **without changing permissions**; explicit sharing is `create_sharing_link`
over `permissions.create`. Deletes trash by default (recycle-bin parity with FEAT-603).

---

## Scope

Add to `GoogleDriveFileManager`: `copy_file`, `delete_file`, `create_folder`,
`remove_folder`, `rename_file`, `rename_folder`, `_move_or_rename`, `create_sharing_link`,
`get_file_url`. Append tests.

**NOT in scope**: batch + serving (TASK-3814); Workspace export (spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` | MODIFY | Mutation + sharing methods |
| `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py` | MODIFY | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# navigator abstract.py — exact signatures
async def get_file_url(self, path: str, expiry: int = 3600) -> str                  # :67
async def copy_file(self, source: str, destination: str) -> FileMetadata            # :107
async def delete_file(self, path: str) -> bool                                      # :119
async def create_folder(self, folder_name: str) -> None                             # :170
async def remove_folder(self, folder_name: str) -> None                             # :183
async def rename_folder(self, old_folder_name: str, new_folder_name: str) -> None   # :196
async def rename_file(self, old_file_name: str, new_file_name: str) -> None         # :212
# DriveClient (TASK-3807): files_copy(file_id, metadata, *, fields, **params); files_delete(file_id, **params);
#   files_update(file_id, metadata=None, *, fields, add_parents=None, remove_parents=None, ...);
#   files_get(file_id, *, fields, **params); permissions_create(file_id, body, *, send_notification_email=False, **params)
# gdrive.py (TASK-3810..3812): _prefixed, _resolve, _resolve_parent, _invalidate, _apply_conflict, _find_conflict,
#   _retrying, _map_error, _make_metadata, _list_params, FIELDS, FOLDER_MIME, permanent_delete, ShareScope, ShareRole
```

### Does NOT Exist
- ~~`expirationTime` for `domain` / `anyone` permissions~~ — Drive rejects it; only `user`/`group`.
- ~~`FileManagerInterface.create_sharing_link`~~ — extension.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/gdrive.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/file/gdrive.py#GoogleDriveFileManager"
  ]
}
```

---

## Implementation Notes

- `copy_file`: `files_copy(id, {"name": dest_name, "parents": [dest_parent_id]}, fields=FIELDS, **_list_params())`
  with `_retrying(idempotent=False)` (AC11 — a retried copy duplicates); destination parents
  created; `conflict_behavior` applies to the destination name.
- `delete_file`: resolve (missing → `False`); `permanent_delete` → `files_delete`, else
  `files_update(id, {"trashed": True}, fields="id")`; invalidate; `True`.
- `create_folder`: idempotent — `_resolve_parent(full + "/x", create=True)` style walk that
  creates every segment of `folder_name`; existing folder → no-op.
- `remove_folder`: resolve `want_folder=True`; trash/delete the folder item (Drive cascades).
- `_move_or_rename(old, new)`: resolve old; new parent via `_resolve_parent(create=True)`;
  apply `_apply_conflict` for the new name (for `replace`, an existing *different* item at the
  target raises `FileExistsError` — do not overwrite on rename; document it); `files_update(id, {"name": new_name},
  add_parents=new_pid, remove_parents=old_pid)` only when the parent changes; invalidate both paths.
- `create_sharing_link(path, *, scope="user", role="reader", email_address=None, domain=None, expiry=0)`:
  `user`/`group` require `email_address`, `domain` requires `domain` → `ValueError`;
  body `{"type": scope, "role": role}` + `emailAddress` / `domain`; `expirationTime`
  (RFC 3339 UTC, now + expiry s) only when `expiry > 0` and scope in `{user, group}`;
  `permissions_create(id, body, send_notification_email=False, **_list_params())` with
  `_retrying(idempotent=False)`; a 403 → `PermissionError` (policy-forbidden); then
  `files_get(id, fields="webViewLink")` → return link.
- `get_file_url(path, expiry=3600)`: `files_get(id, fields="webViewLink")`; `self.logger.debug`
  that `expiry` is ignored; **no** `permissions_create` call (AC10).

---

## Implementation Blueprint

### Steps (in order)
1. Append copy/delete/folder methods — *why*: AC11.
2. Append `_move_or_rename` + rename wrappers — *why*: `addParents`/`removeParents`.
3. Append sharing methods — *why*: AC10 / U3.
4. Append tests.

### `gdrive.py` (MODIFY — appended after TASK-3812's `upload_file_from_bytes`)
```python
    # ---- mutations & sharing (TASK-3813) ---------------------------------
    async def copy_file(self, source: str, destination: str) -> FileMetadata:
        """``files.copy`` (synchronous in Drive); never retried (non-idempotent)."""
        # FILL IN: per Implementation Notes — bounded by AC11
        raise NotImplementedError

    async def delete_file(self, path: str) -> bool:
        """Trash by default; ``permanent_delete`` → ``files.delete``; missing → False."""
        # FILL IN
        raise NotImplementedError

    async def create_folder(self, folder_name: str) -> None:
        # FILL IN: idempotent mkdir -p under the root
        raise NotImplementedError

    async def remove_folder(self, folder_name: str) -> None:
        # FILL IN
        raise NotImplementedError

    async def _move_or_rename(self, old: str, new: str) -> None:
        # FILL IN: per Implementation Notes
        raise NotImplementedError

    async def rename_file(self, old_file_name: str, new_file_name: str) -> None:
        await self._move_or_rename(old_file_name, new_file_name)

    async def rename_folder(self, old_folder_name: str, new_folder_name: str) -> None:
        await self._move_or_rename(old_folder_name, new_folder_name)

    async def create_sharing_link(self, path: str, *, scope: ShareScope = "user", role: ShareRole = "reader",
                                  email_address: Optional[str] = None, domain: Optional[str] = None,
                                  expiry: int = 0) -> str:
        """Create a Drive permission and return the item's ``webViewLink`` (never retried)."""
        # FILL IN: validation → body → permissions_create (idempotent=False) → files_get(webViewLink) — bounded by AC10
        raise NotImplementedError

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Return ``webViewLink`` without changing permissions; ``expiry`` is ignored (U3)."""
        await self._ready()
        self.logger.debug("get_file_url: expiry=%s ignored for Google Drive (no permission change)", expiry)
        # FILL IN: resolve → files_get(id, fields="webViewLink", **_list_params()) via _retrying → link
        raise NotImplementedError
```

### `test_gdrive_filemanager.py` (MODIFY — append)
```python
async def test_copy_is_synchronous_and_never_retried(manager): ...
async def test_delete_trashes_by_default_permanent_optional_missing_false(fake_drive): ...
async def test_folders_create_remove_rename_and_move_across_parents(manager): ...
async def test_get_file_url_returns_webviewlink_without_permissions(manager, caplog): ...
async def test_create_sharing_link_bodies_per_scope_and_expiry_rules(manager): ...
async def test_create_sharing_link_missing_field_value_error(manager): ...
async def test_create_sharing_link_forbidden_scope_permission_error(manager): ...
```

### FILL IN checklist
- [ ] `copy_file`, `delete_file`, `create_folder`, `remove_folder`.
- [ ] `_move_or_rename`.
- [ ] `create_sharing_link`, `get_file_url`.
- [ ] 7 tests.

---

## Acceptance Criteria

- [ ] AC10, AC11.
- [ ] Earlier tests in the module still pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py -q`

---

## Agent Instructions
Standard. `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` inside the worktree.

---

## Completion Note

*(Agent fills this in when done)*
