# TASK-3766: Docs — Graph FileManager guide + Office 365 permissions for the managers

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3754, TASK-3760
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 9** (docs half), AC16 and AC22 (the serving limit must be documented). Written after the base
(TASK-3754) and the agent-facing operations (TASK-3760) exist, so every name the guide shows is real. A small test keeps
the guide from silently losing the sections other readers rely on.

---

## Scope

- Create `docs/interfaces/graph-filemanager.md` (the `docs/interfaces/` directory does not exist yet).
- Add a "File managers (SharePoint / OneDrive)" section to `docs/integrations/office365-oauth2.md`, directly before
  `## Azure AD app registration`, listing the permissions the managers need.
- Create `packages/ai-parrot/tests/test_graph_filemanager_docs.py`.

**NOT in scope**: README / CHANGELOG edits; docs for the O365 toolkits beyond one pointer line.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/interfaces/graph-filemanager.md` | CREATE | user guide |
| `docs/integrations/office365-oauth2.md` | MODIFY | permissions for the managers |
| `packages/ai-parrot/tests/test_graph_filemanager_docs.py` | CREATE | section-presence test |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`.

### Verified Imports
```python
from pathlib import Path   # the docs test only reads files
```

### Existing Signatures to Use
```text
docs/integrations/office365-oauth2.md sections: "## Architecture summary" :13, "## Required delegated scopes" :39,
  "## Azure AD app registration" :63, "## Environment variables" :87, ... "## See also" :179
  The delegated-scope table already lists Files.Read / Files.ReadWrite / Sites.Read.All and mentions
  Sites.ReadWrite.All as optional.
Public API to document (all created by FEAT-603 tasks):
  SharePointFileManager(site, library="Documents", *, tenant=None, prefix="", credentials=None, auth_mode="direct",
      user_assertion=None, scopes=None, conflict_behavior="replace", link_type="view", link_scope="organization",
      max_concurrency=None, max_retries=None, chunk_size=None, small_file_threshold=None)
  OneDriveFileManager(user="me", **same kwargs)
  connect() / close() / async with; adopt_client(client)
  list_files / list_entries / find_files / find_entries / exists / get_file_metadata / upload_file / create_file /
  create_from_bytes / upload_file_from_bytes / download_file / copy_file / delete_file / create_folder / remove_folder /
  rename_file / rename_folder / get_file_url / create_sharing_link / upload_files / download_files / setup / handle_file
  BatchItemResult / BatchSummary (parrot.interfaces.file.batch), DriveEntry, GraphFileManagerError
  FileManagerFactory.create("sharepoint" | "onedrive", ...); FileManagerToolkit(manager_type="sharepoint", ...)
      -> fs_* tools incl. fs_find_files / fs_batch_upload / fs_batch_download
  pip install "ai-parrot[msgraph]" (TASK-3765)
Env configuration: SHAREPOINT_APP_ID / SHAREPOINT_APP_SECRET / SHAREPOINT_TENANT_ID / SHAREPOINT_TENANT_NAME
  (parrot/conf.py:612-615) for SharePoint defaults; O365_CLIENT_ID / O365_CLIENT_SECRET / O365_TENANT_ID (:598-600) for OneDrive
```

### Does NOT Exist
- ~~`docs/interfaces/`~~ — created by this task.
- ~~streaming serving~~ — `setup()` serves through a buffering extension with a 64 MiB default cap (spec §8 Q4 open);
  never describe it as streaming.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/interfaces/graph-filemanager.md", "action": "CREATE"},
    {"path": "docs/integrations/office365-oauth2.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_graph_filemanager_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

The guide's required sections (the test asserts these headings): `## Install`, `## Quick start`, `## Authentication`,
`## Paths`, `## Uploads and downloads`, `## Sharing links`, `## Batch operations`, `## Search`, `## Serving over HTTP`,
`## Agents (FileManagerToolkit)`, `## Permissions`, `## Live tests`. Content rules:
- **Authentication**: the four `auth_mode` values + username/password credentials; `adopt_client` for callers that
  already hold an authenticated client (the O365 tools do this); `"me"` needs delegated auth.
- **Paths**: drive-relative, `prefix` like S3, `site="parent/sub"` for sub-sites, `"Shared Documents"` alias, `..`
  rejected.
- **Uploads**: threshold routing; `conflict_behavior` (`replace` default; `fail` / `rename` always use an upload
  session); MIME type is derived from the file name (`content_type` is not sent).
- **Sharing links**: `get_file_url` = organization/view link; `create_sharing_link` options; expiry fallback; it creates a
  sharing permission on the item.
- **Batch**: per-item `state` (`succeeded` / `failed` / `skipped`), no exception per item, auth failure skips the rest,
  a stream object may not appear twice, concurrency/retry defaults (5 / 3; 429/503/504, `Retry-After` capped at 60 s).
- **Serving**: `setup(app, route)` buffers whole files in memory; files above `serving_max_bytes` (64 MiB default) get
  HTTP 413.
- **Permissions**: application `Files.ReadWrite.All` (OneDrive of any user, app-only), `Sites.ReadWrite.All` (SharePoint
  writes); delegated `Files.ReadWrite` / `Sites.ReadWrite.All`.
- **Live tests**: the four `PARROT_LIVE_*` knobs and the command from spec §4 (TASK-3767).

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
1. Write the guide with the twelve headings — *why*: the test and readers depend on them.
2. Add the permissions section to the O365 doc.
3. Write the test.

### `docs/interfaces/graph-filemanager.md` (CREATE)
```markdown
# SharePoint & OneDrive file managers

`SharePointFileManager` and `OneDriveFileManager` implement navigator's `FileManagerInterface` over Microsoft Graph, so
anything that works with `S3FileManager` works with a SharePoint document library or a OneDrive (FEAT-603).

## Install

    pip install "ai-parrot[msgraph]"

## Quick start
<!-- FILL IN: SharePoint and OneDrive examples: construct, `async with`, list_files, upload_file, get_file_url -->

## Authentication
<!-- FILL IN: per Implementation Notes -->

## Paths
<!-- FILL IN -->

## Uploads and downloads
<!-- FILL IN -->

## Sharing links
<!-- FILL IN -->

## Batch operations
<!-- FILL IN -->

## Search
<!-- FILL IN: find_files / find_entries; server-side search vs recursive walk; all result pages are read -->

## Serving over HTTP
<!-- FILL IN: buffered, 64 MiB default cap, HTTP 413 -->

## Agents (FileManagerToolkit)
<!-- FILL IN: FileManagerToolkit(manager_type="sharepoint", site=..., library=...); fs_find_files / fs_batch_*;
     pointer to the SharePointToolkit / OneDriveToolkit tools, which now run on these managers -->

## Permissions
<!-- FILL IN -->

## Live tests
<!-- FILL IN -->
```

### `docs/integrations/office365-oauth2.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## Azure AD app registration$' docs/integrations/office365-oauth2.md) — :63 -->
<!-- BEFORE — insert above `## Azure AD app registration` -->
## File managers (SharePoint / OneDrive)

`SharePointFileManager` / `OneDriveFileManager` (see `docs/interfaces/graph-filemanager.md`) need:

| Mode | Permission | Why |
|---|---|---|
| Application (app-only) | `Sites.ReadWrite.All` | read/write SharePoint document libraries |
| Application (app-only) | `Files.ReadWrite.All` | read/write any user's OneDrive (`user="<upn>"`) |
| Delegated | `Files.ReadWrite` | the signed-in user's OneDrive (`user="me"`) |
| Delegated | `Sites.ReadWrite.All` | SharePoint libraries the user can write to |

Application permissions require admin consent.

```

### `packages/ai-parrot/tests/test_graph_filemanager_docs.py` (CREATE)
```python
"""FEAT-603 TASK-3766 — the Graph file-manager guide keeps its required sections."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUIDE = ROOT / "docs" / "interfaces" / "graph-filemanager.md"
O365 = ROOT / "docs" / "integrations" / "office365-oauth2.md"
HEADINGS = ["## Install", "## Quick start", "## Authentication", "## Paths", "## Uploads and downloads",
            "## Sharing links", "## Batch operations", "## Search", "## Serving over HTTP",
            "## Agents (FileManagerToolkit)", "## Permissions", "## Live tests"]


def test_guide_has_required_sections():
    text = GUIDE.read_text(encoding="utf-8")
    missing = [h for h in HEADINGS if f"\n{h}\n" not in f"\n{text}\n"]
    assert not missing, missing


def test_guide_documents_serving_limit_and_extra():
    text = GUIDE.read_text(encoding="utf-8")
    assert "413" in text and "64 MiB" in text and "ai-parrot[msgraph]" in text
    serving = text.split("## Serving over HTTP", 1)[1].split("\n## ", 1)[0].lower()
    assert "buffer" in serving   # the section must say the extension buffers whole files (S7)


def test_o365_doc_lists_manager_permissions():
    text = O365.read_text(encoding="utf-8")
    assert "## File managers (SharePoint / OneDrive)" in text and "Files.ReadWrite.All" in text
```

### FILL IN checklist
- [ ] every guide section per Implementation Notes (no `FILL IN` comments left in the published doc)

---

## Acceptance Criteria

- [ ] `docs/interfaces/graph-filemanager.md` exists with the twelve headings and documents the 64 MiB / HTTP 413 serving
      limit without calling it streaming (spec AC16, AC22).
- [ ] `docs/integrations/office365-oauth2.md` lists the manager permissions (spec AC16).
- [ ] No HTML `FILL IN` comments remain in either doc.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_graph_filemanager_docs.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_guide_has_required_sections` | AC16 |
| `test_guide_documents_serving_limit_and_extra` | AC22 wording |
| `test_o365_doc_lists_manager_permissions` | AC16 |

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
