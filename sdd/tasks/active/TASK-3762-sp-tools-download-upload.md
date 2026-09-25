# TASK-3762: SharePoint O365 tools (Download, Upload) delegate to SharePointFileManager

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3761, TASK-3752
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7** (second half), AC13, design research **S1** / **S6**. The Download tool currently drives the
stateful `file_lookup` + `download_found_files` pair through `client._srcfiles` / `client.directory`
(`parrot_tools/o365/sharepoint.py:378-417`) and the Upload tool calls `client.upload_files` (`:535`). Both now go through
the manager's streaming `download_file` and routed `upload_file`. After this task `SharepointClient` is no longer
referenced in the module, so its import is removed (ruff F401).

`download_url` in the Download response becomes the item's `web_url` — the pre-authenticated
`@microsoft.graph.downloadUrl` is never returned or logged (S6, spec §3 M7).

---

## Scope

- Rewrite `DownloadSharePointFileTool._execute_graph_operation` and `UploadSharePointFileTool._execute_graph_operation`.
- Remove `from parrot.interfaces.sharepoint import SharepointClient` once nothing references it.
- Append Download/Upload tests to `test_o365_sharepoint_file_tools.py`.

**NOT in scope**: List/Search (TASK-3761); Delta classes and their imports (byte-identical, FEAT-539).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` | MODIFY | Download + Upload bodies; drop unused import |
| `packages/ai-parrot-tools/tests/test_o365_sharepoint_file_tools.py` | MODIFY | append tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`.

### Verified Imports
```python
from urllib.parse import urlsplit                                     # stdlib
from parrot.interfaces.file.sharepoint import SharePointFileManager   # added by TASK-3761
from parrot_tools.o365.sharepoint import DownloadSharePointFileTool, UploadSharePointFileTool   # tests
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py
class DownloadSharePointFileArgs(O365ToolArgsSchema): site, library="Documents", file_path, local_destination=None, rename_as=None   # :313-322
class DownloadSharePointFileTool(O365Tool):                     # :325 — name "download_sharepoint_file"
    async def _execute_graph_operation(self, client: SharepointClient, **kwargs) -> Dict[str, Any]   # :360-438
        # dest_dir = Path(local_destination) if local_destination else Path.cwd(); dest_dir.mkdir(parents=True, exist_ok=True)
        # returns {"site","library","file_path","local_path","download_url","size"}   (:427-434); FileNotFoundError when missing
class UploadSharePointFileArgs(O365ToolArgsSchema): site, local_file_path, library="Documents", folder_path="", rename_as=None, overwrite=True   # :446-456
class UploadSharePointFileTool(O365Tool):                       # :459 — name "upload_sharepoint_file"
    async def _execute_graph_operation(self, client: SharepointClient, **kwargs) -> Dict[str, Any]   # :495-558
        # FileNotFoundError when the local file is missing (:516-518)
        # returns {"site","library","folder_path","uploaded_file","size","web_url","server_relative_url"}   (:546-553)
# From TASK-3752/3756: SharePointFileManager(site, library, *, credentials, conflict_behavior), adopt_client,
#   download_file(source, Path) -> Path, get_file_metadata(path) -> FileMetadata(url=web_url), upload_file(Path, dest) -> FileMetadata, close()
```

### Does NOT Exist
- ~~`client.file_lookup` / `client.download_found_files` / `client.upload_files` in the new bodies~~ — the stateful
  client protocol is exactly what the refactor removes.
- ~~a `serverRelativeUrl` field on `FileMetadata`~~ — derive it as `urlsplit(web_url).path` (the server-relative URL).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/test_o365_sharepoint_file_tools.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py#DownloadSharePointFileTool._execute_graph_operation",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py#UploadSharePointFileTool._execute_graph_operation"
  ]
}
```

---

## Implementation Notes

- **Download**: `dest_dir` rule unchanged (mkdir via `asyncio.to_thread` is fine but the current sync `mkdir` is
  acceptable too — keep behaviour); `local_path = dest_dir / (rename_as or file_path.rsplit("/", 1)[-1])`;
  `await manager.download_file(file_path, local_path)`; `meta = await manager.get_file_metadata(file_path)`; response
  `local_path` is `str(local_path)`, `download_url` is `meta.url or ""`, `size` from `local_path.stat().st_size`.
  A missing remote file surfaces as `FileNotFoundError` (mapped by the manager).
- **Upload**: keep the local-existence check first; `manager = SharePointFileManager(..., conflict_behavior="replace" if
  overwrite else "fail")`; `dest = f"{folder_path}/{rename_as or local_path.name}".strip("/")`;
  `meta = await manager.upload_file(local_path, dest)`; response `uploaded_file = meta.name`, `size = meta.size`,
  `web_url = meta.url or ""`, `server_relative_url = urlsplit(meta.url).path if meta.url else ""`.
- Same manager lifecycle as TASK-3761 (`adopt_client`, `finally: await manager.close()`).
- Update the method docstrings' "Args: client: …" lines to say `O365Client` (what `_get_client` returns).

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
2. Remove the now-unused `SharepointClient` import (`grep -c SharepointClient` must be 0 afterwards).
3. Append tests.

### `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` (MODIFY) — Download
```python
# occurrences: 1 (verified: grep -c 'class DownloadSharePointFileTool(O365Tool):' parrot_tools/o365/sharepoint.py) — :325
# FILL IN: disambiguate — REPLACE the body of DownloadSharePointFileTool._execute_graph_operation (:360-438):
    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """Download a SharePoint file through SharePointFileManager (streamed to disk)."""
        site = kwargs.get("site")
        library = kwargs.get("library", "Documents")
        file_path = kwargs.get("file_path")
        local_destination = kwargs.get("local_destination")
        rename_as = kwargs.get("rename_as")
        manager = SharePointFileManager(site=site, library=library, credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            # FILL IN: rule in Implementation Notes
            return {"site": site, "library": library, "file_path": file_path, "local_path": str(local_path),
                    "download_url": meta.url or "", "size": local_path.stat().st_size if local_path.exists() else 0}
        except Exception as e:
            self.logger.error(f"Failed to download SharePoint file: {e}")
            raise
        finally:
            await manager.close()
```

### `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` (MODIFY) — Upload + import cleanup
```python
# occurrences: 1 (verified: grep -c 'class UploadSharePointFileTool(O365Tool):' parrot_tools/o365/sharepoint.py) — :459
# FILL IN: disambiguate — REPLACE the body of UploadSharePointFileTool._execute_graph_operation (:495-558):
    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """Upload a local file to SharePoint through SharePointFileManager (single PUT or upload session)."""
        site = kwargs.get("site")
        local_file_path = kwargs.get("local_file_path")
        library = kwargs.get("library", "Documents")
        folder_path = kwargs.get("folder_path", "")
        rename_as = kwargs.get("rename_as")
        overwrite = kwargs.get("overwrite", True)
        local_path = Path(local_file_path)
        if not local_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_file_path}")
        manager = SharePointFileManager(site=site, library=library, credentials=dict(self.credentials or {}),
                                        conflict_behavior="replace" if overwrite else "fail")
        manager.adopt_client(client)
        try:
            # FILL IN: rule in Implementation Notes
            return {"site": site, "library": library, "folder_path": folder_path, "uploaded_file": meta.name,
                    "size": meta.size, "web_url": meta.url or "",
                    "server_relative_url": urlsplit(meta.url).path if meta.url else ""}
        except Exception as e:
            self.logger.error(f"Failed to upload to SharePoint: {e}")
            raise
        finally:
            await manager.close()

# occurrences: 1 (verified: grep -c 'from parrot.interfaces.sharepoint import SharepointClient' parrot_tools/o365/sharepoint.py) — :18
# REPLACE `from parrot.interfaces.sharepoint import SharepointClient` with:
from urllib.parse import urlsplit
```

### `packages/ai-parrot-tools/tests/test_o365_sharepoint_file_tools.py` (MODIFY)
```python
# AFTER — append at end of file
from parrot_tools.o365.sharepoint import DownloadSharePointFileTool, UploadSharePointFileTool

DOWNLOAD_KEYS = {"site", "library", "file_path", "local_path", "download_url", "size"}
UPLOAD_KEYS = {"site", "library", "folder_path", "uploaded_file", "size", "web_url", "server_relative_url"}


async def test_download_sharepoint_file_tool_response_shape(fake, tmp_path):
    # FILL IN: the tool builds its manager internally, so monkeypatch.setattr(SharePointFileManager, "_http_session",
    #          lambda self: session) with session = fakes.FakeAiohttpSession(fake); keys == DOWNLOAD_KEYS;
    #          rename_as honoured; download_url is the web_url (not the _fake/download URL)


async def test_download_missing_file_raises_filenotfound(fake, tmp_path):
    # FILL IN


async def test_upload_sharepoint_file_tool_response_shape_and_overwrite(fake, tmp_path, monkeypatch):
    # FILL IN: keys == UPLOAD_KEYS; overwrite=False -> the session body carries "fail"


def test_sharepoint_client_import_removed():
    import parrot_tools.o365.sharepoint as mod
    assert "SharepointClient" not in vars(mod)
```

### FILL IN checklist
- [ ] Download body; Upload body
- [ ] test bodies (patch `_http_session` at class level with `monkeypatch.setattr`)

---

## Acceptance Criteria

- [ ] Download/Upload keep names, args and exactly the response key sets above (spec AC13).
- [ ] `download_url` is the item `web_url`; no pre-authenticated URL is returned or logged (S6).
- [ ] `overwrite=False` uploads with `conflict_behavior="fail"`.
- [ ] `SharepointClient` no longer imported in the module; `DeltaSharePointFiles*` blocks byte-identical;
      `test_o365_delta_tools.py` passes; `ruff check` clean on the module.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/test_o365_sharepoint_file_tools.py -q`
- `pytest packages/ai-parrot-tools/tests/test_o365_delta_tools.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_download_sharepoint_file_tool_response_shape` | AC13, S6 |
| `test_download_missing_file_raises_filenotfound` | error mapping |
| `test_upload_sharepoint_file_tool_response_shape_and_overwrite` | AC13, conflict |
| `test_sharepoint_client_import_removed` | F401 cleanup |

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
