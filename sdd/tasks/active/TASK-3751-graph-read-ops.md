# TASK-3751: GraphDriveFileManager read ops — paginated listing, list_entries, exists, metadata, find_entries/find_files, delete

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3750
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1** (third of six `graph.py` tasks) and design research **S4** (pagination everywhere) and **S8**
(files-only `list_files` vs folder-aware `list_entries`). These are the operations the O365 List/Search tools
(TASK-3761, TASK-3763) and the toolkit `find` op (TASK-3759) sit on. A single-page `.children.get()` is the bug the
current tools have (`parrot_tools/o365/sharepoint.py:107-121`); every listing here walks `odata_next_link` to the end.

---

## Scope

- Append to `GraphDriveFileManager`: `_drive`, `_get_item`, `_get_item_by_id`, `_iter_children`, `_iter_search`,
  `_query_is_api_safe`, `list_files`, `list_entries`, `exists`, `get_file_metadata`, `find_entries`, `find_files`,
  `delete_file`.

**Task-time addition — `find_entries`.** The O365 Search tools (TASK-3761, TASK-3763) must return each hit's item `id`,
which `FileMetadata` does not carry. So the search/walk logic lives in a public extension `find_entries(keywords,
extension, prefix) -> List[DriveEntry]` (same rules, `DriveEntry` has `id` / `web_url`), and `find_files` is a thin
mapping of its result to `FileMetadata`. Record under "Deviations from spec" (additive extension, like `list_entries`).
- Append the tests of this task to `test_graph_filemanager.py`.

**NOT in scope**: uploads/downloads (3752), copy/links/folders/rename (3753), batch/serving (3754).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/graph.py` | MODIFY | read ops + delete |
| `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` | MODIFY | append read-op tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`, msgraph-sdk 1.63.0.

### Verified Imports
```python
import fnmatch                                           # stdlib
import re                                                # stdlib
from typing import AsyncIterator                         # stdlib
from ._graph_fakes import FakeAPIError, FakeDrive, FakeGraphClient, make_probe, make_sharepoint_client   # tests
```

### Existing Signatures to Use
```python
# msgraph-sdk 1.63 request builders (paths under .venv/lib/python3.12/site-packages/msgraph/generated/)
drives.item.drive_item_request_builder:    def search_with_q(self, q: str) -> SearchWithQRequestBuilder   # :105
                                           def root(self) -> RootRequestBuilder                          # :228
drives.item.items.item.drive_item_item_request_builder:
    async def delete(self, request_configuration=None) -> None     # :65
    def children(self) -> ChildrenRequestBuilder                    # :252
children.children_request_builder:  async def get(...) -> Optional[DriveItemCollectionResponse]   # :50
                                    def with_url(self, raw_url: str) -> ChildrenRequestBuilder      # :120
search_with_q.search_with_q_request_builder:  async def get(...) -> Optional[SearchWithQGetResponse]   # :36
                                              def with_url(self, raw_url: str) -> SearchWithQRequestBuilder   # :68
models.base_collection_pagination_count_response:  odata_next_link: Optional[str]   # :18  (both responses inherit it)

# Existing call pattern being generalised — packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py:105-123
#   client.graph_client.drives.by_drive_id(drive_id).items.by_drive_item_id(f"root:/{folder_path}:").get()
#   ...items.by_drive_item_id(folder_item.id).children.get()      <- single page only (the S4 bug)

# Search-safety rule to replicate — packages/ai-parrot/src/parrot/interfaces/sharepoint.py:867-873
#   return not re.search(r'[*?\[\]\{\}\(\)\^\$|\\]', pattern or "")

# FileManagerInterface (navigator/utils/file/abstract.py) signatures to match EXACTLY:
async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]     # :53
async def delete_file(self, path: str) -> bool                                           # :119
async def exists(self, path: str) -> bool                                                # :130
async def get_file_metadata(self, path: str) -> FileMetadata                             # :141
async def find_files(self, keywords=None, extension=None, prefix=None) -> List[FileMetadata]   # :265 (override)
```

### Does NOT Exist
- ~~`DriveItemCollectionResponse.next_link`~~ — the attribute is `odata_next_link`.
- ~~`OneDriveClient._pattern_is_api_safe`~~ — only `SharepointClient` has it; the base carries its own
  `_query_is_api_safe` so both drive kinds behave the same.
- ~~`parentReference.path` on every search hit~~ — Graph often omits it on `search(q)` results; resolve by id.

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
    "sym:packages/ai-parrot/src/parrot/interfaces/sharepoint.py#SharepointClient._pattern_is_api_safe",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py#ListSharePointFilesTool._execute_graph_operation"
  ]
}
```

---

## Implementation Notes

- **Every public op starts with** `await self._ready()` and resolves the user path with `self._prefixed(path)`.
- **Every SDK call** goes through `await self._retrying(lambda: ..., label="<op>")`; wrap the call in
  `try/except Exception as exc: raise self._map_error(exc, path=path) from exc` at the public-method boundary so no
  kiota `APIError` escapes (spec §7 Errors).
- **Pagination (S4)**: `_iter_children(item_id)` yields `resp.value` items, then while `resp.odata_next_link` is set,
  fetches `children.with_url(resp.odata_next_link).get()`; `_iter_search(q)` does the same on `search_with_q`. The
  next-link is a Graph API URL used through the SDK (authenticated by the SDK) — it is NOT passed to aiohttp, so it
  needs no `_validate_graph_url`.
- **`list_files`** = files only (folders skipped), `fnmatch.fnmatch(name, pattern)`; **`list_entries`** = everything,
  mapped with `_make_entry`. Both build child paths as `f"{parent_full}/{name}"` and pass them as `full_path=` so the
  mapping never needs `parent_reference.path` (S8).
- **`find_entries`** (the logic; `find_files` maps each `DriveEntry` to `FileMetadata(name, path, size, content_type,
  modified_at, url=web_url)`): keyword list = `[keywords]` if str. When the first keyword is non-empty and
  `_query_is_api_safe(keyword)`: stream `_iter_search(keyword)`, resolve each hit's path with `_item_path(item)` or,
  when that is `None`, `_item_path(await self._get_item_by_id(item.id))`; keep files whose path starts with the prefixed
  `prefix` (or `self.prefix`), contain ALL keywords (case-insensitive) and end with `extension`. Otherwise walk the tree
  under the prefixed `prefix` breadth-first with `_iter_children`. Filters apply across all pages (AC20).
- **`delete_file`**: `False` when the item does not exist (404), `True` after `DELETE` (recycle bin, spec §2).
- `exists()` is `True` for folders too (documented, spec §7).

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
1. Add `import fnmatch`, `import re` and `AsyncIterator` to the imports — *why*: listing/search helpers.
2. Append the private helpers, then the public methods, at the end of the class — *why*: 3752+ append after them.
3. Append the tests.

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — imports
```python
# occurrences: 1 (expected after TASK-3750; verify: grep -c '^from typing import Awaitable, Callable, Tuple$' graph.py)
# REPLACE that line with:
import fnmatch
import re
from typing import AsyncIterator, Awaitable, Callable, Tuple
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — helpers (append at end of class)
```python
# occurrences: 1 (expected after TASK-3750; verify: grep -c '    def _validate_graph_url(self, url: str' graph.py)
# AFTER — append at the end of the class body (after `_validate_graph_url`)
    def _drive(self) -> Any:
        """``graph_client.drives.by_drive_id(<resolved drive>)`` request builder."""
        return self.client.graph_client.drives.by_drive_id(self.drive_id)

    async def _get_item(self, full_path: str) -> Any:
        """GET the DriveItem at a prefixed drive path (retried; raw errors propagate to the caller's mapping)."""
        item, _ = await self._retrying(
            lambda: self._drive().items.by_drive_item_id(self._item_ref(full_path)).get(), label="get"
        )
        if item is None:
            raise FileNotFoundError(full_path)
        return item

    async def _get_item_by_id(self, item_id: str) -> Any:
        """GET by stable item id (search hits without a path; the OneDrive download-by-id tool)."""
        # FILL IN: same as _get_item with by_drive_item_id(item_id)

    async def _iter_children(self, item_id: str) -> AsyncIterator[Any]:
        """Yield every child of ``item_id`` across all pages (S4)."""
        builder = self._drive().items.by_drive_item_id(item_id).children
        resp, _ = await self._retrying(lambda: builder.get(), label="children")
        while resp is not None:
            for child in resp.value or []:
                yield child
            nxt = getattr(resp, "odata_next_link", None)
            if not nxt:
                break
            resp, _ = await self._retrying(lambda: builder.with_url(nxt).get(), label="children-next")

    async def _iter_search(self, q: str) -> AsyncIterator[Any]:
        """Yield every ``search(q)`` hit on the drive across all pages (S4)."""
        # FILL IN: same loop over self._drive().search_with_q(q)

    @staticmethod
    def _query_is_api_safe(query: str) -> bool:
        """True when ``query`` has no wildcard/regex metacharacters (rule of sharepoint.py:867-873)."""
        return not re.search(r"[*?\[\]\{\}\(\)\^\$|\\]", query or "")
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — public read ops (append)
```python
# AFTER — append below `_query_is_api_safe` (added by the previous block of this task)
    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]:
        """Non-recursive listing of ``path``: files only, fnmatch ``pattern``, all pages (S4/S8)."""
        await self._ready()
        full = self._prefixed(path)
        try:
            folder = await self._get_item(full)
            out: List[FileMetadata] = []
            async for child in self._iter_children(folder.id):
                # FILL IN: skip folders; fnmatch on child.name; append _make_metadata(child, full_path=...)
                pass
            return out
        except Exception as exc:
            raise self._map_error(exc, path=path) from exc

    async def list_entries(self, path: str = "") -> List[DriveEntry]:
        """Non-recursive listing INCLUDING folders, all pages; used by the O365 List tools (S8)."""
        # FILL IN: same shape as list_files, mapping every child with _make_entry

    async def exists(self, path: str) -> bool:
        """True for files AND folders that resolve; False on 404."""
        # FILL IN

    async def get_file_metadata(self, path: str) -> FileMetadata:
        """Metadata of one item; FileNotFoundError on 404."""
        # FILL IN

    async def find_entries(
        self,
        keywords: Optional[Union[str, List[str]]] = None,
        extension: Optional[str] = None,
        prefix: Optional[str] = None,
    ) -> List[DriveEntry]:
        """Graph search when the keyword is API-safe, else a recursive walk under ``prefix``; files only, all pages (AC20)."""
        # FILL IN: rule in Implementation Notes (entries built with _make_entry(item, full_path=...))

    async def find_files(
        self,
        keywords: Optional[Union[str, List[str]]] = None,
        extension: Optional[str] = None,
        prefix: Optional[str] = None,
    ) -> List[FileMetadata]:
        """FileManagerInterface override (abstract.py:265): ``find_entries`` mapped to FileMetadata."""
        entries = await self.find_entries(keywords=keywords, extension=extension, prefix=prefix)
        return [
            FileMetadata(name=e.name, path=e.path, size=e.size, content_type=e.content_type,
                         modified_at=e.modified_at, url=e.web_url)
            for e in entries
        ]

    async def delete_file(self, path: str) -> bool:
        """DELETE the item (goes to the recycle bin). False when it does not exist."""
        # FILL IN: _get_item -> FileNotFoundError => False; _retrying(delete) => True; map other errors
```
**Why this shape**: `_iter_children` is written out because its next-link loop is the S4 fix and must be identical for
children and search. `list_files` shows the public-boundary pattern (ready → prefixed → try/map) every other public
method in 3751–3754 repeats. Add `Union` to the `typing` import if TASK-3749 did not already import it.

### `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` (MODIFY)
```python
# AFTER — append at end of file
@pytest.fixture
def paged_manager():
    # FILL IN: FakeDrive with reports/ holding 5 files + 1 subfolder; FakeGraphClient(page_size=2); probe with
    #          client_class=SharepointClient, prefix="reports/"; adopt make_sharepoint_client(fake, drive_id="drive-1")


async def test_list_files_follows_next_link(paged_manager):
    # FILL IN: 5 files returned, folder excluded, three "children"/"children-next" calls in fake.calls


async def test_list_files_pattern_excludes_folders(paged_manager):
    # FILL IN: pattern "*.csv"


async def test_list_entries_includes_folders_all_pages(paged_manager):
    # FILL IN: 6 entries, one is_folder


async def test_exists_true_for_folder_and_false_when_missing(paged_manager):
    # FILL IN


async def test_find_files_server_search_vs_recursive_fallback(paged_manager):
    # FILL IN: "q3" -> search_with_q used; "q*" -> no search call, recursive walk; extension + prefix filters


async def test_search_paginates_then_applies_filters(paged_manager):
    # FILL IN: page_size=2 search hits across pages; hits missing parent_reference.path resolved by id


async def test_delete_recycle_bin_and_missing_returns_false(paged_manager):
    # FILL IN


async def test_public_errors_are_mapped(paged_manager):
    # FILL IN: fake.fail_next(500, op="get") -> GraphFileManagerError (not FakeAPIError); 404 -> FileNotFoundError
```

### FILL IN checklist
- [ ] `_get_item_by_id`, `_iter_search`
- [ ] `list_files` loop body, `list_entries`, `exists`, `get_file_metadata`, `find_entries`, `delete_file`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `list_files` (files only), `list_entries` (with folders) and `find_files` follow `odata_next_link` to exhaustion;
      filters apply across all pages (spec AC20).
- [ ] `find_entries` (and `find_files` over it) uses Graph search for API-safe keywords and the recursive walk
      otherwise; hits without a parent path are resolved by id; entries carry `id`.
- [ ] `exists` is True for folders; `delete_file` returns False for a missing item.
- [ ] No kiota/fake API error escapes a public method unmapped (spec §7 Errors).
- [ ] Signatures match `navigator/utils/file/abstract.py` exactly; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_graph_filemanager.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_list_files_follows_next_link` | S4, three pages |
| `test_list_files_pattern_excludes_folders` | files-only + fnmatch |
| `test_list_entries_includes_folders_all_pages` | S8 |
| `test_exists_true_for_folder_and_false_when_missing` | documented semantics |
| `test_find_files_server_search_vs_recursive_fallback` / `test_search_paginates_then_applies_filters` | AC20 |
| `test_delete_recycle_bin_and_missing_returns_false` | delete contract |
| `test_public_errors_are_mapped` | error mapping |

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
