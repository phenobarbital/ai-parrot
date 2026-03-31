# TASK-497: Gorilla Sheds Scraper & PageIndex Builder

**Feature**: advisor-ontologic-rag-agent (FEAT-071)
**Spec**: `sdd/specs/advisor-ontologic-rag-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This is the data acquisition task for FEAT-071. Before the advisor agent can
> answer questions about Gorilla Sheds, we need structured data: a hierarchical
> PageIndex tree for the `PageIndexRetriever` and product JSON for reference.
>
> Note: The `gorillashed.products` PgVector table is **already populated** with
> vectorised products — this task does NOT need to load into PgVector. Instead it
> produces a PageIndex tree and supplementary JSON files that the agent will use
> for tree-based navigation (company info, FAQ, installation, product catalog).
>
> Implements **Module 1** from the spec.

---

## Scope

- Implement `examples/shoply/scraper.py` as an async scraper using `aiohttp` + `BeautifulSoup`
- Fetch and parse these Gorilla Sheds pages:
  - About: `https://gorillashed.com/pages/about`
  - FAQ: `https://gorillashed.com/pages/faq`
  - Installation: `https://gorillashed.com/pages/shed-installation-process`
  - Product collection: `https://gorillashed.com/collections/sheds`
  - Individual product pages linked from the collection
- Extract from each product page: name, description, features, dimensions/specs,
  price (if available), images, URL
- Build a hierarchical `PageIndex` JSON tree:
  ```
  Root: "Gorilla Sheds"
    ├── "About Gorilla Sheds" (company info)
    ├── "FAQ" (frequently asked questions)
    ├── "Installation Process" (post-sale service)
    └── "Sheds Collection"
         ├── Product 1
         ├── Product 2
         └── ...
  ```
- Persist outputs to `examples/shoply/data/`:
  - `page_index.json` — full PageIndex tree
  - `products.json` — flat list of product dicts (for reference/debugging)
- Create `examples/shoply/__init__.py` (empty)
- Create `examples/shoply/data/` directory with `.gitkeep`
- Add polite delays (1-2s) between requests to avoid rate limiting
- Handle missing fields gracefully with sensible defaults
- Standalone: `python examples/shoply/scraper.py` runs the full scrape

**NOT in scope**:
- Loading products into PgVector (already done)
- Building the advisor agent (TASK-499)
- Catalog loader script (TASK-498)

---

## Files to Create / Modify

| File | Action | Description |
|------|--------|-------------|
| `examples/shoply/__init__.py` | CREATE | Package init |
| `examples/shoply/scraper.py` | CREATE | Main scraper with PageIndex builder |
| `examples/shoply/data/.gitkeep` | CREATE | Ensure data directory exists in git |

---

## Implementation Notes

### Pattern to Follow

```python
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://gorillashed.com"
PAGES = {
    "about": "/pages/about",
    "faq": "/pages/faq",
    "installation": "/pages/shed-installation-process",
    "collection": "/collections/sheds",
}
DATA_DIR = Path(__file__).parent / "data"


async def fetch_page(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch a page and return HTML text."""
    async with session.get(url) as resp:
        resp.raise_for_status()
        return await resp.text()


async def scrape_gorillasheds() -> tuple[dict, list[dict]]:
    """Main scrape entry point. Returns (page_index_tree, products_list)."""
    ...


def build_page_index(
    about_text: str,
    faq_text: str,
    installation_text: str,
    products: list[dict],
) -> dict:
    """Build hierarchical PageIndex tree from scraped content."""
    ...


if __name__ == "__main__":
    asyncio.run(scrape_gorillasheds())
```

### Key Constraints

- Use `aiohttp.ClientSession` — never `requests`
- Use `BeautifulSoup` with `lxml` or `html.parser` backend
- Add `asyncio.sleep(1.5)` between requests
- Set a proper User-Agent header
- All functions must be async where I/O is involved
- PageIndex node structure must match `PageIndexRetriever` expectations:
  `node_id`, `title`, `summary`, `text`, and optional `children`
- Use `logging` for operational messages, `print` only for CLI progress

### References in Codebase

- `parrot/pageindex/retriever.py` — PageIndex tree node structure
- `examples/advisors/product_advisor_basebot.py` — example pattern

---

## Acceptance Criteria

- [ ] `python examples/shoply/scraper.py` completes without errors
- [ ] `examples/shoply/data/page_index.json` produced with valid tree structure
- [ ] `examples/shoply/data/products.json` produced with product list
- [ ] Tree has 4 top-level nodes: about, faq, installation, products
- [ ] Products node has children (one per scraped product)
- [ ] Each product node has: `node_id`, `title`, `summary`, `text`
- [ ] Polite delays between requests (no rapid-fire)
- [ ] Graceful handling of missing fields

---

## Test Specification

```python
# tests/examples/test_scraper.py
import pytest
import json
from pathlib import Path


class TestScraperOutput:
    """Test scraper output files (run after scraper.py)."""

    @pytest.fixture
    def page_index(self):
        path = Path("examples/shoply/data/page_index.json")
        if not path.exists():
            pytest.skip("Run scraper.py first")
        return json.loads(path.read_text())

    @pytest.fixture
    def products(self):
        path = Path("examples/shoply/data/products.json")
        if not path.exists():
            pytest.skip("Run scraper.py first")
        return json.loads(path.read_text())

    def test_page_index_has_root(self, page_index):
        assert "title" in page_index
        assert "children" in page_index

    def test_page_index_top_level_nodes(self, page_index):
        ids = [c["node_id"] for c in page_index["children"]]
        assert "company-info" in ids
        assert "faq" in ids
        assert "installation" in ids
        assert "products" in ids

    def test_products_node_has_children(self, page_index):
        products_node = [c for c in page_index["children"] if c["node_id"] == "products"][0]
        assert len(products_node.get("children", [])) > 0

    def test_products_json_not_empty(self, products):
        assert len(products) > 0

    def test_product_has_required_fields(self, products):
        for p in products[:3]:
            assert "name" in p
            assert "url" in p
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-497-gorilla-scraper.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
