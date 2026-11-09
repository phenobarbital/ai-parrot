# TASK-5403: Add paginated GitToolkit PR file and review-context reads

**Feature**: FEAT-851 - Queued chat commands for the integrations
**Spec**: `sdd/specs/queued-commands-integrations.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implements the scoped FEAT-851 deliverable below. Read spec §§2–7 for the fixed behavior and edge cases. This task creates implementation artifacts only when picked up by sdd-start.

## Scope

- Add ListPRItemsInput and four read-only tool_schema methods as specified in M6.
- Reuse existing _resolve_connection/_request within asyncio.to_thread; perform no synchronous request on the event loop.
- Paginate per_page=100 until a short page or max_items, returning only documented fields with author/type metadata.

**NOT in scope**: files outside the table, new dependencies, external workers, cross-worker cancel/dedup, or changes to strict review semantics beyond the declared registration update.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | Input schema and four thread-offloaded paginated readers |
| `packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py` | MODIFY | Task-owned regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against the current dev source on 2026-11-09. Existing signatures below were re-read with AST and source inspection; MODIFY anchors were re-counted with `grep -cF`. Symbols provided by dependencies are explicitly future contracts, not existing imports.

### Verified Imports

```python
import asyncio
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from .decorators import tool_schema
from parrot_tools.gittoolkit import GitToolkit, GitToolkitError
import pytest
```

Standard-library imports are available; pydantic/pytest and platform SDK imports reuse the declared project stack. New imports are supplied only by this task or its named prerequisites; revalidate them when prerequisites land. Existing source relocation preserves its original import block.

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1117
def _resolve_connection(self, repository: Optional[str]) -> _RepoConnection

# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1286
def _request(method: str, url: str, token: str, *, expected: int, **kwargs: Any) -> requests.Response

# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1834
async def list_pull_requests(self, repository: Optional[str]=None, state: Literal['open', 'closed', 'all']='open', per_page: int=100) -> List[Dict[str, Any]]

# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:402
class ConvertPRToDraftInput(BaseModel)

# packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py:16
def _make_response(status_code: int=200, json_data=None, text: str='', headers=None)

# packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py:32
def _toolkit() -> GitToolkit
```

### Does NOT Exist

- The four list_pull_request_* methods and ListPRItemsInput do not exist yet.
- No fakeredis or new HTTP transport is needed.

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
      "path": "packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit._resolve_connection",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit._request",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit.list_pull_requests",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#ConvertPRToDraftInput",
    "sym:packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py#_make_response",
    "sym:packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py#_toolkit"
  ]
}
```

## Implementation Notes

- Write these tests as synchronous functions driving coroutines with asyncio.run, following this file (the package does not enable asyncio auto mode). The scaffold names above define coverage, not a requirement to change the test runner configuration.
- Returned fields: files filename/status/additions/deletions/changes/patch; comments id/author/author_type/body/created_at/html_url; reviews id/author/author_type/state/body/submitted_at/commit_id; inline id/author/author_type/path/line/body/commit_id/created_at/html_url/in_reply_to_id.

**Parallelism**: Independent: owns packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py, packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py; consumes only existing APIs and changes no shared external state.

## Implementation Blueprint

Planning skeletons only: complete all bounded FILL IN items; never leave placeholders in implementation files. Preserve the spec interface signatures.

### Steps (in order)

1. Verify prerequisites and the exact anchors below — dependent files may have moved since planning.
2. Apply only the declared per-file changes — this bounds ownership and preserves unrelated behavior.
3. Complete the acceptance-criteria branches and regression tests — these pin failure, ownership and compatibility boundaries.
4. Run the task validation and format/lint touched Python files — publish complete working files only.

### `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` (MODIFY)

- Anchor `class ConvertPRToDraftInput(BaseModel):`; occurrences: **1** (`grep -cF`); packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:402.
- Anchor `async def get_pr_checks(`; occurrences: **1** (`grep -cF`); packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:2192.

```python
# BEFORE ConvertPRToDraftInput:
class ListPRItemsInput(BaseModel):
    """Bounded PR context listing arguments."""
    pr_number: int = Field(..., description="Pull request number")
    repository: Optional[str] = Field(None, description="owner/repo; defaults to configured repository")
    max_items: int = Field(300, ge=1, le=1000, description="Stop after this many items")

# Inside GitToolkit, BEFORE get_pr_checks; all existing imports suffice:
@tool_schema(ListPRItemsInput)
async def list_pull_request_files(self, pr_number: int, repository: Optional[str] = None,
                                  max_items: int = 300) -> List[Dict[str, Any]]:
    """List changed files, including patch when supplied by GitHub."""
    # FILL IN: AC1-AC4, delegate sync pagination to asyncio.to_thread.
    raise NotImplementedError
@tool_schema(ListPRItemsInput)
async def list_pull_request_comments(self, pr_number: int, repository: Optional[str] = None,
                                     max_items: int = 300) -> List[Dict[str, Any]]:
    """List issue-style comments with author identity and Bot/User type."""
    # FILL IN: AC1-AC4, issues endpoint.
    raise NotImplementedError
@tool_schema(ListPRItemsInput)
async def list_pull_request_reviews(self, pr_number: int, repository: Optional[str] = None,
                                    max_items: int = 300) -> List[Dict[str, Any]]:
    """List PR review summaries with state and commit identity."""
    # FILL IN: AC1-AC4, reviews endpoint.
    raise NotImplementedError
@tool_schema(ListPRItemsInput)
async def list_pull_request_review_comments(self, pr_number: int, repository: Optional[str] = None,
                                            max_items: int = 300) -> List[Dict[str, Any]]:
    """List inline comments, locations and reply relationships."""
    # FILL IN: AC1-AC4, pulls comments endpoint.
    raise NotImplementedError
```

**Why**: Input schema and four thread-offloaded paginated readers. Add ListPRItemsInput and four read-only tool_schema methods as specified in M6.

### `packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py` (MODIFY)

- Anchor `import asyncio`; occurrences: **1** (`grep -cF`); packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py:8.

```python
# Preserve existing fixtures and tests; append the cases below.
"""Regression coverage for Add paginated GitToolkit PR file and review-context reads."""
import asyncio
import pytest

def test_list_pull_request_files_paginates() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: stub _request, run the coroutine with asyncio.run, assert endpoint/pages/fields per ACs.
    raise NotImplementedError

def test_list_pull_request_comments_shapes_author_type() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: stub _request, run the coroutine with asyncio.run, assert endpoint/pages/fields per ACs.
    raise NotImplementedError

def test_list_pull_request_reviews_and_review_comments() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: stub _request, run the coroutine with asyncio.run, assert endpoint/pages/fields per ACs.
    raise NotImplementedError
```

**Why**: Task-owned regression coverage. Add ListPRItemsInput and four read-only tool_schema methods as specified in M6.

### FILL IN checklist

- [ ] packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py — finish the scoped behavior/test branches above, bounded by AC1–AC4.
- [ ] packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py — finish the scoped behavior/test branches above, bounded by AC1–AC4.

## Acceptance Criteria

- [ ] AC1: All four signatures match M6; max_items defaults to 300, accepts 1..1000 and caps the returned list.
- [ ] AC2: Files use pulls/{n}/files; issue comments use issues/{n}/comments; reviews use pulls/{n}/reviews; inline comments use pulls/{n}/comments.
- [ ] AC3: 100+20 item pages yield 120 records and page=1 then 2; limits, empty pages and absent binary patches work.
- [ ] AC4: Author login/type, reply identifiers and documented timestamps/fields retain their meaning; no new imports/dependencies or write requests.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py -q`

## Test Specification

| Test | Module | Required behavior |
|---|---|---|
| `test_list_pull_request_files_paginates` | M6 | stubbed `_request` returns 100 + 20 items → 120 returned, two GETs with `page` 1 and 2; `max_items` honored |
| `test_list_pull_request_comments_shapes_author_type` | M6 | `user.type == "Bot"` → `author_type == "Bot"` |
| `test_list_pull_request_reviews_and_review_comments` | M6 | field mapping per §3 M6 |

Use deterministic doubles for external systems; no live platform/GitHub/LLM credentials. Add all scoped AC cases, not only the scaffold examples. Store test logs under artifacts/logs/.

## Agent Instructions

1. Implement in the feature worktree provisioned by `$sdd-start TASK-5403`; never implement on dev.
2. Read this task/spec and verify all dependencies in `sdd/tasks/index/queued-commands-integrations.json`.
3. Revalidate source contracts and dependency-created anchors before edits.
4. Implement only declared files, complete all FILL IN items, and run Validation Commands.
5. Commit only scoped implementation files. Use `parrot sdd task finalize` with real TaskCompletionEvidence and implementation HEAD, inspect generated Completion Note/staged state, then commit that state. Do not manually move task files.

## Completion Note

Pending; generated by task finalization with validation and commit evidence.
