# TASK-046: LinkDiscoverer

**Feature**: FEAT-013 — CrawlEngine
**Spec**: `sdd/specs/scrapingplan-crawlengine.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-043
**Assigned-to**: claude-session

---

## Context

`LinkDiscoverer` is responsible for extracting and filtering outgoing links from
scraped HTML pages. It applies CSS selector filtering, regex pattern matching, and
domain scoping to determine which links are eligible for crawling. This component
is used by `CrawlEngine` after each page is scraped.

Implements spec Module 4 and proposal Section 5.

---

## Scope

- Implement `LinkDiscoverer` class with configurable:
  - `follow_selector` — CSS selector for link elements (default: `a[href]`)
  - `follow_pattern` — optional regex pattern to filter URLs
  - `base_domain` — domain for same-origin scoping
  - `allow_external` — whether to follow off-domain links
- Implement `discover(html, base_url, current_depth, max_depth) -> List[str]`:
  - Extract links via BeautifulSoup CSS selector
  - Resolve relative URLs to absolute
  - Apply regex pattern filter
  - Apply domain scope filter
  - Apply depth guard (return `[]` if `current_depth >= max_depth`)
  - Deduplicate while preserving order
  - Normalize all URLs using `normalize_url()` from TASK-043
- Write unit tests

**NOT in scope**: Graph management, crawl orchestration, strategy selection.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/link_discoverer.py` | CREATE | `LinkDiscoverer` class |
| `tests/tools/scraping/test_link_discoverer.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
import re
from typing import List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .url_utils import normalize_url

class LinkDiscoverer:
    def __init__(
        self,
        follow_selector: str = "a[href]",
        follow_pattern: Optional[str] = None,
        base_domain: Optional[str] = None,
        allow_external: bool = False,
    ):
        self.follow_selector = follow_selector
        self.follow_pattern = re.compile(follow_pattern) if follow_pattern else None
        self.base_domain = base_domain
        self.allow_external = allow_external

    def discover(self, html: str, base_url: str, current_depth: int, max_depth: int) -> List[str]:
        ...
```

### Key Constraints
- Uses BeautifulSoup with `html.parser` (already a project dependency)
- Must handle `href` and `src` attributes
- Deduplicate using `dict.fromkeys()` to preserve discovery order
- All returned URLs must be normalized via `normalize_url()`
- Must not crash on malformed HTML

### References in Codebase
- `parrot/tools/scraping/models.py` — BeautifulSoup usage patterns
- `parrot/tools/scraping/url_utils.py` (TASK-043) — `normalize_url()`

---

## Acceptance Criteria

- [ ] CSS selector filtering works for custom selectors
- [ ] Regex pattern correctly filters URLs
- [ ] Domain scoping blocks external links when `allow_external=False`
- [ ] External links allowed when `allow_external=True`
- [ ] Depth guard returns empty list at max depth
- [ ] Duplicate URLs deduplicated in output
- [ ] Relative URLs resolved to absolute
- [ ] All returned URLs are normalized
- [ ] All tests pass: `pytest tests/tools/scraping/test_link_discoverer.py -v`
- [ ] Import works: `from parrot.tools.scraping.link_discoverer import LinkDiscoverer`

---

## Test Specification

```python
# tests/tools/scraping/test_link_discoverer.py
import pytest
from parrot.tools.scraping.link_discoverer import LinkDiscoverer


SAMPLE_HTML = """
<html><body>
  <a href="/products">Products</a>
  <a href="/about">About</a>
  <a href="https://external.com/page">External</a>
  <a href="/products?utm=123#section">Products with tracking</a>
  <a href="mailto:test@example.com">Email</a>
</body></html>
"""


class TestLinkDiscoverer:
    def test_basic_discovery(self):
        d = LinkDiscoverer(base_domain="example.com")
        links = d.discover(SAMPLE_HTML, "https://example.com", 0, 2)
        assert "https://example.com/products" in links
        assert "https://example.com/about" in links

    def test_domain_scoping(self):
        d = LinkDiscoverer(base_domain="example.com", allow_external=False)
        links = d.discover(SAMPLE_HTML, "https://example.com", 0, 2)
        assert not any("external.com" in l for l in links)

    def test_allow_external(self):
        d = LinkDiscoverer(base_domain="example.com", allow_external=True)
        links = d.discover(SAMPLE_HTML, "https://example.com", 0, 2)
        assert any("external.com" in l for l in links)

    def test_pattern_filter(self):
        d = LinkDiscoverer(base_domain="example.com", follow_pattern=r"/products")
        links = d.discover(SAMPLE_HTML, "https://example.com", 0, 2)
        assert all("products" in l for l in links)

    def test_depth_guard(self):
        d = LinkDiscoverer(base_domain="example.com")
        links = d.discover(SAMPLE_HTML, "https://example.com", 2, 2)
        assert links == []

    def test_deduplication(self):
        d = LinkDiscoverer(base_domain="example.com")
        links = d.discover(SAMPLE_HTML, "https://example.com", 0, 2)
        assert len(links) == len(set(links))

    def test_rejects_mailto(self):
        d = LinkDiscoverer(base_domain="example.com")
        links = d.discover(SAMPLE_HTML, "https://example.com", 0, 2)
        assert not any("mailto" in l for l in links)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingplan-crawlengine.spec.md` for full context
2. **Check dependencies** — verify TASK-043 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-046-link-discoverer.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Implemented `LinkDiscoverer` class with CSS selector extraction, regex pattern filtering, domain scoping, depth guard, URL normalization, and deduplication. 10 unit tests passing covering all acceptance criteria including edge cases (empty HTML, malformed HTML).

**Deviations from spec**: none
