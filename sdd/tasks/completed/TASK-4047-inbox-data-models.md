# TASK-4047: Define inbox data and result models

**Feature**: FEAT-626 — wikitoolkit inbox autonomous ingestion
**Spec**: `sdd/specs/wikitoolkit-new-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implements spec §3 M3 models for FEAT-626. Source contracts reverified at `18c22a3fd1af1ccf6692be6f795388189e295a76`.
This is a planning artifact; implementation occurs through `$sdd-start` in the feature worktree.

## Scope

- Create the inbox package with the exact M3 classification/link/archive/document/run report fields. Use fresh default_factory lists and dicts and explicit optional defaults for partial/skipped/failed rows.
- Use an explicit Literal union for the five relations (Literal[RELATIONS] in the spec is explanatory, not valid typing). Keep RELATIONS as the matching tuple.
- InboxRunReport.failed is true exactly when a document has status failed. The final package __init__ is created with the processor; model imports work through the namespace during earlier tasks.

**NOT in scope**: unrelated refactors, dependency changes, provider SDK calls, MCP implementation, or changes outside the declared files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py` | CREATE | Scoped M3 models deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_models.py` | CREATE | Focused tests/fixtures |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.inbox.models import InboxDocResult, InboxRunReport, LinkChoice
```
Verified: planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#InboxDocResult; planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#InboxRunReport; planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#LinkChoice.

```python
from pathlib import Path
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from pydantic import BaseModel, Field
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from typing import Literal
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import pytest
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).


### Existing Signatures to Use

No existing repository symbols are imported by this task. Pydantic v2, pytest and standard-library contracts apply.

### Does NOT Exist

- No inbox models exist yet; Literal[RELATIONS] is not a supported replacement for an explicit string Literal union.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_models.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

Independent M3 models deliverable; owns packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py. No prerequisite-created symbol is consumed.

Follow Python 120-column black formatting, strict annotations and Google-style docstrings. Keep I/O off the event loop. Merge imports into the existing import groups; do not duplicate them. All FILL IN markers are planning-only and must be removed from completed implementation.

## Implementation Blueprint

### Steps (in order)

1. Reverify the quoted contracts and dependency outputs before editing — because concurrently landing features may move anchors.
2. Apply the declared per-file blocks and complete only the bounded gaps in Scope — because public signatures and ownership are fixed.
3. Implement the named failure-path tests using temporary resources and fake model responses — because success-only coverage misses the lifecycle guarantees.
4. Run the exact Validation Commands and lint touched Python files — because unchanged defaults and failure behavior are the acceptance evidence.

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py` (CREATE)

```python
"""Validated classification, link and run-report contracts."""
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field
RELATIONS = ("references", "relates_to", "mentions", "follows_up", "supersedes")
class InboxClassification(BaseModel):
    """Structured classification response from the model."""
    kind: str
    title: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    event_date: str | None = None
class ResolvedClassification(BaseModel):
    """Taxonomy-validated classification used by writers."""
    kind: str
    category: str
    title: str
    summary: str
    tags: list[str]
    entities: list[str]
    event_date: str | None
    classification_source: Literal["model", "fallback"]
class LinkCandidate(BaseModel):
    """Verified candidate with its retrieval origin."""
    page_id: str
    title: str
    category: str
    summary: str
    origin: Literal["search", "tag_fts", "verbatim"]
class LinkChoice(BaseModel):
    """One relation proposed by the model."""
    page_id: str
    rel: Literal["references", "relates_to", "mentions", "follows_up", "supersedes"]
    why: str
class LinkSelection(BaseModel):
    """Structured model selection from the candidate set."""
    links: list[LinkChoice] = Field(default_factory=list)
class VerifiedLink(BaseModel):
    """A store-verified outgoing relation."""
    page_id: str
    rel: str
    why: str
    title: str
class ArchiveResult(BaseModel):
    """Result of moving an original and optionally staging its deletion."""
    source: Path
    destination: Path
    rejected: bool
    staged_git: bool
class InboxDocResult(BaseModel):
    """Outcome of processing one original."""
    source_uri: str
    status: Literal["admitted", "archived_category", "rejected", "skipped", "failed", "dry_run"]
    decision: str | None = None
    composite: float | None = None
    decision_source: str | None = None
    kind: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    links: list[VerifiedLink] = Field(default_factory=list)
    doc_page_id: str | None = None
    markdown_path: str | None = None
    archived_to: str | None = None
    adr_candidate_id: str | None = None
    adr_candidate_reused: bool = False
    fireflies_match: str | None = None
    verified: bool = False
    error: str | None = None
```

Continuation of the same file (append directly; no second file):

```python
class InboxRunReport(BaseModel):
    """Deterministic command result with per-document outcomes."""
    inbox_dir: str
    charter_version: str
    charter_fingerprint: str
    models: dict[str, str]
    dry_run: bool
    counts: dict[str, int]
    documents: list[InboxDocResult]
    @property
    def failed(self) -> bool:
        """Whether any document failed."""
        return any(document.status == "failed" for document in self.documents)
```

**Why**: Keep the structured outputs separate from resolved outputs; malformed model values must not become trusted classifications.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/test_models.py` (CREATE)

```python
"""Focused FEAT-626 regression and failure-path tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.inbox.models import InboxDocResult, InboxRunReport, LinkChoice


def test_relation_and_status_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject unknown relations/statuses while allowing every declared value."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_report_failed_and_json_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover all statuses, failed aggregation and Path JSON serialization."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_mutable_defaults_are_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure rows and selections never share mutable defaults."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError
```

**Why**: Use temporary files and stub adapters; assert observable state and side effects, never call providers.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_models.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.

## Acceptance Criteria

- [ ] Create the inbox package with the exact M3 classification/link/archive/document/run report fields. Use fresh default_factory lists and dicts and explicit optional defaults for partial/skipped/failed rows.
- [ ] Use an explicit Literal union for the five relations (Literal[RELATIONS] in the spec is explanatory, not valid typing). Keep RELATIONS as the matching tuple.
- [ ] InboxRunReport.failed is true exactly when a document has status failed. The final package __init__ is created with the processor; model imports work through the namespace during earlier tasks.
- [ ] All declared tests pass; no unfinished implementation placeholders remain; touched Python files pass ruff check.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_models.py -q`

Run in the activated repository environment; in a feature worktree set `PYTHONPATH=packages/ai-parrot/src`. Store test logs under `artifacts/logs/`.

## Test Specification

- Validate all six document statuses and all five relations. Verify skipped/failed partial rows can be serialized.
- Roundtrip model_dump_json/model_validate_json and verify failed is derived without changing stored counts.

## Agent Instructions

1. Use `$sdd-start TASK-4047`; let it provision the feature worktree. Do not implement on dev.
2. Read the spec and this task; verify dependencies are done in `sdd/tasks/index/wikitoolkit-new-ingestion.json`.
3. Reverify source contracts before writing. Record discovered drift and refresh this task before relying on a changed API.
4. Implement only declared files. Run the focused validation commands and the normal lint gate.
5. Commit scoped implementation and finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move task files or use legacy close_task.sh.

## Completion Note

Pending. Populated by the finalizer from implementation and validation evidence.


### Completion Note (orchestrator)
Seat: gpt-5.6-terra (codex). Merged cleanly. Merge-tier validation: only the 2 pre-existing failures (issue:79901cd6b884). No defects confirmed at review.
