# TASK-4045: Add charter taxonomy and preserve fingerprints

**Feature**: FEAT-626 — wikitoolkit inbox autonomous ingestion
**Spec**: `sdd/specs/wikitoolkit-new-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implements spec §3 M1 for FEAT-626. Source contracts reverified at `18c22a3fd1af1ccf6692be6f795388189e295a76`.
This is a planning artifact; implementation occurs through `$sdd-start` in the feature worktree.

## Scope

- AC3: Add TaxonomyKind, Taxonomy, DEFAULT_TAXONOMY and default_taxonomy. Default mappings are meeting→summary, briefing→overview, decision→concept, report→synthesis, memo→summary, note→concept; default_kind=note, max_tags=8 (1..32).
- Validate kebab-case unique ids, membership of default_kind and WikiPageCategory values. Return fresh deep copies; default mutation must not leak between Charter instances.
- Add Charter.taxonomy using default_factory without changing load_charter raw-byte fingerprinting or the existing triage prompts.

**NOT in scope**: unrelated refactors, dependency changes, provider SDK calls, MCP implementation, or changes outside the declared files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/charter.py` | MODIFY | Scoped M1 deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_taxonomy.py` | CREATE | Focused tests/fixtures |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.charter import Charter, default_taxonomy
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/charter.py:208; planned in TASK-4045: packages/ai-parrot/src/parrot/knowledge/wiki/charter.py#default_taxonomy.

```python
from parrot.knowledge.wiki.models import WikiPageCategory
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/models.py:25.

```python
from pathlib import Path
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from pydantic import BaseModel, Field, model_validator
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import pytest
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import re
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).


### Existing Signatures to Use

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/charter.py#Charter`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/charter.py:208
class Charter(BaseModel):
    version: str
    scope: CharterScope
    weights: dict[str, float]
    thresholds: Thresholds
    destinations: list[str] = Field(default_factory=lambda: ['wiki', 'archive', 'discard'])
    calibration: CalibrationPolicy
    examples: list[TriageExample] = Field(default_factory=list)
    examples_file: Path | None = None
    amendments: list[Amendment] = Field(default_factory=list)
    fingerprint: str = Field(default='', description='sha256 of the raw charter YAML bytes, set by load_charter() after validation. Empty until then.')
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/charter.py#load_charter`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/charter.py:303
def load_charter(path: Path) -> Charter:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/models.py#WikiPageCategory`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py:25
class WikiPageCategory(str, Enum):
```


### Does NOT Exist

- Charter.taxonomy, Taxonomy and default_taxonomy do not exist before this task.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/charter.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_taxonomy.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/charter.py#Charter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/charter.py#load_charter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/models.py#WikiPageCategory"
  ]
}
```

## Implementation Notes

Independent M1 deliverable; owns packages/ai-parrot/src/parrot/knowledge/wiki/charter.py. No prerequisite-created symbol is consumed.

Follow Python 120-column black formatting, strict annotations and Google-style docstrings. Keep I/O off the event loop. Merge imports into the existing import groups; do not duplicate them. All FILL IN markers are planning-only and must be removed from completed implementation.

## Implementation Blueprint

### Steps (in order)

1. Reverify the quoted contracts and dependency outputs before editing — because concurrently landing features may move anchors.
2. Apply the declared per-file blocks and complete only the bounded gaps in Scope — because public signatures and ownership are fixed.
3. Implement the named failure-path tests using temporary resources and fake model responses — because success-only coverage misses the lifecycle guarantees.
4. Run the exact Validation Commands and lint touched Python files — because unchanged defaults and failure behavior are the acceptance evidence.

### `packages/ai-parrot/src/parrot/knowledge/wiki/charter.py` (MODIFY)

Verified attachment points (literal `grep -F -c` counts):

- `class Charter(BaseModel):` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/charter.py:208`.
- `    amendments: list[Amendment] = Field(default_factory=list)` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/charter.py:241`.
```python
# MODIFY: insert before class Charter(BaseModel); add the final field inside Charter.
import re
from pydantic import BaseModel, Field, model_validator
from parrot.knowledge.wiki.models import WikiPageCategory

class TaxonomyKind(BaseModel):
    """One allowed document kind and its wiki category."""
    id: str
    description: str
    category: str
    tag_hints: list[str] = Field(default_factory=list)
    @model_validator(mode="after")
    def _validate_kind(self) -> "TaxonomyKind":
        """Reject invalid ids and categories."""
        # FILL IN: enforce AC3 without extending WikiPageCategory.
        raise NotImplementedError

class Taxonomy(BaseModel):
    """Closed document taxonomy for inbox classification."""
    default_kind: str = "note"
    max_tags: int = Field(default=8, ge=1, le=32)
    kinds: list[TaxonomyKind]
    @model_validator(mode="after")
    def _validate_kinds(self) -> "Taxonomy":
        """Require unique ids and a defined default kind."""
        # FILL IN: AC3 validation including an empty kinds list.
        raise NotImplementedError
    def kind(self, kind_id: str) -> TaxonomyKind | None:
        """Return the declared kind, or None."""
        return next((kind for kind in self.kinds if kind.id == kind_id), None)

# FILL IN: assign DEFAULT_TAXONOMY = Taxonomy(...) with the six fixed mappings (AC3).
DEFAULT_TAXONOMY: Taxonomy

def default_taxonomy() -> Taxonomy:
    """Return an independent copy of the built-in taxonomy."""
    return DEFAULT_TAXONOMY.model_copy(deep=True)

# Insert after Charter.amendments, at the same class indentation:
# taxonomy: Taxonomy = Field(default_factory=default_taxonomy)
```

**Why**: Retain the raw YAML fingerprint because applying defaults must not change existing charter identities.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/test_taxonomy.py` (CREATE)

```python
"""Focused FEAT-626 regression and failure-path tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.charter import Charter, default_taxonomy


def test_default_taxonomy_six_kinds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify exact mappings and independent mutable defaults."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_charter_without_taxonomy_block_still_loads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the raw-byte fingerprint unchanged for an old charter."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_taxonomy_validators(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject duplicates, invalid ids/categories/default kinds and invalid tag limits."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError
```

**Why**: Use temporary files and stub adapters; assert observable state and side effects, never call providers.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/charter.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_taxonomy.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.

## Acceptance Criteria

- [ ] AC3: Add TaxonomyKind, Taxonomy, DEFAULT_TAXONOMY and default_taxonomy. Default mappings are meeting→summary, briefing→overview, decision→concept, report→synthesis, memo→summary, note→concept; default_kind=note, max_tags=8 (1..32).
- [ ] Validate kebab-case unique ids, membership of default_kind and WikiPageCategory values. Return fresh deep copies; default mutation must not leak between Charter instances.
- [ ] Add Charter.taxonomy using default_factory without changing load_charter raw-byte fingerprinting or the existing triage prompts.
- [ ] All declared tests pass; no unfinished implementation placeholders remain; touched Python files pass ruff check.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_taxonomy.py -q`
- `pytest tests/knowledge/wiki/test_charter.py -q`

Run in the activated repository environment; in a feature worktree set `PYTHONPATH=packages/ai-parrot/src`. Store test logs under `artifacts/logs/`.

## Test Specification

- Use the FEAT-402 charter fixture shape; compare fingerprint to hashlib.sha256(original_yaml_bytes).hexdigest().
- Parametrize invalid category, blank/non-kebab ids, duplicate ids, unknown default, empty kinds and max_tags bounds.

## Agent Instructions

1. Use `$sdd-start TASK-4045`; let it provision the feature worktree. Do not implement on dev.
2. Read the spec and this task; verify dependencies are done in `sdd/tasks/index/wikitoolkit-new-ingestion.json`.
3. Reverify source contracts before writing. Record discovered drift and refresh this task before relying on a changed API.
4. Implement only declared files. Run the focused validation commands and the normal lint gate.
5. Commit scoped implementation and finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move task files or use legacy close_task.sh.

## Completion Note

Pending. Populated by the finalizer from implementation and validation evidence.
