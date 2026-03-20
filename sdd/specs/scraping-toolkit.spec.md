# Feature Specification: WebScrapingToolkit

**Feature ID**: FEAT-014
**Date**: 2026-02-25
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

`WebScrapingTool` is a monolithic `AbstractTool` subclass that conflates plan
generation, single-page scraping, multi-page crawling, and plan management into a
single `_execute` method. This makes it difficult for agents to invoke fine-grained
scraping operations, and impossible to expose individual capabilities (plan creation,
scraping, crawling, plan management) as separate tools.

The `AbstractToolkit` pattern already exists in the framework and automatically
exposes each public async method as an individual tool — but `WebScrapingTool` does
not use it. Additionally, plan caching, session management, and driver lifecycle
are tightly coupled inside `_execute`, making them hard to test or reuse.

### Goals

- **Toolkit migration**: Rewrite the scraping entry point as `WebScrapingToolkit`
  (inheriting `AbstractToolkit`) so each operation is an individual, agent-invocable tool.
- **Clean method separation**: Expose `plan_create`, `scrape`, `crawl`, `plan_save`,
  `plan_load`, `plan_list`, and `plan_delete` as distinct public async methods.
- **Session management**: Support `session_based=True` (persistent browser) and
  `session_based=False` (per-operation browser) modes via a `_driver_context` pattern.
- **Driver-agnostic**: Support both Selenium and Playwright drivers through a
  `DriverConfig` model and `DriverFactory`.
- **Plan-first workflow**: `plan_create` generates plans without executing them;
  `scrape` and `crawl` resolve plans via a priority chain (explicit → cached → auto-generate).
- **Backward compatibility**: Retain `WebScrapingTool` with a deprecation warning.

### Non-Goals (explicitly out of scope)

- Implementing a new browser driver — existing `SeleniumSetup` and any Playwright
  driver are used as-is.
- CrawlEngine internals — that is FEAT-013 (separate spec).
- robots.txt enforcement (future enhancement at the orchestrator level).
- UI or CLI for plan management.

---

## 2. Architectural Design

### Overview

`WebScrapingToolkit` replaces `WebScrapingTool` as the primary entry point for all
scraping operations. It inherits from `AbstractToolkit`, which auto-discovers all
public async methods and exposes them as individual tools. The toolkit coordinates:

1. **Plan inference** — LLM-based plan creation with registry cache check.
2. **Single-page scraping** — Execute a plan's steps against one URL.
3. **Multi-page crawling** — Delegate to `CrawlEngine` (FEAT-013).
4. **Plan persistence** — Save/load/list/delete via `PlanRegistry` (FEAT-012).

### Component Diagram

```
Agent / Chatbot
     │
     ▼
WebScrapingToolkit (AbstractToolkit)
     │
     ├── plan_create()  ─→ LLM Client ─→ ScrapingPlan
     │                     ↕
     ├── plan_save()    ─→ PlanRegistry + plan_io
     ├── plan_load()    ─→ PlanRegistry + plan_io
     ├── plan_list()    ─→ PlanRegistry
     ├── plan_delete()  ─→ PlanRegistry + filesystem
     │
     ├── scrape()       ─→ _driver_context() ─→ StepExecutor ─→ ScrapingResult
     │                     ↕
     └── crawl()        ─→ CrawlEngine (FEAT-013) ─→ CrawlResult
                            ↕
                        _driver_context()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` (`parrot/tools/toolkit.py`) | inherits | Methods become tools automatically |
| `WebScrapingTool` (`parrot/tools/scraping/tool.py`) | wraps/deprecates | Existing execution logic reused internally; class retained with deprecation warning |
| `ScrapingPlan` (FEAT-012) | uses | Plan model for all plan operations |
| `PlanRegistry` (FEAT-012) | uses | Cache lookup, registration, touch, remove |
| `plan_io` (FEAT-012, TASK-040) | uses | `save_plan_to_disk`, `load_plan_from_disk` |
| `CrawlEngine` (FEAT-013) | uses | Multi-page crawl delegation |
| `SeleniumSetup` (`parrot/tools/scraping/driver.py`) | uses | Browser driver creation |
| `BrowserAction` models (`parrot/tools/scraping/models.py`) | uses | Step execution |
| `ScrapingResult` (`parrot/tools/scraping/models.py`) | produces | Per-page result |
| `AbstractClient` | uses (optional) | LLM inference for plan_create |

### Data Models

```python
class DriverConfig(BaseModel):
    """Frozen browser configuration passed to DriverFactory."""
    driver_type: Literal["selenium", "playwright"] = "selenium"
    browser: Literal["chrome", "firefox", "edge", "safari",
                     "undetected", "webkit"] = "chrome"
    headless: bool = True
    mobile: bool = False
    mobile_device: Optional[str] = None
    auto_install: bool = True
    default_timeout: int = 10
    retry_attempts: int = 3
    delay_between_actions: float = 1.0
    overlay_housekeeping: bool = True
    disable_images: bool = False
    custom_user_agent: Optional[str] = None

    def merge(self, overrides: Optional[Dict[str, Any]] = None) -> "DriverConfig":
        """Return a new config with overrides applied."""
        ...


class PlanSummary(BaseModel):
    """Slim projection of PlanRegistryEntry for plan_list."""
    name: str
    version: str
    url: str
    domain: str
    created_at: datetime
    last_used_at: Optional[datetime]
    use_count: int
    tags: List[str]


class PlanSaveResult(BaseModel):
    """Result of a plan_save operation."""
    success: bool
    path: str
    name: str
    version: str
    registered: bool
    message: str
```

### New Public Interfaces

```python
class WebScrapingToolkit(AbstractToolkit):
    def __init__(
        self,
        driver_type: Literal["selenium", "playwright"] = "selenium",
        browser: Literal["chrome", "firefox", "edge", "safari",
                         "undetected", "webkit"] = "chrome",
        headless: bool = True,
        session_based: bool = False,
        mobile: bool = False,
        mobile_device: Optional[str] = None,
        auto_install: bool = True,
        default_timeout: int = 10,
        retry_attempts: int = 3,
        delay_between_actions: float = 1.0,
        overlay_housekeeping: bool = True,
        disable_images: bool = False,
        custom_user_agent: Optional[str] = None,
        plans_dir: Optional[Union[str, Path]] = None,
        llm_client: Optional[Any] = None,
        **kwargs,
    ): ...

    # Lifecycle (override AbstractToolkit)
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    # Plan operations (each becomes a tool)
    async def plan_create(self, url: str, objective: str,
                          hints: Optional[Dict[str, Any]] = None,
                          force_regenerate: bool = False) -> ScrapingPlan: ...
    async def plan_save(self, plan: ScrapingPlan,
                        overwrite: bool = False) -> PlanSaveResult: ...
    async def plan_load(self, url_or_name: str) -> Optional[ScrapingPlan]: ...
    async def plan_list(self, domain_filter: Optional[str] = None,
                        tag_filter: Optional[str] = None) -> List[PlanSummary]: ...
    async def plan_delete(self, name: str,
                          delete_file: bool = True) -> bool: ...

    # Execution operations (each becomes a tool)
    async def scrape(self, url: str,
                     plan: Optional[Union[ScrapingPlan, Dict[str, Any]]] = None,
                     objective: Optional[str] = None,
                     save_plan: bool = False,
                     browser_config_override: Optional[Dict[str, Any]] = None) -> ScrapingResult: ...
    async def crawl(self, start_url: str, depth: int = 1,
                    max_pages: Optional[int] = None,
                    follow_selector: Optional[str] = None,
                    follow_pattern: Optional[str] = None,
                    plan: Optional[Union[ScrapingPlan, Dict[str, Any]]] = None,
                    objective: Optional[str] = None,
                    save_plan: bool = False,
                    concurrency: int = 1) -> CrawlResult: ...
```

---

## 3. Module Breakdown

### Module 1: DriverConfig & PlanSummary Models
- **Path**: `parrot/tools/scraping/toolkit_models.py`
- **Responsibility**: `DriverConfig` (frozen browser config with `merge()`),
  `PlanSummary` (slim registry projection), `PlanSaveResult` (save operation result).
- **Depends on**: None (standard library + pydantic)

### Module 2: Driver Context Manager
- **Path**: `parrot/tools/scraping/driver_context.py`
- **Responsibility**: `DriverContextManager` — async context manager that yields a
  browser driver, managing lifecycle based on `session_based` flag. Wraps existing
  `SeleniumSetup` and future Playwright drivers via `DriverConfig`.
- **Depends on**: Module 1 (DriverConfig), existing `driver.py` (SeleniumSetup)

### Module 3: Step Executor
- **Path**: `parrot/tools/scraping/executor.py`
- **Responsibility**: Extract the step-execution logic from `WebScrapingTool._execute`
  into a standalone async function `execute_plan_steps(driver, plan) -> ScrapingResult`.
  This allows both `scrape()` and `CrawlEngine` to reuse the same execution logic.
- **Depends on**: Module 2, existing `models.py` (BrowserAction, ScrapingResult)

### Module 4: WebScrapingToolkit Core
- **Path**: `parrot/tools/scraping/toolkit.py`
- **Responsibility**: The `WebScrapingToolkit` class itself — constructor, internal
  state, `start()`/`stop()`, `_driver_context()`, plan resolution chain, and all
  seven public tool methods. Delegates execution to Module 3, crawling to
  `CrawlEngine` (FEAT-013), and plan I/O to FEAT-012 components.
- **Depends on**: Module 1, Module 2, Module 3, FEAT-012 (PlanRegistry, plan_io),
  FEAT-013 (CrawlEngine — optional, crawl() gracefully errors if not available)

### Module 5: LLM Plan Generation
- **Path**: `parrot/tools/scraping/plan_generator.py`
- **Responsibility**: `PlanGenerator` class — builds the LLM prompt from a page
  snapshot, calls the LLM client, parses the JSON response into a `ScrapingPlan`.
  Encapsulates the prompt template and response parsing logic.
- **Depends on**: FEAT-012 (ScrapingPlan model), existing `AbstractClient`

### Module 6: Package Init & Deprecation
- **Path**: `parrot/tools/scraping/__init__.py` (modification)
- **Responsibility**: Export `WebScrapingToolkit` and new models. Add deprecation
  warning to `WebScrapingTool`.
- **Depends on**: Module 4

### Module 7: Integration Tests
- **Path**: `tests/tools/scraping/test_toolkit.py`
- **Responsibility**: End-to-end tests for the toolkit using mocked drivers and
  LLM clients.
- **Depends on**: All modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_driver_config_defaults` | Module 1 | DriverConfig initializes with correct defaults |
| `test_driver_config_merge` | Module 1 | `merge()` applies overrides without mutating original |
| `test_plan_summary_from_entry` | Module 1 | PlanSummary can be created from PlanRegistryEntry |
| `test_driver_context_session_mode` | Module 2 | Session mode reuses same driver across calls |
| `test_driver_context_fresh_mode` | Module 2 | Fresh mode creates and destroys driver per use |
| `test_execute_plan_steps` | Module 3 | Steps execute in order, selectors extract data |
| `test_execute_plan_handles_failure` | Module 3 | Failed step produces error in ScrapingResult |
| `test_toolkit_init` | Module 4 | Toolkit initializes with valid config |
| `test_toolkit_get_tools` | Module 4 | `get_tools()` returns 7 tools (one per method) |
| `test_plan_create_cached` | Module 4 | Returns cached plan when registry has a match |
| `test_plan_create_llm` | Module 4 | Calls LLM when no cache hit |
| `test_scrape_explicit_plan` | Module 4 | Uses provided plan directly |
| `test_scrape_cached_plan` | Module 4 | Falls back to registry when no explicit plan |
| `test_scrape_auto_generate` | Module 4 | Auto-generates plan when objective provided |
| `test_scrape_no_plan_raises` | Module 4 | Raises ValueError when no plan source available |
| `test_plan_save_and_load` | Module 4 | Round-trip: save then load by URL |
| `test_plan_list_filters` | Module 4 | Domain and tag filters work correctly |
| `test_plan_delete` | Module 4 | Removes from registry and optionally from disk |
| `test_plan_generator_prompt` | Module 5 | Prompt includes URL, objective, schema |
| `test_plan_generator_parse` | Module 5 | Valid LLM JSON response parsed into ScrapingPlan |
| `test_plan_generator_invalid_json` | Module 5 | Invalid LLM response raises gracefully |
| `test_deprecation_warning` | Module 6 | `WebScrapingTool()` emits DeprecationWarning |

### Integration Tests

| Test | Description |
|---|---|
| `test_scrape_full_lifecycle` | Create plan → scrape → save → load → scrape with cache |
| `test_crawl_delegates_to_engine` | `crawl()` instantiates CrawlEngine with correct params |
| `test_session_based_scrape` | Multiple `scrape()` calls reuse driver in session mode |
| `test_toolkit_as_agent_tools` | Toolkit `get_tools()` returns callable tools with correct schemas |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_llm_client():
    """LLM client that returns a fixed ScrapingPlan JSON."""
    class MockClient:
        async def complete(self, prompt: str) -> str:
            return json.dumps({
                "url": "https://example.com/products",
                "objective": "Extract products",
                "steps": [
                    {"action": "navigate", "url": "https://example.com/products"},
                    {"action": "wait", "condition": ".product-list",
                     "condition_type": "selector"},
                ],
            })
    return MockClient()


@pytest.fixture
def mock_driver():
    """Mock browser driver with controllable page content."""
    ...


@pytest.fixture
def toolkit(tmp_path, mock_llm_client):
    return WebScrapingToolkit(
        headless=True,
        plans_dir=tmp_path / "plans",
        llm_client=mock_llm_client,
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `WebScrapingToolkit` inherits `AbstractToolkit` and `get_tools()` returns 7 tools
- [ ] `plan_create` returns cached plan on registry hit, calls LLM on miss
- [ ] `scrape` resolves plan via priority chain: explicit → cached → auto-generate → error
- [ ] `crawl` delegates to `CrawlEngine` with correct parameters
- [ ] `plan_save` persists to disk and registers in `PlanRegistry`
- [ ] `plan_load` retrieves plan by URL (registry lookup) or by name
- [ ] `plan_list` supports domain and tag filtering
- [ ] `plan_delete` removes from registry and optionally from disk
- [ ] Session mode (`session_based=True`) reuses driver across calls
- [ ] Fresh mode (`session_based=False`) creates/destroys driver per operation
- [ ] `WebScrapingTool` emits `DeprecationWarning` on instantiation
- [ ] All unit tests pass: `pytest tests/tools/scraping/test_toolkit.py -v`
- [ ] No new external dependencies
- [ ] No breaking changes to existing `WebScrapingTool` public API
- [ ] `from parrot.tools.scraping import WebScrapingToolkit` works

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Inherit `AbstractToolkit` — public async methods are auto-discovered as tools
  (see `parrot/tools/toolkit.py:183-220`)
- Use `asynccontextmanager` for `_driver_context()` pattern
- Use `PlanRegistry` (FEAT-012) for all cache operations
- Use `save_plan_to_disk` / `load_plan_from_disk` (FEAT-012 TASK-040) for file I/O
- Follow logging pattern: `self.logger = logging.getLogger(__name__)`
- Use Pydantic models for all structured data (DriverConfig, PlanSummary, PlanSaveResult)

### Plan Resolution Priority (scrape method)

1. Explicit `plan` argument (highest priority)
2. Registry cache lookup by URL (`PlanRegistry.lookup()`)
3. Auto-generate via `plan_create()` if `objective` is provided
4. Raise `ValueError` if none of the above yields a plan

### LLM Client Resolution

1. Explicit `llm_client` constructor argument
2. Environment variable `AIPARROT_DEFAULT_MODEL`
3. Raise `RuntimeError` if none available and `plan_create` is called

### Known Risks / Gotchas

- **Step execution extraction**: The existing `WebScrapingTool._execute` logic is
  tightly coupled to the class. Extracting it into a standalone function (Module 3)
  requires careful handling of driver state, retry logic, and overlay housekeeping.
- **Playwright support**: The proposal mentions Playwright but only `SeleniumSetup`
  exists. Module 2 should abstract over both, but Playwright implementation can be
  deferred — use a clean interface that accepts either.
- **CrawlEngine dependency**: `crawl()` depends on FEAT-013. If `CrawlEngine` is not
  yet available, `crawl()` should raise `NotImplementedError` with a clear message.
- **Thread safety**: `_driver_context()` in session mode shares a single driver
  instance. Concurrent `scrape()` calls in session mode would conflict. Document
  that session mode is for sequential use only.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.0` | Model definitions (already in project) |
| `aiofiles` | `>=23.0` | Async file I/O (already in project) |
| `beautifulsoup4` | `>=4.12` | HTML parsing (already in project) |

No new dependencies required.

---

## 7. Open Questions

- [x] Should `WebScrapingTool` be removed or kept with deprecation? — *Owner: Jesus Lara*: Kept with deprecation warning.
- [x] Should `plan_create` auto-save generated plans? — *Owner: Jesus Lara*: No, saving is explicit via `plan_save` or `save_plan=True` on scrape/crawl.
- [x] Should the toolkit support plugin-style driver registration (e.g., `register_driver("playwright", PlaywrightDriver)`)? — *Owner: Jesus Lara*: Yes
- [x] Should `scrape()` accept a raw `steps` list (without a full ScrapingPlan) for quick ad-hoc usage? — *Owner: Jesus Lara*: Yes

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-25 | Jesus Lara | Initial draft from proposal SPEC-02 |
