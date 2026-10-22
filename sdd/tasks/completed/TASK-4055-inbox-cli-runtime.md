# TASK-4055: Expose inbox CLI and factor the ingest runtime safely

**Feature**: FEAT-626 — wikitoolkit inbox autonomous ingestion
**Spec**: `sdd/specs/wikitoolkit-new-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4054
**Assigned-to**: unassigned

## Context

Implements spec §3 M8 for FEAT-626. Source contracts reverified at `18c22a3fd1af1ccf6692be6f795388189e295a76`.
This is a planning artifact; implementation occurs through `$sdd-start` in the feature worktree.

## Scope

- Implement _build_ingest_runtime with the exact spec signature and lazy imports. Preserve model environment fallbacks, PARROT_NO_AUTO_LLM auto-detection, monkeypatch seam _build_triage_adapters, same-provider PageIndex handling, sync_graph and fetch_timeout.
- AC2: Factor construction for ordinary ingest modes into the helper while preserving all existing outputs, options and fields. ingest --review currently applies a manifest even when no charter exists; retain that legacy construction/application branch rather than forcing a required Charter into the fixed helper signature. Existing tests and new no-charter review regression are the oracle.
- AC1/17/18: Add inbox with --path, --dry-run, --limit, --charter, --lightweight-model, --model, --archive/--no-archive, --force, --json. Reject negative limits. Missing inbox or invalid layout exits 2, failed document exits 1, lock contention exits 3, empty/success exits 0.
- The CLI calls processor.run without acquiring a lock. Keep construction lazy and prevent business-data writes during dry-run setup; do not eagerly create PageIndex output or initialize writeful services just to plan. Clean up owned stores/adapters through existing lifecycle patterns on all exit paths.
- --json stdout is one valid InboxRunReport JSON object; route setup diagnostics away from it. Human output includes per-status counts. Preserve startup behavior for unrelated CLI commands and never import decisions or provider clients eagerly.

**NOT in scope**: unrelated refactors, dependency changes, provider SDK calls, MCP implementation, or changes outside the declared files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Scoped M8 deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py` | CREATE | Focused tests/fixtures |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from click.testing import CliRunner
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
```
Verified: packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:54.

```python
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py:31.

```python
from parrot.knowledge.wiki.charter import Charter
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/charter.py:208.

```python
from parrot.knowledge.wiki.charter import load_charter
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/charter.py:303.

```python
from parrot.knowledge.wiki.documents import DocumentAcquirer
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:466.

```python
from parrot.knowledge.wiki.inbox.processor import InboxProcessor, InboxLockBusy
```
Verified: planned in TASK-4054: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py#InboxProcessor; planned in TASK-4054: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py#InboxLockBusy.

```python
from parrot.knowledge.wiki.inbox.processor import InboxRuntime
```
Verified: planned in TASK-4054: packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py#InboxRuntime.

```python
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py:144.

```python
from parrot.knowledge.wiki.models import WikiConfig
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/models.py:52.

```python
from parrot.knowledge.wiki.project import WikiProjectConfig
```
Verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:382.

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
from typing import TYPE_CHECKING
```
Verified: stdlib or existing dependency (pydantic/click/PyYAML/pytest/pytest-asyncio verified in workspace metadata).

```python
import click
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


### Existing Signatures to Use

`sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit`

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:54
class PageIndexToolkit(AbstractToolkit):

    def __init__(
        self,
        adapter: PageIndexLLMAdapter,
        storage_dir: str | Path,
        reranker: Optional[Any] = None,
        lightweight_model: Optional[str] = None,
        model: Optional[str] = None,
        default_bm25_k: int = 20,
        folder_concurrency: int = 4,
        content_cache_size: int = 256,
        embedding_model: Optional[str] = None,
        embedding_dimension: int = 256,
        embedding_backend: Optional[str] = None,
        use_vec_rank: bool = False,
        use_embedding_walk: bool = False,
        **kwargs: Any,
    ):
```

`sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.__init__`

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:92
    def __init__(
        self,
        adapter: PageIndexLLMAdapter,
        storage_dir: str | Path,
        reranker: Optional[Any] = None,
        lightweight_model: Optional[str] = None,
        model: Optional[str] = None,
        default_bm25_k: int = 20,
        folder_concurrency: int = 4,
        content_cache_size: int = 256,
        embedding_model: Optional[str] = None,
        embedding_dimension: int = 256,
        embedding_backend: Optional[str] = None,
        use_vec_rank: bool = False,
        use_embedding_walk: bool = False,
        **kwargs: Any,
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

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_build_novelty_scorer`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4511
def _build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_build_triage_adapters`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4477
def _build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_open_sources`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:521
def _open_sources(
    root: Path,
    config: WikiProjectConfig,
    store: Optional[BaseWikiStore] = None,
) -> SourceCollectionManager:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_open_store`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:464
def _open_store(root: Path, config: WikiProjectConfig) -> BaseWikiStore:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_charter_path`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4430
def _resolve_charter_path(root: Path, charter_opt: str | None) -> Path:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_model_id`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4455
def _resolve_model_id(cli_value: str | None, env_name: str) -> str:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_project`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:367
def _resolve_project(path: str | None) -> tuple[Path, WikiProjectConfig]:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_run`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:560
def _run(coro: Any) -> Any:
```

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ingest`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4794
def ingest(
    source: str,
    path_: str | None,
    charter_opt: str | None,
    dry_run: bool,
    review_opt: Path | None,
    interactive_flag: bool,
    auto_flag: bool,
    extract_flag: bool,
    lightweight_model_opt: str | None,
    model_opt: str | None,
    audit_rate: float,
    manifest_opt: Path | None,
    recursive: bool,
    fetch_timeout: float,
    refresh_flag: bool,
) -> None:
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

`sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore`

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525
class BaseWikiStore(ABC):
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

- The inbox command and _build_ingest_runtime do not exist before this task.
- There is no requirement for a charter in existing ingest --review; do not add one.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py#WikiBookkeeper",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/charter.py#Charter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/charter.py#load_charter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_build_novelty_scorer",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_build_triage_adapters",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_open_sources",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_open_store",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_charter_path",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_model_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_project",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_run",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ingest",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#DocumentAcquirer",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py#WikiIngestOrchestrator",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/models.py#WikiConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/search.py#WikiCombinedSearch",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/triage.py#IngestTriageRouter"
  ]
}
```

## Implementation Notes

Consumes InboxProcessor, InboxRuntime and InboxLockBusy from TASK-4054; no CLI-side lock acquisition.

Follow Python 120-column black formatting, strict annotations and Google-style docstrings. Keep I/O off the event loop. Merge imports into the existing import groups; do not duplicate them. All FILL IN markers are planning-only and must be removed from completed implementation.

## Implementation Blueprint

### Steps (in order)

1. Reverify the quoted contracts and dependency outputs before editing — because concurrently landing features may move anchors.
2. Apply the declared per-file blocks and complete only the bounded gaps in Scope — because public signatures and ownership are fixed.
3. Implement the named failure-path tests using temporary resources and fake model responses — because success-only coverage misses the lifecycle guarantees.
4. Run the exact Validation Commands and lint touched Python files — because unchanged defaults and failure behavior are the acceptance evidence.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)

Verified attachment points (literal `grep -F -c` counts):

- `def _build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any:` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4511`.
- `    pi_toolkit = PageIndexToolkit(` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4944`.
- `    orch = WikiIngestOrchestrator(` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4957`.
- `@wiki.command(name="ingest-jira")` — occurrences: 1; `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:5168`.
```python
# MODIFY: add runtime helper after _build_novelty_scorer and command before ingest-jira.
# Runtime imports remain inside functions; use TYPE_CHECKING for annotation-only imports.
from pathlib import Path
from typing import TYPE_CHECKING
import click
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.sources import SourceCollectionManager
if TYPE_CHECKING:
    from parrot.knowledge.wiki.charter import Charter
    from parrot.knowledge.wiki.inbox.processor import InboxRuntime

def _build_ingest_runtime(root: Path, config: WikiProjectConfig, store: BaseWikiStore,
                          sources: SourceCollectionManager, charter: "Charter", charter_path: Path, *,
                          lightweight_model_opt: str | None, model_opt: str | None,
                          fetch_timeout: float = 30.0) -> "InboxRuntime":
    """Build shared ingestion services with existing model resolution semantics."""
    from parrot.knowledge.wiki.inbox.processor import InboxRuntime
    from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
    from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
    from parrot.knowledge.wiki.triage import IngestTriageRouter
    from parrot.knowledge.wiki.search import WikiCombinedSearch
    from parrot.knowledge.wiki.documents import DocumentAcquirer
    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
    from parrot.knowledge.wiki.models import WikiConfig
    # FILL IN: preserve old construction/model handling and defer writeful setup (AC2/10).
    raise NotImplementedError

@wiki.command()
@click.option("--path", "path_", type=click.Path(file_okay=False, path_type=str), default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--limit", type=click.IntRange(min=0), default=None)
@click.option("--charter", "charter_opt", default=None)
@click.option("--lightweight-model", "lightweight_model_opt", default=None)
@click.option("--model", "model_opt", default=None)
@click.option("--archive/--no-archive", default=True)
@click.option("--force", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def inbox(path_: str | None, dry_run: bool, limit: int | None, charter_opt: str | None,
          lightweight_model_opt: str | None, model_opt: str | None, archive: bool,
          force: bool, as_json: bool) -> None:
    """Ingest the configured inbox, verify persistence and archive originals."""
    from parrot.knowledge.wiki.charter import load_charter
    from parrot.knowledge.wiki.inbox.processor import InboxProcessor, InboxLockBusy
    # FILL IN: AC1/10/17/18 option wiring, clean JSON, exact exits and resource cleanup.
    raise NotImplementedError

# At pi_toolkit/orch construction in ingest: use the helper for non-review modes.
# Keep --review's no-charter behavior and existing diagnostics unchanged (AC2).
```

**Why**: One runtime builder prevents drift while the legacy review exception avoids adding a new charter precondition.

### `packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py` (CREATE)

```python
"""Focused FEAT-626 regression and failure-path tests."""
from pathlib import Path
import pytest
from click.testing import CliRunner
import parrot.knowledge.wiki.cli as wiki_cli


def test_cli_inbox_options_and_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover success/empty=0, failed=1, missing/invalid=2 and busy=3."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_cli_json_stdout_is_report_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parse stdout as one JSON object even with model detection diagnostics."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_cli_forwards_options_without_double_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Forward every option and assert the CLI never takes the processor lock."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_ingest_unchanged_after_runtime_factoring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ingest model selection/output and persisted field behavior."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_ingest_review_without_charter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Apply an existing review manifest without requiring a charter file."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError

def test_cli_dry_run_has_no_setup_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Planning must not create PageIndex output or mutate sources."""
    # FILL IN: Arrange isolated fakes and assert this named behavior; see Test Specification.
    raise NotImplementedError
```

**Why**: Use temporary files and stub adapters; assert observable state and side effects, never call providers.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py` — complete the bounded behavior and test assertions above; preserve fixed signatures and remove planning markers.

## Acceptance Criteria

- [ ] Implement _build_ingest_runtime with the exact spec signature and lazy imports. Preserve model environment fallbacks, PARROT_NO_AUTO_LLM auto-detection, monkeypatch seam _build_triage_adapters, same-provider PageIndex handling, sync_graph and fetch_timeout.
- [ ] AC2: Factor construction for ordinary ingest modes into the helper while preserving all existing outputs, options and fields. ingest --review currently applies a manifest even when no charter exists; retain that legacy construction/application branch rather than forcing a required Charter into the fixed helper signature. Existing tests and new no-charter review regression are the oracle.
- [ ] AC1/17/18: Add inbox with --path, --dry-run, --limit, --charter, --lightweight-model, --model, --archive/--no-archive, --force, --json. Reject negative limits. Missing inbox or invalid layout exits 2, failed document exits 1, lock contention exits 3, empty/success exits 0.
- [ ] The CLI calls processor.run without acquiring a lock. Keep construction lazy and prevent business-data writes during dry-run setup; do not eagerly create PageIndex output or initialize writeful services just to plan. Clean up owned stores/adapters through existing lifecycle patterns on all exit paths.
- [ ] --json stdout is one valid InboxRunReport JSON object; route setup diagnostics away from it. Human output includes per-status counts. Preserve startup behavior for unrelated CLI commands and never import decisions or provider clients eagerly.
- [ ] All declared tests pass; no unfinished implementation placeholders remain; touched Python files pass ruff check.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q`
- `pytest tests/knowledge/wiki/test_ingest.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_hook_startup.py -q`

Run in the activated repository environment; in a feature worktree set `PYTHONPATH=packages/ai-parrot/src`. Store test logs under `artifacts/logs/`.

## Test Specification

- Use CliRunner and monkeypatch _build_triage_adapters. Keep all tests offline; inspect output and persisted state, not only mock call counts.
- Exercise differing providers and missing model configuration; preserve preexisting ingest diagnostic strings.
- Use monkeypatched runtime for option/exit tests and real temporary configuration for layout and no-charter review regression.

## Agent Instructions

1. Use `$sdd-start TASK-4055`; let it provision the feature worktree. Do not implement on dev.
2. Read the spec and this task; verify dependencies are done in `sdd/tasks/index/wikitoolkit-new-ingestion.json`.
3. Reverify source contracts before writing. Record discovered drift and refresh this task before relying on a changed API.
4. Implement only declared files. Run the focused validation commands and the normal lint gate.
5. Commit scoped implementation and finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move task files or use legacy close_task.sh.

## Completion Note

Pending. Populated by the finalizer from implementation and validation evidence.


### Completion Note (orchestrator)
Seat: gpt-5.6-terra (codex). Review fix 166ea6001: InboxRuntime isinstance-validated adapters and broke 16 existing ingest tests (AC2); adapters now SkipValidation. feedback_id coder-feedback:dfb214068922a1c31b52dd47. Merge-tier sweep: 22 remaining failures in tests/knowledge/wiki (mcp_server, hook_startup, installer_mcp, bookstore graph, ...) are IDENTICAL on the merge-base ff34424bd (verified with compiled .so present), i.e. pre-existing; see ledger issue.
