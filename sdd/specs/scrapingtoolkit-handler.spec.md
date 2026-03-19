# Feature Specification: ScrapingToolkit HTTP Handler

**Feature ID**: FEAT-016
**Date**: 2026-02-26
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The `WebScrapingToolkit` (FEAT-014) provides a powerful async toolkit for web scraping — plan creation, plan management, scraping execution, and crawling — but it is only accessible programmatically within Python code. There is no HTTP API layer to expose these capabilities to external clients, particularly the **ScrapingToolkit Svelte component UI** in `navigator-frontend-next`.

The frontend needs:
- REST endpoints to create, evaluate, save, list, load, and delete scraping plans.
- An endpoint to execute scraping/crawling tasks with real-time feedback.
- Reference data endpoints for browser actions, driver types, driver configuration options, and crawling strategies — so the UI can dynamically render forms and dropdowns.

### Goals
- Expose all `WebScrapingToolkit` capabilities as a RESTful HTTP API under `/api/v1/scraping/`.
- Provide a helper handler serving static/reference metadata (BrowserActions, DriverConfig options, DriverFactory types, CrawlStrategy definitions) via GET endpoints.
- Integrate with an AI Agent so that plan creation leverages LLM reasoning.
- Follow existing handler patterns (`ChatHandler`, `AgentHandler`) for consistency.
- Design all endpoints to be consumed by the `ScrapingToolkit` Svelte component in `navigator-frontend-next`.

### Non-Goals (explicitly out of scope)
- WebSocket/SSE streaming for real-time scraping progress (future enhancement).
- Multi-tenant plan isolation (all plans are shared within the application instance).
- Authentication/authorization beyond existing `@is_authenticated()` decorator.
- Frontend implementation (handled separately in `navigator-frontend-next`).

---

## 2. Architectural Design

### Overview

Two handler classes expose the scraping subsystem over HTTP:

1. **`ScrapingHandler`** (extends `BaseView`) — A class-based view at `/api/v1/scraping/` that wraps an AI Agent equipped with `WebScrapingToolkit`. Handles CRUD for scraping plans and execution of scrape/crawl operations.

2. **`ScrapingInfoHandler`** (extends `BaseHandler`) — A method-based handler serving GET-only reference data: available browser actions, driver types, driver configuration schema, and crawling strategy definitions.

```
┌─────────────────────────────────────────────────────────────────┐
│                    navigator-frontend-next                      │
│                  (ScrapingToolkit Svelte UI)                     │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP REST
                            ▼
┌───────────────────────────────────────────────────────────────┐
│  /api/v1/scraping/                                            │
│  ┌──────────────────────┐    ┌──────────────────────────────┐ │
│  │   ScrapingHandler    │    │   ScrapingInfoHandler         │ │
│  │   (BaseView)         │    │   (BaseHandler)               │ │
│  │                      │    │                               │ │
│  │ POST /plans          │    │ GET /info/actions             │ │
│  │ GET  /plans          │    │ GET /info/drivers             │ │
│  │ GET  /plans/{name}   │    │ GET /info/config              │ │
│  │ PUT  /plans/{name}   │    │ GET /info/strategies          │ │
│  │ DELETE /plans/{name} │    │                               │ │
│  │ POST /scrape         │    └──────────────────────────────┘ │
│  │ POST /crawl          │                                     │
│  └──────────┬───────────┘                                     │
│             │                                                  │
│             ▼                                                  │
│  ┌──────────────────────┐                                     │
│  │  Agent + Toolkit     │                                     │
│  │  ┌────────────────┐  │                                     │
│  │  │WebScrapingTK   │  │                                     │
│  │  │  plan_create   │  │                                     │
│  │  │  plan_save     │  │                                     │
│  │  │  plan_load     │  │                                     │
│  │  │  plan_list     │  │                                     │
│  │  │  plan_delete   │  │                                     │
│  │  │  scrape        │  │                                     │
│  │  │  crawl         │  │                                     │
│  │  └────────────────┘  │                                     │
│  └──────────────────────┘                                     │
└───────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.views.BaseView` | extends | `ScrapingHandler` inherits class-based view routing |
| `navigator.views.BaseHandler` | extends | `ScrapingInfoHandler` inherits method-based handler |
| `WebScrapingToolkit` | uses | Toolkit instance installed in agent, provides all scraping operations |
| `DriverConfig` | uses | Serialized as JSON schema for `/info/config` |
| `DriverFactory` | uses | Queried for available driver types |
| `BrowserAction` subclasses | uses | Introspected for `/info/actions` catalog |
| `CrawlStrategy` (BFS/DFS) | uses | Enumerated for `/info/strategies` |
| `ScrapingPlan` | uses | Request/response model for plan endpoints |
| `AgentHandler` pattern | follows | Similar setup/route registration pattern |
| `@is_authenticated()` | uses | Authentication decorator on handler class |

### Data Models

```python
# Request models for API endpoints

class PlanCreateRequest(BaseModel):
    """Request body for POST /plans (create a new plan via LLM)."""
    url: str
    objective: str
    hints: Optional[Dict[str, Any]] = None
    force_regenerate: bool = False
    save: bool = False  # If True, also persist immediately

class ScrapeRequest(BaseModel):
    """Request body for POST /scrape."""
    url: str
    plan_name: Optional[str] = None           # Use saved plan by name
    plan: Optional[Dict[str, Any]] = None     # Or provide inline plan
    objective: Optional[str] = None           # Or auto-generate plan
    steps: Optional[List[Dict[str, Any]]] = None
    selectors: Optional[List[Dict[str, Any]]] = None
    save_plan: bool = False
    browser_config_override: Optional[Dict[str, Any]] = None

class CrawlRequest(BaseModel):
    """Request body for POST /crawl."""
    start_url: str
    depth: int = 1
    max_pages: Optional[int] = None
    follow_selector: Optional[str] = None
    follow_pattern: Optional[str] = None
    plan_name: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    objective: Optional[str] = None
    save_plan: bool = False
    strategy: Literal["bfs", "dfs"] = "bfs"
    concurrency: int = 1

class PlanSaveRequest(BaseModel):
    """Request body for PUT /plans/{name} (save/update a plan)."""
    plan: Dict[str, Any]
    overwrite: bool = False

# Response models

class ActionInfo(BaseModel):
    """Description of a single browser action for the UI."""
    name: str                                 # e.g., "click", "navigate"
    description: str                          # From docstring
    fields: List[Dict[str, Any]]              # JSON schema of action params

class DriverTypeInfo(BaseModel):
    """Available driver type."""
    name: str                                 # e.g., "selenium", "playwright"
    browsers: List[str]                       # Supported browser names

class StrategyInfo(BaseModel):
    """Crawl strategy description."""
    name: str                                 # e.g., "bfs", "dfs"
    description: str
```

### New Public Interfaces

- IMPORTANT: a class-based View is registered in the aiohttp application factory as:
```
from . import ScrapingHandler

app.router.add_view("/api/v1/scraping", ScrapingHandler)
```
we use app.py to register the view.

- for method-based handlers, we use:
```
from . import ScrapingInfoHandler

app.router.add_route("GET", "/api/v1/scraping/info/actions", ScrapingInfoHandler.get_actions)
```
on this case, we can use `setup` method to register the routes.


```python
class ScrapingHandler(BaseView):
    """Class-based HTTP view for /api/v1/scraping/.

    Wraps an AI Agent with WebScrapingToolkit installed.
    Handles plan CRUD and scrape/crawl execution.
    """

    async def get(self) -> web.Response:
        """GET /api/v1/scraping/plans — list all plans.
        GET /api/v1/scraping/plans/{name} — load a specific plan.

        Query params: domain_filter, tag_filter
        """

    async def post(self) -> web.Response:
        """POST /api/v1/scraping/plans — create a new plan (via LLM).
        POST /api/v1/scraping/scrape — execute a scraping task.
        POST /api/v1/scraping/crawl — execute a crawl task.

        Dispatches based on URL path.
        """

    async def put(self) -> web.Response:
        """PUT /api/v1/scraping/plans/{name} — save/update a plan."""

    async def patch(self) -> web.Response:
        """PATCH /api/v1/scraping/plans/{name} — update a plan."""

    async def delete(self) -> web.Response:
        """DELETE /api/v1/scraping/plans/{name} — delete a plan."""


class ScrapingInfoHandler(BaseHandler):
    """Method-based handler serving reference data for the Scraping UI.

    All endpoints are GET-only and return static/introspected metadata.
    """

    async def get_actions(self, request: web.Request) -> web.Response:
        """GET /api/v1/scraping/info/actions — list all BrowserAction types."""

    async def get_drivers(self, request: web.Request) -> web.Response:
        """GET /api/v1/scraping/info/drivers — list driver types and browsers."""

    async def get_config_schema(self, request: web.Request) -> web.Response:
        """GET /api/v1/scraping/info/config — DriverConfig JSON schema."""

    async def get_strategies(self, request: web.Request) -> web.Response:
        """GET /api/v1/scraping/info/strategies — crawl strategy definitions."""

    def setup(self, app: web.Application) -> None:
        """Register info routes with the application."""
```

---

## 3. Module Breakdown

### Module 1: Request/Response Models
- **Path**: `parrot/handlers/scraping/models.py`
- **Responsibility**: Pydantic models for all API request and response payloads (`PlanCreateRequest`, `ScrapeRequest`, `CrawlRequest`, `PlanSaveRequest`, `ActionInfo`, `DriverTypeInfo`, `StrategyInfo`).
- **Depends on**: `parrot.tools.scraping` models (ScrapingPlan, DriverConfig)

### Module 2: ScrapingInfoHandler
- **Path**: `parrot/handlers/scraping/info.py`
- **Responsibility**: GET-only handler providing reference metadata for the UI — browser actions catalog, driver types, driver config JSON schema, and crawl strategies. Introspects `BrowserAction` subclasses, `DriverFactory`, `DriverConfig`, and strategy classes.
- **Depends on**: Module 1, `parrot.tools.scraping.models` (ACTION_MAP, BrowserAction subclasses), `parrot.tools.scraping.toolkit_models` (DriverConfig), `parrot.tools.scraping.driver_factory` (DriverFactory), `parrot.tools.scraping.crawl_strategy` (BFSStrategy, DFSStrategy)

### Module 3: ScrapingHandler
- **Path**: `parrot/handlers/scraping/handler.py`
- **Responsibility**: Main class-based view handling plan CRUD (create via LLM, list, load, save, delete) and scrape/crawl execution. Manages an internal `WebScrapingToolkit` instance. Dispatches POST requests based on route path.
- **Depends on**: Module 1, Module 2, `WebScrapingToolkit`, `navigator.views.BaseView`

### Module 4: Route Registration & Package Init
- **Path**: `parrot/handlers/scraping/__init__.py`
- **Responsibility**: Package exports and `setup_scraping_routes(app)` convenience function that registers all scraping handler routes on an aiohttp application.
- **Depends on**: Module 2, Module 3

### Module 5: Unit & Integration Tests
- **Path**: `tests/handlers/test_scraping_handler.py`, `tests/handlers/test_scraping_info.py`
- **Responsibility**: Test all endpoints — plan CRUD, scrape/crawl execution, info metadata endpoints. Mock `WebScrapingToolkit` for unit tests.
- **Depends on**: Module 1–4

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_plan_create_request_validation` | Module 1 | Validates PlanCreateRequest with valid/invalid payloads |
| `test_scrape_request_validation` | Module 1 | Validates ScrapeRequest with various field combos |
| `test_crawl_request_validation` | Module 1 | Validates CrawlRequest defaults and constraints |
| `test_get_actions_returns_all` | Module 2 | `/info/actions` returns all ACTION_MAP entries with schemas |
| `test_get_drivers_returns_types` | Module 2 | `/info/drivers` returns selenium/playwright + browsers |
| `test_get_config_schema` | Module 2 | `/info/config` returns DriverConfig JSON schema |
| `test_get_strategies` | Module 2 | `/info/strategies` returns bfs/dfs descriptions |
| `test_plan_create_via_post` | Module 3 | POST /plans calls toolkit.plan_create() |
| `test_plan_list_via_get` | Module 3 | GET /plans returns plan list |
| `test_plan_load_by_name` | Module 3 | GET /plans/{name} loads specific plan |
| `test_plan_save_via_put` | Module 3 | PUT /plans/{name} saves plan |
| `test_plan_delete_via_delete` | Module 3 | DELETE /plans/{name} removes plan |
| `test_scrape_execution` | Module 3 | POST /scrape delegates to toolkit.scrape() |
| `test_crawl_execution` | Module 3 | POST /crawl delegates to toolkit.crawl() |
| `test_error_handling_invalid_json` | Module 3 | Returns 400 on malformed JSON body |
| `test_error_handling_plan_not_found` | Module 3 | Returns 404 when plan name doesn't exist |

### Integration Tests
| Test | Description |
|---|---|
| `test_full_plan_lifecycle` | Create → List → Load → Update → Delete flow |
| `test_scrape_with_inline_plan` | POST /scrape with inline steps + selectors |
| `test_info_endpoints_consistency` | All info endpoints return valid JSON schemas |

### Test Data / Fixtures
```python
@pytest.fixture
def sample_plan_create_request():
    return {
        "url": "https://example.com/products",
        "objective": "Extract product names and prices",
        "hints": {"pagination": True},
    }

@pytest.fixture
def sample_scrape_request():
    return {
        "url": "https://example.com/products",
        "steps": [
            {"action": "navigate", "url": "https://example.com/products"},
            {"action": "wait", "condition": ".product-list", "condition_type": "selector"},
        ],
        "selectors": [
            {"name": "products", "selector": ".product-item", "multiple": True},
        ],
    }

@pytest.fixture
def mock_toolkit():
    """Mock WebScrapingToolkit with pre-configured responses."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `ScrapingHandler` properly extends `BaseView` with GET/POST/PUT/DELETE methods
- [ ] `ScrapingInfoHandler` properly extends `BaseHandler` with GET method handlers
- [ ] Plan CRUD endpoints work: create (POST), list (GET), load (GET/{name}), save (PUT/{name}), delete (DELETE/{name})
- [ ] POST /scrape executes scraping via `WebScrapingToolkit.scrape()`
- [ ] POST /crawl executes crawling via `WebScrapingToolkit.crawl()`
- [ ] GET /info/actions returns all browser action types with field schemas
- [ ] GET /info/drivers returns available driver types (selenium, playwright) with browsers
- [ ] GET /info/config returns DriverConfig JSON schema
- [ ] GET /info/strategies returns crawl strategy definitions (bfs, dfs)
- [ ] All responses use `self.json_response()` / `self.error()` patterns
- [ ] Error handling: 400 for invalid requests, 404 for missing plans, 500 for execution errors
- [ ] All unit tests pass: `pytest tests/handlers/test_scraping*.py -v`
- [ ] No breaking changes to existing `WebScrapingToolkit` API
- [ ] Route registration via `setup_scraping_routes(app)` convenience function

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Follow `ChatHandler` pattern for class-based view with GET/POST routing.
- Follow `GoogleGeneration` pattern for `post_init()` hook to initialize toolkit.
- Follow `AgentHandler.setup()` pattern for route registration.
- Use `BaseHandler` for `ScrapingInfoHandler` (method-based, each method is a separate route).
- Use `self.json_response()` for success, `self.error()` for client errors, `self.critical()` for server errors.
- Use `self.request.match_info.get()` for path params, `self.query_parameters()` for query strings.
- All toolkit calls are async — use `await` throughout.
- Use Pydantic models for request validation (validate before passing to toolkit).

### Route Registration Convention
```python
# In setup_scraping_routes(app):
# Class-based view routes (ScrapingHandler)
app.router.add_view('/api/v1/scraping/plans', ScrapingHandler)
app.router.add_view('/api/v1/scraping/plans/{name}', ScrapingHandler)

# IMPORTANT: we don't have access to the scraping handler instance here, so we need to add the routes manually.
app.router.add_route('POST', '/api/v1/scraping/scrape', scraping_handler_instance.handle_scrape)
app.router.add_route('POST', '/api/v1/scraping/crawl', scraping_handler_instance.handle_crawl)

# Method-based routes (ScrapingInfoHandler)
app.router.add_route('GET', '/api/v1/scraping/info/actions', info_handler.get_actions)
app.router.add_route('GET', '/api/v1/scraping/info/drivers', info_handler.get_drivers)
app.router.add_route('GET', '/api/v1/scraping/info/config', info_handler.get_config_schema)
app.router.add_route('GET', '/api/v1/scraping/info/strategies', info_handler.get_strategies)
```

### BrowserAction Introspection for `/info/actions`
```python
from parrot.tools.scraping.models import ACTION_MAP

def get_action_catalog() -> List[Dict[str, Any]]:
    """Introspect all BrowserAction subclasses to build UI catalog."""
    actions = []
    for action_name, action_class in ACTION_MAP.items():
        schema = action_class.model_json_schema()
        actions.append({
            "name": action_name,
            "description": action_class.__doc__ or "",
            "fields": schema.get("properties", {}),
            "required": schema.get("required", []),
        })
    return actions
```

### DriverConfig Schema for `/info/config`
```python
from parrot.tools.scraping.toolkit_models import DriverConfig

def get_config_schema() -> Dict[str, Any]:
    """Return DriverConfig JSON schema for dynamic form rendering."""
    return DriverConfig.model_json_schema()
```

### Known Risks / Gotchas
- **Long-running scrape/crawl**: HTTP requests may timeout for complex scraping jobs. Consider returning a task ID for async polling in a future iteration: can we use the `PATCH` method for request the status and result and using the current `JobManager` for that purpose? (register the Job, Job is execut)
- **Driver lifecycle**: The handler should create toolkit instances with `session_based=False` (default) to avoid driver leaks. Session mode should only be used if explicitly requested: Yes.
- **LLM dependency**: `plan_create` requires an LLM client. If no LLM is configured, the endpoint should return a clear error: Yes.
- **Concurrency**: Multiple concurrent scrape requests will each spin up their own browser. Consider rate limiting in production: Yes.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navigator` | `>=4.0` | BaseView, BaseHandler base classes |
| `aiohttp` | `>=3.9` | HTTP framework (via navigator) |
| `pydantic` | `>=2.0` | Request/response validation |

---

## 7. Open Questions

- [ ] Should plan creation go through an Agent (with LLM reasoning) or call `WebScrapingToolkit.plan_create()` directly? — *Owner: Jesus Lara*: on Handler startup (we can register signals to aiohttp using a `setup` method, we can create an instance of `BaseAgent` and register it in the app context)
- [ ] Should scrape/crawl endpoints support async task IDs for long-running jobs, or is synchronous response sufficient for v1? — *Owner: Jesus Lara*: Yes, we can use the current `JobManager` for that purpose (register the Job, Job is execut)
- [ ] Should the handler manage its own `WebScrapingToolkit` instance or receive one via `app` context (e.g., `request.app['scraping_toolkit']`)? — *Owner: Jesus Lara*: Handler manages its own `WebScrapingToolkit` instance and own `JobManager` instance and on `BaseAgent`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-26 | Jesus Lara | Initial draft |
