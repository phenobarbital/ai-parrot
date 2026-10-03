# TASK-4052: Project inbox pages to deterministic OKF markdown

**Feature**: FEAT-626 — wikitoolkit inbox autonomous ingestion
**Spec**: `sdd/specs/wikitoolkit-new-ingestion.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4048
**Assigned-to**: unassigned

## Context

Implements spec §3 M6 projection for FEAT-626. Source contracts reverified at `18c22a3fd1af1ccf6692be6f795388189e295a76`.
This is a planning artifact; implementation occurs through `$sdd-start` in the feature worktree.

## Scope

- AC8: Implement the four fixed projection functions. Paths use category_dir and flatten_concept_id_for_filename, under the configured markdown_dir (never the memory backend pages directory).
- Render page_frontmatter(tags=[category,*tags]), then add machine fields exactly as the verified file-store renderer does, then one newline and body. Do not mutate tags by string replacement.
- Write markdown and index through sibling temporary files and os.replace, remove failed temporary artifacts, sort index entries deterministically, and include only inbox doc pages provided by the caller. Call synchronous writer functions via asyncio.to_thread from async callers.

**NOT in scope**: unrelated refactors, dependency changes, provider SDK calls, MCP implementation, or changes outside the declared files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/projection.py` | CREATE | Scoped M6 projection deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_projection.py` | CREATE | Focused tests/fixtures |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.okf.utils import flatten_concept_id_for_filename
```
Verified: packages/ai-parrot/src/parrot/knowledge/okf/utils.py:18.

```python
from parrot.knowledge.wiki.export import category_dir, generate_index, page_frontmatter
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/export.py:76; packages/ai-parrot/src/parrot/knowledge/wiki/export.py:109; packages/ai-parrot/src/parrot/knowledge/wiki/export.py:86.

```python
from parrot.knowledge.wiki.inbox.projection import render_doc_markdown, write_doc_markdown, write_inbox_index
```
Verified: planned in TASK-4052: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/projection.py#render_doc_markdown; planned in TASK-4052: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/projection.py#write_doc_markdown; planned in TASK-4052: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/projection.py#write_inbox_index.

```python
from pathlib import Path
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from typing import Any
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import os
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import pytest
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import tempfile
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import yaml
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).


### Existing Signatures to Use

`sym:packages/ai-parrot/src/parrot/knowledge/okf/utils.py#flatten_concept_id_for_filename`

```python
# packages/ai-parrot/src/parrot/knowledge/okf/utils.py:18
def flatten_concept_id_for_filename(concept_id: str) -> str:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/export.py#category_dir`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/export.py:76
def category_dir(category: str) -> str:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/export.py#generate_index`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/export.py:109
def generate_index(wiki_name: str, entries: list[tuple[str, str, str]]) -> str:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/export.py#page_frontmatter`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/export.py:86
def page_frontmatter(
    page: dict[str, Any],
    relates_to: list[dict[str, str]],
) -> str:
```


### Does NOT Exist

- No public file-store rendering API exists; mirror the verified rendering format, not a private import.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/projection.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_projection.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/okf/utils.py#flatten_concept_id_for_filename",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/export.py#category_dir",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/export.py#generate_index",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/export.py#page_frontmatter"
  ]
}
```

## Implementation Notes

Consumes the page_frontmatter(tags=...) extension from TASK-4048.

Follow Python 120-column black formatting, strict annotations and Google-style docstrings. Keep I/O off the event loop. Merge imports into the existing import groups; do not duplicate them. All FILL IN markers are planning-only and must be removed from completed implementation.

## Implementation Blueprint

### Steps (in order)

1. Reverify the quoted contracts and dependency outputs before editing — because concurrently landing features may move anchors.
2. Apply the declared per-file blocks and complete only the bounded gaps in Scope — because public signatures and ownership are fixed.
3. Implement the named failure-path tests using temporary resources and fake model responses — because success-only coverage misses the lifecycle guarantees.
4. Run the exact Validation Commands and lint touched Python files — because unchanged defaults and failure behavior are the acceptance evidence.

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/projection.py` (CREATE)

```python
"""Write-only deterministic OKF projection of inbox document pages."""
import os
import tempfile
from pathlib import Path
from typing import Any
import yaml
from parrot.knowledge.wiki.export import category_dir, generate_index, page_frontmatter
from parrot.knowledge.okf.utils import flatten_concept_id_for_filename

def doc_markdown_path(markdown_dir: Path, page: dict[str, Any]) -> Path:
    """Resolve the category directory and flattened concept filename."""
    return markdown_dir / category_dir(str(page.get("category") or "concept")) / (
        f"{flatten_concept_id_for_filename(page['concept_id'])}.md"
    )

def render_doc_markdown(page: dict[str, Any], relates_to: list[dict[str, str]], tags: list[str]) -> str:
    """Render frontmatter, machine fields and body without modifying the input."""
    # FILL IN: AC8 deterministic projection, mirroring file_store._render_page_file.
    raise NotImplementedError

def write_doc_markdown(markdown_dir: Path, page: dict[str, Any],
                       relates_to: list[dict[str, str]], tags: list[str]) -> Path:
    """Atomically replace one markdown projection; synchronous by design."""
    # FILL IN: sibling temp + os.replace, cleanup on failure; return destination (AC8).
    raise NotImplementedError

def write_inbox_index(markdown_dir: Path, store_pages: list[dict[str, Any]]) -> Path:
    """Atomically regenerate index.md from the supplied inbox doc pages."""
    # FILL IN: sorted entries, generate_index and atomic write (AC8).
    raise NotImplementedError
```

**Why**: The store remains retrieval truth; projection failures propagate so the processor leaves originals in place.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/test_projection.py` (CREATE)

```python
"""Focused FEAT-626 regression and failure-path tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.inbox.projection import render_doc_markdown, write_doc_markdown, write_inbox_index


def test_render_doc_markdown_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Equal page input yields identical output and ordered custom tags."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_write_doc_markdown_atomic_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Check category/flat-id path and absence of temporary files."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_projection_write_failure_preserves_previous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject replacement failure and retain existing output without temp leaks."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_index_is_sorted_and_contains_only_inbox_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify sorted relative links to supplied document pages."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError
```

**Why**: Use temporary files and stub adapters; assert observable state and side effects, never call providers.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/projection.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_projection.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.

## Acceptance Criteria

- [ ] AC8: Implement the four fixed projection functions. Paths use category_dir and flatten_concept_id_for_filename, under the configured markdown_dir (never the memory backend pages directory).
- [ ] Render page_frontmatter(tags=[category,*tags]), then add machine fields exactly as the verified file-store renderer does, then one newline and body. Do not mutate tags by string replacement.
- [ ] Write markdown and index through sibling temporary files and os.replace, remove failed temporary artifacts, sort index entries deterministically, and include only inbox doc pages provided by the caller. Call synchronous writer functions via asyncio.to_thread from async callers.
- [ ] All declared tests pass; no unfinished implementation placeholders remain; touched Python files pass ruff check.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_projection.py -q`

Run in the activated repository environment; in a feature worktree set `PYTHONPATH=packages/ai-parrot/src`. Store test logs under `artifacts/logs/`.

## Test Specification

- Use fixed timestamps and content hashes in page dicts; compare bytes across repeated renders.
- Monkeypatch os.replace for failure; verify no partial replacement and that failure propagates.

## Agent Instructions

1. Use `$sdd-start TASK-4052`; let it provision the feature worktree. Do not implement on dev.
2. Read the spec and this task; verify dependencies are done in `sdd/tasks/index/wikitoolkit-new-ingestion.json`.
3. Reverify source contracts before writing. Record discovered drift and refresh this task before relying on a changed API.
4. Implement only declared files. Run the focused validation commands and the normal lint gate.
5. Commit scoped implementation and finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move task files or use legacy close_task.sh.

## Completion Note

Pending. Populated by the finalizer from implementation and validation evidence.
