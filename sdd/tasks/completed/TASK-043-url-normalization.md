# TASK-043: URL Normalization Utilities

**Feature**: FEAT-013 — CrawlEngine
**Spec**: `sdd/specs/scrapingplan-crawlengine.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

URL normalization is the foundation for deduplication across the CrawlEngine.
Without consistent normalization, the crawler would re-visit the same page via
different URL variants (trailing slashes, query params, `www.` prefix, etc.).
This module is used by both `CrawlGraph` and `LinkDiscoverer`.

Implements spec Section 9 (URL Normalization Rules) and Module 1.

---

## Scope

- Implement `normalize_url(url: str, base: str) -> Optional[str]` function
- Handle all normalization rules from the spec:
  - Resolve relative URLs against base
  - Convert scheme to lowercase
  - Remove `www.` prefix for domain comparison
  - Strip query string and fragment
  - Remove trailing slash (`/products/` → `/products`)
  - Reject non-HTTP(S) schemes (`mailto:`, `javascript:`, `data:`, etc.)
- Return `None` for URLs that should be discarded
- Write comprehensive unit tests

**NOT in scope**: Link discovery logic, graph management, crawl strategies.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/url_utils.py` | CREATE | `normalize_url()` function |
| `tests/tools/scraping/test_url_utils.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
from urllib.parse import urlparse, urlunparse, urljoin
from typing import Optional

def normalize_url(url: str, base: str) -> Optional[str]:
    """Normalize URL for deduplication. Returns None if URL should be discarded."""
    ...
```

### Key Constraints
- Standard library only — no external dependencies
- Pure function, no side effects
- Must handle edge cases: empty strings, malformed URLs, anchors-only (`#section`)

### References in Codebase
- `parrot/tools/scraping/models.py` — existing URL handling patterns
- `sdd/proposals/scrapingplan-crawlengine.md` Section 9 — normalization spec

---

## Acceptance Criteria

- [ ] `normalize_url` resolves relative URLs correctly
- [ ] Query params and fragments stripped
- [ ] `www.` prefix removed
- [ ] Trailing slashes removed
- [ ] Non-HTTP schemes return None
- [ ] All tests pass: `pytest tests/tools/scraping/test_url_utils.py -v`
- [ ] Import works: `from parrot.tools.scraping.url_utils import normalize_url`

---

## Test Specification

```python
# tests/tools/scraping/test_url_utils.py
import pytest
from parrot.tools.scraping.url_utils import normalize_url


class TestNormalizeUrl:
    def test_relative_url(self):
        result = normalize_url("/products", "https://example.com/page")
        assert result == "https://example.com/products"

    def test_strips_query_and_fragment(self):
        result = normalize_url("https://example.com/page?utm_source=google#top", "")
        assert result == "https://example.com/page"

    def test_removes_www(self):
        result = normalize_url("https://www.example.com/page", "")
        assert result == "https://example.com/page"

    def test_removes_trailing_slash(self):
        result = normalize_url("https://example.com/products/", "")
        assert result == "https://example.com/products"

    def test_root_path_preserved(self):
        result = normalize_url("https://example.com/", "")
        assert result == "https://example.com/"

    def test_rejects_mailto(self):
        assert normalize_url("mailto:user@example.com", "") is None

    def test_rejects_javascript(self):
        assert normalize_url("javascript:void(0)", "") is None

    def test_rejects_data_uri(self):
        assert normalize_url("data:text/html,<h1>Hi</h1>", "") is None

    def test_lowercase_scheme(self):
        result = normalize_url("HTTPS://Example.Com/Page", "")
        assert result.startswith("https://")

    def test_empty_url_returns_none(self):
        assert normalize_url("", "https://example.com") is None or \
               normalize_url("", "https://example.com") == "https://example.com/"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingplan-crawlengine.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-043-url-normalization.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Implemented `normalize_url()` in `parrot/tools/scraping/url_utils.py` with all 6 normalization rules from the spec. 23 unit tests written and passing covering relative URLs, query/fragment stripping, www removal, trailing slash handling, scheme rejection, empty/malformed inputs, and idempotence.

**Deviations from spec**: none
