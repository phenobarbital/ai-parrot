# Feature Specification: Vector Store Handler API

**Feature ID**: FEAT-087
**Date**: 2026-04-07
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Brainstorm**: `sdd/proposals/vectorstore-handler-api.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

Developers and frontend applications need a REST API to create, manage, load data into, and test vector store collections without writing Python code. Currently, all vector store operations require direct use of `PgVectorStore`, loaders, and `AbstractBot.define_store_config()` — all Python-only paths. This blocks non-Python frontends and centralized management tools from leveraging AI-Parrot's RAG infrastructure.

### Goals

- Provide a complete REST API at `/api/v1/ai/stores` for vector store lifecycle management
- Support collection creation/preparation across all supported vector stores
- Support data loading from file uploads, inline JSON content, and URLs (including YouTube)
- Provide search testing (similarity + MMR) with wrapped results
- Expose metadata helpers (supported stores, embeddings, loaders, index types) as public endpoints
- Use background jobs for long-running operations (file processing, scraping, video/image understanding)

### Non-Goals (explicitly out of scope)

- Multi-tenancy / per-user store isolation (future work)
- DELETE endpoint for dropping collections or tables
- Listing records within a vector store
- Real-time streaming of search results
- Store connection pooling at the framework level (handler-level cache only)

---

## 2. Architectural Design

### Overview

A single `VectorStoreHandler(BaseView)` class handles authenticated CRUD operations (POST, PUT, PATCH) on vector stores. A companion `VectorStoreHelper(BaseHandler)` serves unauthenticated GET endpoints for metadata. Long-running PUT operations are dispatched to a handler-owned `JobManager(id="vectorstore")` instance. A store connection cache (dict keyed by store type + DSN, max-size eviction) avoids re-instantiating stores per request. File uploads use `TempFileManager` for temporary storage with automatic cleanup.

### Component Diagram

```
                         /api/v1/ai/stores
                               │
              ┌────────────────┼────────────────┐
              │                │                │
         GET (public)    POST/PUT/PATCH    GET /jobs/{id}
              │          (authenticated)        │
              ▼                │                ▼
   VectorStoreHelper           │         VectorStoreHandler
   (BaseHandler)               ▼         (reads job status)
   - supported stores    VectorStoreHandler
   - supported embeds    (BaseView)
   - supported loaders         │
   - index types         ┌─────┼──────┐
                         │     │      │
                      POST   PUT   PATCH
                      create  load  search
                         │     │      │
                         ▼     ▼      ▼
                    ┌─────────────────────┐
                    │  _get_store(config)  │
                    │  (connection cache)  │
                    └────────┬────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
         PgVectorStore  BigQueryStore  MilvusStore ...
                             │
                    ┌────────┼────────┐
                    │        │        │
               Loaders   Scraping   Direct
               (PDF,     (URL,      (JSON
                CSV...)   YouTube)   content)
                    │        │        │
                    └────────┼────────┘
                             │
                     JobManager (async)
                     or immediate return
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.views.BaseView` | extends | Handler inherits for HTTP method dispatch |
| `navigator.views.BaseHandler` | extends | Helper inherits for function-based GET |
| `navigator_auth.decorators` | uses | `@is_authenticated()` on VectorStoreHandler |
| `parrot.stores.AbstractStore` | uses | All store operations via polymorphic interface |
| `parrot.stores.models.StoreConfig` | uses | Request body deserialization for store config |
| `parrot.handlers.jobs.JobManager` | uses | Handler-owned instance for background tasks |
| `parrot.interfaces.file.tmp.TempFileManager` | uses | Temporary file storage for uploads |
| `parrot_loaders.factory` | uses | Dynamic loader resolution by file extension |
| `parrot_tools.scraping` | uses | URL content extraction and site crawling |
| `parrot.interfaces.vector.VectorInterface._get_database_store` | adapts | Store instantiation logic copied into handler helper |
| `app.py` | extends | Route registration via `VectorStoreHandler.setup(app)` |
| `parrot.conf` | extends | New `VECTOR_HANDLER_MAX_FILE_SIZE` config variable |

### Data Models

```python
# Request model for POST (create collection)
# Sent as JSON body; extends StoreConfig with control flags
{
    "vector_store": "postgres",       # from StoreConfig
    "table": "employee_information",
    "schema": "mso",
    "embedding_model": {"model": "thenlper/gte-base", "model_type": "huggingface"},
    "dimension": 768,
    "dsn": null,                      # optional; falls back to async_default_dsn for postgres
    "index_type": "COSINE",
    "metric_type": "L2",
    "extra": {},                      # store-specific params (e.g., BigQuery project_id)
    "no_drop_table": false            # if true, skip delete_collection, only prepare_embedding_table
}

# Request model for PATCH (test search)
{
    "vector_store": "postgres",
    "table": "employee_information",
    "schema": "mso",
    "embedding_model": {"model": "thenlper/gte-base", "model_type": "huggingface"},
    "dimension": 768,
    "dsn": null,
    "query": "Maximum paid time off",
    "method": "both",                 # "similarity", "mmr", or "both"
    "k": 5                            # optional, default 5
}

# Response wrapper for PATCH search results
{
    "query": "Maximum paid time off",
    "method": "both",
    "count": 5,
    "results": [SearchResult...]      # serialized SearchResult objects
}

# Response for PUT when background job is dispatched
{
    "job_id": "uuid-string",
    "status": "pending",
    "message": "Data loading started in background"
}

# Response for PUT when immediate (inline content)
{
    "status": "loaded",
    "documents": 3
}

# Job status response
{
    "job_id": "uuid-string",
    "status": "running|completed|failed",
    "result": {...},                  # present when completed
    "error": "...",                   # present when failed
    "elapsed_time": 12.5             # seconds, if available
}
```

### New Public Interfaces

```python
# parrot/handlers/stores/handler.py
@is_authenticated()
@user_session()
class VectorStoreHandler(BaseView):
    """REST API for vector store lifecycle management."""

    @classmethod
    def setup(cls, app: web.Application) -> None: ...

    async def post(self) -> web.Response:
        """Create or prepare a vector store collection."""

    async def put(self) -> web.Response:
        """Load data into a collection (file upload, URL, or JSON)."""

    async def patch(self) -> web.Response:
        """Test search against a collection."""

    async def get(self) -> web.Response:
        """Get job status by job_id."""


# parrot/handlers/stores/helpers.py
class VectorStoreHelper(BaseHandler):
    """Public metadata endpoints for vector store configuration."""

    @staticmethod
    def supported_stores() -> dict: ...

    @staticmethod
    def supported_embeddings() -> dict: ...

    @staticmethod
    def supported_loaders() -> dict: ...

    @staticmethod
    def supported_index_types() -> list: ...
```

---

## 3. Module Breakdown

### Module 1: Configuration Variable
- **Path**: `parrot/conf.py`
- **Responsibility**: Add `VECTOR_HANDLER_MAX_FILE_SIZE` config variable (default 25MB)
- **Depends on**: nothing

### Module 2: Helper (VectorStoreHelper)
- **Path**: `parrot/handlers/stores/helpers.py`
- **Responsibility**: Unauthenticated GET endpoints returning supported stores, embeddings, loaders, and index types. Implements a `BaseHandler` with static methods.
- **Depends on**: `parrot.stores.supported_stores`, `parrot.embeddings.supported_embeddings`, `parrot_loaders.factory.LOADER_MAPPING`, `parrot.stores.models.DistanceStrategy`

### Module 3: Store Connection Cache
- **Path**: `parrot/handlers/stores/handler.py` (private helper within handler)
- **Responsibility**: `_get_store(config: StoreConfig) -> AbstractStore` method that instantiates stores using `VectorInterface._get_database_store` logic. Maintains a max-size `OrderedDict` cache keyed by `(vector_store, dsn_or_equivalent)`. Handles DSN fallback to `async_default_dsn` for postgres. Maps `StoreConfig.schema` to `dataset` for BigQuery. **On cache eviction (max-size exceeded), MUST call `await store.disconnect()` on the evicted instance.** After instantiation, MUST call `await store.connection()` to establish the connection before returning.
- **Depends on**: Module 1, `parrot.stores.supported_stores`, `parrot.interfaces.vector.VectorInterface._get_database_store` (logic adapted, not called directly)

### Module 4: Handler Core (VectorStoreHandler)
- **Path**: `parrot/handlers/stores/handler.py`
- **Responsibility**: Class-based view handling POST (create collection), PATCH (search test), and the `setup()` classmethod for route registration and lifecycle management. **`_on_cleanup` signal MUST: (1) iterate all cached store instances and call `await store.disconnect()` on each, (2) stop JobManager, (3) cleanup TempFileManager.** This ensures no leaked database connections, Milvus sockets, or BigQuery clients on app shutdown.
- **Depends on**: Modules 1, 2, 3, `parrot.handlers.jobs.JobManager`, `parrot.interfaces.file.tmp.TempFileManager`

### Module 5: Data Loading (PUT endpoint)
- **Path**: `parrot/handlers/stores/handler.py` (PUT method + private helpers)
- **Responsibility**: PUT endpoint handling file uploads (multipart/form-data), JSON inline content, and URL processing. Routes to appropriate loaders via `get_loader_class()`. Dispatches long-running tasks to JobManager. Handles special cases: `.json` files via `JSONDataSource`, YouTube URLs via `YoutubeLoader`, web URLs via `WebScrapingTool`/`CrawlEngine`, images/videos with optional prompt. Supports multiple file uploads per request. Enforces `VECTOR_HANDLER_MAX_FILE_SIZE`.
- **Depends on**: Modules 3, 4, `parrot_loaders.factory`, `parrot_loaders.extractors.json_source.JSONDataSource`, `parrot_tools.scraping.WebScrapingTool`, `parrot_tools.scraping.CrawlEngine`

### Module 6: Package Init & Route Registration
- **Path**: `parrot/handlers/stores/__init__.py` + `app.py`
- **Responsibility**: Package exports and route registration via `VectorStoreHandler.setup(app)` in `app.py`. Add lazy import in `parrot/handlers/__init__.py`.
- **Depends on**: Modules 2, 4, 5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_helper_supported_stores` | Module 2 | Returns correct store dict from `supported_stores` |
| `test_helper_supported_embeddings` | Module 2 | Returns correct embeddings dict |
| `test_helper_supported_loaders` | Module 2 | Returns loader mapping with cleaned extension→class format |
| `test_helper_index_types` | Module 2 | Returns list of DistanceStrategy values |
| `test_get_store_postgres_default_dsn` | Module 3 | Falls back to `async_default_dsn` when no DSN provided for postgres |
| `test_get_store_cache_hit` | Module 3 | Same config returns cached store instance |
| `test_get_store_cache_eviction` | Module 3 | Cache evicts oldest entry when max-size exceeded |
| `test_get_store_eviction_disconnects` | Module 3 | Evicted store has `disconnect()` called |
| `test_get_store_reconnect_on_stale` | Module 3 | Cache hit with `_connected=False` triggers `connection()` |
| `test_cleanup_disconnects_all_stores` | Module 4 | `_on_cleanup` calls `disconnect()` on every cached store |
| `test_get_store_bigquery_schema_mapping` | Module 3 | Maps `StoreConfig.schema` to BigQuery `dataset` parameter |
| `test_file_size_validation` | Module 5 | Rejects files exceeding `VECTOR_HANDLER_MAX_FILE_SIZE` |
| `test_loader_detection_by_extension` | Module 5 | Correctly resolves loader class from file extension |
| `test_json_file_routes_to_json_datasource` | Module 5 | `.json` files use `JSONDataSource`, not `MarkdownLoader` |
| `test_inline_content_creates_document` | Module 5 | JSON body with `content` creates Document directly |
| `test_default_prompt_for_image` | Module 5 | Image upload without prompt uses handler default |

### Integration Tests

| Test | Description |
|---|---|
| `test_create_collection_postgres` | POST creates a postgres collection and returns success |
| `test_create_collection_no_drop` | POST with `no_drop_table=true` only prepares embedding table |
| `test_search_similarity` | PATCH with `method=similarity` returns wrapped SearchResult list |
| `test_search_mmr` | PATCH with `method=mmr` returns MMR results |
| `test_load_inline_content` | PUT with JSON `content` field loads document immediately |
| `test_load_file_upload` | PUT with multipart PDF returns immediate result |
| `test_load_url_background_job` | PUT with URL list returns job_id, job completes |
| `test_job_status_lifecycle` | GET /jobs/{id} returns pending → running → completed |
| `test_helper_endpoints_no_auth` | GET metadata endpoints work without authentication |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_store_config():
    return {
        "vector_store": "postgres",
        "table": "test_collection",
        "schema": "public",
        "embedding_model": {
            "model": "thenlper/gte-base",
            "model_type": "huggingface"
        },
        "dimension": 768,
        "index_type": "COSINE",
        "metric_type": "L2"
    }

@pytest.fixture
def sample_search_request(sample_store_config):
    return {
        **sample_store_config,
        "query": "test search query",
        "method": "similarity",
        "k": 5
    }
```

---

## 5. Acceptance Criteria

- [ ] POST `/api/v1/ai/stores` creates a collection for any store in `supported_stores`
- [ ] POST with `no_drop_table=true` skips `delete_collection` and only calls `prepare_embedding_table`
- [ ] PUT `/api/v1/ai/stores` loads data from file upload (multipart/form-data)
- [ ] PUT loads data from inline JSON content (`{"content": "..."}`)
- [ ] PUT loads data from URL list (dispatched as background job)
- [ ] PUT handles YouTube URLs via `YoutubeLoader`
- [ ] PUT handles image/video uploads with optional prompt (background job)
- [ ] PUT handles `.json` files via `JSONDataSource` (not MarkdownLoader)
- [ ] PUT supports multiple file uploads per request
- [ ] PUT rejects files exceeding `VECTOR_HANDLER_MAX_FILE_SIZE` (25MB default)
- [ ] PATCH `/api/v1/ai/stores` performs similarity and/or MMR search with wrapped response
- [ ] GET `/api/v1/ai/stores?resource=stores|embeddings|loaders|index_types` returns metadata without auth
- [ ] GET `/api/v1/ai/stores/jobs/{job_id}` returns job status
- [ ] Handler manages its own `JobManager(id="vectorstore")` with startup/cleanup lifecycle
- [ ] Store connection cache uses max-size eviction with `await store.disconnect()` on evicted entries
- [ ] `_on_cleanup` signal disconnects ALL cached store instances before clearing the cache
- [ ] Cache hit on a disconnected store (`_connected=False`) triggers `await store.connection()` to reconnect
- [ ] Postgres stores fall back to `async_default_dsn` when no DSN provided
- [ ] BigQuery stores map `StoreConfig.schema` to `dataset` parameter
- [ ] All authenticated endpoints use `@is_authenticated()` decorator
- [ ] Error responses follow `{"error": "...", "detail": "..."}` format
- [ ] No breaking changes to existing handlers or stores

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# Store layer
from parrot.stores import AbstractStore, supported_stores          # parrot/stores/__init__.py:1-10
from parrot.stores.models import StoreConfig, SearchResult, Document, DistanceStrategy  # parrot/stores/models.py:1-59

# Embeddings
from parrot.embeddings import supported_embeddings, EmbeddingRegistry  # parrot/embeddings/__init__.py:1-10

# Job management
from parrot.handlers.jobs import JobManager, JobStatus             # parrot/handlers/jobs/__init__.py:1-12
from parrot.handlers.jobs.job import JobManager                    # parrot/handlers/jobs/job.py:22

# File management
from parrot.interfaces.file.tmp import TempFileManager             # parrot/interfaces/file/tmp.py:15

# Loaders
from parrot_loaders.factory import LOADER_MAPPING, get_loader_class  # parrot_loaders/factory.py:12-73
from parrot_loaders.extractors.json_source import JSONDataSource   # parrot_loaders/extractors/json_source.py:12

# Scraping tools
from parrot_tools.scraping import WebScrapingTool, CrawlEngine     # parrot_tools/scraping/__init__.py

# Configuration
from parrot.conf import async_default_dsn                          # parrot/conf.py:57

# Framework
from aiohttp import web                                            # aiohttp
from navigator.views import BaseView, BaseHandler                  # navigator.views (installed package)
from navigator_auth.decorators import is_authenticated, user_session  # navigator_auth (installed package)
from navconfig.logging import logging                              # navconfig (installed package)
from datamodel.parsers.json import json_encoder                    # datamodel (installed package)
```

### Existing Class Signatures

```python
# parrot/stores/abstract.py:17-135 — Base class for ALL stores
class AbstractStore(ABC):
    _connected: bool = False                                             # line 41
    _connection: Any = None                                              # line 80
    @abstractmethod
    async def connection(self) -> tuple:                                  # line 117
        """Establish connection. Must be called after instantiation."""
    @abstractmethod
    async def disconnect(self) -> None:                                  # line 127
        """Close connection and cleanup resources."""
    async def __aenter__(self):                                          # line 131
        """Context manager calls connection() if not connected."""
    async def __aexit__(self, *args):                                    # line 135+
        """Context manager calls disconnect()."""

# parrot/stores/models.py:42-59
@dataclass
class StoreConfig:
    vector_store: str = 'postgres'                                   # line 44
    table: Optional[str] = None                                      # line 45
    schema: str = 'public'                                           # line 46
    embedding_model: Union[str, dict] = field(default_factory=...)   # line 47
    dimension: int = 768                                             # line 53
    dsn: Optional[str] = None                                        # line 54
    distance_strategy: str = 'COSINE'                                # line 55
    metric_type: str = 'COSINE'                                      # line 56
    index_type: str = 'IVF_FLAT'                                     # line 57
    auto_create: bool = False                                        # line 58
    extra: Dict[str, Any] = field(default_factory=dict)              # line 59

# parrot/stores/models.py:7-18
class SearchResult(BaseModel):
    id: str                                                          # line 11
    content: str                                                     # line 12
    metadata: Dict[str, Any] = Field(default_factory=dict)           # line 13
    score: float                                                     # line 14
    ensemble_score: float = None                                     # line 15
    search_source: str = None                                        # line 16
    similarity_rank: Optional[int] = None                            # line 17
    mmr_rank: Optional[int] = None                                   # line 18

# parrot/stores/models.py:21-27
class Document(BaseModel):
    page_content: str                                                # line 26
    metadata: Dict[str, Any] = Field(default_factory=dict)           # line 27

# parrot/stores/models.py:30-38
class DistanceStrategy(str, Enum):
    EUCLIDEAN_DISTANCE = "EUCLIDEAN_DISTANCE"                        # line 34
    MAX_INNER_PRODUCT = "MAX_INNER_PRODUCT"                          # line 35
    DOT_PRODUCT = "DOT_PRODUCT"                                      # line 36
    JACCARD = "JACCARD"                                              # line 37
    COSINE = "COSINE"                                                # line 38

# parrot/stores/postgres.py:56-113
class PgVectorStore(AbstractStore):
    def __init__(self, table=None, schema='public', id_column='id',
                 embedding_column='embedding', document_column='document',
                 text_column='text', embedding_model=..., embedding=None,
                 distance_strategy=DistanceStrategy.COSINE, use_uuid=False,
                 pool_size=50, auto_initialize=True, enable_colbert=False, **kwargs)  # line 61
    async def create_collection(self, table, schema='public', dimension=768,
                                 index_type="COSINE", metric_type='L2',
                                 id_column=None, **kwargs) -> None               # line 2804
    async def delete_collection(self, table, schema='public') -> None            # line 2772
    async def collection_exists(self, table, schema='public') -> bool            # line 2747
    async def prepare_embedding_table(self, table, schema='public', conn=None,
                                       id_column='id', embedding_column='embedding',
                                       document_column='document', metadata_column='cmetadata',
                                       dimension=768, colbert_dimension=128,
                                       use_jsonb=True, drop_columns=False,
                                       create_all_indexes=True, **kwargs) -> bool  # line 808
    async def add_documents(self, documents, table=None, schema=None,
                             embedding_column='embedding', content_column='document',
                             metadata_column='cmetadata', **kwargs) -> None       # line 498
    async def similarity_search(self, query, table=None, schema=None, k=None,
                                 limit=None, metadata_filters=None,
                                 score_threshold=None, metric=None,
                                 embedding_column='embedding',
                                 content_column='document',
                                 metadata_column='cmetadata', id_column='id',
                                 additional_columns=None) -> List[SearchResult]   # line 634
    async def mmr_search(self, query, table=None, schema=None, k=10,
                          fetch_k=None, lambda_mult=0.5,
                          metadata_filters=None, score_threshold=None,
                          metric=None, embedding_column='embedding',
                          content_column='document', metadata_column='cmetadata',
                          id_column='id',
                          additional_columns=None) -> List[SearchResult]          # line 1670

# parrot/stores/bigquery.py:23-78
class BigQueryStore(AbstractStore):
    def __init__(self, table=None, dataset=None, project_id=None,
                 credentials=None, id_column='id', embedding_column='embedding',
                 document_column='document', text_column='text',
                 metadata_column='metadata', embedding_model=..., embedding=None,
                 distance_strategy=DistanceStrategy.COSINE,
                 auto_initialize=True, **kwargs)                                  # line 29
    async def create_collection(self, table, dataset=None, dimension=768,
                                 id_column=None, embedding_column=None,
                                 document_column=None, metadata_column=None,
                                 **kwargs) -> None                                # line 238
    async def collection_exists(self, table, dataset=None) -> bool               # line 224
    async def delete_collection(self, table, dataset=None) -> None               # line 1278
    async def add_documents(self, documents, table=None, dataset=None,
                             embedding_column='embedding', content_column='document',
                             metadata_column='metadata', **kwargs) -> None        # line 449
    async def similarity_search(self, query, table=None, dataset=None, k=None,
                                 limit=None, metadata_filters=None,
                                 score_threshold=None, metric=None, ...) -> List[SearchResult]  # line 583
    async def mmr_search(self, query, table=None, dataset=None, k=10,
                          fetch_k=None, lambda_mult=0.5, ...) -> List[SearchResult]  # line 701

# parrot/handlers/jobs/job.py:22-57
class JobManager:
    def __init__(self, id="default", cleanup_interval=3600,
                 job_ttl=86400, store=None)                                       # line 42
    async def start(self) -> None                                                # method
    async def stop(self) -> None                                                 # method
    def create_job(self, job_id, obj_id, query, user_id=None,
                   session_id=None, execution_mode=None) -> Job                  # method
    async def execute_job(self, job_id, execution_func) -> None                  # method
    def get_job(self, job_id) -> Optional[Job]                                   # method
    def list_jobs(self, obj_id=None, status=None, limit=100) -> list             # method

# parrot/handlers/jobs/models.py:6-12
class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

# parrot/handlers/jobs/models.py:15-117
@dataclass
class Job:
    job_id: str
    obj_id: str
    query: Union[str, Dict[str, str]]
    status: JobStatus = JobStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    execution_mode: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    @property
    def is_finished(self) -> bool: ...
    @property
    def is_failed(self) -> bool: ...
    @property
    def elapsed_time(self) -> Optional[float]: ...

# parrot/interfaces/file/tmp.py:15-310
class TempFileManager:
    def __init__(self, prefix="ai_parrot_", cleanup_on_exit=True,
                 cleanup_on_delete=True)                                          # line 15
    async def upload_file(self, source, destination) -> FileMetadata              # method
    async def create_from_bytes(self, path, source, encoding='utf-8') -> FileMetadata  # method
    async def delete_file(self, path) -> bool                                    # method
    async def exists(self, path) -> bool                                         # method
    def cleanup(self) -> None                                                    # method

# parrot_loaders/imageunderstanding.py:81
class ImageUnderstandingLoader(AbstractLoader):
    def __init__(self, source=None, *, model=GoogleModel.GEMINI_3_1_FLASH_IMAGE_PREVIEW,
                 temperature=0.2, prompt=None, custom_instructions=None,
                 language="en", detect_objects=False, **kwargs)
    async def load(self) -> List[Document]: ...   # inherited from AbstractLoader

# parrot_loaders/videounderstanding.py:100
class VideoUnderstandingLoader(BaseVideoLoader):
    def __init__(self, source=None, *, model=GoogleModel.GEMINI_3_PRO_PREVIEW,
                 temperature=0.2, prompt=None, custom_instructions=None, **kwargs)
    async def load(self) -> List[Document]: ...   # inherited

# parrot_loaders/extractors/json_source.py:12
class JSONDataSource(ExtractDataSource):
    async def extract(self, fields=None, filters=None) -> ExtractionResult

# parrot_tools/scraping/tool.py:119
class WebScrapingTool(AbstractTool):
    async def execute_scraping_workflow(self, ...) -> Any

# parrot_tools/scraping/crawler.py:24
class CrawlEngine:
    def __init__(self, scrape_fn, strategy=None, follow_selector="a[href]",
                 follow_pattern=None, allow_external=False,
                 concurrency=1, logger=None)                                      # line 24
    async def run(self, start_url, plan, depth=1, max_pages=None) -> CrawlResult

# parrot/interfaces/vector.py:42-75  (logic to adapt, not call directly)
class VectorInterface:
    def _get_database_store(self, store: dict) -> AbstractStore:
        # Uses supported_stores to resolve class name
        # Dynamically imports from parrot.stores.<name>
        # Passes embedding_model and embedding to constructor
        # Returns instantiated store

# BaseView.handle_upload — navigator.views.base (installed package)
async def handle_upload(self, request=None, form_key=None,
                         ext='.csv', preserve_filenames=True
                         ) -> Tuple[Dict[str, List[dict]], dict]
    # Returns: (files_dict, form_fields_dict)
    # files_dict[field_name] = [{"file_path": Path, "file_name": str, "mime_type": str}]
```

### Key Constants & Attributes

- `supported_stores` → `dict` (`parrot/stores/__init__.py:3`) — `{'postgres': 'PgVectorStore', 'milvus': 'MilvusStore', 'kb': 'KnowledgeBaseStore', 'faiss_store': 'FaissStore', 'arango': 'ArangoStore', 'bigquery': 'BigQueryStore'}`
- `supported_embeddings` → `dict` (`parrot/embeddings/__init__.py:3`) — `{'huggingface': 'SentenceTransformerModel', 'google': 'GoogleEmbeddingModel', 'openai': 'OpenAIEmbeddingModel'}`
- `LOADER_MAPPING` → `dict` (`parrot_loaders/factory.py:12`) — maps file extensions to `(module_name, class_name)` tuples
- `async_default_dsn` → `str` (`parrot/conf.py:57`) — default PostgreSQL async DSN
- `json_encoder` → callable (`datamodel.parsers.json`) — JSON serializer used in responses
- `AbstractStore._connected` → `bool` (`parrot/stores/abstract.py:41`) — whether store has active connection
- `AbstractStore._connection` → `Any` (`parrot/stores/abstract.py:80`) — underlying connection object

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `VectorStoreHandler._get_store()` | `PgVectorStore.__init__()` | dynamic import + instantiation | `parrot/interfaces/vector.py:42-75` (pattern) |
| `VectorStoreHandler.post()` | `AbstractStore.create_collection()` | method call | `parrot/stores/postgres.py:2804` |
| `VectorStoreHandler.post()` | `AbstractStore.prepare_embedding_table()` | method call | `parrot/stores/postgres.py:808` |
| `VectorStoreHandler.post()` | `AbstractStore.collection_exists()` | method call | `parrot/stores/postgres.py:2747` |
| `VectorStoreHandler.post()` | `AbstractStore.delete_collection()` | method call | `parrot/stores/postgres.py:2772` |
| `VectorStoreHandler.put()` | `AbstractStore.add_documents()` | method call | `parrot/stores/postgres.py:498` |
| `VectorStoreHandler.put()` | `get_loader_class(ext)` | function call | `parrot_loaders/factory.py:50` |
| `VectorStoreHandler.put()` | `BaseView.handle_upload()` | inherited method | `navigator.views.base` (installed) |
| `VectorStoreHandler.put()` | `JobManager.create_job()` / `execute_job()` | method call | `parrot/handlers/jobs/job.py` |
| `VectorStoreHandler.patch()` | `AbstractStore.similarity_search()` | method call | `parrot/stores/postgres.py:634` |
| `VectorStoreHandler.patch()` | `AbstractStore.mmr_search()` | method call | `parrot/stores/postgres.py:1670` |
| `VectorStoreHandler.get()` | `JobManager.get_job()` | method call | `parrot/handlers/jobs/job.py` |
| `VectorStoreHelper` | `supported_stores`, `supported_embeddings`, `LOADER_MAPPING` | dict access | see constants above |
| `VectorStoreHandler.setup()` | `app.router.add_view()` | route registration | `parrot/handlers/scraping/handler.py:392` (pattern) |
| `VectorStoreHandler.setup()` | `app.on_startup` / `app.on_cleanup` | lifecycle hooks | `parrot/handlers/scraping/handler.py:403-404` (pattern) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.stores.create_store_from_config()`~~ — no factory function; must adapt `VectorInterface._get_database_store()` logic
- ~~`parrot.stores.StorePool`~~ — no connection pooling exists for stores
- ~~`parrot.conf.VECTOR_HANDLER_MAX_FILE_SIZE`~~ — does not exist yet; must be added in Module 1
- ~~`AbstractStore.from_config(config: StoreConfig)`~~ — no classmethod on AbstractStore to create from StoreConfig
- ~~`parrot.handlers.stores`~~ — this package does not exist yet; must be created
- ~~`StoreConfig.to_store()`~~ — StoreConfig has no method to instantiate a store
- ~~`LOADER_MAPPING['.json'] -> JSONDataSource`~~ — `.json` maps to `('markdown', 'MarkdownLoader')`; handler must special-case `.json` files to route to `JSONDataSource`
- ~~`AbstractStore.connection_pool`~~ — no built-in pooling attribute
- ~~`BaseView.get_job_manager()`~~ — no such method; access via `self.request.app[key]` or handler-owned instance

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Handler lifecycle**: Follow `ScrapingHandler.setup()` pattern exactly (`parrot/handlers/scraping/handler.py:384-434`) — `classmethod setup()` registers routes and hooks `_on_startup`/`_on_cleanup` static methods
- **Error responses**: Use `self.json_response({"error": "...", "detail": "..."}, status=NNN)` pattern from existing handlers
- **JSON serialization**: Use `datamodel.parsers.json.json_encoder` for responses containing complex objects (datetimes, enums)
- **Authentication**: Apply `@is_authenticated()` and `@user_session()` decorators on `VectorStoreHandler` class, NOT on `VectorStoreHelper`
- **Logging**: Use `self.logger = logging.getLogger("Parrot.VectorStoreHandler")` in `post_init()`
- **Store instantiation**: Adapt logic from `VectorInterface._get_database_store()` (`parrot/interfaces/vector.py:42-75`) into a private `_get_store()` method; use `importlib.import_module()` to dynamically load store classes from `parrot.stores.<name>`

### Store Connection Cache Design

```
Cache key: (config.vector_store, config.dsn or "default")
Cache type: OrderedDict with max-size eviction
Max size: configurable, default 10
Eviction: remove oldest entry when full (FIFO)
On eviction: call await store.disconnect() on evicted instance
On app cleanup (_on_cleanup signal):
  - iterate ALL cached stores
  - call await store.disconnect() on each (with try/except per store)
  - clear the cache dict
After instantiation: call await store.connection() before returning
Reconnection: if store._connected is False on cache hit, call await store.connection() again
```

**Lifecycle summary:**
```
_on_startup  → create empty cache dict
_get_store() → cache miss: instantiate + connection() + cache
             → cache hit + connected: return cached
             → cache hit + disconnected: reconnect via connection()
             → cache full: evict oldest → disconnect() → add new
_on_cleanup  → for each cached store: disconnect() → clear cache
```

### File Upload Flow

```
1. handle_upload() → files_dict + form_fields
2. Check file size against VECTOR_HANDLER_MAX_FILE_SIZE
3. Save to TempFileManager
4. Determine loader:
   - .json → JSONDataSource (special case)
   - image extensions → ImageUnderstandingLoader (background job)
   - video extensions → VideoUnderstandingLoader (background job)
   - all others → get_loader_class(ext) (immediate for small/fast loaders)
5. Load documents → store.add_documents()
6. Cleanup temp file
```

### URL Processing Flow

```
1. Extract URL list from JSON body
2. For each URL:
   - YouTube URL (contains "youtube.com" or "youtu.be") → YoutubeLoader
   - Other URL → WebScrapingTool or CrawlEngine (if crawl_entire_site=true)
3. Always dispatched as background job
4. Collect documents → store.add_documents()
```

### Known Risks / Gotchas

- **Store connection lifecycle**: Stores require `await store.connection()` after instantiation. Cache must: (1) connect on first use, (2) reconnect on cache hit if `_connected=False`, (3) disconnect all on eviction and app cleanup. PgVectorStore holds a SQLAlchemy `AsyncEngine` with its own pool; BigQuery holds a client handle; Milvus holds a socket — all leak resources if not disconnected
- **BigQuery `schema` → `dataset` mapping**: BigQueryStore uses `dataset` parameter, not `schema`; the handler must translate
- **`.json` extension special case**: `LOADER_MAPPING` maps `.json` to `MarkdownLoader`, but the handler must route to `JSONDataSource` instead
- **File cleanup on error**: If loading fails after file upload, `TempFileManager` must still clean up the temp file
- **JobManager in-memory only**: Jobs are not persisted to Redis; app restart loses job history

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiohttp` | existing | HTTP framework |
| `navigator` | existing | BaseView, BaseHandler |
| `navigator-auth` | existing | `@is_authenticated()` |
| `datamodel` | existing | `json_encoder` |
| No new dependencies | | All functionality uses existing packages |

---

## Worktree Strategy

- **Default isolation:** `per-spec` — all tasks run sequentially in one worktree
- **Rationale:** The handler, helper, connection cache, and route registration are tightly coupled. Modules 3-5 all live in `handler.py`. Splitting would create merge conflicts.
- **Cross-feature dependencies:** None. This is a new package (`parrot/handlers/stores/`) with no overlap with in-flight specs.
- **Recommended worktree:**
  ```bash
  git worktree add -b feat-087-vectorstore-handler-api \
    .claude/worktrees/feat-087-vectorstore-handler-api HEAD
  ```

---

## 8. Open Questions

All questions from brainstorm have been resolved:

- [x] Store connection cache: max-size eviction (default 10)
- [x] Multiple files per PUT request: supported
- [x] BigQuery `dataset`: mapped from `StoreConfig.schema`
- [x] Job persistence: in-memory only for now
- [x] Embedding model listing: out of scope (no curated model list exists yet)

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-07 | Jesus Lara | Initial draft from brainstorm |
