---
type: Wiki Overview
title: 'TASK-1050: Add `_action_extract_jsonld` Executor Handler + Dispatch Wiring'
id: doc:sdd-tasks-completed-task-1050-add-extract-jsonld-executor-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: With the model registered (TASK-1049) and the shared `EXTRACTOR_REGISTRY`
relates_to:
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.utils.jsonld_extractors
  rel: mentions
- concept: mod:parrot_tools.scraping.executor
  rel: mentions
---

# TASK-1050: Add `_action_extract_jsonld` Executor Handler + Dispatch Wiring

**Feature**: FEAT-154 — WebScrapingToolkit `extract_jsonld` Browser Action
**Spec**: `sdd/specs/webscrapingtoolkit-jsonld.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1048, TASK-1049
**Assigned-to**: unassigned

---

## Context

With the model registered (TASK-1049) and the shared `EXTRACTOR_REGISTRY`
reachable from core (TASK-1048), the runtime executor now needs to (a)
dispatch `extract_jsonld` steps and (b) implement the actual extraction
logic. The handler mirrors `_action_extract` in shape — same signature,
same key-resolution rules, same key-collision merge semantics — but
operates on JSON-LD `<script>` blocks instead of CSS/XPath selectors,
and routes typed nodes through the shared registry rather than reading
DOM nodes directly.

This task implements **Module 4** from the spec (§3 — *`_action_extract_jsonld`
executor handler*) and the integration tests from **Module 5**.

Reference: spec §2 *Architectural Design — Overview (3)*, §3 *Module 4*,
§3 *Module 5*, §6 *Codebase Contract* (executor anchors), §7 *Patterns
to Follow* and *Known Risks*.

---

## Scope

- Add a new `async def _action_extract_jsonld(driver, action, step,
  step_extracted)` function to
  `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`,
  modeled after `_action_extract` (lines 543–615).
- Add a private helper `def _walk_jsonld_for_extractor(data, allowed_types,
  out: list)` (or equivalent) that reproduces the loader's recursion
  algorithm (`_walk_jsonld_node` at `webscraping.py:605`): descend into
  `@graph` and arrays, dispatch typed objects via `EXTRACTOR_REGISTRY`,
  break after first matching extractor for a node.
- Add the dispatch branch in `_dispatch_step` (executor.py around line
  263) **between** the existing `"extract"` and `"get_text"` branches.
- Import `EXTRACTOR_REGISTRY` and `JsonLdItem` from
  `parrot.utils.jsonld_extractors`.
- De-duplicate items by `(content_kind, page_content)` to match the loader.
- Honor `action.types` filter (`None` → all registered; otherwise the
  intersection of `types` and registry keys).
- Resolve the `step_extracted` storage key with the same fallback chain
  as `_action_extract`: `extract_name` → `name` → `step.description` →
  literal `"jsonld"`.
- Convert each `JsonLdItem` to a JSON-serializable dict via
  `dataclasses.asdict()` before storing.
- Implement key-collision merge semantics (when an existing list is
  present in `step_extracted[key]`, append non-duplicate dicts) parity
  with `_action_extract` lines 597–609.
- Add 7 integration tests covering: basic single-type extraction,
  multi-type page with `@graph`, `types` filter, empty page, malformed
  block tolerance, custom `extract_name`, and `_dispatch_step` wiring.

**NOT in scope**:
- Adding a `WebScrapingTool.extract_jsonld()` convenience method (open
  question 2 in spec §8 — deferred).
- Refactoring `_action_extract` (it stays as-is).
- Modifying `WebScrapingLoader._extract_jsonld` (the loader keeps its
  own recursion).
- Adding new schema.org types to `EXTRACTOR_REGISTRY`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | MODIFY | Add import, new handler, helper, and dispatch branch. |
| `packages/ai-parrot-tools/tests/scraping/test_extract_jsonld_action.py` | CREATE | Seven integration tests for the new handler. |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports

```python
# Already present at the top of parrot_tools/scraping/executor.py (lines 11-29):
from __future__ import annotations
import asyncio
import logging
import re as _re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .drivers.abstract import AbstractDriver
from .models import (
    ScrapingResult,
    ScrapingSelector,
    ScrapingStep,
)
from .plan import ScrapingPlan
from .toolkit_models import DriverConfig

# NEW — add to executor.py imports:
import json
from dataclasses import asdict
from parrot.utils.jsonld_extractors import EXTRACTOR_REGISTRY, JsonLdItem
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py:225
async def _dispatch_step(
    driver: AbstractDriver,
    step: ScrapingStep,
    base_url: str,
    timeout: int,
    step_extracted: Dict[str, Any],
) -> bool: ...
# Branch table at lines 247-289. Insert new branch BETWEEN:
#     elif action_type == "extract":               # line 263
#         return await _action_extract(...)
#     # ← NEW BRANCH HERE
#     elif action_type == "get_text":              # line 265
#         return await _action_get_text(...)


# packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py:543 — REFERENCE
async def _action_extract(
    driver: AbstractDriver,
    action: Any,
    step: ScrapingStep,
    step_extracted: Dict[str, Any],
) -> bool:
    """Run an ``extract`` step against the current DOM."""
    html = await driver.get_page_source()
    soup = BeautifulSoup(html, "html.parser")
    key = (
        getattr(action, "extract_name", "")
        or getattr(action, "name", "")
        or step.description
        or "extracted_data"
    )
    # ... (key-collision merge semantics at lines 597-609 are the reference
    # for the new handler's merge logic)


# packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:605 — REFERENCE
def _walk_jsonld_node(self, data: Any, items: List[JsonLdItem]) -> None:
    """Recursively walk a JSON-LD structure dispatching nodes to extractors."""
    if isinstance(data, list):
        for item in data:
            self._walk_jsonld_node(item, items)
        return
    if not isinstance(data, dict):
        return
    if "@graph" in data:
        self._walk_jsonld_node(data["@graph"], items)
        return
    node_type = data.get("@type")
    type_set = (
        {node_type} if isinstance(node_type, str) else set(node_type or [])
    )
    allowed = self._jsonld_types  # None = all, [] = disabled
    for t in EXTRACTOR_REGISTRY:
        if t not in type_set:
            continue
        if allowed is not None and t not in allowed:
            continue
        items.extend(EXTRACTOR_REGISTRY[t](data))
        break  # one match per node
# Reproduce this algorithm in a private helper inside executor.py.
# Note iteration order: walk EXTRACTOR_REGISTRY (insertion order) so that
# nodes carrying multiple @types get the highest-priority extractor.


# packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:646 — REFERENCE
def _extract_jsonld(self, soup: BeautifulSoup) -> List[JsonLdItem]:
    """Extract structured data from all JSON-LD blocks on the page."""
    if self._jsonld_types is not None and len(self._jsonld_types) == 0:
        return []
    items: List[JsonLdItem] = []
    seen: set[tuple[str, str]] = set()
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for s in scripts:
        raw = (s.string or s.text or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.logger.debug("Skipping malformed JSON-LD block: %s", exc)
            continue
        self._walk_jsonld_node(data, items)
    # de-dupe by (content_kind, page_content)
    unique: List[JsonLdItem] = []
    for item in items:
        key_ = (item.content_kind, item.page_content)
        if key_ not in seen:
            seen.add(key_)
            unique.append(item)
    return unique
# Reproduce this skeleton in _action_extract_jsonld, but log via the
# module-level `logger` (line 31 of executor.py) and write asdict(item)
# records into step_extracted[key] instead of returning a list.


# packages/ai-parrot/src/parrot/utils/jsonld_extractors.py — POST TASK-1048
JsonLdItem  # @dataclass — convert to dict via dataclasses.asdict
EXTRACTOR_REGISTRY: Dict[str, Callable[[Dict[str, Any]], List[JsonLdItem]]]
# Iteration over EXTRACTOR_REGISTRY relies on insertion-ordered dicts
# (Python 3.7+) to make multi-@type tie-breaking deterministic.


# packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py — module logger
logger = logging.getLogger(__name__)  # line 31 — already present
```

### Does NOT Exist

- ~~`driver.get_jsonld()` / `driver.extract_structured()`~~ — no such
  method on `AbstractDriver`. Use `await driver.get_page_source()` +
  BeautifulSoup, exactly mirroring `_action_extract`.
- ~~`JsonLdItem.to_dict()` / `JsonLdItem.dict()` / `JsonLdItem.model_dump()`~~
  — `JsonLdItem` is a stdlib `@dataclass`, NOT a Pydantic model. Convert
  via `dataclasses.asdict(item)` (or build the dict manually with the five
  documented fields).
- ~~`EXTRACTOR_REGISTRY[t](data, options=...)`~~ — extractor functions
  take exactly one argument: the JSON-LD node dict. No keyword arguments.
- ~~`step_extracted[key].append(item)`~~ as the merge primitive — the
  existing `_action_extract` merge does dedup-on-list-merge (lines 597-609).
  Reproduce that exact behavior.
- ~~`bs4.BeautifulSoup(html, "lxml")`~~ — the existing executor uses
  `"html.parser"`. Stay with `"html.parser"` for consistency and to avoid
  a hard `lxml` dep.
- ~~Filter falls back to all when `types == []`~~ — empty list MUST
  filter to nothing (the loader's `_jsonld_types == []` semantics). Only
  `None` means "every registered type".

---

## Implementation Notes

### Pattern to Follow

Reference is `_action_extract` (executor.py:543) for the outer shape and
key-collision merge semantics; reference is `WebScrapingLoader._extract_jsonld`
+ `_walk_jsonld_node` (webscraping.py:605, 646) for the JSON-LD recursion.

```python
# parrot_tools/scraping/executor.py — sketch (NOT a copy-paste — adapt)

import json
from dataclasses import asdict
from parrot.utils.jsonld_extractors import EXTRACTOR_REGISTRY, JsonLdItem


def _walk_jsonld_for_extract(
    data: Any,
    allowed_types: Optional[set[str]],
    out: List[JsonLdItem],
) -> None:
    """Reproduce WebScrapingLoader._walk_jsonld_node for the executor."""
    if isinstance(data, list):
        for item in data:
            _walk_jsonld_for_extract(item, allowed_types, out)
        return
    if not isinstance(data, dict):
        return
    if "@graph" in data:
        _walk_jsonld_for_extract(data["@graph"], allowed_types, out)
        return
    node_type = data.get("@type")
    type_set = (
        {node_type} if isinstance(node_type, str) else set(node_type or [])
    )
    for t in EXTRACTOR_REGISTRY:
        if t not in type_set:
            continue
        if allowed_types is not None and t not in allowed_types:
            continue
        out.extend(EXTRACTOR_REGISTRY[t](data))
        break  # first matching extractor wins per node


async def _action_extract_jsonld(
    driver: AbstractDriver,
    action: Any,
    step: ScrapingStep,
    step_extracted: Dict[str, Any],
) -> bool:
    """Run an ``extract_jsonld`` step against the current DOM."""
    html = await driver.get_page_source()
    soup = BeautifulSoup(html, "html.parser")

    key = (
        getattr(action, "extract_name", "")
        or getattr(action, "name", "")
        or step.description
        or "jsonld"
    )

    types_filter = getattr(action, "types", None)
    allowed: Optional[set[str]] = (
        set(types_filter) if types_filter is not None else None
    )
    # Empty list → filter to nothing (parity with loader's _jsonld_types).
    if allowed is not None and not allowed:
        step_extracted.setdefault(key, [])
        return True

    items: List[JsonLdItem] = []
    seen: set[tuple[str, str]] = set()
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for s in scripts:
        raw = (s.string or s.text or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.debug("Skipping malformed JSON-LD block: %s", exc)
            continue
        _walk_jsonld_for_extract(data, allowed, items)

    # De-duplicate by (content_kind, page_content) — parity with loader
    unique: List[Dict[str, Any]] = []
    for item in items:
        sig = (item.content_kind, item.page_content)
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(asdict(item))

    # Key-collision merge semantics — parity with _action_extract:597-609
    existing = step_extracted.get(key)
    if isinstance(existing, list):
        merged = list(existing)
        for record in unique:
            if record not in merged:
                merged.append(record)
        step_extracted[key] = merged
        logger.info(
            "extract_jsonld %r: appended %d new item(s) (total %d)",
            key, len(unique), len(merged),
        )
    else:
        step_extracted[key] = unique
        logger.info(
            "extract_jsonld %r: captured %d item(s)", key, len(unique),
        )
    return True
```

Dispatch wiring — insert the new branch between `"extract"` and `"get_text"`:

```python
# In _dispatch_step (executor.py around line 263):
    elif action_type == "extract":
        return await _action_extract(driver, action, step, step_extracted)
    elif action_type == "extract_jsonld":          # NEW
        return await _action_extract_jsonld(       # NEW
            driver, action, step, step_extracted   # NEW
        )                                          # NEW
    elif action_type == "get_text":
        return await _action_get_text(driver, action)
```

### Key Constraints

- **Async-first**: handler is `async def`, awaits `driver.get_page_source()`,
  no blocking I/O.
- **JSON-serializable output**: every record stored in `step_extracted[key]`
  must round-trip through `json.dumps(record)` without a `default=` arg.
  Verified against every shipped extractor — all `row_data` values are
  primitives, lists of primitives, or nested dicts of primitives.
- **De-duplication**: tuple `(content_kind, page_content)` — `page_content`
  is a string, hashable, and unique per logical item.
- **Empty list → empty result**: when no JSON-LD blocks are present, set
  `step_extracted[key] = []` (not `None`, not absent) and return `True`.
- **Malformed blocks**: `json.JSONDecodeError` → `logger.debug` + skip.
  Sibling valid blocks must still produce items.
- **Logger**: use the module-level `logger = logging.getLogger(__name__)`
  already declared at executor.py:31 — do NOT create a new logger.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py:543` —
  `_action_extract` reference shape.
- `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py:225` —
  `_dispatch_step` branch insertion site.
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:605` —
  `_walk_jsonld_node` recursion algorithm.
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:646` —
  `_extract_jsonld` skeleton.
- `packages/ai-parrot-tools/tests/scraping/test_executor.py` (top) —
  fixture pattern (`AsyncMock`-backed driver) for the new tests.

---

## Acceptance Criteria

- [ ] `_action_extract_jsonld` is defined in
      `parrot_tools/scraping/executor.py` with the documented signature.
- [ ] `_dispatch_step` routes `action_type == "extract_jsonld"` to the
      new handler and returns its result.
- [ ] Imports `EXTRACTOR_REGISTRY` and `JsonLdItem` from
      `parrot.utils.jsonld_extractors` (the core module from TASK-1048).
- [ ] On a page with one Product JSON-LD block, `step_extracted["jsonld"]`
      is a list of one dict with `content_kind == "jsonld-product"`.
- [ ] On a page with mixed FAQ + Product + Recipe blocks (and a `@graph`
      wrapper), the output flat list contains items for all three types,
      de-duplicated by `(content_kind, page_content)`.
- [ ] `types=["Product"]` keeps only product items; other types absent.
- [ ] `types=[]` produces an empty list (parity with loader's `_jsonld_types==[]`).
- [ ] On a page with no JSON-LD blocks, `step_extracted[key] == []`.
- [ ] Malformed JSON-LD blocks are silently skipped; sibling valid blocks
      still emit items.
- [ ] Custom `extract_name="products"` lands the result in
      `step_extracted["products"]`.
- [ ] Every emitted dict has the keys `content_kind`, `source_type`,
      `page_content`, `row_data`, `selector_name`, and `json.dumps(record)`
      succeeds for every record.
- [ ] All new tests pass:
      `pytest packages/ai-parrot-tools/tests/scraping/test_extract_jsonld_action.py -v`.
- [ ] Existing executor tests still pass:
      `pytest packages/ai-parrot-tools/tests/scraping/test_executor.py -v`.
- [ ] No linting / type errors:
      `ruff check packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`
      and `mypy packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/scraping/test_extract_jsonld_action.py

"""Integration tests for the extract_jsonld BrowserAction — FEAT-154 / TASK-1050."""

import json

import pytest
from unittest.mock import AsyncMock

from parrot.tools.scraping.executor import (
    _action_extract_jsonld,
    _dispatch_step,
)
from parrot.tools.scraping.models import ExtractJsonLd, ScrapingStep


# ── Fixtures ───────────────────────────────────────────────────────────

PRODUCT_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product",
 "name":"Acme Widget","description":"A useful widget"}
</script>
</head><body></body></html>
"""

MULTI_TYPE_GRAPH_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"Product","name":"Widget","description":"thing"},
  {"@type":"Recipe","name":"Pancakes","description":"breakfast",
   "recipeIngredient":["flour","milk"]},
  {"@type":"FAQPage","mainEntity":[
    {"@type":"Question","name":"Q1?",
     "acceptedAnswer":{"@type":"Answer","text":"A1."}}
  ]}
]}
</script>
</head><body></body></html>
"""

EMPTY_HTML = "<html><head></head><body><p>nothing here</p></body></html>"

MALFORMED_PLUS_VALID_HTML = """
<html><head>
<script type="application/ld+json">{ broken json </script>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"OK","description":"valid"}
</script>
</head><body></body></html>
"""


def _driver_returning(html: str):
    drv = AsyncMock()
    drv.get_page_source = AsyncMock(return_value=html)
    return drv


# ── Tests ──────────────────────────────────────────────────────────────

class TestActionExtractJsonLd:

    async def test_action_extract_jsonld_basic(self) -> None:
        action = ExtractJsonLd()
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        ok = await _action_extract_jsonld(
            _driver_returning(PRODUCT_HTML), action, step, step_extracted,
        )
        assert ok is True
        rows = step_extracted["jsonld"]
        assert len(rows) == 1
        assert rows[0]["content_kind"] == "jsonld-product"
        # JSON-serializable
        assert json.dumps(rows[0])

    async def test_action_extract_jsonld_multi_type(self) -> None:
        action = ExtractJsonLd()
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        await _action_extract_jsonld(
            _driver_returning(MULTI_TYPE_GRAPH_HTML), action, step, step_extracted,
        )
        kinds = {r["content_kind"] for r in step_extracted["jsonld"]}
        # The shared registry emits exactly these kinds for the documented types
        assert "jsonld-product" in kinds
        assert "jsonld-recipe" in kinds
        assert "faq" in kinds  # faq_extractor uses content_kind="faq"

    async def test_action_extract_jsonld_types_filter(self) -> None:
        action = ExtractJsonLd(types=["Product"])
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        await _action_extract_jsonld(
            _driver_returning(MULTI_TYPE_GRAPH_HTML), action, step, step_extracted,
        )
        kinds = {r["content_kind"] for r in step_extracted["jsonld"]}
        assert kinds == {"jsonld-product"}

    async def test_action_extract_jsonld_empty_list_filter(self) -> None:
        """types=[] disables extraction (parity with loader's _jsonld_types==[])."""
        action = ExtractJsonLd(types=[])
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        await _action_extract_jsonld(
            _driver_returning(MULTI_TYPE_GRAPH_HTML), action, step, step_extracted,
        )
        assert step_extracted["jsonld"] == []

    async def test_action_extract_jsonld_empty_page(self) -> None:
        action = ExtractJsonLd()
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        await _action_extract_jsonld(
            _driver_returning(EMPTY_HTML), action, step, step_extracted,
        )
        assert step_extracted["jsonld"] == []

    async def test_action_extract_jsonld_malformed_block(self) -> None:
        action = ExtractJsonLd()
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        await _action_extract_jsonld(
            _driver_returning(MALFORMED_PLUS_VALID_HTML),
            action, step, step_extracted,
        )
        rows = step_extracted["jsonld"]
        # Valid block survives; malformed silently skipped
        assert len(rows) == 1
        assert rows[0]["content_kind"] == "jsonld-product"

    async def test_action_extract_jsonld_custom_extract_name(self) -> None:
        action = ExtractJsonLd(extract_name="products")
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        await _action_extract_jsonld(
            _driver_returning(PRODUCT_HTML), action, step, step_extracted,
        )
        assert "products" in step_extracted
        assert "jsonld" not in step_extracted

    async def test_action_extract_jsonld_dispatch_wiring(self) -> None:
        """`_dispatch_step` routes extract_jsonld to the new handler."""
        action = ExtractJsonLd()
        step = ScrapingStep(action=action)
        step_extracted: dict = {}
        ok = await _dispatch_step(
            _driver_returning(PRODUCT_HTML),
            step,
            base_url="https://example.com",
            timeout=10,
            step_extracted=step_extracted,
        )
        assert ok is True
        assert step_extracted["jsonld"][0]["content_kind"] == "jsonld-product"
```

> **NOTE**: This file imports `from parrot.tools.scraping.executor import …`
> matching the pattern already used in
> `packages/ai-parrot-tools/tests/scraping/test_executor.py:8`. If a future
> test-discovery change moves to `parrot_tools.scraping.executor` directly,
> update both files together — do NOT introduce a third pattern here.
>
> Tests are `async def` — the existing `pytest.ini` / `conftest.py` of
> the toolkit package configures `pytest-asyncio` in `auto` mode (verify
> on first run; if it doesn't, add `pytest.mark.asyncio` to the test class
> or each test).

---

## Agent Instructions

When you pick up this task:

1. **Verify TASK-1048 and TASK-1049 are in `sdd/tasks/completed/`**.
   `_action_extract_jsonld` imports from the core module that TASK-1048
   creates and tests reference the `ExtractJsonLd` class that TASK-1049 adds.
2. **Re-read** `parrot_tools/scraping/executor.py:543-615` (`_action_extract`)
   in full — the new handler shadow-copies its key-resolution and merge
   logic. Any change to that code path since the spec was written must
   be reflected here.
3. **Update status** → `"in-progress"` in
   `sdd/tasks/index/webscrapingtoolkit-jsonld.json`.

…(truncated)…
