# TASK-632: Tests for trafilatura extraction pipeline and handler refactor

**Feature**: vector-store-handler-scraping
**Spec**: `sdd/specs/vector-store-handler-scraping.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-629, TASK-630, TASK-631
**Assigned-to**: unassigned

---

## Context

> This task creates the test suite for the entire FEAT-091 feature: trafilatura extraction
> in both `WebScrapingLoader` and `WebLoader`, the handler refactor, and integration tests
> verifying clean content flows into the vector store.
>
> Implements: Spec Module 4 (Tests) and Spec Section 4 (Test Specification).

---

## Scope

- Create `tests/loaders/test_webscraping_trafilatura.py` — unit tests for `WebScrapingLoader` trafilatura extraction
- Create `tests/loaders/test_webloader_trafilatura.py` — unit tests for `WebLoader` trafilatura extraction
- Extend handler tests for `_load_urls()` refactor (create `tests/handlers/test_vectorstore_url_loading.py`)
- Create test fixtures for sample HTML pages (product page with noise, minimal page, empty page)
- Test: trafilatura extraction, fallback logic, metadata enrichment, handler delegation, backward compatibility

**NOT in scope**:
- Live integration tests requiring actual web scraping (use mocked HTML)
- Performance benchmarks
- Tests for existing functionality not modified by this feature

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/loaders/test_webscraping_trafilatura.py` | CREATE | Unit tests for WebScrapingLoader trafilatura extraction |
| `tests/loaders/test_webloader_trafilatura.py` | CREATE | Unit tests for WebLoader trafilatura extraction |
| `tests/handlers/test_vectorstore_url_loading.py` | CREATE | Tests for handler _load_urls() refactor |
| `tests/conftest.py` | MODIFY (if needed) | Add shared fixtures for sample HTML |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Test imports:
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bs4 import BeautifulSoup

# Components under test:
from parrot_loaders.webscraping import WebScrapingLoader
# verified: packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:51

from parrot.stores.models import Document
# verified: packages/ai-parrot/src/parrot/stores/models.py:21

# For WebLoader tests:
from parrot_loaders.web import WebLoader
# verified: packages/ai-parrot-loaders/src/parrot_loaders/web.py:169

# For handler tests — the handler class:
# Note: VectorStoreHandler requires aiohttp request context, so tests
# should mock at the _load_urls method level
```

### Existing Signatures to Use

```python
# WebScrapingLoader (after TASK-629):
class WebScrapingLoader(AbstractLoader):
    def __init__(
        self,
        source=None,
        *,
        content_extraction: Literal["auto", "trafilatura", "markdown", "text"] = "auto",
        trafilatura_fallback_threshold: float = 0.1,
        # ... other params ...
    ) -> None: ...

    def _result_to_documents(self, result, url, crawl_depth=None) -> List[Document]: ...
    # This is the key method to test

# WebLoader (after TASK-630):
class WebLoader(AbstractLoader):
    def __init__(
        self,
        source_type='website',
        *,
        content_extraction: Literal["auto", "trafilatura", "markdown", "text"] = "auto",
        trafilatura_fallback_threshold: float = 0.1,
        # ... other params ...
    ) -> None: ...

    def clean_html(self, html, tags, ...) -> Tuple[List[str], str, str]: ...

# Document model:
class Document(BaseModel):
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

### Does NOT Exist

- ~~`tests/loaders/test_webscraping_trafilatura.py`~~ — does not exist yet; must be created
- ~~`tests/loaders/test_webloader_trafilatura.py`~~ — does not exist yet; must be created
- ~~`tests/handlers/test_vectorstore_url_loading.py`~~ — does not exist yet; must be created
- ~~`WebScrapingLoader.extract_with_trafilatura()`~~ — the method is named `_extract_with_trafilatura()` (private)

---

## Implementation Notes

### Test Structure

#### WebScrapingLoader Tests (`test_webscraping_trafilatura.py`)

```python
import pytest
from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup
from parrot_loaders.webscraping import WebScrapingLoader
from parrot.stores.models import Document


@pytest.fixture
def sample_product_html():
    """HTML mimicking a product page with nav, footer, scripts, main content."""
    return """
    <html lang="en">
    <head>
        <title>Prepaid Plans | Example Wireless</title>
        <meta name="description" content="Check out our prepaid plans">
        <meta name="author" content="Example Wireless">
        <script>var tracking = true;</script>
        <style>.nav { color: blue; }</style>
    </head>
    <body>
        <nav><a href="/">Home</a><a href="/plans">Plans</a></nav>
        <main>
            <h1>Prepaid Plans</h1>
            <p>Get the best prepaid wireless plans starting at $25/mo.</p>
            <table>
                <thead><tr><th>Plan</th><th>Price</th><th>Data</th></tr></thead>
                <tbody>
                    <tr><td>Basic</td><td>$25/mo</td><td>5GB</td></tr>
                    <tr><td>Plus</td><td>$40/mo</td><td>15GB</td></tr>
                </tbody>
            </table>
            <h2>Why Choose Prepaid?</h2>
            <p>No credit check. No annual contract. No surprises.</p>
        </main>
        <footer>Copyright 2026 Example Wireless</footer>
        <script>analytics.track('page_view');</script>
    </body>
    </html>
    """


@pytest.fixture
def mock_scraping_result(sample_product_html):
    """Mock ScrapingResult with bs_soup."""
    result = MagicMock()
    result.success = True
    result.url = "https://example.com/plans"
    result.bs_soup = BeautifulSoup(sample_product_html, "html.parser")
    result.extracted_data = {}
    result.content = sample_product_html
    return result


class TestTrafilaturaExtraction:
    def test_trafilatura_extraction_clean_content(self, mock_scraping_result):
        """Trafilatura extracts main content, strips nav/footer/scripts."""
        loader = WebScrapingLoader(
            source="https://example.com/plans",
            content_extraction="auto",
        )
        docs = loader._result_to_documents(
            mock_scraping_result, "https://example.com/plans"
        )
        # Should have at least one document with clean content
        assert len(docs) > 0
        main_doc = docs[0]
        assert "Prepaid Plans" in main_doc.page_content
        assert "<script>" not in main_doc.page_content
        assert "<nav>" not in main_doc.page_content

    def test_trafilatura_metadata_extraction(self, mock_scraping_result):
        """Metadata includes author, date, sitename from trafilatura."""
        loader = WebScrapingLoader(
            source="https://example.com/plans",
            content_extraction="auto",
        )
        docs = loader._result_to_documents(
            mock_scraping_result, "https://example.com/plans"
        )
        assert len(docs) > 0
        meta = docs[0].metadata.get("document_meta", {})
        assert "title" in meta
        # author/date/sitename may or may not be present depending on HTML

    def test_trafilatura_fallback_on_sparse_output(self, sample_product_html):
        """When trafilatura returns sparse output, fallback to markdownify."""
        result = MagicMock()
        result.success = True
        result.url = "https://example.com/plans"
        result.bs_soup = BeautifulSoup(sample_product_html, "html.parser")
        result.extracted_data = {}
        result.content = sample_product_html

        with patch("parrot_loaders.webscraping.trafilatura") as mock_traf:
            mock_traf.extract.return_value = "tiny"  # Very sparse
            mock_traf.bare_extraction.return_value = {}
            loader = WebScrapingLoader(
                source="https://example.com/plans",
                content_extraction="auto",
                trafilatura_fallback_threshold=0.5,  # High threshold forces fallback
            )
            docs = loader._result_to_documents(result, "https://example.com/plans")
            assert len(docs) > 0
            # Should have fallen back — metadata should indicate fallback
            assert docs[0].metadata.get("content_extraction") in (
                "markdownify_fallback", "markdown"
            )

    def test_content_extraction_mode_markdown(self, mock_scraping_result):
        """content_extraction='markdown' skips trafilatura entirely."""
        loader = WebScrapingLoader(
            source="https://example.com/plans",
            content_extraction="markdown",
        )
        docs = loader._result_to_documents(
            mock_scraping_result, "https://example.com/plans"
        )
        assert len(docs) > 0
        # Should use markdownify path

    def test_tables_extracted_separately(self, mock_scraping_result):
        """Tables always extracted as separate Documents."""
        loader = WebScrapingLoader(
            source="https://example.com/plans",
            content_extraction="auto",
            parse_tables=True,
        )
        docs = loader._result_to_documents(
            mock_scraping_result, "https://example.com/plans"
        )
        table_docs = [d for d in docs if d.metadata.get("content_kind") == "table"]
        assert len(table_docs) > 0
        assert "Basic" in table_docs[0].page_content
        assert "$25/mo" in table_docs[0].page_content


class TestTrafilaturaImportGuard:
    def test_missing_trafilatura_graceful(self, mock_scraping_result):
        """If trafilatura not installed, falls back silently in auto mode."""
        with patch.dict("sys.modules", {"trafilatura": None}):
            # This tests the import guard — when trafilatura is None,
            # the loader should fall back to markdownify
            loader = WebScrapingLoader(
                source="https://example.com/plans",
                content_extraction="auto",
            )
            docs = loader._result_to_documents(
                mock_scraping_result, "https://example.com/plans"
            )
            assert len(docs) > 0  # Should work via fallback
```

#### Handler Tests (`test_vectorstore_url_loading.py`)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.stores.models import Document


class TestLoadUrlsRefactor:
    @pytest.mark.asyncio
    async def test_load_urls_uses_loader(self):
        """_load_urls() uses WebScrapingLoader, not WebScrapingTool."""
        with patch("parrot.handlers.stores.handler.WebScrapingLoader") as MockLoader:
            # ... mock setup and handler instantiation
            pass

    @pytest.mark.asyncio
    async def test_load_urls_crawl_mode(self):
        """crawl_entire_site=True maps to crawl=True, depth=2."""
        pass

    @pytest.mark.asyncio
    async def test_load_urls_youtube_bypass(self):
        """YouTube URLs route to YoutubeLoader, others to WebScrapingLoader."""
        pass

    @pytest.mark.asyncio
    async def test_load_urls_content_extraction_passthrough(self):
        """content_extraction parameter is passed to WebScrapingLoader."""
        pass
```

### Key Constraints

- Use `pytest` and `pytest-asyncio` for async tests
- Mock the `WebScrapingToolkit` and browser interactions — these tests should NOT launch browsers
- Use `unittest.mock.patch` for trafilatura import guard tests
- Test both the happy path AND the fallback paths
- Verify backward compatibility: existing usage without new parameters still works

### References in Codebase

- `tests/` — existing test directory structure
- Spec Section 4 (Test Specification) — test fixture definitions
- TASK-629 implementation — `_result_to_documents()` modifications to test
- TASK-630 implementation — `clean_html()` modifications to test
- TASK-631 implementation — `_load_urls()` refactor to test

---

## Acceptance Criteria

- [ ] `tests/loaders/test_webscraping_trafilatura.py` created and all tests pass
- [ ] `tests/loaders/test_webloader_trafilatura.py` created and all tests pass
- [ ] `tests/handlers/test_vectorstore_url_loading.py` created and all tests pass
- [ ] All tests: `pytest tests/loaders/test_webscraping_trafilatura.py tests/loaders/test_webloader_trafilatura.py tests/handlers/test_vectorstore_url_loading.py -v`
- [ ] Tests cover: trafilatura extraction, fallback logic, metadata enrichment, handler delegation, backward compatibility, import guard
- [ ] No existing tests broken

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/vector-store-handler-scraping.spec.md` for full context
2. **Check dependencies** — verify TASK-629, TASK-630, TASK-631 are in `tasks/completed/`
3. **Read the implementations** from TASK-629, TASK-630, TASK-631 to understand what to test
4. **Verify the Codebase Contract** — confirm the new parameters and methods exist
5. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
6. **Implement** following the scope and test scaffold above
7. **Run all tests**: `source .venv/bin/activate && pytest tests/loaders/test_webscraping_trafilatura.py tests/loaders/test_webloader_trafilatura.py tests/handlers/test_vectorstore_url_loading.py -v`
8. **Verify** all acceptance criteria are met
9. **Move this file** to `tasks/completed/TASK-632-tests-extraction-pipeline.md`
10. **Update index** → `"done"`
11. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
