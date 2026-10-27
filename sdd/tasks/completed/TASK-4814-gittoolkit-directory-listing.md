# TASK-4814: Add ref-specific GitToolkit directory listing

**Feature**: FEAT-759 — GitHubReviewer SDD Spec Acceptance Criteria
**Spec**: `sdd/specs/github-reviewer-sdd-spec-acceptance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement spec M2: a typed directory-listing tool at an explicit git ref.

## Scope

Implement spec M2: a typed directory-listing tool at an explicit git ref.
- Add RepoDirectoryEntry, RepoDirectoryListing and ListRepoDirectoryInput exactly as specified.
- Add _list_repo_directory_sync and its async @tool_schema wrapper beside the file-content tool.
- Reuse existing connection/auth/_request infrastructure in the synchronous helper; offload I/O from the async wrapper.
- Preserve the existing 404 string-match handling; other GitToolkitError failures propagate to the caller.
- Parse directory arrays, retain file/dir entries, and reject a single-file object as an invalid directory response.
- Export the new public models in __all__; do not alter existing HTTP transport or file-content behavior.
- Add mocked API tests in the existing toolkit PR-context test module.

**NOT in scope**: Jira toolkit changes, `_extract_ticket_key` or `_fetch_ticket` behavior changes,
`_ask_llm_for_review` changes, external review submission during tests, dependency updates, and unrelated refactors.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | Directory models, helper, tool and exports |
| `packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py` | MODIFY | Directory API and schema regressions |

## Codebase Contract (Anti-Hallucination)

Verified at `ddaf44b059ebc2f2699f6750cadbc4141370000f`. Recheck these references after dependencies land; source line numbers
have moved since the spec, but the quoted attachment anchors are still present.

### Verified Imports
```python
import asyncio
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from .decorators import tool_schema
```
Existing toolkit imports at `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:23-43`; the decorator facade re-exports the core decorator.
Tests already import pytest, unittest.mock.patch/MagicMock and GitToolkit at `packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py:9-22`.
Add direct imports of GitToolkitError (existing at `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:46`) and the three models created here.
No new HTTP library imports are required.
### Existing Signatures to Use
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1091`: _resolve_connection(self, repository: Optional[str]) -> _RepoConnection; connection.repository and connection.token().
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1260`: _request(method: str, url: str, token: str, *, expected: int, **kwargs: Any); returns an object exposing json().
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:2362`: _get_file_content_sync; see lines 2401-2418 for URL/ref/auth/404 behavior.
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:2518`: async get_file_content_at_ref(self, path: str, ref: str, repository: Optional[str] = None, start_line: Optional[int] = None, end_line: Optional[int] = None) -> FileContentResult.
- `packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py:31`: git_toolkit_pat fixture; `packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py:51`: _make_response creates offline response objects.
### Does NOT Exist
- list_repo_directory, RepoDirectoryEntry, RepoDirectoryListing and ListRepoDirectoryInput are new.
- GitToolkit.list_directory/list_files/get_tree are not existing alternatives.
- A single-file FileContentResult cannot represent a directory response array.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit._resolve_connection",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit._request",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit._get_file_content_sync",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit.get_file_content_at_ref",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkitError",
    "sym:packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py#git_toolkit_pat",
    "sym:packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py#_make_response"
  ]
}
```

## Implementation Notes

No dependencies: owns gittoolkit.py and test_gittoolkit_pr_context.py; no reviewer files or shared configuration are modified. Can run alongside TASK-4813.

Use strict type hints, Google-style docstrings, existing logging, and black (120 columns).
Keep all network and LLM traffic mocked in tests. Do not add dependencies or new HTTP client imports.
Blueprint FILL IN markers describe planning gaps; remove every marker from completed implementation code.
This task has no Delegation Contract: edge-case implementation and test bodies require the normal executor.

## Implementation Blueprint

### Steps (in order)
1. Add input/output models and exports — because tools must expose a validated schema.
2. Add sync helper beside the existing file reader and async offload wrapper — because the transport must not block the event loop.
3. Mock the existing request boundary for array/404/error tests — because no live GitHub access is required.

### `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` (MODIFY)

Anchor at `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:493`; occurrences: 1 (verified against `ddaf44b05`).
```python
class FileContentResult(BaseModel):
```
Anchor at `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:2599`; occurrences: 1 (verified against `ddaf44b05`).
```python
    def _compare_pr_versions_sync(
```
Anchor at `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:2930`; occurrences: 1 (verified against `ddaf44b05`).
```python
__all__ = [
```
Apply these scoped insertions; retain all surrounding code:
```python
# Insert models before FileContentResult:
class RepoDirectoryEntry(BaseModel):
    """One file or directory in a repository directory listing."""
    name: str
    path: str
    type: Literal["file", "dir"]

class RepoDirectoryListing(BaseModel):
    """Directory listing at an explicitly selected repository ref."""
    exists: bool
    path: str
    ref: str
    repository: str
    entries: List[RepoDirectoryEntry] = Field(default_factory=list)

class ListRepoDirectoryInput(BaseModel):
    """Input for a ref-specific repository directory listing."""
    path: str
    ref: str
    repository: Optional[str] = None

# Insert these methods before _compare_pr_versions_sync within GitToolkit:
def _list_repo_directory_sync(
    self, repository: Optional[str], path: str, ref: str,
) -> "RepoDirectoryListing":
    """Read directory entries; report exists=False on a missing directory."""
    conn = self._resolve_connection(repository)
    repo, token = conn.repository, conn.token()
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    # FILL IN: self._request("GET", url, token, expected=200, params={"ref": ref}).
    # FILL IN: copy _get_file_content_sync's 404 check; propagate other failures.
    # FILL IN: require a list response, map file/dir entries and return typed listing.

@tool_schema(ListRepoDirectoryInput)
async def list_repo_directory(
    self, path: str, ref: str, repository: Optional[str] = None,
) -> "RepoDirectoryListing":
    """List files and subdirectories at path for an explicit git ref."""
    return await asyncio.to_thread(self._list_repo_directory_sync, repository, path, ref)
# Add RepoDirectoryEntry, RepoDirectoryListing, ListRepoDirectoryInput to __all__.
```

**Why**: The Contents API uses an array for directories, so the existing single-file decoder cannot be reused. Reuse the established transport without adding requests imports.

### `packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py` (MODIFY)

Anchor at `packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py:69`; occurrences: 1 (verified against `ddaf44b05`).
```python
class TestPydanticModels:
```
Apply these scoped insertions; retain all surrounding code:
```python
# Append a separate test class; add new models and GitToolkitError to existing imports.
class TestRepoDirectoryListing:
    @pytest.mark.asyncio
    async def test_list_repo_directory_returns_entries(self, git_toolkit_pat: GitToolkit) -> None:
        """Forward the exact ref and repository and return typed file/dir entries."""
        # FILL IN: mock _request, return array, assert URL/token/params and entry fields.
    @pytest.mark.asyncio
    async def test_list_repo_directory_404_is_not_exists(self, git_toolkit_pat: GitToolkit) -> None:
        """A missing directory returns empty entries instead of raising."""
        # FILL IN: raise GitToolkitError with existing 404 message pattern.
    @pytest.mark.asyncio
    async def test_list_repo_directory_errors(self, git_toolkit_pat: GitToolkit) -> None:
        """Non-404 failures propagate and a file response is not a directory."""
        # FILL IN: auth/rate-limit errors, object response, unsupported entry types.
```

**Why**: The existing fixture supplies fake PAT credentials and _make_response; patch the request boundary so all tests remain offline.

### FILL IN checklist
- [ ] Map array responses, retain file/dir records, and define a clear GitToolkitError for non-array responses.
- [ ] Copy the verified 404 branch and test non-404 propagation.
- [ ] Cover default and explicit repositories, ref forwarding, empty lists and input schema/export availability.


## Acceptance Criteria

- [ ] Typed input/output models and decorated tool are discoverable; exports include the three models.
- [ ] Listing forwards repository and ref exactly, returns typed entries, and handles empty arrays.
- [ ] 404 returns exists=False with empty entries and requested path/ref/repository.
- [ ] Non-404 toolkit errors propagate; file-object responses cannot masquerade as directory listings.
- [ ] Async wrapper offloads the existing sync transport; tests make no network calls.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py -q`

## Test Specification

The task-owned regression cases are listed in the blueprint and acceptance criteria.
Extend existing fixtures only as required; preserve existing regression assertions.
Use fake GitHub responses and AsyncMock for asynchronous boundaries. Assert actual
call arguments/counts and public outcomes, not just private implementation details.

## Agent Instructions

1. Run `$sdd-start TASK-4814` to provision the feature worktree; never implement on dev.
2. Read the spec and verify all dependencies are done in `sdd/tasks/index/github-reviewer-sdd-spec-acceptance.json`.
3. Recheck the contract and anchors after dependency changes, then implement only declared files.
4. Run the Validation Commands; save logs under `artifacts/logs/`.
5. Commit scoped code and use `scripts.sdd.finalize_task` with real TaskCompletionEvidence
   and the implementation HEAD to finalize task state. Never manually move this file or use close_task.sh.

## Completion Note

Seat: gpt-5.6-sol · Backend: codex · Attempts: 1. Ref-specific directory listing added to gittoolkit. Merged by engine; 38 tests in test_gittoolkit_pr_context.py pass. Residual lint: 2x ASYNC240 (gittoolkit.py:1687,1755) left for /sdd-done.
