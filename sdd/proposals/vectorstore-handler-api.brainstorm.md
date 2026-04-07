# Brainstorm: Vector Store Handler API

**Date**: 2026-04-07
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

Developers and frontend applications need a REST API to create, manage, load data into, and test vector store collections without writing Python code or interacting with the framework programmatically. Currently, vector store operations (creating collections, loading documents, running searches) require direct use of `PgVectorStore`, loaders, and `AbstractBot.define_store_config()` — all Python-only paths. This blocks non-Python frontends and centralized management tools from using AI-Parrot's RAG infrastructure.

The API will live in `parrot/handlers/stores/` and follow existing aiohttp handler patterns.

## Constraints & Requirements

- Async-first: all store operations, file processing, and loader calls must be async
- Single-tenant for now, but design should not preclude future multi-tenancy
- File uploads limited to 25MB (configurable via `parrot.conf.VECTOR_HANDLER_MAX_FILE_SIZE`)
- Long-running operations (file loading, scraping, video/image understanding) must run as background jobs via a handler-owned `JobManager`
- Authentication via `@is_authenticated()` on CRUD endpoints; helper/metadata endpoints are public
- Must support all stores in `supported_stores` dict (postgres, milvus, bigquery, faiss, arango, kb)
- Handler must manage its own store connection pool (no existing pooling in store classes)
- Uses `StoreConfig` in request body for POST/PUT/PATCH — no store config in URL path
- Error responses follow existing pattern: `{"error": "message", "detail": "..."}` with appropriate HTTP status codes

---

## Options Explored

### Option A: Single BaseView with Helper + Background Jobs via JobManager

A single `VectorStoreHandler(BaseView)` class handles POST (create), PUT (load data), and PATCH (test search). A companion `VectorStoreHelper(BaseHandler)` serves unauthenticated GET endpoints for metadata (supported stores, embeddings, loaders, index types). Long-running PUT operations (file loading, scraping) are dispatched to a handler-owned `JobManager` instance, returning a job UUID immediately. A store connection cache (dict keyed by store type + DSN) avoids re-instantiating stores per request.

**Pros:**
- Follows established patterns exactly (ScrapingHandler uses same JobManager-per-handler approach)
- Clean separation: authenticated CRUD vs public metadata
- Store connection cache reduces overhead without over-engineering
- `TempFileManager` handles uploaded files with automatic cleanup
- Single module, easy to navigate

**Cons:**
- Single view class may grow large as more operations are added
- Connection cache needs manual eviction/TTL (no framework support)

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | HTTP framework | Already in use |
| `navigator.views.BaseView` | Class-based handler base | Existing |
| `navigator_auth.decorators` | `@is_authenticated()` | Existing |
| `parrot.handlers.jobs.JobManager` | Background job execution | Existing, handler-owned instance |
| `parrot.interfaces.file.tmp.TempFileManager` | Temp file management for uploads | Existing |
| `parrot_loaders.factory.get_loader_class` | Dynamic loader resolution | Existing |
| `parrot_tools.scraping.WebScrapingTool` | URL content extraction | Existing |
| `parrot_tools.scraping.CrawlEngine` | Full-site crawling | Existing |

**Existing Code to Reuse:**
- `parrot/interfaces/vector.py:42-75` — `_get_database_store()` logic for store instantiation
- `parrot/handlers/scraping/handler.py:390-434` — JobManager setup/teardown pattern
- `parrot/stores/models.py` — `StoreConfig`, `SearchResult`, `Document`, `DistanceStrategy`
- `parrot/embeddings/__init__.py` — `supported_embeddings`, `EmbeddingRegistry`
- `parrot/stores/__init__.py` — `supported_stores`
- `parrot_loaders/factory.py` — `LOADER_MAPPING`, `get_loader_class()`

---

### Option B: Microservice-Style with Separate Views per Operation

Three separate BaseView classes: `CollectionCreateView` (POST), `DataLoadView` (PUT), `SearchTestView` (PATCH), plus `VectorStoreHelper`. Each view is small and focused. A shared module (`_pool.py`) manages the store connection cache. Routes registered individually in `app.py`.

**Pros:**
- Each class is small and single-purpose
- Easier to test individual operations in isolation
- Can add new operations without modifying existing views

**Cons:**
- More files and classes to maintain
- Shared state (connection pool, JobManager) requires a separate module or app-level storage
- More route registrations in `app.py`
- Diverges from codebase convention where one BaseView handles multiple HTTP methods

**Effort:** Medium-High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Same as Option A | | |

**Existing Code to Reuse:**
- Same as Option A

---

### Option C: Event-Driven with Full Job Queue for All Operations

All operations (including create and search) go through the JobManager as background jobs. Every request returns a job UUID. Clients poll for results. This treats the API as a pure async task submission system.

**Pros:**
- Uniform interface: every response is a job status
- Naturally handles long-running operations
- Easy to add rate limiting and priority queues

**Cons:**
- Over-engineered for fast operations (create_collection, similarity_search take <1s)
- Doubles round-trips for simple operations (submit + poll)
- Poor developer experience for interactive testing
- No existing handler follows this pattern

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Same as Option A | | |
| Redis | Job persistence | Already available via RedisJobStore |

**Existing Code to Reuse:**
- Same as Option A

---

## Recommendation

**Option A** is recommended because:

- It follows the exact patterns already established in the codebase (`ScrapingHandler` for JobManager lifecycle, `ChatHandler`/`AgentTalk` for BaseView with multiple HTTP methods)
- Background jobs are only used where truly needed (file loading, scraping, video/image processing) — fast operations like collection creation and search return immediately
- A single view class with a companion helper matches how `GoogleGeneration` + `GoogleGenerationHelper` are structured
- The store connection cache is the simplest viable pooling mechanism; a TTL-based eviction can be added later without changing the API surface

The tradeoff vs Option B (more granular classes) is acceptable because the view methods won't be excessively large — each HTTP method delegates to focused private methods.

---

## Feature Description

### User-Facing Behavior

**Base endpoint:** `/api/v1/ai/stores`

| Method | Purpose | Auth | Response |
|--------|---------|------|----------|
| POST | Create/prepare a vector store collection | Yes | Immediate: collection status |
| PUT | Load data into a collection (file upload, URL, JSON content) | Yes | Job UUID for long tasks, immediate for inline content |
| PATCH | Test search against a collection | Yes | Search results wrapper |
| GET | List supported stores, embeddings, loaders, index types | No | Metadata lists |

**POST — Create Collection:**
- Accepts `StoreConfig` as JSON body + `table`, `schema`, `no_drop_table` flag
- If collection exists and `no_drop_table=false` (default): drops and recreates
- If collection exists and `no_drop_table=true`: only runs `prepare_embedding_table`
- Returns: `{"status": "created", "table": "...", "schema": "...", "vector_store": "..."}`

**PUT — Load Data:**
- Accepts multipart/form-data (file upload) or JSON body (inline content/URLs)
- File upload: detects loader from extension via `LOADER_MAPPING`, processes file, calls `add_documents()`
- JSON with `content`: creates `Document` directly, adds to store immediately
- JSON with `url` list: dispatches as background job (YouTube via `YoutubeLoader`, others via `WebScrapingTool`/`CrawlEngine`)
- Image/video uploads: dispatches as background job with optional `prompt`
- Returns: `{"job_id": "uuid"}` for async tasks, or `{"status": "loaded", "documents": N}` for immediate

**PATCH — Test Search:**
- Accepts `StoreConfig` + `query` + optional `method` (similarity/mmr/both) + optional `k`
- Returns: `{"query": "...", "method": "...", "count": N, "results": [SearchResult...]}`

**GET — Helpers:**
- `?resource=stores` → `{"stores": {"postgres": "PgVectorStore", ...}}`
- `?resource=embeddings` → `{"embeddings": {"huggingface": "SentenceTransformerModel", ...}}`
- `?resource=loaders` → `{"loaders": {".pdf": "PDFLoader", ...}}`
- `?resource=index_types` → `{"index_types": ["COSINE", "L2", "IVF_FLAT", ...]}`

**GET — Job Status:**
- `/api/v1/ai/stores/jobs/{job_id}` → `{"job_id": "...", "status": "running|completed|failed", "result": ...}`

### Internal Behavior

1. **Handler initialization (`setup` classmethod):** Registers routes, hooks `_on_startup`/`_on_cleanup` to app lifecycle. On startup, creates `JobManager(id="vectorstore")` and `TempFileManager`. On cleanup, stops both.

2. **Store instantiation helper:** `_get_store(config: StoreConfig) -> AbstractStore` — adapts `VectorInterface._get_database_store` logic. Uses an LRU-style dict cache keyed by `(vector_store, dsn_or_project_id)`. Calls `await store.connection()` on first use.

3. **File upload flow:**
   - `handle_upload()` receives multipart data → saves to `TempFileManager`
   - Determine loader from file extension via `get_loader_class(ext)`
   - For small/fast files (text, CSV, PDF): load synchronously in request, return immediate result
   - For large/slow files (video, image, scraping): create job via `JobManager`, return job UUID
   - After loading, file is deleted from temp storage

4. **URL processing flow:**
   - YouTube URLs → `YoutubeLoader` (always background job)
   - Regular URLs → `WebScrapingTool.execute_scraping_workflow()` or `CrawlEngine.run()` if `crawl_entire_site=true`
   - Results converted to `Document` objects → `store.add_documents()`

5. **Loader LRU cache:** `functools.lru_cache(maxsize=5)` on `get_loader_class` calls within the handler to avoid repeated module imports.

### Edge Cases & Error Handling

- **File too large:** Check `Content-Length` before processing, return 413 if > `VECTOR_HANDLER_MAX_FILE_SIZE`
- **Unsupported file extension:** Return 400 with list of supported extensions
- **Store connection failure:** Return 503 with error detail
- **Collection doesn't exist on PATCH/PUT:** Return 404 with suggestion to create first
- **Invalid StoreConfig:** Pydantic/dataclass validation → 400 with detail
- **Job not found:** Return 404 on job status check
- **Image/video without prompt:** Use handler default prompt (e.g., "Describe this content in detail for use as a searchable document")
- **JSON file upload:** Route to `JSONDataSource.extract()` instead of regular loader, convert records to Documents
- **Empty search results:** Return 200 with empty results array, not an error

---

## Capabilities

### New Capabilities
- `vectorstore-handler-api`: REST API for vector store CRUD, data loading, and search testing
- `vectorstore-connection-pool`: Handler-level store connection caching with key-based lookup
- `vectorstore-background-loader`: Background job execution for long-running data loading operations

### Modified Capabilities
- `parrot.conf` — new variable `VECTOR_HANDLER_MAX_FILE_SIZE` (default 25MB)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/handlers/__init__.py` | extends | Add lazy import for `VectorStoreHandler` |
| `app.py` | extends | Register routes via `VectorStoreHandler.setup(app)` |
| `parrot/conf.py` | extends | Add `VECTOR_HANDLER_MAX_FILE_SIZE` config variable |
| `parrot/stores/` | depends on | Uses `AbstractStore` subclasses, `StoreConfig`, `Document`, `SearchResult` |
| `parrot/embeddings/` | depends on | Uses `supported_embeddings` for helper endpoint |
| `parrot_loaders/factory.py` | depends on | Uses `LOADER_MAPPING`, `get_loader_class()` |
| `parrot_loaders/extractors/json_source.py` | depends on | Uses `JSONDataSource` for .json files |
| `parrot_tools/scraping/` | depends on | Uses `WebScrapingTool`, `CrawlEngine` for URL loading |
| `parrot/handlers/jobs/` | depends on | Uses `JobManager` for background tasks |
| `parrot/interfaces/file/tmp.py` | depends on | Uses `TempFileManager` for upload handling |

---

## Code Context

### User-Provided Code

```python
# Source: user-provided — Store creation example
embed_model = {
    "model": "thenlper/gte-base",
    "model_type": "huggingface"
}
StoreConfig(
    vector_store='postgres',
    embedding_model=embed_model,
    dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
    dimension=768,
)

if await store.collection_exists(table='employee_information', schema='mso'):
    await store.delete_collection(table='employee_information', schema='mso')
await store.create_collection(
    table='employee_information',
    schema='mso',
    dimension=768,
    index_type="COSINE",
    metric_type='L2'
)
```

```python
# Source: user-provided — Search test example
query = "Maximum paid time off to be taken"
results = await store.similarity_search(query)
results = await store.mmr_search(query)
```

```python
# Source: user-provided — PDF loading example
loader = PDFLoader(
    directory,
    source_type=f"MSO",
    language="en",
    parse_images=False,
    as_markdown=True,
    use_chapters=False
)
docs = await loader.load()
await agent.store.add_documents(
    table='employee_information',
    schema='mso',
    documents=docs
)
```

### Verified Codebase References

#### Classes & Signatures

```python
# From parrot/stores/models.py:42-60
@dataclass
class StoreConfig:
    vector_store: str = 'postgres'
    table: Optional[str] = None
    schema: str = 'public'
    embedding_model: Union[str, dict] = field(default_factory=lambda: {...})
    dimension: int = 768
    dsn: Optional[str] = None
    distance_strategy: str = 'COSINE'
    metric_type: str = 'COSINE'
    index_type: str = 'IVF_FLAT'
    auto_create: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

# From parrot/stores/models.py:7-18
class SearchResult(BaseModel):
    id: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: float
    ensemble_score: float = None
    search_source: str = None
    similarity_rank: Optional[int] = None
    mmr_rank: Optional[int] = None

# From parrot/stores/models.py:21-27
class Document(BaseModel):
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

# From parrot/stores/models.py:30-38
class DistanceStrategy(str, Enum):
    EUCLIDEAN_DISTANCE = "EUCLIDEAN_DISTANCE"
    MAX_INNER_PRODUCT = "MAX_INNER_PRODUCT"
    DOT_PRODUCT = "DOT_PRODUCT"
    JACCARD = "JACCARD"
    COSINE = "COSINE"

# From parrot/stores/postgres.py:56
class PgVectorStore(AbstractStore):
    async def create_collection(self, table, schema='public', dimension=768,
                                 index_type="COSINE", metric_type='L2', **kwargs) -> None  # line 2804
    async def delete_collection(self, table, schema='public') -> None  # line 2772
    async def collection_exists(self, table, schema='public') -> bool  # line 2747
    async def prepare_embedding_table(self, table, schema='public', ...) -> bool  # line 808
    async def add_documents(self, documents, table=None, schema=None, **kwargs) -> None  # line 498
    async def similarity_search(self, query, table=None, schema=None, k=None, ...) -> List[SearchResult]  # line 634
    async def mmr_search(self, query, table=None, schema=None, k=10, ...) -> List[SearchResult]  # line 1670

# From parrot/stores/bigquery.py:23
class BigQueryStore(AbstractStore):
    async def create_collection(self, table, dataset=None, dimension=768, **kwargs) -> None  # line 238
    async def delete_collection(self, table, dataset=None) -> None  # line 1278
    async def collection_exists(self, table, dataset=None) -> bool  # line 224
    async def add_documents(self, documents, table=None, dataset=None, **kwargs) -> None  # line 449
    async def similarity_search(self, query, table=None, dataset=None, ...) -> List[SearchResult]  # line 583
    async def mmr_search(self, query, table=None, dataset=None, ...) -> List[SearchResult]  # line 701

# From parrot/handlers/jobs/job.py:22
class JobManager:
    def __init__(self, id="default", cleanup_interval=3600, job_ttl=86400, store=None)
    async def start() -> None
    async def stop() -> None
    def create_job(self, job_id, obj_id, query, user_id=None, ...) -> Job
    async def execute_job(self, job_id, execution_func) -> None
    def get_job(self, job_id) -> Optional[Job]
    def list_jobs(self, obj_id=None, status=None, limit=100) -> list

# From parrot/handlers/jobs/models.py:6-12
class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

# From parrot/interfaces/file/tmp.py:15
class TempFileManager:
    def __init__(self, prefix="ai_parrot_", cleanup_on_exit=True, cleanup_on_delete=True)
    async def upload_file(self, source, destination) -> FileMetadata
    async def delete_file(self, path) -> bool
    async def exists(self, path) -> bool
    def cleanup() -> None

# From parrot_loaders/imageunderstanding.py:81
class ImageUnderstandingLoader(AbstractLoader):
    def __init__(self, source=None, *, model=GoogleModel.GEMINI_3_1_FLASH_IMAGE_PREVIEW,
                 temperature=0.2, prompt=None, custom_instructions=None, language="en",
                 detect_objects=False, **kwargs)

# From parrot_loaders/videounderstanding.py:100
class VideoUnderstandingLoader(BaseVideoLoader):
    def __init__(self, source=None, *, model=GoogleModel.GEMINI_3_PRO_PREVIEW,
                 temperature=0.2, prompt=None, custom_instructions=None, **kwargs)

# From parrot_loaders/extractors/json_source.py:12
class JSONDataSource(ExtractDataSource):
    async def extract(self, fields=None, filters=None) -> ExtractionResult

# From parrot_tools/scraping/tool.py:119
class WebScrapingTool(AbstractTool):
    async def execute_scraping_workflow(self, ...) -> ...

# From parrot_tools/scraping/crawler.py:24
class CrawlEngine:
    def __init__(self, scrape_fn, strategy=None, follow_selector="a[href]",
                 follow_pattern=None, allow_external=False, concurrency=1, logger=None)
    async def run(self, start_url, plan, depth=1, max_pages=None) -> CrawlResult
```

#### Verified Imports

```python
# These imports have been confirmed to work:
from parrot.stores import AbstractStore, supported_stores  # parrot/stores/__init__.py:1-10
from parrot.stores.models import StoreConfig, SearchResult, Document, DistanceStrategy  # parrot/stores/models.py
from parrot.embeddings import supported_embeddings, EmbeddingRegistry  # parrot/embeddings/__init__.py:1-10
from parrot.handlers.jobs import JobManager, JobStatus  # parrot/handlers/jobs/__init__.py
from parrot.interfaces.file.tmp import TempFileManager  # parrot/interfaces/file/tmp.py
from parrot_loaders.factory import LOADER_MAPPING, get_loader_class  # parrot_loaders/factory.py
from parrot_loaders.extractors.json_source import JSONDataSource  # parrot_loaders/extractors/json_source.py
from parrot_tools.scraping import WebScrapingTool, CrawlEngine  # parrot_tools/scraping/__init__.py
from parrot.conf import async_default_dsn  # parrot/conf.py:57
from navigator.views import BaseView, BaseHandler  # navigator.views
from navigator_auth.decorators import is_authenticated, user_session  # navigator_auth.decorators
```

#### Key Attributes & Constants

- `supported_stores` → `dict` (parrot/stores/__init__.py:3) — `{'postgres': 'PgVectorStore', 'milvus': 'MilvusStore', ...}`
- `supported_embeddings` → `dict` (parrot/embeddings/__init__.py:3) — `{'huggingface': 'SentenceTransformerModel', ...}`
- `LOADER_MAPPING` → `dict` (parrot_loaders/factory.py:12) — maps file extensions to `(module, class_name)` tuples
- `async_default_dsn` → `str` (parrot/conf.py:57) — default PostgreSQL async DSN

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.stores.create_store_from_config()`~~ — no factory function exists; must use `VectorInterface._get_database_store()` pattern
- ~~`parrot.stores.StorePool`~~ — no connection pooling for stores exists
- ~~`parrot.conf.VECTOR_HANDLER_MAX_FILE_SIZE`~~ — does not exist yet, must be added
- ~~`AbstractStore.from_config()`~~ — no classmethod to create from StoreConfig
- ~~`parrot.handlers.stores`~~ — this package does not exist yet, must be created
- ~~`StoreConfig.to_store()`~~ — StoreConfig has no method to instantiate a store
- ~~`LOADER_MAPPING['.json'] -> JSONDataSource`~~ — `.json` maps to `('markdown', 'MarkdownLoader')`, NOT JSONDataSource; handler must special-case `.json` files

---

## Parallelism Assessment

- **Internal parallelism:** Moderate. The handler module (`VectorStoreHandler`), helper module (`VectorStoreHelper`), and config variable can be developed independently. However, the store connection cache and JobManager setup are shared dependencies within the handler.
- **Cross-feature independence:** No conflicts with in-flight specs. The handler is a new package (`parrot/handlers/stores/`) with no shared files beyond `app.py` route registration and `parrot/conf.py`.
- **Recommended isolation:** `per-spec` — all tasks sequential in one worktree. The handler, helper, and route registration are tightly coupled and best developed together.
- **Rationale:** The connection cache, JobManager lifecycle, and file upload flow are interdependent within the handler. Splitting into parallel worktrees would create merge conflicts in the handler's `__init__.py` and shared utilities.

---

## Open Questions

- [x] Should the store connection cache have a TTL or max-size eviction policy? — *Owner: Jesus Lara*: max-size
- [x] Should PUT (load data) support batch operations (multiple files in one request)? — *Owner: Jesus Lara*: multiple files can be useful but will take more time to process, but multiple can be useful.
- [x] For BigQuery stores, should `dataset` be mapped from `StoreConfig.schema` or require a separate field? — *Owner: Jesus Lara*: mapped from schema.
- [x] Should job results be persisted in Redis (via `RedisJobStore`) or in-memory only? — *Owner: Jesus Lara*: in-memory only for now.
- [x] Future: should the helper endpoints also expose available models per embedding type (e.g., list HuggingFace models)? — *Owner: Jesus Lara*: if possible, but currently we don't have a list of "selected" used models.
