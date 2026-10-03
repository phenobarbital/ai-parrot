# TASK-4051: Write stable document pages, tags and ADR candidates

**Feature**: FEAT-626 — wikitoolkit inbox autonomous ingestion
**Spec**: `sdd/specs/wikitoolkit-new-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4047
**Assigned-to**: unassigned

## Context

Implements spec §3 M5 for FEAT-626. Source contracts reverified at `18c22a3fd1af1ccf6692be6f795388189e295a76`.
This is a planning artifact; implementation occurs through `$sdd-start` in the feature worktree.

## Scope

- AC6: Write one doc page with origin=authored, source_id=None and asserted_by=agent:wikitoolkit-inbox. Use archive category only for an archive decision. Preserve source_id/source_uri/file_hash in metadata.extra frontmatter, without rewriting acquired metadata in place.
- Read SourceCollectionManager.get_source(source_id).pages_generated; create child→doc part_of, doc→related typed links and doc→tag tagged edges, all asserted. Never rewrite children. Keep doc identity supplied by caller and inbound edges across replace_source_slice.
- AC7: Lazy-import decisions internals. For decision kind and enabled plane, compute candidate_decision_id(doc_id, stable_content_hash, PROMPT_VERSION, summary), get before save, and reuse an existing record without modification.
- Fresh ADRs use inferred/unknown/unreviewed, external_id=inbox:<doc_id>, nonempty decision sentence from the summary, source_path/doc evidence rel_path and required source_sha1. Capture evidence before moving; log failures and return (None, False) without failing ingestion. Log reuse separately.
- Use raw original bytes for evidence source_sha1 (DocumentMetadata.extra has no guaranteed hash); async filesystem/source/bookkeeper I/O must be offloaded. The processor persists the chosen doc id for subsequent source/Fireflies reuse.

**NOT in scope**: unrelated refactors, dependency changes, provider SDK calls, MCP implementation, or changes outside the declared files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/pages.py` | CREATE | Scoped M5 deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_pages.py` | CREATE | Focused tests/fixtures |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py:31.

```python
from parrot.knowledge.wiki.decisions.codec import candidate_decision_id
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py:109.

```python
from parrot.knowledge.wiki.decisions.generation import PROMPT_VERSION
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/decisions/generation.py:50.

```python
from parrot.knowledge.wiki.decisions.models import DecisionRecord, EvidenceRef
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py:143; packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py:78.

```python
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py:26.

```python
from parrot.knowledge.wiki.documents import AcquiredDocument, TriageProvenance, render_frontmatter
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:119; packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:136; packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:221.

```python
from parrot.knowledge.wiki.inbox.models import ResolvedClassification, VerifiedLink
```
Verified: planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#ResolvedClassification; planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#VerifiedLink.

```python
from parrot.knowledge.wiki.inbox.pages import DocPageWriter
```
Verified: planned in TASK-4051: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/pages.py#DocPageWriter.

```python
from parrot.knowledge.wiki.project import WikiProjectConfig
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:382.

```python
from parrot.knowledge.wiki.review import ManifestDocEntry
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/review.py:135.

```python
from parrot.knowledge.wiki.sources import SourceCollectionManager
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:108.

```python
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525; packages/ai-parrot/src/parrot/knowledge/wiki/store.py:409; packages/ai-parrot/src/parrot/knowledge/wiki/store.py:318.

```python
from pathlib import Path
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import asyncio
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import hashlib
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


### Existing Signatures to Use

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py#WikiBookkeeper`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py:31
class WikiBookkeeper:
    INDEX_FILENAME: str = 'index.md'
    LOG_FILENAME: str = 'log.md'
    def __init__(self) -> None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py#WikiBookkeeper.log_operation`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py:175
    def log_operation(
        self,
        wiki_dir: Path,
        operation: str,
        details: str,
        timestamp: Optional[str] = None,
    ) -> None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py#candidate_decision_id`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py:109
def candidate_decision_id(scope_id: str, evidence_fingerprint: str, prompt_version: int, decision_text: str) -> str:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/generation.py#PROMPT_VERSION`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/generation.py:50
PROMPT_VERSION = 1
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionRecord`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py:143
class DecisionRecord(_Strict):
    schema_version: Literal[1] = 1
    decision_id: str = Field(..., min_length=1)
    revision: int = Field(default=1, ge=1)
    title: str = ''
    context: str = ''
    decision: str = Field(..., min_length=1)
    consequences: str = ''
    source_status: Literal['unknown', 'proposed', 'accepted', 'rejected', 'deprecated', 'superseded'] = 'unknown'
    source_status_raw: str = ''
    origin: Literal['documented', 'inferred']
    review_status: Literal['unreviewed', 'accepted', 'rejected'] = 'unreviewed'
    source_path: str | None = None
    external_id: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    links: list[DecisionLink] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    review_history: list[ReviewEvent] = Field(default_factory=list)
    generation: GenerationInfo | None = None
    content_fingerprint: str = ''
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#EvidenceRef`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py:78
class EvidenceRef(_Strict):
    page_id: str = Field(..., min_length=1)
    rel_path: str = Field(..., min_length=1)
    start_line: int = Field(..., ge=1)
    end_line: int = Field(..., ge=1)
    source_sha1: str = Field(..., min_length=1)
    excerpt: str = ''
    kind: Literal['adr', 'code', 'comment', 'document']
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py:26
class DecisionRepository:

    def __init__(self, store: BaseWikiStore, max_records: int = 10_000) -> None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.get`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py:45
    async def get(self, decision_id: str) -> tuple[DecisionRecord, str | None] | None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.save`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py:96
    async def save(self, record: DecisionRecord, expected_content_hash: str | None) -> DecisionRecord:
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

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#TriageProvenance`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:136
class TriageProvenance(BaseModel):
    composite_score: float | None = None
    decision: str | None = None
    decision_source: str | None = None
    charter_version: str | None = None
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#render_frontmatter`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:221
def render_frontmatter(
    metadata: DocumentMetadata,
    provenance: TriageProvenance | None = None,
) -> str:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:382
class WikiProjectConfig(BaseModel):
    wiki_name: str = Field(default='codebase')
    storage_dir: str = Field(default=f'{PARROT_DIR}/wiki')
    backend: Literal['sqlite', 'memory', 'arangodb'] = Field(default='sqlite')
    include_suffixes: list[str] = Field(default_factory=list)
    exclude_dirs: list[str] = Field(default_factory=list)
    body_max_chars: int = Field(default=16000, ge=1000)
    max_file_kb: int = Field(default=512, ge=1)
    claude: ClaudeIntegrationConfig = Field(default_factory=ClaudeIntegrationConfig)
    sync_graph: bool = Field(default=False)
    arango_database: str | None = Field(default=None, description='ArangoDB database name; defaults to wiki_{wiki_name}')
    arango_credentials_env: str = Field(default='ARANGODB', description='Env var prefix for credentials (e.g. ARANGODB -> ARANGODB_HOST, ARANGODB_PASSWORD)')
    arango_text_analyzer: str = Field(default='text_en', description='ArangoSearch text analyzer for FTS')
    vault_dir: str | None = Field(default=None, description='Obsidian vault directory served by the wiki MCP server; absolute, or relative to the project root. When omitted, the project root itself is used if it is a vault (.obsidian/).')
    namespaces: dict[str, WikiNamespaceConfig] = Field(default_factory=dict, description='Federated namespaces declared by this repo, keyed by name. Repo entries override same-named global registry entries.')
    obsidian_sync: ObsidianSyncConfig | None = Field(default=None, description='Settings for `wikitoolkit sync obsidian`: which categories sync into the vault and which folder each one maps onto.')
    symbol_depth: int = Field(default=2, ge=1, le=6, description='Maximum symbol nesting depth persisted as sym: pages (FEAT-498) — 1 = top-level declarations only, 2 = top-level plus direct members.')
    structural_backend: bool = Field(default=True, description='Kill switch for the optional ast-grep structural extraction seam (FEAT-498). When False, scanners always use their tree-sitter/heuristic tiers even if ast-grep-py is installed.')
    decisions: DecisionConfig = Field(default_factory=DecisionConfig, description='ADR decision-plane settings (FEAT-578): discovery globs, inventory bound, and the opt-in candidate-generation budget. Generation is disabled by default.')
    schema_plane: SchemaPlaneConfig = Field(default_factory=SchemaPlaneConfig, alias='schema', description='SQL schema plane settings (FEAT-600): declared sources (env NAMES only), staleness policy.')
    sqlite_busy_timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Seconds a SQLite connection waits for the writer lock before giving up (FEAT-557). Bounds the wait for every wiki reader and writer on this plane; an exhausted wait surfaces as a typed WikiStoreBusy rather than 'database is locked'.")
    sqlite_performance_pragmas: bool = Field(default=False, description='Opt-in memory-oriented SQLite pragmas (mmap_size, cache_size, temp_store) (FEAT-557). Off by default so that N concurrent agents do not each map excessive memory. The safe pragmas (busy_timeout, synchronous=NORMAL, 64 MiB journal_size_limit) are always applied and are not gated by this flag.')
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

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:108
class SourceCollectionManager:
    _MANIFEST_FILENAME: str = '.manifest.json'
    def __init__(
        self,
        sources_dir: Path,
        db_path: Path | None = None,
        backend: Literal["sqlite", "json", "arangodb"] = "sqlite",
        arango_db: Any | None = None,
        arango_store: Any | None = None,
        *,
        busy_timeout: float = 15.0,
    ) -> None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.get_source`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:514
    def get_source(self, source_id: str) -> SourceManifestEntry | None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525
class BaseWikiStore(ABC):
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.add_edges`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:547

```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.get_page`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:565

```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.replace_source_slice`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:550
    async def replace_source_slice(
        self,
        source_id: str,
        pages: list[WikiPageRecord],
        edges: Optional[list[tuple[str, str, str]]] = None,
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

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#estimate_tokens`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:318
def estimate_tokens(text: str) -> int:
```


### Does NOT Exist

- WikiPageRecord.tags and IngestReport.page_ids do not exist.
- EvidenceRef.source_sha1 has no default; omitting it fails validation.
- DecisionRepository.upsert/save_or_reuse do not exist; get then save(record, None).

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/pages.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_pages.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py#WikiBookkeeper",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py#WikiBookkeeper.log_operation",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py#candidate_decision_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/generation.py#PROMPT_VERSION",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#EvidenceRef",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.get",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.save",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#AcquiredDocument",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#TriageProvenance",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#render_frontmatter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/review.py#ManifestDocEntry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.get_source",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.add_edges",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.get_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.replace_source_slice",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.upsert_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#estimate_tokens"
  ]
}
```

## Implementation Notes

Consumes ResolvedClassification and VerifiedLink from TASK-4047.

Follow Python 120-column black formatting, strict annotations and Google-style docstrings. Keep I/O off the event loop. Merge imports into the existing import groups; do not duplicate them. All FILL IN markers are planning-only and must be removed from completed implementation.

## Implementation Blueprint

### Steps (in order)

1. Reverify the quoted contracts and dependency outputs before editing — because concurrently landing features may move anchors.
2. Apply the declared per-file blocks and complete only the bounded gaps in Scope — because public signatures and ownership are fixed.
3. Implement the named failure-path tests using temporary resources and fake model responses — because success-only coverage misses the lifecycle guarantees.
4. Run the exact Validation Commands and lint touched Python files — because unchanged defaults and failure behavior are the acceptance evidence.

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/pages.py` (CREATE)

```python
"""Stable document pages and their asserted graph neighbourhood."""
import asyncio
import hashlib
import logging
from pathlib import Path
from parrot.knowledge.wiki.documents import AcquiredDocument, TriageProvenance, render_frontmatter
from parrot.knowledge.wiki.review import ManifestDocEntry
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.inbox.models import ResolvedClassification, VerifiedLink
INBOX_ASSERTED_BY = "agent:wikitoolkit-inbox"
REL_PART_OF = "part_of"
REL_TAGGED = "tagged"
TAG_CATEGORY = "tag"

def tag_page_id(tag: str) -> str:
    """Return a tag node id for an already normalized tag."""
    return f"tag:{tag}"

def render_doc_body(classification: ResolvedClassification, acquired: AcquiredDocument, provenance: TriageProvenance,
                    links: list[VerifiedLink], child_ids: list[str]) -> str:
    """Render source metadata, title/summary, related links and child sections."""
    # FILL IN: M5 frontmatter and deterministic Related/Sections wikilinks (AC6).
    raise NotImplementedError

class DocPageWriter:
    """Persist authored document/tag pages without owning PageIndex's source slice."""
    def __init__(self, store: BaseWikiStore, sources: SourceCollectionManager,
                 bookkeeper: WikiBookkeeper, wiki_dir: Path) -> None:
        """Bind graph persistence and audit dependencies."""
        self.store = store
        self.sources = sources
        self.bookkeeper = bookkeeper
        self.wiki_dir = wiki_dir
        self.logger = logging.getLogger(__name__)
    async def write_doc_page(self, doc_id: str, source_id: str, classification: ResolvedClassification,
                             acquired: AcquiredDocument, triage: ManifestDocEntry, charter_version: str,
                             links: list[VerifiedLink], archive_decision: bool) -> str:
        """Write the doc page and asserted child/link edges, returning doc_id."""
        # FILL IN: source_id=None, authored origin, metadata copy and AC6 graph wiring.
        raise NotImplementedError
    async def ensure_tags(self, doc_id: str, tags: list[str]) -> list[str]:
        """Create missing tag nodes and idempotent asserted tagged edges."""
        # FILL IN: get before creating tags; upsert and add_edges (AC6).
        raise NotImplementedError
    async def emit_adr_candidate(self, doc_id: str, classification: ResolvedClassification,
                                 acquired: AcquiredDocument, doc_rel_path: str,
                                 config: WikiProjectConfig) -> tuple[str | None, bool]:
        """Create or reuse an inferred ADR; return None on disabled/nondecision/error."""
        from parrot.knowledge.wiki.decisions.models import DecisionRecord, EvidenceRef
        from parrot.knowledge.wiki.decisions.repository import DecisionRepository
        from parrot.knowledge.wiki.decisions.codec import candidate_decision_id
        from parrot.knowledge.wiki.decisions.generation import PROMPT_VERSION
        # FILL IN: AC7 get-before-save and required EvidenceRef.source_sha1; never overwrite reviews.
        raise NotImplementedError
```

**Why**: The doc page remains outside source replacement; ADR insertion is best-effort and idempotent.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/test_pages.py` (CREATE)

```python
"""Focused FEAT-626 regression and failure-path tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.inbox.pages import DocPageWriter


def test_write_doc_page_edges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert authored origin, source_id=None, provenance and source identity in frontmatter."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_ensure_tags_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated tags create neither duplicate nodes nor edges."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_emit_adr_candidate_only_for_decisions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only enabled decision documents save valid inferred candidates."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_emit_adr_candidate_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repository failures are logged without failing the document."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_emit_adr_candidate_reuses_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserve an existing reviewed record and report reuse."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_doc_page_survives_reingest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the child source slice and retain the doc page and inbound relations."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError
```

**Why**: Use temporary files and stub adapters; assert observable state and side effects, never call providers.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/pages.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_pages.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.

## Acceptance Criteria

- [ ] AC6: Write one doc page with origin=authored, source_id=None and asserted_by=agent:wikitoolkit-inbox. Use archive category only for an archive decision. Preserve source_id/source_uri/file_hash in metadata.extra frontmatter, without rewriting acquired metadata in place.
- [ ] Read SourceCollectionManager.get_source(source_id).pages_generated; create child→doc part_of, doc→related typed links and doc→tag tagged edges, all asserted. Never rewrite children. Keep doc identity supplied by caller and inbound edges across replace_source_slice.
- [ ] AC7: Lazy-import decisions internals. For decision kind and enabled plane, compute candidate_decision_id(doc_id, stable_content_hash, PROMPT_VERSION, summary), get before save, and reuse an existing record without modification.
- [ ] Fresh ADRs use inferred/unknown/unreviewed, external_id=inbox:<doc_id>, nonempty decision sentence from the summary, source_path/doc evidence rel_path and required source_sha1. Capture evidence before moving; log failures and return (None, False) without failing ingestion. Log reuse separately.
- [ ] Use raw original bytes for evidence source_sha1 (DocumentMetadata.extra has no guaranteed hash); async filesystem/source/bookkeeper I/O must be offloaded. The processor persists the chosen doc id for subsequent source/Fireflies reuse.
- [ ] All declared tests pass; no unfinished implementation placeholders remain; touched Python files pass ruff check.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_pages.py -q`

Run in the activated repository environment; in a feature worktree set `PYTHONPATH=packages/ai-parrot/src`. Store test logs under `artifacts/logs/`.

## Test Specification

- Use a real temporary sqlite store for source-slice and ADR tests; SQLite initializes lazily through its operations and has no public initialize()/close() API.
- Assert every EvidenceRef field, including raw-source SHA1, relative path, nonempty excerpt and ordered line bounds.
- An empty pages_generated list is legal: still write the authored document with zero child edges.

## Agent Instructions

1. Use `$sdd-start TASK-4051`; let it provision the feature worktree. Do not implement on dev.
2. Read the spec and this task; verify dependencies are done in `sdd/tasks/index/wikitoolkit-new-ingestion.json`.
3. Reverify source contracts before writing. Record discovered drift and refresh this task before relying on a changed API.
4. Implement only declared files. Run the focused validation commands and the normal lint gate.
5. Commit scoped implementation and finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move task files or use legacy close_task.sh.

## Completion Note

Pending. Populated by the finalizer from implementation and validation evidence.
