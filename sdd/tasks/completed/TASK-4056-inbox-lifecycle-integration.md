# TASK-4056: Verify complete inbox lifecycle on SQLite

**Feature**: FEAT-626 — wikitoolkit inbox autonomous ingestion
**Spec**: `sdd/specs/wikitoolkit-new-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4055
**Assigned-to**: unassigned

## Context

Implements spec §3 M7/M8 integration for FEAT-626. Source contracts reverified at `18c22a3fd1af1ccf6692be6f795388189e295a76`.
This is a planning artifact; implementation occurs through `$sdd-start` in the feature worktree.

## Scope

- Create suite-local conftest fixtures tmp_repo, fake_adapters and seeded_store. Use a real temporary git repository, isolated SQLite store, declared charter, no provider calls, and deterministic documents/dates.
- AC1-12/16-21: End-to-end ingest one meeting, one decision and one rejected document. Assert two authored doc pages, child/tag/related edges, stable markdown/index, one valid ADR and all three archive outcomes with an empty inbox.
- Rerun the empty inbox as a no-op, redrop an original as a duplicate reject, then force reingest without losing authored document identity/inbound edges. Check archive source URIs, metadata and git staged deletions with unchanged HEAD.
- Cover false-success verification, Fireflies existing source reuse, no-archive, dry-run isolation and lock failure exits through the command. Never change existing upstream tests or conftest files.

**NOT in scope**: unrelated refactors, dependency changes, provider SDK calls, MCP implementation, or changes outside the declared files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/inbox/conftest.py` | CREATE | Focused tests/fixtures |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_end_to_end.py` | CREATE | Focused tests/fixtures |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from click.testing import CliRunner
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from collections.abc import AsyncIterator
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from parrot.knowledge.wiki.inbox.models import InboxClassification, LinkSelection
```
Verified: planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#InboxClassification; planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#LinkSelection.

```python
from parrot.knowledge.wiki.review import TriageOutput
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/review.py:88.

```python
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, create_wiki_store
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525; packages/ai-parrot/src/parrot/knowledge/wiki/store.py:409; packages/ai-parrot/src/parrot/knowledge/wiki/store.py:2376.

```python
from pathlib import Path
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from typing import Any
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import parrot.knowledge.wiki.cli as wiki_cli
```
Verified: verified module packages/ai-parrot/src/parrot/knowledge/wiki/cli.py.

```python
import pytest
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import pytest_asyncio
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).


### Existing Signatures to Use

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_build_triage_adapters`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4477
def _build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/review.py#TriageOutput`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/review.py:88
class TriageOutput(BaseModel):
    briefing: str
    scores: DimensionScores
    claims: list[Claim] = Field(default_factory=list)
    sensitive: bool = False
    category_hint: str | None = None
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525
class BaseWikiStore(ABC):
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.dump_edges`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:593

```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.dump_pages`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:590

```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.upsert_pages`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:544

```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:409
class WikiPageRecord(BaseModel):
    concept_id: str = Field(..., min_length=1)
    node_id: Optional[str] = None
    title: str = ''
    category: str = 'concept'
    summary: str = ''
    body: str = ''
    source_id: Optional[str] = None
    token_count: int = Field(default=0, ge=0)
    origin: str = 'ingest'
    asserted_by: Optional[str] = None
    updated_at: Optional[str] = None
    content_hash: Optional[str] = None
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#create_wiki_store`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:2376
def create_wiki_store(
    storage_dir: str | Path,
    wiki_name: str = "",
    backend: str = "sqlite",
    **kwargs: Any,
) -> BaseWikiStore:
```


### Does NOT Exist

- BaseWikiStore.initialize()/close() do not exist; SQLite opens lazily in operations.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/conftest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_end_to_end.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_build_triage_adapters",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/review.py#TriageOutput",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.dump_edges",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.dump_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.upsert_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#create_wiki_store"
  ]
}
```

## Implementation Notes

Exercises the inbox command and runtime wiring from TASK-4055. Exclusive: creates inbox/conftest.py, which pytest loads for all inbox tests.

Follow Python 120-column black formatting, strict annotations and Google-style docstrings. Keep I/O off the event loop. Merge imports into the existing import groups; do not duplicate them. All FILL IN markers are planning-only and must be removed from completed implementation.

## Implementation Blueprint

### Steps (in order)

1. Reverify the quoted contracts and dependency outputs before editing — because concurrently landing features may move anchors.
2. Apply the declared per-file blocks and complete only the bounded gaps in Scope — because public signatures and ownership are fixed.
3. Implement the named failure-path tests using temporary resources and fake model responses — because success-only coverage misses the lifecycle guarantees.
4. Run the exact Validation Commands and lint touched Python files — because unchanged defaults and failure behavior are the acceptance evidence.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/conftest.py` (CREATE)

```python
"""Isolated SQLite and git fixtures for inbox lifecycle acceptance tests."""
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
import pytest
import pytest_asyncio
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.review import TriageOutput
from parrot.knowledge.wiki.inbox.models import InboxClassification, LinkSelection

@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a temporary git root with inbox, SQLite config and fixed charter."""
    # FILL IN: local git identity only; fixture commit before snapshots; no real repo mutations.
    raise NotImplementedError

@pytest.fixture
def fake_adapters(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch the CLI adapter seam with typed, schema-directed responses and call records."""
    # FILL IN: output_type-dispatched triage/classification/links and PageIndex stubs (AC1-12).
    # Patch only model outputs; keep the real orchestrator, source manifest and SQLite store.
    raise NotImplementedError

@pytest_asyncio.fixture
async def seeded_store(tmp_repo: Path) -> AsyncIterator[BaseWikiStore]:
    """Yield a real temporary store with known code and authored link targets."""
    # FILL IN: create_wiki_store, upsert fixed file:/sym:/mem- pages, then yield; SQLite connections are operation-scoped.
    raise NotImplementedError
    yield
```

**Why**: Only this task adds shared fixtures, so it executes exclusively while other tests could load conftest.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/test_end_to_end.py` (CREATE)

```python
"""Focused FEAT-626 regression and failure-path tests."""
from pathlib import Path
import pytest
from click.testing import CliRunner
import parrot.knowledge.wiki.cli as wiki_cli


def test_inbox_end_to_end_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist meeting/decision pages, tags/links/ADR/projections and all archives."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_inbox_rerun_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty rerun is a no-op; redrop rejects and force reuses document identity."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_inbox_fireflies_source_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing external source updates without duplicate sources or doc pages."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_inbox_false_success_preserves_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing persisted children block archive despite an ok report."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_inbox_dry_run_and_no_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry-run mutates no business data; no-archive persists but retains originals."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_inbox_lock_contention_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A held writer lock yields exit 3 without processing originals."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError
```

**Why**: Use temporary files and stub adapters; assert observable state and side effects, never call providers.

### FILL IN checklist

- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/conftest.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_end_to_end.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.

## Acceptance Criteria

- [ ] Create suite-local conftest fixtures tmp_repo, fake_adapters and seeded_store. Use a real temporary git repository, isolated SQLite store, declared charter, no provider calls, and deterministic documents/dates.
- [ ] AC1-12/16-21: End-to-end ingest one meeting, one decision and one rejected document. Assert two authored doc pages, child/tag/related edges, stable markdown/index, one valid ADR and all three archive outcomes with an empty inbox.
- [ ] Rerun the empty inbox as a no-op, redrop an original as a duplicate reject, then force reingest without losing authored document identity/inbound edges. Check archive source URIs, metadata and git staged deletions with unchanged HEAD.
- [ ] Cover false-success verification, Fireflies existing source reuse, no-archive, dry-run isolation and lock failure exits through the command. Never change existing upstream tests or conftest files.
- [ ] All declared tests pass; no unfinished implementation placeholders remain; touched Python files pass ruff check.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_end_to_end.py -q`

Run in the activated repository environment; in a feature worktree set `PYTHONPATH=packages/ai-parrot/src`. Store test logs under `artifacts/logs/`.

## Test Specification

- Add typed tmp_repo/fake_adapters/seeded_store parameters to the scaffold tests that use them; tests share this conftest only.
- Keep real WikiIngestOrchestrator persistence. Fake only LLM/PageIndex generated output and intentionally injected failure points.
- Inspect real SQLite/manifest rows and actual projection/git status; ensure rejected documents skip classification/link model calls.
- Validate ADR evidence hashes and reused reviewed records, metadata preservation, no duplicate sources and read-only PageIndex children.

## Agent Instructions

1. Use `$sdd-start TASK-4056`; let it provision the feature worktree. Do not implement on dev.
2. Read the spec and this task; verify dependencies are done in `sdd/tasks/index/wikitoolkit-new-ingestion.json`.
3. Reverify source contracts before writing. Record discovered drift and refresh this task before relying on a changed API.
4. Implement only declared files. Run the focused validation commands and the normal lint gate.
5. Commit scoped implementation and finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move task files or use legacy close_task.sh.

## Completion Note

Pending. Populated by the finalizer from implementation and validation evidence.


### Completion Note (orchestrator)
Seat: gpt-5.6-terra (codex). Merged cleanly; merge-tier green (6 end-to-end tests passed). No defects confirmed.
