# Vector Store Handler — API Reference

REST API for vector store lifecycle management: create collections, load data (files, URLs, inline content), run test searches, and query configuration metadata.

**Base URL:** `/api/v1/ai/stores`

**Authentication:** All mutating endpoints (POST, PUT, PATCH) require authentication via `@is_authenticated`. GET metadata endpoints are public (delegated to `VectorStoreHelper`).

---

## Table of Contents

- [Endpoints Overview](#endpoints-overview)
- [Common Fields](#common-fields)
- [GET — Metadata & Job Status](#get--metadata--job-status)
- [POST — Create Collection](#post--create-collection)
- [PUT — Load Data](#put--load-data)
- [PATCH — Test Search](#patch--test-search)
- [Data Models](#data-models)
- [Embedding Model Catalog](#embedding-model-catalog)
- [Error Handling](#error-handling)

---

## Endpoints Overview

| Method | URL | Auth | Purpose |
|--------|-----|------|---------|
| `GET` | `/api/v1/ai/stores` | No | Return all metadata (stores, embeddings, loaders, index types, embedding models) |
| `GET` | `/api/v1/ai/stores?resource=<name>` | No | Return a single metadata resource |
| `GET` | `/api/v1/ai/stores/jobs/{job_id}` | Yes | Poll background job status |
| `POST` | `/api/v1/ai/stores` | Yes | Create or prepare a vector store collection |
| `PUT` | `/api/v1/ai/stores` | Yes | Load data into a collection (files, URLs, inline content) |
| `PATCH` | `/api/v1/ai/stores` | Yes | Run a test search against a collection |

---

## Common Fields

These fields appear across multiple endpoints. Unless noted otherwise, they share the same defaults and validation rules.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `table` | `string` | *required* | Collection/table name. Must be a valid SQL identifier: `[a-zA-Z_][a-zA-Z0-9_]{0,62}` |
| `schema` | `string` | `"public"` | Database schema or namespace. Same validation as `table` |
| `vector_store` | `string` | `"postgres"` | Store backend type. See `GET ?resource=stores` for supported values |
| `embedding_model` | `string \| object` | `{"model": "thenlper/gte-base", "model_type": "huggingface"}` | Embedding model to use. Either a model name string or a dict with `model` and `model_type` keys |
| `dimension` | `integer` | `768` | Embedding vector dimensionality (1–65536) |
| `dsn` | `string \| null` | `null` | Database connection string. Falls back to server-configured DSN when omitted. SSRF protection blocks loopback and cloud-metadata addresses |

### Embedding Model Format

The `embedding_model` field accepts two formats:

**String format** (resolves to HuggingFace by default):
```json
"embedding_model": "thenlper/gte-base"
```

**Object format** (explicit provider):
```json
"embedding_model": {
  "model": "text-embedding-3-large",
  "model_type": "openai"
}
```

Supported `model_type` values: `huggingface`, `openai`, `google`.

---

## GET — Metadata & Job Status

### Get All Metadata

Returns all configuration metadata in a single response.

**Request:**
```
GET /api/v1/ai/stores
```

**Response `200`:**
```json
{
  "stores": {
    "postgres": "PgVectorStore",
    "milvus": "MilvusStore",
    "kb": "KnowledgeBaseStore",
    "faiss_store": "FaissStore",
    "arango": "ArangoStore",
    "bigquery": "BigQueryStore"
  },
  "embeddings": {
    "huggingface": "SentenceTransformerModel",
    "google": "GoogleEmbeddingModel",
    "openai": "OpenAIEmbeddingModel"
  },
  "embedding_models": [
    {
      "model": "thenlper/gte-base",
      "provider": "huggingface",
      "name": "GTE Base",
      "dimension": 768,
      "multilingual": false,
      "language": "en",
      "description": "768-dim general-purpose model, great for information retrieval and text re-ranking."
    }
  ],
  "loaders": {
    ".pdf": "PDFLoader",
    ".docx": "DocxLoader",
    ".csv": "CSVLoader"
  },
  "index_types": [
    "EUCLIDEAN_DISTANCE",
    "MAX_INNER_PRODUCT",
    "DOT_PRODUCT",
    "JACCARD",
    "COSINE"
  ]
}
```

### Get Single Resource

**Request:**
```
GET /api/v1/ai/stores?resource=<name>
```

Available `resource` values:

| Resource | Returns | Description |
|----------|---------|-------------|
| `stores` | `object` | Supported vector store types (`key` → `class_name`) |
| `embeddings` | `object` | Supported embedding providers (`key` → `class_name`) |
| `embedding_models` | `array` | Curated catalog of all embedding models with metadata |
| `loaders` | `object` | Supported file loaders (`extension` → `class_name`) |
| `index_types` | `array` | Supported distance strategies / index types |

### Get Embedding Models (with optional provider filter)

```
GET /api/v1/ai/stores?resource=embedding_models
GET /api/v1/ai/stores?resource=embedding_models&provider=huggingface
GET /api/v1/ai/stores?resource=embedding_models&provider=openai
GET /api/v1/ai/stores?resource=embedding_models&provider=google
```

**Response `200`:**
```json
[
  {
    "model": "thenlper/gte-base",
    "provider": "huggingface",
    "name": "GTE Base",
    "dimension": 768,
    "multilingual": false,
    "language": "en",
    "description": "768-dim general-purpose model, great for information retrieval and text re-ranking."
  },
  {
    "model": "text-embedding-3-large",
    "provider": "openai",
    "name": "Text Embedding 3 Large",
    "dimension": 3072,
    "multilingual": true,
    "language": "multi",
    "description": "3072-dim flagship OpenAI model. Highest quality for search, clustering, and classification. Supports dimension reduction."
  }
]
```

### Get Job Status

Poll the status of a background job (file/URL loading).

**Request:**
```
GET /api/v1/ai/stores/jobs/{job_id}
```

**Response `200`:**
```json
{
  "job_id": "a1b2c3d4e5f6...",
  "status": "completed",
  "result": {
    "status": "loaded",
    "documents": 42
  },
  "elapsed_time": 12.5
}
```

**Response `404`:**
```json
{
  "error": "Job 'xyz' not found"
}
```

**Job status values:** `pending`, `running`, `completed`, `failed`

When `status` is `"failed"`, the response includes an `error` field with the error message.

---

## POST — Create Collection

Create or reset a vector store collection with the specified configuration.

**Request:**
```
POST /api/v1/ai/stores
Content-Type: application/json
```

**Body:**
```json
{
  "table": "my_documents",
  "schema": "public",
  "vector_store": "postgres",
  "embedding_model": {"model": "thenlper/gte-base", "model_type": "huggingface"},
  "dimension": 768,
  "distance_strategy": "COSINE",
  "metric_type": "COSINE",
  "index_type": "IVF_FLAT",
  "no_drop_table": false,
  "dsn": null,
  "extra": {}
}
```

| Field | Type | Default | Required | Description |
|-------|------|---------|----------|-------------|
| `table` | `string` | — | **Yes** | Collection name |
| `schema` | `string` | `"public"` | No | Database schema |
| `vector_store` | `string` | `"postgres"` | No | Store backend |
| `embedding_model` | `string \| object` | `thenlper/gte-base` | No | Embedding model config |
| `dimension` | `integer` | `768` | No | Vector dimension |
| `distance_strategy` | `string` | `"COSINE"` | No | Distance metric for similarity |
| `metric_type` | `string` | `"COSINE"` | No | Backend-specific metric type |
| `index_type` | `string` | `"IVF_FLAT"` | No | Vector index type |
| `no_drop_table` | `boolean` | `false` | No | If `true`, preserve existing data when collection already exists. If `false`, drop and recreate |
| `dsn` | `string` | `null` | No | Custom database connection string |
| `extra` | `object` | `{}` | No | Store-specific extra configuration |

**Behavior:**
- If collection does **not** exist → create + prepare embedding table.
- If collection exists and `no_drop_table: false` → drop, recreate, prepare.
- If collection exists and `no_drop_table: true` → prepare only (preserves data).

**Response `200`:**
```json
{
  "status": "created",
  "table": "my_documents",
  "schema": "public",
  "vector_store": "postgres"
}
```

---

## PUT — Load Data

Load data into an existing collection. Supports three ingestion modes: file upload, inline content, and URL loading.

### Mode 1: File Upload (multipart)

**Request:**
```
PUT /api/v1/ai/stores
Content-Type: multipart/form-data
```

**Form fields:**

| Field | Type | Default | Required | Description |
|-------|------|---------|----------|-------------|
| `file` | `file(s)` | — | **Yes** | One or more files to upload |
| `table` | `string` | — | **Yes** | Target collection name |
| `schema` | `string` | `"public"` | No | Database schema |
| `vector_store` | `string` | `"postgres"` | No | Store backend |
| `embedding_model` | `string` | `thenlper/gte-base` | No | Embedding model |
| `dimension` | `string` | `"768"` | No | Vector dimension (parsed as int) |
| `dsn` | `string` | — | No | Custom connection string |
| `prompt` | `string` | — | No | Custom prompt for image/video processing |

**Supported file types:** All extensions registered in the loader factory (`.pdf`, `.docx`, `.csv`, `.txt`, `.html`, `.pptx`, `.xlsx`, `.md`, etc.) plus images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.webp`, `.tiff`) and videos (`.mp4`, `.webm`, `.avi`, `.mov`, `.mkv`).

Use `GET ?resource=loaders` to retrieve the full list of supported extensions.

**File size limit:** Controlled by `VECTOR_HANDLER_MAX_FILE_SIZE` server configuration. Files exceeding this limit return `413`.

**Processing behavior:**
- **Text files** (PDF, DOCX, etc.): Processed immediately, response returns document count.
- **Images/Videos**: Dispatched as a background job. Response returns `job_id` to poll.
- **JSON files**: Processed via `JSONDataSource` extractor.

**Response — immediate `200`:**
```json
{
  "status": "loaded",
  "documents": 15
}
```

**Response — background `200`:**
```json
{
  "job_id": "a1b2c3d4...",
  "status": "pending",
  "message": "Data loading started in background"
}
```

### Mode 2: Inline Content (JSON)

**Request:**
```
PUT /api/v1/ai/stores
Content-Type: application/json
```

**Body:**
```json
{
  "table": "my_documents",
  "schema": "public",
  "content": "This is the text content to embed and store.",
  "metadata": {"source": "manual", "category": "example"},
  "embedding_model": {"model": "thenlper/gte-base", "model_type": "huggingface"},
  "dimension": 768
}
```

| Field | Type | Default | Required | Description |
|-------|------|---------|----------|-------------|
| `table` | `string` | — | **Yes** | Target collection |
| `content` | `string` | — | **Yes*** | Text content to embed and store |
| `metadata` | `object` | `{}` | No | Metadata attached to the document |

*Either `content` or `url` is required.

**Response `200`:**
```json
{
  "status": "loaded",
  "documents": 1
}
```

### Mode 3: URL Loading (JSON)

Load and embed content from web pages. Always runs as a background job.

**Request:**
```
PUT /api/v1/ai/stores
Content-Type: application/json
```

**Body:**
```json
{
  "table": "web_content",
  "url": ["https://example.com/page1", "https://example.com/page2"],
  "web_loader": "simple",
  "crawl_entire_site": false,
  "prompt": null,
  "scraping_options": {}
}
```

| Field | Type | Default | Required | Description |
|-------|------|---------|----------|-------------|
| `table` | `string` | — | **Yes** | Target collection |
| `url` | `string \| string[]` | — | **Yes*** | URL or list of URLs to scrape |
| `web_loader` | `string` | `"simple"` | No | Loader strategy: `"simple"` or `"scraping"` |
| `crawl_entire_site` | `boolean` | `false` | No | Enable multi-page crawling |
| `prompt` | `string` | `null` | No | Optional prompt (reserved) |
| `scraping_options` | `object` | `{}` | No | Options for `"scraping"` loader (see below) |

*Either `content` or `url` is required.

**Web loader strategies:**

| Strategy | Engine | Best For |
|----------|--------|----------|
| `"simple"` | `WebLoader` (Selenium) | Basic content extraction, minimal overhead |
| `"scraping"` | `WebScrapingLoader` (CrawlEngine) | Advanced scraping with CSS selectors, LLM-driven plans, multi-page crawling |

**YouTube URLs** are automatically detected and processed by `YoutubeLoader` regardless of the `web_loader` choice.

**Scraping options** (only used when `web_loader: "scraping"`):

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `selectors` | `array` | `null` | CSS/XPath selector dicts for extraction |
| `tags` | `string[]` | `null` | HTML tags to extract (e.g. `["p", "h1", "article"]`) |
| `steps` | `array` | `null` | Raw browser automation steps |
| `objective` | `string` | `null` | Scraping objective for LLM plan generation |
| `depth` | `integer` | `2` | Max crawl depth |
| `max_pages` | `integer` | `null` | Max pages to crawl |
| `follow_selector` | `string` | `null` | CSS selector for links to follow |
| `follow_pattern` | `string` | `null` | URL regex for link filtering |
| `parse_videos` | `boolean` | `true` | Extract video links |
| `parse_navs` | `boolean` | `false` | Extract navigation menus |
| `parse_tables` | `boolean` | `true` | Extract tables as markdown |
| `content_format` | `string` | `"markdown"` | Output format: `"markdown"` or `"text"` |

**Response `200`:**
```json
{
  "job_id": "a1b2c3d4...",
  "status": "pending",
  "message": "Data loading started in background"
}
```

**Job result** (polled via `GET /jobs/{job_id}`):
```json
{
  "job_id": "a1b2c3d4...",
  "status": "completed",
  "result": {
    "status": "loaded",
    "documents": 28,
    "errors": []
  }
}
```

If some URLs fail, status is `"partial"` and `errors` contains the error messages.

---

## PATCH — Test Search

Run a test search query against an existing collection.

**Request:**
```
PATCH /api/v1/ai/stores
Content-Type: application/json
```

**Body:**
```json
{
  "query": "What is the company's revenue?",
  "table": "financial_docs",
  "schema": "public",
  "method": "both",
  "k": 5,
  "vector_store": "postgres",
  "embedding_model": {"model": "thenlper/gte-base", "model_type": "huggingface"},
  "dimension": 768,
  "dsn": null
}
```

| Field | Type | Default | Required | Description |
|-------|------|---------|----------|-------------|
| `query` | `string` | — | **Yes** | Search query text |
| `table` | `string` | — | No | Target collection |
| `schema` | `string` | `"public"` | No | Database schema |
| `method` | `string` | `"similarity"` | No | Search method: `"similarity"`, `"mmr"`, or `"both"` |
| `k` | `integer` | `5` | No | Number of results to return |
| `vector_store` | `string` | `"postgres"` | No | Store backend |
| `embedding_model` | `string \| object` | `thenlper/gte-base` | No | Embedding model config |
| `dimension` | `integer` | `768` | No | Vector dimension |
| `dsn` | `string` | `null` | No | Custom connection string |

**Search methods:**

| Method | Description |
|--------|-------------|
| `similarity` | Pure cosine/distance similarity search |
| `mmr` | Maximal Marginal Relevance — balances relevance with diversity |
| `both` | Runs both methods and returns combined results |

**Response `200`:**
```json
{
  "query": "What is the company's revenue?",
  "method": "both",
  "count": 10,
  "results": [
    {
      "id": "doc-uuid-1",
      "content": "The company reported $5.2B in revenue...",
      "metadata": {"source": "annual_report.pdf", "page": 12},
      "score": 0.92,
      "ensemble_score": null,
      "search_source": "similarity",
      "similarity_rank": 1,
      "mmr_rank": null
    },
    {
      "id": "doc-uuid-2",
      "content": "Revenue growth exceeded expectations...",
      "metadata": {"source": "earnings_call.pdf", "page": 3},
      "score": 0.87,
      "ensemble_score": null,
      "search_source": "mmr",
      "similarity_rank": null,
      "mmr_rank": 1
    }
  ]
}
```

**Response `404`:**
```json
{
  "error": "Collection 'public.financial_docs' not found"
}
```

---

## Data Models

### StoreConfig

Internal configuration model (Pydantic). Constructed from request bodies.

```
vector_store      string              "postgres"
table             string | null       null
schema            string              "public"
embedding_model   string | object     {"model": "sentence-transformers/all-mpnet-base-v2", "model_type": "huggingface"}
dimension         integer (1-65536)   768
dsn               string | null       null
distance_strategy string              "COSINE"
metric_type       string              "COSINE"
index_type        string              "IVF_FLAT"
auto_create       boolean             false
extra             object              {}
```

### SearchResult

Returned by PATCH search queries.

```
id                string              Document identifier
content           string              Document text content
metadata          object              Document metadata (source, page, etc.)
score             float               Similarity/distance score
ensemble_score    float | null        Combined score (when applicable)
search_source     string | null       "similarity" or "mmr"
similarity_rank   integer | null      Rank in similarity results
mmr_rank          integer | null      Rank in MMR results
```

### Document

Input model for adding data.

```
page_content      string              The text content to embed
metadata          object              Arbitrary metadata dict
```

### DistanceStrategy (enum)

```
EUCLIDEAN_DISTANCE
MAX_INNER_PRODUCT
DOT_PRODUCT
JACCARD
COSINE
```

---

## Embedding Model Catalog

The backend serves a curated catalog of tested embedding models via `GET ?resource=embedding_models`. Each entry contains:

| Field | Type | Description |
|-------|------|-------------|
| `model` | `string` | Model identifier (use this in `embedding_model` fields) |
| `provider` | `string` | Provider type: `huggingface`, `openai`, `google` |
| `name` | `string` | Human-readable display name |
| `dimension` | `integer` | Output vector dimension |
| `multilingual` | `boolean` | Whether the model supports multiple languages |
| `language` | `string` | `"en"` or `"multi"` |
| `description` | `string` | Usage description and characteristics |

### Available Models

#### HuggingFace (local, no API key required)

| Model | Dimension | Language | Use Case |
|-------|-----------|----------|----------|
| `thenlper/gte-base` | 768 | EN | General-purpose retrieval and re-ranking |
| `Alibaba-NLP/gte-multilingual-base` | 768 | Multi | Cross-lingual retrieval and semantic search |
| `sentence-transformers/all-mpnet-base-v2` | 768 | EN | Best overall quality for semantic similarity |
| `sentence-transformers/all-MiniLM-L12-v2` | 384 | EN | Balanced speed/quality for general search |
| `sentence-transformers/all-MiniLM-L6-v2` | 384 | EN | Fast inference, resource-constrained environments |
| `sentence-transformers/msmarco-MiniLM-L12-v3` | 384 | EN | Search and question-answer retrieval |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 384 | Multi | Lightweight multilingual paraphrase detection |
| `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` | 768 | Multi | High-quality multilingual similarity |
| `intfloat/e5-base-v2` | 768 | EN | Asymmetric retrieval (query vs passage) |
| `BAAI/bge-base-en-v1.5` | 768 | EN | Retrieval, classification, clustering |
| `BAAI/bge-small-en-v1.5` | 384 | EN | Compact model for resource-constrained use |
| `BAAI/bge-large-en-v1.5` | 1024 | EN | Highest accuracy for critical pipelines |

#### OpenAI (requires `OPENAI_API_KEY`)

| Model | Dimension | Language | Use Case |
|-------|-----------|----------|----------|
| `text-embedding-3-large` | 3072 | Multi | Flagship quality, supports dimension reduction |
| `text-embedding-3-small` | 1536 | Multi | Cost-efficient with good quality |
| `text-embedding-ada-002` | 1536 | Multi | Legacy, widely adopted |

#### Google (requires `GOOGLE_API_KEY`)

| Model | Dimension | Language | Use Case |
|-------|-----------|----------|----------|
| `gemini-embedding-001` | 3072 | Multi | Configurable output dimensionality |

---

## Error Handling

All errors return JSON with an `error` field.

| Status | Cause |
|--------|-------|
| `400` | Missing required field, invalid identifier, invalid method, unsupported store type, or no content/URL provided |
| `404` | Collection not found (PATCH), or job not found (GET job) |
| `413` | Uploaded file exceeds `VECTOR_HANDLER_MAX_FILE_SIZE` |
| `500` | Unexpected server error |
| `503` | Job manager not available |

**Example error response:**
```json
{
  "error": "Missing required field: table"
}
```

### Validation Rules

- **SQL identifiers** (`table`, `schema`): Must match `[a-zA-Z_][a-zA-Z0-9_]{0,62}`.
- **DSN protection**: Connection strings targeting `localhost`, `127.x.x.x`, `::1`, `169.254.x.x`, or `0.0.0.0` are rejected (SSRF mitigation).
- **Search method**: Must be one of `similarity`, `mmr`, `both`.
- **Store type**: Must be a key in the supported stores registry.

---

## UI Integration Notes

### Typical Workflow

1. **Load metadata** — `GET /api/v1/ai/stores` on page load to populate dropdowns (stores, embedding models, loaders, index types).
2. **Create collection** — `POST` with user-selected configuration.
3. **Upload data** — `PUT` with files (multipart) or URLs (JSON). For URLs, poll `GET /jobs/{job_id}` until completion.
4. **Test search** — `PATCH` to verify the collection works as expected.

### Auto-setting Dimension

When the user selects an embedding model from the catalog, auto-fill the `dimension` field from the model's `dimension` value. This prevents mismatches between model output and collection configuration.

```javascript
// Example: auto-fill dimension on model select
const models = await fetch('/api/v1/ai/stores?resource=embedding_models').then(r => r.json());
modelSelect.addEventListener('change', (e) => {
  const model = models.find(m => m.model === e.target.value);
  if (model) dimensionInput.value = model.dimension;
});
```

### Populating Embedding Model Selector

Use the `embedding_models` resource to build a grouped dropdown:

```javascript
const models = await fetch('/api/v1/ai/stores?resource=embedding_models').then(r => r.json());
const grouped = Object.groupBy(models, m => m.provider);

for (const [provider, items] of Object.entries(grouped)) {
  const optgroup = document.createElement('optgroup');
  optgroup.label = provider.charAt(0).toUpperCase() + provider.slice(1);
  for (const m of items) {
    const opt = document.createElement('option');
    opt.value = m.model;
    opt.textContent = `${m.name} (${m.dimension}-dim)`;
    opt.title = m.description;
    optgroup.appendChild(opt);
  }
  select.appendChild(optgroup);
}
```
