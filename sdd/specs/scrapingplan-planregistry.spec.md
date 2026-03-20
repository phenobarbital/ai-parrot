# Feature Specification: ScrapingPlan & PlanRegistry

**Feature ID**: FEAT-012
**Date**: 2026-02-25
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The `WebScrapingTool` currently generates a fresh LLM inference call every time it
scrapes a URL — even if the same site (or a close variant) was scraped minutes ago.
This wastes tokens, increases latency, and produces non-deterministic plans for
identical targets. There is no mechanism to persist, cache, or reuse the scraping
plans that the LLM produces.

### Goals

- **Plan persistence**: Save LLM-generated scraping plans to disk as versioned JSON
  files, enabling reuse without redundant inference calls.
- **Cache-first lookup**: Before invoking the LLM, check a registry index for an
  existing plan that matches the target URL (exact, path-prefix, or domain).
- **Immutable versioning**: Never mutate a saved plan; always write a new version,
  preserving a full revision trail.
- **Zero external dependencies**: Disk-only persistence (no Redis, no DB) using a
  single `registry.json` index file.
- **Fingerprint stability**: Normalize URLs (strip query params and fragments) before
  hashing so tracking parameters don't defeat cache matches.

### Non-Goals (explicitly out of scope)

- Redis or database-backed plan storage (future enhancement).
- Automatic plan invalidation based on page-change detection.
- Plan execution — that remains in `WebScrapingTool` / orchestrator.
- UI for plan management (CLI may come later as a separate spec).

---

## 2. Architectural Design

### Overview

Two new components are introduced in `parrot/tools/scraping/`:

1. **`ScrapingPlan`** — A Pydantic model representing the declarative contract that
   travels between plan creation, human review, execution, and caching.
2. **`PlanRegistry`** — An async, disk-backed index that maps URLs/domains to saved
   plan files, enabling fast lookup without scanning all plan files.

### Component Diagram

```
WebScrapingTool ──→ PlanRegistry.lookup(url)
                        │
           ┌────────────┼────────────┐
           │            │            │
      Tier 1:       Tier 2:      Tier 3:
      Exact FP    Path-prefix   Domain-only
           │            │            │
           └────────────┼────────────┘
                        │
                   ┌────┴────┐
                   │  HIT?   │
                   └────┬────┘
                  yes/     \no
                 /          \
    load_plan_from_disk    LLM inference
           │                    │
           │              ScrapingPlan
           │                    │
           │         save_plan_to_disk
           │         registry.register()
           │                    │
           └────────┬───────────┘
                    │
              Execute plan
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `WebScrapingTool` | uses | Consults registry before LLM call; saves new plans after inference |
| `BrowserAction` / `models.py` | referenced by | Plan `steps` field contains serialized `BrowserAction` sequences |
| `AbstractToolkit` | parent pattern | `ScrapingPlan` follows Pydantic model conventions used across toolkits |

### Data Models

```python
class ScrapingPlan(BaseModel):
    """Declarative scraping plan — value object, immutable once saved."""

    # Identity
    name: Optional[str] = None          # auto-derived from domain
    version: str = "1.0"
    tags: List[str] = []

    # Target
    url: str
    domain: str                          # auto-populated
    objective: str

    # Execution contract
    steps: List[Dict[str, Any]]          # ordered BrowserAction dicts
    selectors: Optional[List[Dict[str, Any]]] = None
    browser_config: Optional[Dict[str, Any]] = None

    # Crawl hints (optional)
    follow_selector: Optional[str] = None
    follow_pattern: Optional[str] = None
    max_depth: Optional[int] = None

    # Metadata
    created_at: datetime
    updated_at: Optional[datetime] = None
    source: str = "llm"                  # 'llm' | 'manual' | 'imported'
    fingerprint: str = ""                # SHA-256 prefix of normalized URL

    # Computed
    @computed_field
    @property
    def normalized_url(self) -> str: ...

    def model_post_init(self, __context): ...
```

```python
class PlanRegistryEntry(BaseModel):
    name: str
    plan_version: str
    url: str
    domain: str
    path: str                   # relative to plans_dir
    created_at: datetime
    last_used_at: Optional[datetime] = None
    use_count: int = 0
    tags: List[str] = []
```

### New Public Interfaces

```python
class PlanRegistry:
    def __init__(self, plans_dir: Optional[Path] = None): ...
    async def load(self) -> None: ...
    def lookup(self, url: str) -> Optional[PlanRegistryEntry]: ...
    def get_by_name(self, name: str) -> Optional[PlanRegistryEntry]: ...
    def list_all(self) -> List[PlanRegistryEntry]: ...
    async def register(self, plan: ScrapingPlan, relative_path: str) -> None: ...
    async def touch(self, fingerprint: str) -> None: ...
    async def remove(self, name: str) -> bool: ...

# Free functions
async def save_plan_to_disk(plan: ScrapingPlan, plans_dir: Path) -> Path: ...
async def load_plan_from_disk(path: Path) -> ScrapingPlan: ...
```

---

## 3. Module Breakdown

### Module 1: ScrapingPlan Model
- **Path**: `parrot/tools/scraping/plan.py`
- **Responsibility**: Pydantic model for the scraping plan value object. Handles
  auto-population of `domain`, `name`, and `fingerprint`. Provides `normalized_url`
  computed field and JSON serialization.
- **Depends on**: None (standard library + pydantic)

### Module 2: PlanRegistry
- **Path**: `parrot/tools/scraping/registry.py`
- **Responsibility**: Async, disk-backed index maintaining `registry.json`. Provides
  three-tier URL lookup (exact fingerprint → path-prefix → domain). Guards mutations
  with `asyncio.Lock`.
- **Depends on**: Module 1 (ScrapingPlan)

### Module 3: Plan File I/O Helpers
- **Path**: `parrot/tools/scraping/plan_io.py`
- **Responsibility**: `save_plan_to_disk()` and `load_plan_from_disk()` free functions.
  Manages the `{plans_dir}/{domain}/{name}_v{version}_{fingerprint}.json` file layout.
- **Depends on**: Module 1 (ScrapingPlan)

### Module 4: WebScrapingTool Integration
- **Path**: `parrot/tools/scraping/tool.py` (modification)
- **Responsibility**: Wire `PlanRegistry` into the existing scraping workflow: check
  cache before LLM inference, save new plans after inference, touch registry on
  cache hits.
- **Depends on**: Module 1, Module 2, Module 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_fingerprint_stability` | Module 1 | Same URL with different query params produces same fingerprint |
| `test_auto_populate_domain` | Module 1 | Domain and name auto-derived from URL |
| `test_auto_populate_name` | Module 1 | Name defaults to sanitized domain |
| `test_json_roundtrip` | Module 1 | `model_dump_json()` → `model_validate_json()` preserves all fields |
| `test_lookup_exact_fingerprint` | Module 2 | Tier 1: exact match returns correct entry |
| `test_lookup_path_prefix` | Module 2 | Tier 2: sub-path URL matches parent plan |
| `test_lookup_domain_only` | Module 2 | Tier 3: domain-only match as fallback |
| `test_lookup_no_match` | Module 2 | Returns None when no plan matches |
| `test_register_and_lookup` | Module 2 | Register a plan then look it up |
| `test_touch_increments_count` | Module 2 | `touch()` updates `last_used_at` and `use_count` |
| `test_remove_by_name` | Module 2 | `remove()` deletes entry from index |
| `test_concurrent_register` | Module 2 | Multiple async `register()` calls don't corrupt index |
| `test_save_and_load_plan` | Module 3 | Save plan to disk, reload, verify field equality |
| `test_save_creates_domain_dir` | Module 3 | Domain subdirectory created automatically |

### Integration Tests

| Test | Description |
|---|---|
| `test_full_plan_lifecycle` | Create plan → save → register → lookup → load → verify |
| `test_registry_persistence` | Save registry, create new instance, load, verify entries survive |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_plan():
    return ScrapingPlan(
        url="https://example.com/products",
        domain="example.com",
        objective="Extract product listings",
        steps=[
            {"action": "navigate", "url": "https://example.com/products"},
            {"action": "wait", "condition": ".product-list", "condition_type": "selector"},
            {"action": "get_html", "selector": ".product-list"},
        ],
        tags=["ecommerce", "products"],
    )

@pytest.fixture
def tmp_plans_dir(tmp_path):
    return tmp_path / "plans"
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `ScrapingPlan` model validates, auto-populates derived fields, and round-trips through JSON
- [ ] `PlanRegistry` loads/saves `registry.json` and supports all three lookup tiers
- [ ] `save_plan_to_disk` / `load_plan_from_disk` produce correct file layout
- [ ] All unit tests pass: `pytest tests/tools/scraping/ -v`
- [ ] Concurrent async mutations do not corrupt registry state
- [ ] No new external dependencies beyond `pydantic` v2 and `aiofiles` (already in project)
- [ ] No breaking changes to existing `WebScrapingTool` public API
- [ ] `parrot/tools/scraping/__init__.py` exports `ScrapingPlan`, `PlanRegistry`

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use Pydantic v2 `BaseModel` with `computed_field` for derived values (matches existing `models.py`)
- Use `asyncio.Lock` for write safety (matches patterns in `parrot/memory/`)
- Use `aiofiles` for all file I/O (matches existing usage in scraping tool)
- Follow the `{domain_dir}/{name}_v{version}_{fingerprint}.json` naming convention

### Known Risks / Gotchas

- **Fingerprint collisions**: Using 16-char SHA-256 prefix. Collision probability is
  negligible for expected plan volumes (~thousands), but document this limitation.
- **Concurrent file access**: Multiple processes writing the same `registry.json`
  could corrupt it. The `asyncio.Lock` protects within a single process; cross-process
  safety is out of scope (documented as limitation).
- **`model_post_init` side effects**: Auto-populating fields in `model_post_init`
  means `model_construct()` callers must call `model_post_init(None)` manually.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.0` | Model definition and JSON serialization (already in project) |
| `aiofiles` | `>=23.0` | Async file I/O (already in project) |

No new dependencies required.

---

## 7. Open Questions

- [ ] Should `WebScrapingTool` auto-save every LLM-generated plan, or require an explicit `save=True` parameter? — *Owner: Jesus Lara*: auto-save every plan generated by LLM, but non-blocking.
- [ ] Should the registry support TTL-based expiration for stale plans? — *Owner: Jesus Lara*: no.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-25 | Jesus Lara | Initial draft from proposal SPEC-01 |
