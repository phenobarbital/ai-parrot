# TASK-4054: Compose the crash-safe inbox processor with asynchronous locking

**Feature**: FEAT-626 — wikitoolkit inbox autonomous ingestion
**Spec**: `sdd/specs/wikitoolkit-new-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4046, TASK-4049, TASK-4050, TASK-4051, TASK-4052, TASK-4053
**Assigned-to**: unassigned

## Context

Implements spec §3 M7 for FEAT-626. Source contracts reverified at `18c22a3fd1af1ccf6692be6f795388189e295a76`.
This is a planning artifact; implementation occurs through `$sdd-start` in the feature worktree.

## Scope

- AC1/10/17/18: Create the Pydantic frozen InboxRuntime (arbitrary_types_allowed=True) and InboxProcessor. Resolve storage_path(root), validate directories in __init__, discover original paths before resolve_sources erases symlinks, skip dotfiles and unsafe paths with report rows, order by (mtime,name), then apply a nonnegative limit.
- USER-APPROVED OVERRIDE (2026-10-03): processor.run is the sole owner of NONBLOCKING acquisition. This supersedes the blocking-lock prose in spec M7/§6/§7. Use the existing wiki_write_lock(storage_path(root), timeout=0) in off-loop attempts, retry with await asyncio.sleep against a monotonic deadline, and retain the acquired context for the whole run. Never block the loop or reacquire in CLI.
- Implement a private async context manager for the lock. Shield each offloaded enter attempt; if cancelled while an attempt runs, await its completion and release any acquired context before propagating cancellation. Shield/wait cleanup as well. Close unsuccessful contexts immediately. Timeout raises InboxLockBusy; zero timeout performs one attempt. Acquisition, processing, failure and cancellation all release descriptors.
- AC11/21: Acquire, detect Fireflies id in metadata.extra/text, look up external identity, and (non-dry-run only) repoint to the inbox path before ingest. Reuse doc id from source metadata.extra.inbox_doc_id or a matching existing authored doc frontmatter/source identity; persist the mapping for subsequent runs. Only generate a slug for a new document identity.
- AC19/20: Triage with skip_duplicate_check=force, fill decision=proposed_action and auto decision source except heuristic. Discards bypass classify/links and go through orchestrator rejection recording. Dry-run performs acquisition/triage/classify/link planning only, never source repointing, ingest, doc/ADR writes, projection or archiving.
- AC6/7/8/16: For admitted/archive decisions classify, exclude own doc and prior child ids from link retrieval, ingest with acquired document, reject error reports, write doc/tags/ADR, project markdown and index, then verify. Manifest destination is wiki for admit, archive for archive, discard for discard; there is no manifest decision field. Check every child id, the doc and markdown. Empty legitimate child lists are allowed; missing claimed children/manifests are not.
- AC9/12/21: Archive only after verification (or verified discard record). Move, repoint, then merge archived_to/archived_at into doc_metadata.extra without losing existing metadata or inbox_doc_id. --no-archive retains originals but performs normal persistence/verification. Report verified=False for rejected/dry-run.
- One document failure produces a failed row and processing continues; DocumentAcquisitionError produces skipped. Propagate cancellation rather than converting it to a failed row. Write the named classification/doc/tag/ADR/archive/run audit operations only outside dry-run; dry-run writes only DRY_RUN. Offload filesystem, manifest and bookkeeper calls; no source/store schema changes.
- Prevent duplicate pages on retry after partial persistence: recover source/doc identity before slugging. Check source identity mapping before PageIndex may replace metadata; merge it again afterward. Re-verify path containment immediately before moving/staging an original.

**NOT in scope**: unrelated refactors, dependency changes, provider SDK calls, MCP implementation, or changes outside the declared files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py` | CREATE | Scoped M7 deliverable |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py` | CREATE | Scoped M7 deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_processor.py` | CREATE | Focused tests/fixtures |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from collections.abc import AsyncIterator
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from contextlib import asynccontextmanager
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from datetime import date
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
```
Verified: packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:42.

```python
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py:31.

```python
from parrot.knowledge.wiki.charter import Charter
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/charter.py:208.

```python
from parrot.knowledge.wiki.documents import AcquiredDocument, DocumentAcquirer, DocumentAcquisitionError, DocumentRef, resolve_sources
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:119; packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:466; packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:158; packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:69; packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:166.

```python
from parrot.knowledge.wiki.inbox.archive import archive_destination, archive_original, repoint_source
```
Verified: planned in TASK-4053: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/archive.py#archive_destination; planned in TASK-4053: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/archive.py#archive_original; planned in TASK-4053: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/archive.py#repoint_source.

```python
from parrot.knowledge.wiki.inbox.classify import InboxClassifier, slugify_doc_id
```
Verified: planned in TASK-4049: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py#InboxClassifier; planned in TASK-4049: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py#slugify_doc_id.

```python
from parrot.knowledge.wiki.inbox.links import LinkProposer
```
Verified: planned in TASK-4050: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/links.py#LinkProposer.

```python
from parrot.knowledge.wiki.inbox.models import InboxDocResult, InboxRunReport
```
Verified: planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#InboxDocResult; planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#InboxRunReport.

```python
from parrot.knowledge.wiki.inbox.models import InboxRunReport, InboxDocResult
```
Verified: planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#InboxRunReport; planned in TASK-4047: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/models.py#InboxDocResult.

```python
from parrot.knowledge.wiki.inbox.pages import DocPageWriter
```
Verified: planned in TASK-4051: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/pages.py#DocPageWriter.

```python
from parrot.knowledge.wiki.inbox.processor import InboxProcessor, InboxRuntime
```
Verified: planned in TASK-4054: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py#InboxProcessor; planned in TASK-4054: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py#InboxRuntime.

```python
from parrot.knowledge.wiki.inbox.processor import InboxProcessor, InboxRuntime, InboxLockBusy
```
Verified: planned in TASK-4054: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py#InboxProcessor; planned in TASK-4054: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py#InboxRuntime; planned in TASK-4054: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py#InboxLockBusy.

```python
from parrot.knowledge.wiki.inbox.projection import write_doc_markdown, write_inbox_index
```
Verified: planned in TASK-4052: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/projection.py#write_doc_markdown; planned in TASK-4052: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/projection.py#write_inbox_index.

```python
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py:144.

```python
from parrot.knowledge.wiki.models import WikiConfig
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/models.py:52.

```python
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiConfigError, validate_inbox_paths, wiki_write_lock
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:382; packages/ai-parrot/src/parrot/knowledge/wiki/project.py:768; planned in TASK-4046: packages/ai-parrot/src/parrot/knowledge/wiki/project.py#validate_inbox_paths; packages/ai-parrot/src/parrot/knowledge/wiki/project.py:74.

```python
from parrot.knowledge.wiki.search import WikiCombinedSearch
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/search.py:32.

```python
from parrot.knowledge.wiki.sources import SourceCollectionManager
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:108.

```python
from parrot.knowledge.wiki.store import BaseWikiStore
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525.

```python
from parrot.knowledge.wiki.triage import IngestTriageRouter
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/triage.py:252.

```python
from pathlib import Path
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from pydantic import BaseModel, ConfigDict
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import asyncio
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

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#AcquiredDocument`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:119
class AcquiredDocument(BaseModel):
    ref: DocumentRef
    text: str
    metadata: DocumentMetadata
    ebook_sections: list[dict[str, Any]] = Field(default_factory=list)
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#DocumentAcquirer`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:466
class DocumentAcquirer:

    def __init__(
        self,
        *,
        fetch_timeout: float = 30.0,
        max_bytes: int = 100 * 1024 * 1024,
        cache_dir: Path | None = None,
    ) -> None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#DocumentAcquirer.acquire`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:500
    async def acquire(self, ref: DocumentRef) -> AcquiredDocument:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#DocumentAcquisitionError`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:158
class DocumentAcquisitionError(Exception):
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#DocumentRef`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:69
class DocumentRef(BaseModel):
    uri: str
    is_url: bool = False
    suffix: str = ''
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#resolve_sources`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:166
def resolve_sources(source: str, *, recursive: bool = True) -> list[DocumentRef]:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py#WikiIngestOrchestrator`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py:144
class WikiIngestOrchestrator:

    def __init__(
        self,
        pageindex_toolkit: Any,
        graphindex_toolkit: Any,
        source_manager: SourceCollectionManager,
        bookkeeper: WikiBookkeeper,
        store: Optional[BaseWikiStore] = None,
        sync_graph: bool = False,
    ) -> None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py#WikiIngestOrchestrator.ingest`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py:198
    async def ingest(
        self,
        source_path: str,
        wiki_config: WikiConfig,
        *,
        triage: Optional[ManifestDocEntry] = None,
        charter_version: Optional[str] = None,
        acquired: AcquiredDocument | None = None,
    ) -> IngestReport:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/models.py#SourceManifestEntry`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py:155
class SourceManifestEntry(BaseModel):
    source_id: str = Field(..., description='Stable source identifier')
    source_uri: str = Field(..., description='Absolute path or URI')
    file_hash: str = Field(..., description='SHA-1 hex digest at ingest time')
    mtime: float = Field(..., description='File mtime at ingest time')
    ingested_at: str = Field(..., description='ISO-8601 UTC ingest timestamp')
    pages_generated: list[str] = Field(default_factory=list, description='Wiki page IDs produced by this ingest')
    status: str = Field(default='ingested', description='Source lifecycle status')
    destination: str | None = Field(default=None, description="Supervised-ingestion (FEAT-402) triage destination: 'wiki' | 'archive' | 'discard'. None when not triaged.")
    decision_source: str | None = Field(default=None, description="Who/what made the triage decision: 'heuristic' | 'model' | 'human' | 'auto'. None when not triaged.")
    charter_version: str | None = Field(default=None, description='Editorial charter version the decision was made against.')
    composite_score: float | None = Field(default=None, ge=0.0, le=1.0, description='Weighted composite triage score in [0, 1].')
    doc_metadata: dict[str, Any] | None = Field(default=None, description='FEAT-451: extracted DocumentMetadata as a dict. None for sources ingested before FEAT-451.')
    content_type: str | None = Field(default=None, description='FEAT-451: MIME type of the source document.')
    loader: str | None = Field(default=None, description='FEAT-451: name of the loader used to extract this document.')
    external_id: str | None = Field(default=None, description="FEAT-472: immutable external identity in '<source>:<id>' form (e.g. 'fireflies:abc123'). None when the source has no external identity.")
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/models.py#WikiConfig`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py:52
class WikiConfig(BaseModel):
    wiki_name: str = Field(..., description='Unique wiki name / identifier')
    storage_dir: Path = Field(..., description='Root storage directory')
    source_dir: Path | None = Field(default=None, description='Raw sources directory; defaults to storage_dir/sources')
    page_categories: list[WikiPageCategory] = Field(default_factory=lambda: list(WikiPageCategory), description='Supported page categories (all by default)')
    search_weights: dict[str, float] = Field(default_factory=lambda: {'pageindex': 0.6, 'graphindex': 0.4}, description='Score weights per search backend; must sum to ~1.0')
    lightweight_model: str | None = Field(default=None, description='LLM model for fast CoT analysis step')
    model: str | None = Field(default=None, description='LLM model for heavyweight generation step')
    sync_graph: bool = Field(default=False, description='Mirror wiki pages into GraphIndex on write. Off by default — the WikiStore plane is the retrieval backend.')
    storage_backend: Literal['sqlite', 'memory', 'arangodb'] = Field(default='sqlite', description="Retrieval-plane backend: 'sqlite' (single-file wiki.db, FTS5/BM25), 'memory' (in-memory indexes persisted as an OKF markdown bundle under {storage_dir}/pages/), or 'arangodb' (server-hosted, shared retrieval plane). Explicit selection only — no auto-fallback.")
    charter_path: Path | None = Field(default=None, description='Path to a supervised-ingestion editorial charter YAML file (FEAT-402). None when this wiki does not use supervised ingestion (`wikitoolkit ingest`).')
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiConfigError`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:768
class WikiConfigError(ValueError):
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

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig.storage_path`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:555
    def storage_path(self, root: Path) -> Path:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#wiki_write_lock`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:74
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/search.py#WikiCombinedSearch`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/search.py:32
class WikiCombinedSearch:

    def __init__(
        self,
        pageindex_toolkit: Any,
        graphindex_toolkit: Any,
        default_weights: Optional[dict[str, float]] = None,
        store: Optional[BaseWikiStore] = None,
        embedder: Optional[Callable[[str], Awaitable[list[float]]]] = None,
        normalize_store_rows: bool = True,
    ) -> None:
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

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.find_by_external_id`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:822
    def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.find_by_uri`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:807
    def find_by_uri(self, source_uri: str) -> str | None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.get_source`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:514
    def get_source(self, source_id: str) -> SourceManifestEntry | None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.record_document_metadata`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:730
    def record_document_metadata(
        self,
        source_id: str,
        *,
        doc_metadata: dict[str, Any] | None,
        content_type: str | None,
        loader: str | None,
    ) -> None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.update_source_uri`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:948
    def update_source_uri(self, source_id: str, new_uri: Path | str) -> SourceManifestEntry | None:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525
class BaseWikiStore(ABC):
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.dump_pages`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:590

```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.get_page`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:565

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


### Does NOT Exist

- SourceManifestEntry.decision does not exist; use destination with admit→wiki mapping.
- The write lock is not an async context manager; the new private adapter supplies asynchronous waiting.
- IngestReport.pages_generated/page_ids do not exist; read the manifest.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_processor.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py#PageIndexLLMAdapter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py#WikiBookkeeper",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py#WikiBookkeeper.log_operation",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/charter.py#Charter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#AcquiredDocument",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#DocumentAcquirer",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#DocumentAcquirer.acquire",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#DocumentAcquisitionError",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#DocumentRef",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#resolve_sources",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py#WikiIngestOrchestrator",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py#WikiIngestOrchestrator.ingest",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/models.py#SourceManifestEntry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/models.py#WikiConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiConfigError",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig.storage_path",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#wiki_write_lock",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/search.py#WikiCombinedSearch",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.find_by_external_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.find_by_uri",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.get_source",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.record_document_metadata",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager.update_source_uri",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.dump_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.get_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/triage.py#IngestTriageRouter"
  ]
}
```

## Implementation Notes

Consumes config/path helpers from TASK-4046, InboxClassifier/slugify_doc_id from TASK-4049, LinkProposer from TASK-4050, DocPageWriter from TASK-4051, projection writers from TASK-4052, and archive helpers from TASK-4053. Compatibility seams and data models are transitive prerequisites.

Follow Python 120-column black formatting, strict annotations and Google-style docstrings. Keep I/O off the event loop. Merge imports into the existing import groups; do not duplicate them. All FILL IN markers are planning-only and must be removed from completed implementation.

## Implementation Blueprint

### Steps (in order)

1. Reverify the quoted contracts and dependency outputs before editing — because concurrently landing features may move anchors.
2. Apply the declared per-file blocks and complete only the bounded gaps in Scope — because public signatures and ownership are fixed.
3. Implement the named failure-path tests using temporary resources and fake model responses — because success-only coverage misses the lifecycle guarantees.
4. Run the exact Validation Commands and lint touched Python files — because unchanged defaults and failure behavior are the acceptance evidence.

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py` (CREATE)

```python
"""Crash-safe autonomous inbox processing with one asynchronous lock owner."""
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
import logging
from pathlib import Path
import re
from pydantic import BaseModel, ConfigDict
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.wiki.charter import Charter
from parrot.knowledge.wiki.documents import AcquiredDocument, DocumentAcquirer, DocumentAcquisitionError, DocumentRef, resolve_sources
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiConfigError, validate_inbox_paths, wiki_write_lock
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.triage import IngestTriageRouter
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.inbox.models import InboxDocResult, InboxRunReport
from parrot.knowledge.wiki.inbox.classify import InboxClassifier, slugify_doc_id
from parrot.knowledge.wiki.inbox.links import LinkProposer
from parrot.knowledge.wiki.inbox.pages import DocPageWriter
from parrot.knowledge.wiki.inbox.projection import write_doc_markdown, write_inbox_index
from parrot.knowledge.wiki.inbox.archive import archive_destination, archive_original, repoint_source
# FILL IN: match fireflies[_-]?id values and fireflies:<id> markers (AC11).
_FIREFLIES_RE: re.Pattern[str]
class InboxRuntime(BaseModel):
    """Frozen service bindings for a single processing run."""
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    root: Path
    config: WikiProjectConfig
    wiki_config: WikiConfig
    charter: Charter
    store: BaseWikiStore
    sources: SourceCollectionManager
    bookkeeper: WikiBookkeeper
    acquirer: DocumentAcquirer
    router: IngestTriageRouter
    orchestrator: WikiIngestOrchestrator
    light_adapter: PageIndexLLMAdapter
    heavy_adapter: PageIndexLLMAdapter
    search: WikiCombinedSearch
    models: dict[str, str]
class InboxLockBusy(RuntimeError):
    """The whole-run writer lock could not be acquired before its deadline."""
@asynccontextmanager
async def _inbox_write_lock(storage_path: Path, timeout: float) -> AsyncIterator[None]:
    """Acquire without blocking the loop and release on failure or cancellation."""
    # FILL IN: user-approved lock algorithm and cancellation cleanup described in Scope.
    raise NotImplementedError
    yield

def detect_fireflies_id(acquired: AcquiredDocument) -> str | None:
    """Find a fireflies:<id> external identity in metadata or text."""
    # FILL IN: AC11 metadata and body forms.
    raise NotImplementedError
```

Continuation of the same file (append directly; no second file):

```python
class InboxProcessor:
    """Compose the ordered per-document pipeline under one whole-run lock."""
    def __init__(self, runtime: InboxRuntime, *, today: date | None = None) -> None:
        """Bind runtime and validate resolved directories before writes."""
        self.runtime = runtime
        self.today = today or date.today()
        self.logger = logging.getLogger(__name__)
        # FILL IN: AC18 layout validation and collaborators.
    def discover(self, *, limit: int | None) -> list[DocumentRef]:
        """Discover safe originals, record skips, sort and apply the limit."""
        # FILL IN: AC1/18; inspect unresolved directory entries before resolve_sources.
        raise NotImplementedError
    async def run(self, *, dry_run: bool = False, limit: int | None = None, force: bool = False,
                  archive: bool = True) -> InboxRunReport:
        """Hold the sole writer lock while processing isolated document outcomes."""
        # FILL IN: async with _inbox_write_lock, discovery, processing, counts, audit (AC1/10/17).
        raise NotImplementedError
    async def process_one(self, ref: DocumentRef, *, dry_run: bool, force: bool, archive: bool) -> InboxDocResult:
        """Run acquire/triage/classify/link/persist/project/verify/archive in order."""
        # FILL IN: AC6-12/16/19-21; never archive a false-success report.
        raise NotImplementedError
    async def verify_persisted(self, source_id: str, doc_id: str, markdown_path: Path,
                               expected_decision: str) -> list[str]:
        """Re-read manifest, children, document and markdown, returning every problem."""
        # FILL IN: destination mapping and AC16 checks; empty problems means verified.
        raise NotImplementedError
```

**Why**: The processor owns locking and verification so direct callers receive the same crash-safety guarantees as the CLI.

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py` (CREATE)

```python
"""Autonomous wiki inbox ingestion public interfaces."""
from parrot.knowledge.wiki.inbox.processor import InboxProcessor, InboxRuntime
from parrot.knowledge.wiki.inbox.models import InboxRunReport, InboxDocResult
__all__ = ["InboxProcessor", "InboxRuntime", "InboxRunReport", "InboxDocResult"]
```

**Why**: Publish the specified public API only once every referenced symbol exists.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/test_processor.py` (CREATE)

```python
"""Focused FEAT-626 regression and failure-path tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.inbox.processor import InboxProcessor, InboxRuntime, InboxLockBusy


def test_processor_order_persist_project_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A projection or verification failure leaves the original and later rows continue."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_processor_discard_archives_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rejects bypass classification/linking and verify their discard record before moving."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_processor_duplicate_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Duplicate input rejects by default; force preserves all remaining policy checks."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_processor_fireflies_updates_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repoint existing source before ingest and preserve its authored document id."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_processor_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No store/source/ADR/projection/archive/git mutations; only DRY_RUN audit."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_verify_persisted_gates_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """False success with missing manifest/claimed child/doc/markdown cannot archive."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_run_holds_write_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeout while another writer holds the lock and release on every exit."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_lock_wait_is_responsive_and_cancellation_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A heartbeat runs during contention and cancellation never leaks the lock."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_discover_skips_symlinks_and_escapes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Report unsafe paths before resolution, skip dotfiles and sort/limit safely."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_no_archive_and_provenance_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Retain original with no-archive and preserve existing metadata while recording archive provenance."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError
```

**Why**: Use temporary files and stub adapters; assert observable state and side effects, never call providers.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_processor.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.

## Acceptance Criteria

- [ ] AC1/10/17/18: Create the Pydantic frozen InboxRuntime (arbitrary_types_allowed=True) and InboxProcessor. Resolve storage_path(root), validate directories in __init__, discover original paths before resolve_sources erases symlinks, skip dotfiles and unsafe paths with report rows, order by (mtime,name), then apply a nonnegative limit.
- [ ] USER-APPROVED OVERRIDE (2026-10-03): processor.run is the sole owner of NONBLOCKING acquisition. This supersedes the blocking-lock prose in spec M7/§6/§7. Use the existing wiki_write_lock(storage_path(root), timeout=0) in off-loop attempts, retry with await asyncio.sleep against a monotonic deadline, and retain the acquired context for the whole run. Never block the loop or reacquire in CLI.
- [ ] Implement a private async context manager for the lock. Shield each offloaded enter attempt; if cancelled while an attempt runs, await its completion and release any acquired context before propagating cancellation. Shield/wait cleanup as well. Close unsuccessful contexts immediately. Timeout raises InboxLockBusy; zero timeout performs one attempt. Acquisition, processing, failure and cancellation all release descriptors.
- [ ] AC11/21: Acquire, detect Fireflies id in metadata.extra/text, look up external identity, and (non-dry-run only) repoint to the inbox path before ingest. Reuse doc id from source metadata.extra.inbox_doc_id or a matching existing authored doc frontmatter/source identity; persist the mapping for subsequent runs. Only generate a slug for a new document identity.
- [ ] AC19/20: Triage with skip_duplicate_check=force, fill decision=proposed_action and auto decision source except heuristic. Discards bypass classify/links and go through orchestrator rejection recording. Dry-run performs acquisition/triage/classify/link planning only, never source repointing, ingest, doc/ADR writes, projection or archiving.
- [ ] AC6/7/8/16: For admitted/archive decisions classify, exclude own doc and prior child ids from link retrieval, ingest with acquired document, reject error reports, write doc/tags/ADR, project markdown and index, then verify. Manifest destination is wiki for admit, archive for archive, discard for discard; there is no manifest decision field. Check every child id, the doc and markdown. Empty legitimate child lists are allowed; missing claimed children/manifests are not.
- [ ] AC9/12/21: Archive only after verification (or verified discard record). Move, repoint, then merge archived_to/archived_at into doc_metadata.extra without losing existing metadata or inbox_doc_id. --no-archive retains originals but performs normal persistence/verification. Report verified=False for rejected/dry-run.
- [ ] One document failure produces a failed row and processing continues; DocumentAcquisitionError produces skipped. Propagate cancellation rather than converting it to a failed row. Write the named classification/doc/tag/ADR/archive/run audit operations only outside dry-run; dry-run writes only DRY_RUN. Offload filesystem, manifest and bookkeeper calls; no source/store schema changes.
- [ ] Prevent duplicate pages on retry after partial persistence: recover source/doc identity before slugging. Check source identity mapping before PageIndex may replace metadata; merge it again afterward. Re-verify path containment immediately before moving/staging an original.
- [ ] All declared tests pass; no unfinished implementation placeholders remain; touched Python files pass ruff check.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_processor.py -q`

Run in the activated repository environment; in a feature worktree set `PYTHONPATH=packages/ai-parrot/src`. Store test logs under `artifacts/logs/`.

## Test Specification

- Use spec-settled Pydantic runtime; mocks must satisfy annotated service classes (spec mocks or typed subclasses), not arbitrary untyped dicts.
- Cancellation tests cover waiting, successful acquisition during cancellation, and cancellation inside process_one. Reacquire from an independent lock context afterward.
- Run an asyncio heartbeat while the lock is contended; verify timeout uses monotonic time and a zero timeout does not sleep.
- For false-success tests populate pages_generated with a missing claimed id; separately verify a legitimately empty list succeeds after doc/projection persistence.
- Snapshot SQLite rows/source metadata, projection paths, originals, git index and audit contents for dry-run; Fireflies dry-run must not repoint the source.
- Stub expensive pipeline collaborators locally; shared suite fixtures are not required for these unit tests.

## Agent Instructions

1. Use `$sdd-start TASK-4054`; let it provision the feature worktree. Do not implement on dev.
2. Read the spec and this task; verify dependencies are done in `sdd/tasks/index/wikitoolkit-new-ingestion.json`.
3. Reverify source contracts before writing. Record discovered drift and refresh this task before relying on a changed API.
4. Implement only declared files. Run the focused validation commands and the normal lint gate.
5. Commit scoped implementation and finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move task files or use legacy close_task.sh.

## Completion Note

Pending. Populated by the finalizer from implementation and validation evidence.
