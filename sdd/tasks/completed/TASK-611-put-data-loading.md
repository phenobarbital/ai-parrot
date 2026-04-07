# TASK-611: PUT Endpoint — Data Loading

**Feature**: vectorstore-handler-api
**Spec**: `sdd/specs/vectorstore-handler-api.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-608
**Assigned-to**: unassigned

---

## Context

> Implements Spec Module 5. The PUT method handles data loading into vector store
> collections from three sources: file uploads (multipart/form-data), inline JSON
> content, and URL lists. Long-running operations are dispatched as background jobs
> via the handler's JobManager. This is the most complex task in the feature.

---

## Scope

- Implement `VectorStoreHandler.put()`:
  - **File upload path** (multipart/form-data):
    - Use `self.handle_upload()` to receive files
    - Validate file size against `VECTOR_HANDLER_MAX_FILE_SIZE`
    - Save to `TempFileManager` for processing
    - Determine loader by extension via `get_loader_class(ext)`
    - Special case `.json` → `JSONDataSource` (NOT MarkdownLoader)
    - Image extensions → `ImageUnderstandingLoader` with optional `prompt` (background job)
    - Video extensions → `VideoUnderstandingLoader` with optional `prompt` (background job)
    - Other extensions → immediate loading via detected loader
    - Support multiple files per request
    - Cleanup temp files after loading (even on error)
  - **JSON body path** (no file upload):
    - If body has `content` field: create `Document` directly, call `store.add_documents()`, return immediate
    - If body has `url` list:
      - YouTube URLs → `YoutubeLoader` (background job)
      - Other URLs → `WebScrapingTool` or `CrawlEngine` if `crawl_entire_site=true` (background job)
  - **Background job flow**:
    - Create job via `job_manager.create_job()`
    - Execute via `job_manager.execute_job(job_id, async_func)`
    - Return `{"job_id": "...", "status": "pending", "message": "Data loading started in background"}`
  - **Immediate result flow**:
    - Return `{"status": "loaded", "documents": N}`
- Implement private helper methods:
  - `_load_file(store, file_info, config, prompt)` — process a single file
  - `_load_urls(store, urls, config, crawl_entire_site)` — process URL list
  - `_is_youtube_url(url)` — check if URL is YouTube
- Handle default prompts for image/video when user doesn't provide one

**NOT in scope**: POST (TASK-609), PATCH (TASK-610), helpers, route registration

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/stores/handler.py` | MODIFY | Replace `put()` stub + add private helpers |
| `packages/ai-parrot/tests/unit/test_vectorstore_put.py` | CREATE | Unit tests for PUT endpoint |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in handler.py from TASK-608:
import uuid
from parrot.stores.models import StoreConfig, Document
from parrot.handlers.jobs import JobManager, JobStatus
from parrot.interfaces.file.tmp import TempFileManager
from parrot.conf import VECTOR_HANDLER_MAX_FILE_SIZE               # created in TASK-606

# New imports needed for this task:
from parrot_loaders.factory import LOADER_MAPPING, get_loader_class  # parrot_loaders/factory.py:12-73
from parrot_loaders.extractors.json_source import JSONDataSource   # parrot_loaders/extractors/json_source.py:12
from parrot_tools.scraping import WebScrapingTool, CrawlEngine     # parrot_tools/scraping/__init__.py
```

### Existing Signatures to Use
```python
# parrot/stores/models.py:21-27
class Document(BaseModel):
    page_content: str                                                # line 26
    metadata: Dict[str, Any] = Field(default_factory=dict)           # line 27

# AbstractStore.add_documents — all stores implement this:
async def add_documents(self, documents, table=None, schema=None,
                         embedding_column='embedding', content_column='document',
                         metadata_column='cmetadata', **kwargs) -> None       # postgres.py:498

# BaseView.handle_upload — navigator.views.base (installed package)
async def handle_upload(self, request=None, form_key=None,
                         ext='.csv', preserve_filenames=True
                         ) -> Tuple[Dict[str, List[dict]], dict]
    # Returns: (files_dict, form_fields_dict)
    # files_dict[field_name] = [{"file_path": Path, "file_name": str, "mime_type": str}]

# parrot_loaders/factory.py:50-73
def get_loader_class(extension: str):
    # Returns loader class for given extension
    # Defaults to MarkdownLoader if extension not found

# LOADER_MAPPING — maps extensions to (module_name, class_name) tuples
# '.pdf': ('pdf', 'PDFLoader'), '.json': ('markdown', 'MarkdownLoader'), etc.

# parrot_loaders/imageunderstanding.py:81
class ImageUnderstandingLoader(AbstractLoader):
    def __init__(self, source=None, *, prompt=None, **kwargs)
    async def load(self) -> List[Document]: ...

# parrot_loaders/videounderstanding.py:100
class VideoUnderstandingLoader(BaseVideoLoader):
    def __init__(self, source=None, *, prompt=None, **kwargs)
    async def load(self) -> List[Document]: ...

# parrot_loaders/extractors/json_source.py:12
class JSONDataSource(ExtractDataSource):
    async def extract(self, fields=None, filters=None) -> ExtractionResult

# parrot/interfaces/file/tmp.py:15
class TempFileManager:
    async def upload_file(self, source, destination) -> FileMetadata
    async def delete_file(self, path) -> bool

# parrot/handlers/jobs/job.py
class JobManager:
    def create_job(self, job_id, obj_id, query, user_id=None,
                   session_id=None, execution_mode=None) -> Job
    async def execute_job(self, job_id, execution_func) -> None

# parrot_tools/scraping/tool.py:119
class WebScrapingTool(AbstractTool):
    async def execute_scraping_workflow(self, ...) -> Any

# parrot_tools/scraping/crawler.py:24
class CrawlEngine:
    def __init__(self, scrape_fn, strategy=None, follow_selector="a[href]",
                 follow_pattern=None, allow_external=False,
                 concurrency=1, logger=None)
    async def run(self, start_url, plan, depth=1, max_pages=None) -> CrawlResult
```

### Does NOT Exist
- ~~`LOADER_MAPPING['.json'] -> JSONDataSource`~~ — `.json` maps to `('markdown', 'MarkdownLoader')` NOT JSONDataSource; handler MUST special-case `.json` files
- ~~`AbstractLoader.load_file(path)`~~ — no such convenience method; instantiate loader with source, then call `await loader.load()`
- ~~`store.load_documents()`~~ — no such method; use `store.add_documents(documents)`
- ~~`TempFileManager.get_path()`~~ — no such method; use the path returned by `upload_file()`
- ~~`YoutubeLoader` from parrot_loaders.factory~~ — YoutubeLoader exists but must be imported explicitly if needed: `from parrot_loaders.youtube import YoutubeLoader`

---

## Implementation Notes

### File Upload Decision Tree
```
extension = Path(file_name).suffix.lower()

if extension == '.json':
    → JSONDataSource (immediate)
elif extension in IMAGE_EXTENSIONS (.png, .jpg, .jpeg, .gif, .bmp, .webp, .tiff, .tif):
    → ImageUnderstandingLoader with prompt (background job)
elif extension in VIDEO_EXTENSIONS (.mp4, .webm, .avi, .mov, .mkv):
    → VideoUnderstandingLoader with prompt (background job)
else:
    → get_loader_class(extension) (immediate)
```

### Default Prompts
```python
DEFAULT_IMAGE_PROMPT = "Describe this image in detail for use as a searchable document."
DEFAULT_VIDEO_PROMPT = "Analyze and describe the content of this video in detail for use as a searchable document."
```

### URL Detection
```python
def _is_youtube_url(url: str) -> bool:
    return any(domain in url.lower() for domain in ['youtube.com', 'youtu.be'])
```

### Key Constraints
- File size check MUST happen before processing (check `Content-Length` header or file size after upload)
- Temp file cleanup MUST happen in a `finally` block
- Multiple files: process each file, collect all documents, then `add_documents` once
- For background jobs: use `uuid.uuid4().hex` for job_id
- JSON body with `content`: create `Document(page_content=content, metadata=body.get('metadata', {}))`
- The `prompt` for image/video can come from form fields (multipart) or query params

### References in Codebase
- `packages/ai-parrot/src/parrot/handlers/chat.py:396` — handle_upload usage
- `packages/ai-parrot/src/parrot/handlers/scraping/handler.py` — JobManager job creation pattern
- User-provided code in brainstorm for PDF loading flow

---

## Acceptance Criteria

- [ ] PUT with file upload loads documents from supported file types
- [ ] PUT rejects files exceeding `VECTOR_HANDLER_MAX_FILE_SIZE` with 413
- [ ] PUT with `.json` file uses `JSONDataSource` (not MarkdownLoader)
- [ ] PUT with image files dispatches to background job with optional prompt
- [ ] PUT with video files dispatches to background job with optional prompt
- [ ] PUT with JSON body `{"content": "..."}` creates Document and loads immediately
- [ ] PUT with JSON body `{"url": [...]}` dispatches URL loading as background job
- [ ] YouTube URLs are handled via YoutubeLoader
- [ ] Non-YouTube URLs use WebScrapingTool (or CrawlEngine if `crawl_entire_site=true`)
- [ ] Multiple files per request are supported
- [ ] Temp files are cleaned up after processing (even on error)
- [ ] Default prompts used for image/video when user doesn't provide one
- [ ] Background jobs return `{"job_id": "...", "status": "pending", ...}`
- [ ] Immediate loads return `{"status": "loaded", "documents": N}`
- [ ] All unit tests pass

---

## Test Specification

```python
# tests/unit/test_vectorstore_put.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


class TestPutFileUpload:
    @pytest.mark.asyncio
    async def test_pdf_file_loads_immediately(self):
        """PDF file is loaded via PDFLoader and returns immediate result."""
        pass

    @pytest.mark.asyncio
    async def test_json_file_uses_json_datasource(self):
        """.json file routes to JSONDataSource, not MarkdownLoader."""
        pass

    @pytest.mark.asyncio
    async def test_image_dispatches_background_job(self):
        """Image upload creates background job with prompt."""
        pass

    @pytest.mark.asyncio
    async def test_video_dispatches_background_job(self):
        """Video upload creates background job."""
        pass

    @pytest.mark.asyncio
    async def test_file_too_large_returns_413(self):
        """Rejects file exceeding max size."""
        pass

    @pytest.mark.asyncio
    async def test_multiple_files(self):
        """Multiple files are all processed."""
        pass

    @pytest.mark.asyncio
    async def test_temp_file_cleanup_on_error(self):
        """Temp files cleaned up even when loading fails."""
        pass

    @pytest.mark.asyncio
    async def test_default_prompt_for_image(self):
        """Image without prompt uses default."""
        pass


class TestPutJsonContent:
    @pytest.mark.asyncio
    async def test_inline_content_creates_document(self):
        """JSON with content field creates Document directly."""
        pass

    @pytest.mark.asyncio
    async def test_url_list_dispatches_job(self):
        """JSON with url list creates background job."""
        pass

    @pytest.mark.asyncio
    async def test_youtube_url_uses_youtube_loader(self):
        """YouTube URLs route to YoutubeLoader."""
        pass

    @pytest.mark.asyncio
    async def test_crawl_entire_site_flag(self):
        """crawl_entire_site=true uses CrawlEngine."""
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-608 is in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-611-put-data-loading.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet)
**Date**: 2026-04-07
**Notes**: PUT method with file upload, JSON content, and URL paths. Image/video dispatched to background jobs. File size check moved before _get_store per spec. 9 unit tests all pass.

**Deviations from spec**: File size check reordered to before _get_store for correct early-return behavior.
