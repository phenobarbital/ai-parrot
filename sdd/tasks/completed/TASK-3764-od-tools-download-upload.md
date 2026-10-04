# TASK-3764: OneDrive O365 tools (Download by path/id, Upload) delegate to OneDriveFileManager

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3763, TASK-3752
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 8** (second half), AC13. The Download tool finds a file *by path* today by running a name search and
suffix-matching the results (`parrot_tools/o365/onedrive.py:297-313`), and downloads by id through
`client._resolve_drive()` + raw Graph (`:283-292`). The manager addresses paths directly (`root:/<path>:`) and ids via
`_get_item_by_id` (TASK-3751). The Upload tool's rename trick — copy the local file to `<parent>/<rename_as>`, upload,
delete the copy (`:405-420`) — becomes a destination name, so `shutil` is no longer used and its import is removed
together with the now-unused `OneDriveClient` import (ruff F401).

**Download by id path resolution:** `DownloadOneDriveFileTool` keeps `file_id` support: `item = await
manager._get_item_by_id(file_id)` after `await manager._ready()`, then `path = manager._item_path(item) or item.name` and
`download_file(path, dest)`. Using these two private helpers from the tool is an accepted, documented coupling (spec §3 M8
names `_get_item_by_id` for exactly this); do not add a new public method.

---

## Scope

- Rewrite `DownloadOneDriveFileTool._execute_graph_operation` and `UploadOneDriveFileTool._execute_graph_operation`.
- Remove `import shutil` and `from parrot.interfaces.onedrive import OneDriveClient` once unused.
- Append tests to `test_o365_onedrive_file_tools.py`.

**NOT in scope**: List/Search (TASK-3763); Delta classes (byte-identical).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` | MODIFY | Download + Upload bodies; drop unused imports |
| `packages/ai-parrot-tools/tests/test_o365_onedrive_file_tools.py` | MODIFY | append tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`.

### Verified Imports
```python
from parrot.interfaces.file.onedrive import OneDriveFileManager       # added by TASK-3763
from parrot_tools.o365.onedrive import DownloadOneDriveFileTool, UploadOneDriveFileTool   # tests
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py
import shutil                                                         # :13 — only used by the Upload rename trick (:409)
from parrot.interfaces.onedrive import OneDriveClient                 # :18
class DownloadOneDriveFileArgs(O365ToolArgsSchema): file_path=None, file_id=None, local_destination=None, rename_as=None   # :199-210
class DownloadOneDriveFileTool(O365Tool):                             # :213 — name "download_onedrive_file"
    async def _execute_graph_operation(self, client: OneDriveClient, **kwargs) -> Dict[str, Any]   # :250-330
        # ValueError when neither file_path nor file_id; returns {"file_path","file_id","local_path","size"}   (:321-326)
class UploadOneDriveFileArgs(O365ToolArgsSchema): local_file_path, folder_path="", rename_as=None   # :338-345
class UploadOneDriveFileTool(O365Tool):                               # :348 — name "upload_onedrive_file"
    async def _execute_graph_operation(self, client: OneDriveClient, **kwargs) -> Dict[str, Any]   # :379-436
        # FileNotFoundError for a missing local file; returns {"folder_path": folder_path or "root","uploaded_file",
        #   "file_id","size","web_url"}   (:426-432)
# From TASK-3751/3752/3757: OneDriveFileManager, adopt_client, _ready, _get_item_by_id, _item_path, download_file,
#   get_file_metadata, upload_file (FileMetadata has no id -> fetch it: see Implementation Notes), close
```

### Does NOT Exist
- ~~`FileMetadata.id`~~ — the Upload response needs `file_id`: after `upload_file`, get the id with
  `(await manager._get_item(manager._prefixed(dest))).id` (private, same accepted coupling as Download by id).
- ~~a temp-copy rename in the new Upload~~ — rename is the destination name.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/test_o365_onedrive_file_tools.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py#DownloadOneDriveFileTool._execute_graph_operation",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py#UploadOneDriveFileTool._execute_graph_operation"
  ]
}
```

---

## Implementation Notes

- Manager lifecycle as TASK-3763 (`user=kwargs.get("user_id") or "me"`, `adopt_client`, `finally: close`).
- **Download**: keep the "either file_path or file_id" `ValueError` and the `dest_dir` rule (cwd default, mkdir).
  By path: `local = dest_dir / (rename_as or file_path.rsplit("/", 1)[-1])`, `await manager.download_file(file_path,
  local)`, `file_id = (await manager._get_item(manager._prefixed(file_path))).id`. By id: Context rule. Response
  `{"file_path": file_path, "file_id": file_id, "local_path": str(local), "size": local.stat().st_size}`.
- **Upload**: local-existence check first; `dest = f"{folder_path}/{rename_as or local_path.name}".strip("/")`;
  `meta = await manager.upload_file(local_path, dest)`; id per "Does NOT Exist"; response keys as today
  (`web_url = meta.url or ""`).
- After both rewrites: `grep -c 'shutil' onedrive.py` == 0 and `grep -c 'OneDriveClient' onedrive.py` == 0 — remove
  the two imports.

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
1. Rewrite Download, then Upload.
2. Remove the two unused imports.
3. Append tests.

### `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` (MODIFY) — Download
```python
# occurrences: 1 (verified: grep -c 'class DownloadOneDriveFileTool(O365Tool):' parrot_tools/o365/onedrive.py) — :213
# FILL IN: disambiguate — REPLACE DownloadOneDriveFileTool._execute_graph_operation (:250-330):
    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """Download a OneDrive file by path or id through OneDriveFileManager (streamed to disk)."""
        file_path = kwargs.get("file_path")
        file_id = kwargs.get("file_id")
        local_destination = kwargs.get("local_destination")
        rename_as = kwargs.get("rename_as")
        if not file_path and not file_id:
            raise ValueError("Either file_path or file_id must be provided")
        dest_dir = Path(local_destination) if local_destination else Path.cwd()
        dest_dir.mkdir(parents=True, exist_ok=True)
        manager = OneDriveFileManager(user=kwargs.get("user_id") or "me", credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            # FILL IN: by-id and by-path branches per Context / Implementation Notes
            return {"file_path": file_path, "file_id": file_id, "local_path": str(local),
                    "size": local.stat().st_size if local.exists() else 0}
        except Exception as e:
            self.logger.error(f"Failed to download OneDrive file: {e}")
            raise
        finally:
            await manager.close()
```

### `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` (MODIFY) — Upload + imports
```python
# occurrences: 1 (verified: grep -c 'class UploadOneDriveFileTool(O365Tool):' parrot_tools/o365/onedrive.py) — :348
# FILL IN: disambiguate — REPLACE UploadOneDriveFileTool._execute_graph_operation (:379-436):
    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """Upload a local file to OneDrive through OneDriveFileManager (rename = destination name)."""
        local_file_path = kwargs.get("local_file_path")
        folder_path = kwargs.get("folder_path", "")
        rename_as = kwargs.get("rename_as")
        local_path = Path(local_file_path)
        if not local_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_file_path}")
        manager = OneDriveFileManager(user=kwargs.get("user_id") or "me", credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            # FILL IN: rule in Implementation Notes
            return {"folder_path": folder_path or "root", "uploaded_file": meta.name, "file_id": item_id,
                    "size": meta.size, "web_url": meta.url or ""}
        except Exception as e:
            self.logger.error(f"Failed to upload to OneDrive: {e}")
            raise
        finally:
            await manager.close()

# occurrences: 1 each (verified: grep -c '^import shutil$' and grep -c 'from parrot.interfaces.onedrive import OneDriveClient')
# DELETE the lines `import shutil` (:13) and `from parrot.interfaces.onedrive import OneDriveClient` (:18)
```

### `packages/ai-parrot-tools/tests/test_o365_onedrive_file_tools.py` (MODIFY)
```python
# AFTER — append at end of file
from parrot.interfaces.file.onedrive import OneDriveFileManager
from parrot_tools.o365.onedrive import DownloadOneDriveFileTool, UploadOneDriveFileTool


async def test_download_by_path_and_by_id_shape(fake, tmp_path, monkeypatch):
    # FILL IN: monkeypatch.setattr(OneDriveFileManager, "_http_session", lambda self: session); keys
    #          {"file_path","file_id","local_path","size"}; by-id resolves the item's path; rename_as honoured


async def test_download_requires_path_or_id(fake):
    # FILL IN


async def test_upload_onedrive_file_shape_and_rename_without_temp_copy(fake, tmp_path, monkeypatch):
    # FILL IN: keys {"folder_path","uploaded_file","file_id","size","web_url"}; no extra file created next to the source


def test_unused_imports_removed():
    import parrot_tools.o365.onedrive as mod
    assert "shutil" not in vars(mod) and "OneDriveClient" not in vars(mod)
```

### FILL IN checklist
- [ ] Download branches; Upload body
- [ ] import removals
- [ ] test bodies

---

## Acceptance Criteria

- [ ] Download (by path and by id) and Upload keep names, args and response key sets (spec AC13).
- [ ] Upload renames via the destination name; no temporary copy next to the source file.
- [ ] `shutil` and `OneDriveClient` no longer imported; `DeltaOneDriveFiles*` byte-identical;
      `test_o365_delta_tools.py` passes; `ruff check` clean on the module.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/test_o365_onedrive_file_tools.py -q`
- `pytest packages/ai-parrot-tools/tests/test_o365_delta_tools.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_download_by_path_and_by_id_shape` | AC13 |
| `test_download_requires_path_or_id` | validation kept |
| `test_upload_onedrive_file_shape_and_rename_without_temp_copy` | AC13, no temp copy |
| `test_unused_imports_removed` | F401 cleanup |

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


- Task: TASK-3764
- Feature: sharepoint-filemanager
- Implementation SHA: 9bf7760b3e8c6285f3dc7eaa69c6230eee0cadfc
- Closed at (UTC): 2026-09-25T21:19:57+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 223.2s · Tokens: n/a |
| validation_note | packages/ai-parrot-tools/tests collection blocked by 5 pre-existing unrelated errors (ledger issue:69189219cfd6). Own tests confirmed manually: 79 passed across the three o365 test files; tests/tools/test_office365_toolkit.py 8/8 passed. |
