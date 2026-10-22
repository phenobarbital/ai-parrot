# TASK-4049: Classify inbox documents against the charter

**Feature**: FEAT-626 — wikitoolkit inbox autonomous ingestion
**Spec**: `sdd/specs/wikitoolkit-new-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4045, TASK-4047
**Assigned-to**: unassigned

## Context

Implements spec §3 M3 classifier for FEAT-626. Source contracts reverified at `18c22a3fd1af1ccf6692be6f795388189e295a76`.
This is a planning artifact; implementation occurs through `$sdd-start` in the feature worktree.

## Scope

- AC4/AC20: Implement the fixed classify.py interfaces and InboxClassificationError. Require an InboxClassification instance; dict/list/None/raw string and adapter exceptions raise the typed error. Only an explicit unknown kind uses default_kind and classification_source=fallback.
- Normalize tags with lowercase ASCII folding, collapse non-alphanumeric runs to hyphens, drop empty or >64 characters, dedupe in order, cap at taxonomy.max_tags. Category always comes from the taxonomy.
- Use max_chars=24000 for bounded document text. Derive a nonempty title from model title, metadata title, then source stem. Produce doc:<title-slug-up-to-48>-<hash-first-8>; use note for an empty normalized title. Treat document content as untrusted prompt data.

**NOT in scope**: unrelated refactors, dependency changes, provider SDK calls, MCP implementation, or changes outside the declared files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py` | CREATE | Scoped M3 classifier deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_classify.py` | CREATE | Focused tests/fixtures |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from collections.abc import Iterable
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
```
Verified: packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:42.

```python
from parrot.knowledge.wiki.charter import Taxonomy
```
Verified: planned in TASK-4045: packages/ai-parrot/src/parrot/knowledge/wiki/charter.py#Taxonomy.

```python
from parrot.knowledge.wiki.documents import AcquiredDocument, DocumentMetadata
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:119; packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:83.

```python
from parrot.knowledge.wiki.inbox.classify import InboxClassifier, normalize_tags, slugify_doc_id
```
Verified: planned in TASK-4049: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py#InboxClassifier; planned in TASK-4049: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py#normalize_tags; planned in TASK-4049: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py#slugify_doc_id.

```python
from parrot.knowledge.wiki.inbox.models import InboxClassification, ResolvedClassification
```
Verified: planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#InboxClassification; planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#ResolvedClassification.

```python
from parrot.knowledge.wiki.review import ManifestDocEntry
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/review.py:135.

```python
from pathlib import Path
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import logging
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

```python
import unicodedata
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).


### Existing Signatures to Use

`sym:packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py#PageIndexLLMAdapter`

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:42
class PageIndexLLMAdapter:

    def __init__(
        self,
        client: AbstractClient,
        model: Optional[str] = "gemini-3.1-flash-lite-preview",
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
```

`sym:packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py#PageIndexLLMAdapter.ask_structured`

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:99
    async def ask_structured(
        self,
        prompt: str,
        output_type: type,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> Any:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#AcquiredDocument`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:119
class AcquiredDocument(BaseModel):
    ref: DocumentRef
    text: str
    metadata: DocumentMetadata
    ebook_sections: list[dict[str, Any]] = Field(default_factory=list)
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#DocumentMetadata`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:83
class DocumentMetadata(BaseModel):
    title: str | None = None
    author: str | None = None
    created_at: str | None = None
    modified_at: str | None = None
    page_count: int | None = None
    word_count: int | None = None
    language: str | None = None
    content_type: str | None = None
    source_url: str | None = None
    loader: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
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


### Does NOT Exist

- InboxClassificationError and normalize_tags do not exist until this task.
- Do not accept a raw dict merely because it could be model_validate-ed: the caller requires a structured instance.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_classify.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py#PageIndexLLMAdapter",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py#PageIndexLLMAdapter.ask_structured",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#AcquiredDocument",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#DocumentMetadata",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/review.py#ManifestDocEntry"
  ]
}
```

## Implementation Notes

Consumes Taxonomy/default_taxonomy from TASK-4045 and structured result models from TASK-4047.

Follow Python 120-column black formatting, strict annotations and Google-style docstrings. Keep I/O off the event loop. Merge imports into the existing import groups; do not duplicate them. All FILL IN markers are planning-only and must be removed from completed implementation.

## Implementation Blueprint

### Steps (in order)

1. Reverify the quoted contracts and dependency outputs before editing — because concurrently landing features may move anchors.
2. Apply the declared per-file blocks and complete only the bounded gaps in Scope — because public signatures and ownership are fixed.
3. Implement the named failure-path tests using temporary resources and fake model responses — because success-only coverage misses the lifecycle guarantees.
4. Run the exact Validation Commands and lint touched Python files — because unchanged defaults and failure behavior are the acceptance evidence.

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py` (CREATE)

```python
"""Taxonomy-bound document classification and deterministic tag/id normalization."""
from collections.abc import Iterable
import logging
import re
import unicodedata
from pathlib import Path
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.wiki.charter import Taxonomy
from parrot.knowledge.wiki.documents import AcquiredDocument, DocumentMetadata
from parrot.knowledge.wiki.review import ManifestDocEntry
from parrot.knowledge.wiki.inbox.models import InboxClassification, ResolvedClassification

class InboxClassificationError(RuntimeError):
    """Classification failed or returned a malformed structured response."""

def normalize_tag(raw: str) -> str | None:
    """ASCII-fold and kebab-case a tag; drop empty or overlong results."""
    # FILL IN: normalize without truncating overlong tags (AC4).
    raise NotImplementedError

def normalize_tags(raw: Iterable[str], *, max_tags: int) -> list[str]:
    """Normalize, dedupe in order and cap the tag sequence."""
    # FILL IN: apply normalize_tag and the taxonomy cap (AC4).
    raise NotImplementedError

def slugify_doc_id(title: str, file_hash: str) -> str:
    """Return doc:<kebab-title-max-48>-<file_hash[:8]>."""
    # FILL IN: deterministic slug, using note when normalization is empty.
    raise NotImplementedError

def build_classification_prompt(text: str, taxonomy: Taxonomy, briefing: str, metadata: DocumentMetadata) -> str:
    """Build a bounded data-only prompt declaring allowed kinds and the tag cap."""
    # FILL IN: list ids/descriptions, triage briefing and metadata; forbid new kinds (AC4).
    raise NotImplementedError

class InboxClassifier:
    """Run and validate one structured classification call."""
    def __init__(self, adapter: PageIndexLLMAdapter, taxonomy: Taxonomy, *, max_chars: int = 24_000) -> None:
        """Bind the adapter, taxonomy and text budget."""
        self.adapter = adapter
        self.taxonomy = taxonomy
        self.max_chars = max_chars
        self.logger = logging.getLogger(__name__)
    async def classify(self, acquired: AcquiredDocument, triage: ManifestDocEntry) -> ResolvedClassification:
        """Classify or raise InboxClassificationError; unknown kinds alone may fall back."""
        # FILL IN: ask_structured(prompt, InboxClassification), isinstance-check and resolve (AC4/20).
        raise NotImplementedError
```

**Why**: Keep model output untrusted; code chooses category and normalizes tags, preventing taxonomy invention.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/test_classify.py` (CREATE)

```python
"""Focused FEAT-626 regression and failure-path tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.inbox.classify import InboxClassifier, normalize_tags, slugify_doc_id


def test_normalize_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover accents, punctuation, empties, overlong values, deduplication and cap."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_slugify_doc_id_stable_and_unique(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Check repeated inputs, equal titles with different hashes and length bounds."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_classify_unknown_kind_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a valid structured unknown kind falls back to the default."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_classify_adapter_failure_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrap adapter failures in InboxClassificationError."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_classify_rejects_malformed_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject dict, list, None and raw text without fallback."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_prompt_budget_and_title_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bound prompt text and derive a nonempty title without trusting model category."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError
```

**Why**: Use temporary files and stub adapters; assert observable state and side effects, never call providers.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_classify.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.

## Acceptance Criteria

- [ ] AC4/AC20: Implement the fixed classify.py interfaces and InboxClassificationError. Require an InboxClassification instance; dict/list/None/raw string and adapter exceptions raise the typed error. Only an explicit unknown kind uses default_kind and classification_source=fallback.
- [ ] Normalize tags with lowercase ASCII folding, collapse non-alphanumeric runs to hyphens, drop empty or >64 characters, dedupe in order, cap at taxonomy.max_tags. Category always comes from the taxonomy.
- [ ] Use max_chars=24000 for bounded document text. Derive a nonempty title from model title, metadata title, then source stem. Produce doc:<title-slug-up-to-48>-<hash-first-8>; use note for an empty normalized title. Treat document content as untrusted prompt data.
- [ ] All declared tests pass; no unfinished implementation placeholders remain; touched Python files pass ruff check.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_classify.py -q`

Run in the activated repository environment; in a feature worktree set `PYTHONPATH=packages/ai-parrot/src`. Store test logs under `artifacts/logs/`.

## Test Specification

- Run async cases with pytest-asyncio (convert scaffold functions to async where necessary). Use strict fake adapters returning actual Pydantic instances.
- Check selected output_type and prompt contents; ensure malformed results cannot reach a writer.

## Agent Instructions

1. Use `$sdd-start TASK-4049`; let it provision the feature worktree. Do not implement on dev.
2. Read the spec and this task; verify dependencies are done in `sdd/tasks/index/wikitoolkit-new-ingestion.json`.
3. Reverify source contracts before writing. Record discovered drift and refresh this task before relying on a changed API.
4. Implement only declared files. Run the focused validation commands and the normal lint gate.
5. Commit scoped implementation and finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move task files or use legacy close_task.sh.

## Completion Note

Pending. Populated by the finalizer from implementation and validation evidence.


### Completion Note (orchestrator)
Seat: gpt-5.6-terra (codex). Review fix 178135fd0: slugify_doc_id reused normalize_tag (None for >64 chars -> long titles became "note"); replaced with scoped slug. feedback_id coder-feedback:f23f4f0cea244d64a96f5ffd. Merge-tier validation green after fix (55 passed).
