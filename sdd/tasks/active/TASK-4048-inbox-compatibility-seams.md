# TASK-4048: Add duplicate bypass and frontmatter tag compatibility seams

**Feature**: FEAT-626 — wikitoolkit inbox autonomous ingestion
**Spec**: `sdd/specs/wikitoolkit-new-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implements spec §3 M10 for FEAT-626. Source contracts reverified at `18c22a3fd1af1ccf6692be6f795388189e295a76`.
This is a planning artifact; implementation occurs through `$sdd-start` in the feature worktree.

## Scope

- AC19: Add keyword-only skip_duplicate_check=False to triage and _heuristic_reject; forward it and guard only the same-URI and other-URI duplicate branches.
- AC2: Keep size, suffix, sensitivity, novelty and both model stages unchanged. Default output and behavior must match existing fixtures.
- AC8: Add tags: Sequence[str] | None = None to page_frontmatter. None preserves current bytes; explicit values are deduped in input order, including an explicitly empty list. Keep the spec signature positional-compatible.

**NOT in scope**: unrelated refactors, dependency changes, provider SDK calls, MCP implementation, or changes outside the declared files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py` | MODIFY | Scoped M10 deliverable |
| `packages/ai-parrot/src/parrot/knowledge/wiki/export.py` | MODIFY | Scoped M10 deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_compatibility.py` | CREATE | Focused tests/fixtures |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from collections.abc import Sequence
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from parrot.knowledge.wiki.export import page_frontmatter
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/export.py:86.

```python
from parrot.knowledge.wiki.review import ManifestDocEntry
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/review.py:135.

```python
from parrot.knowledge.wiki.triage import IngestTriageRouter
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/triage.py:252.

```python
from pathlib import Path
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from typing import Any
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import pytest
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).


### Existing Signatures to Use

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/export.py#page_frontmatter`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/export.py:86
def page_frontmatter(
    page: dict[str, Any],
    relates_to: list[dict[str, str]],
) -> str:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/review.py#ManifestDocEntry`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/review.py:135
class ManifestDocEntry(BaseModel):
    kind: Literal['doc'] = 'doc'
    source_uri: str
    file_hash: str
    briefing: str
    scores: DimensionScores
    composite: float = Field(ge=0.0, le=1.0)
    proposed_action: Literal['admit', 'archive', 'discard']
    claims: list[Claim] = Field(default_factory=list)
    decision: Literal['admit', 'archive', 'discard'] | None = None
    decision_source: Literal['heuristic', 'model', 'human', 'auto'] | None = None
    audit_sample: bool = False
    audit_stratum: str | None = None
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/triage.py#IngestTriageRouter`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/triage.py:252
class IngestTriageRouter:

    def __init__(
        self,
        charter: Charter,
        adapter: PageIndexLLMAdapter,
        sources: SourceCollectionManager,
        novelty_scorer: NoveltyScorer,
        *,
        heavy_adapter: PageIndexLLMAdapter | None = None,
        max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
        allowed_suffixes: frozenset[str] | None = None,
    ) -> None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/triage.py#IngestTriageRouter._heuristic_reject`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/triage.py:367
    def _heuristic_reject(
        self, path: Path, content: str, file_hash: str
    ) -> ManifestDocEntry | None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/triage.py#IngestTriageRouter.triage`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/triage.py:304
    async def triage(self, path: Path, content: str) -> ManifestDocEntry:
```


### Does NOT Exist

- triage(force=...) does not exist; this task adds skip_duplicate_check instead.
- page_frontmatter(tags=...) does not exist until this task.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/triage.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/export.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_compatibility.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/export.py#page_frontmatter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/review.py#ManifestDocEntry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/triage.py#IngestTriageRouter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/triage.py#IngestTriageRouter._heuristic_reject",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/triage.py#IngestTriageRouter.triage"
  ]
}
```

## Implementation Notes

Independent M10 deliverable; owns packages/ai-parrot/src/parrot/knowledge/wiki/triage.py, packages/ai-parrot/src/parrot/knowledge/wiki/export.py. No prerequisite-created symbol is consumed.

Follow Python 120-column black formatting, strict annotations and Google-style docstrings. Keep I/O off the event loop. Merge imports into the existing import groups; do not duplicate them. All FILL IN markers are planning-only and must be removed from completed implementation.

## Implementation Blueprint

### Steps (in order)

1. Reverify the quoted contracts and dependency outputs before editing — because concurrently landing features may move anchors.
2. Apply the declared per-file blocks and complete only the bounded gaps in Scope — because public signatures and ownership are fixed.
3. Implement the named failure-path tests using temporary resources and fake model responses — because success-only coverage misses the lifecycle guarantees.
4. Run the exact Validation Commands and lint touched Python files — because unchanged defaults and failure behavior are the acceptance evidence.

### `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py` (MODIFY)

Verified attachment points (literal `grep -F -c` counts):

- `    async def triage(self, path: Path, content: str) -> ManifestDocEntry:` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py:304`.
- `        heuristic_entry = self._heuristic_reject(path, content, file_hash)` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py:318`.
- `    def _heuristic_reject(` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py:367`.
```python
# MODIFY signatures and forwarding at the verified anchors; preserve other branches.
from pathlib import Path
from parrot.knowledge.wiki.review import ManifestDocEntry

# Inside IngestTriageRouter:
async def triage(self, path: Path, content: str, *, skip_duplicate_check: bool = False) -> ManifestDocEntry:
    """Run the existing cascade, optionally bypassing only duplicate checks."""
    # FILL IN: retain existing body; forward skip_duplicate_check to _heuristic_reject.
    raise NotImplementedError

def _heuristic_reject(self, path: Path, content: str, file_hash: str, *,
                      skip_duplicate_check: bool = False) -> ManifestDocEntry | None:
    """Apply size/suffix checks and, by default, both duplicate checks."""
    # FILL IN: preserve size/suffix guards; wrap both duplicate branches in `if not skip_duplicate_check`.
    raise NotImplementedError
```

**Why**: The bypass belongs below the CLI because skipping the entire triage cascade would bypass policy.

### `packages/ai-parrot/src/parrot/knowledge/wiki/export.py` (MODIFY)

Verified attachment points (literal `grep -F -c` counts):

- `def page_frontmatter(` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/export.py:86`.
```python
# MODIFY the existing function and imports; retain YAML keys, ordering and formatting.
from collections.abc import Sequence
from typing import Any

def page_frontmatter(page: dict[str, Any], relates_to: list[dict[str, str]],
                     tags: Sequence[str] | None = None) -> str:
    """Render stable OKF frontmatter with optional caller-supplied tags."""
    # FILL IN: retain body and replace only data['tags'] with the expression below.
    # list(dict.fromkeys(tags)) if tags is not None else [str(page.get("category") or "concept")]
    raise NotImplementedError
```

**Why**: An additive argument keeps old exporters byte-compatible and avoids tag string surgery.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/test_compatibility.py` (CREATE)

```python
"""Focused FEAT-626 regression and failure-path tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.export import page_frontmatter
from parrot.knowledge.wiki.triage import IngestTriageRouter


def test_force_skips_only_duplicate_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass both duplicate cases but preserve size, suffix and sensitivity rejection."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_force_retains_llm_stages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both model tiers and novelty remain available after duplicate bypass."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_page_frontmatter_tags_param(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default bytes remain identical; explicit tags dedupe in order and empty stays empty."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError
```

**Why**: Use temporary files and stub adapters; assert observable state and side effects, never call providers.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/export.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_compatibility.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.

## Acceptance Criteria

- [ ] AC19: Add keyword-only skip_duplicate_check=False to triage and _heuristic_reject; forward it and guard only the same-URI and other-URI duplicate branches.
- [ ] AC2: Keep size, suffix, sensitivity, novelty and both model stages unchanged. Default output and behavior must match existing fixtures.
- [ ] AC8: Add tags: Sequence[str] | None = None to page_frontmatter. None preserves current bytes; explicit values are deduped in input order, including an explicitly empty list. Keep the spec signature positional-compatible.
- [ ] All declared tests pass; no unfinished implementation placeholders remain; touched Python files pass ruff check.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_compatibility.py -q`
- `pytest tests/knowledge/wiki/test_triage.py -q`
- `pytest tests/knowledge/wiki/test_export.py -q`
- `pytest tests/knowledge/wiki/test_file_store.py -q`

Run in the activated repository environment; in a feature worktree set `PYTHONPATH=packages/ai-parrot/src`. Store test logs under `artifacts/logs/`.

## Test Specification

- Use adapter call spies and source fakes for both duplicate branches; assert oversized and disallowed suffix inputs make no model calls.
- Compare default rendered output to fixed pre-change text and load explicit tags to verify order.

## Agent Instructions

1. Use `$sdd-start TASK-4048`; let it provision the feature worktree. Do not implement on dev.
2. Read the spec and this task; verify dependencies are done in `sdd/tasks/index/wikitoolkit-new-ingestion.json`.
3. Reverify source contracts before writing. Record discovered drift and refresh this task before relying on a changed API.
4. Implement only declared files. Run the focused validation commands and the normal lint gate.
5. Commit scoped implementation and finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move task files or use legacy close_task.sh.

## Completion Note

Pending. Populated by the finalizer from implementation and validation evidence.
