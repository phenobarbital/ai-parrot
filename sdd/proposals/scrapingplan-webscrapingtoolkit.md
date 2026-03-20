# SPEC-02 — `WebScrapingToolkit`
**Project:** AI-Parrot · WebScrapingToolkit  
**Version:** 1.0  
**Status:** Draft  
**File:** `parrot/tools/scraping/toolkit.py`

---

## 1. Purpose

`WebScrapingToolkit` is the main entry point for all scraping and crawling
operations. It inherits from `AbstractToolkit`, meaning every public async
method is automatically exposed as an individual tool to agents and chatbots.

The toolkit cleanly separates:

| Concern | Method |
|---------|--------|
| Plan inference (LLM) | `plan_create` |
| Single-page/flow scraping | `scrape` |
| Multi-page crawling | `crawl` |
| Plan persistence | `plan_save`, `plan_load` |
| Plan discovery | `plan_list`, `plan_delete` |

---

## 2. Class Signature

```python
class WebScrapingToolkit(AbstractToolkit):
    """
    Toolkit for intelligent web scraping and crawling with plan caching.

    Each public async method becomes a tool automatically via AbstractToolkit.
    All browser operations are delegated to the driver layer (Selenium or
    Playwright); the toolkit itself is driver-agnostic.

    Session mode:
        session_based=True  — the browser instance is kept alive across
                              multiple calls (faster, stateful).
        session_based=False — a fresh browser is created and destroyed per
                              operation (safer, stateless). Default.
    """

    def __init__(
        self,
        # Driver selection
        driver_type: Literal["selenium", "playwright"] = "selenium",
        browser: Literal["chrome", "firefox", "edge", "safari",
                         "undetected", "webkit"] = "chrome",
        headless: bool = True,
        # Session management
        session_based: bool = False,
        # Browser tuning
        mobile: bool = False,
        mobile_device: Optional[str] = None,
        auto_install: bool = True,
        default_timeout: int = 10,
        retry_attempts: int = 3,
        delay_between_actions: float = 1.0,
        overlay_housekeeping: bool = True,
        disable_images: bool = False,
        custom_user_agent: Optional[str] = None,
        # Plan storage
        plans_dir: Optional[Union[str, Path]] = None,
        # LLM client for plan inference
        llm_client: Optional[Any] = None,
        **kwargs,
    ): ...
```

---

## 3. Internal State

```python
self._driver_config: DriverConfig       # frozen after __init__
self._session_based: bool
self._driver: Optional[AbstractDriver]  # None when session_based=False
self._plan_registry: PlanRegistry       # loaded lazily on first use
self._llm_client: Optional[Any]         # injected or resolved at runtime
self.logger: logging.Logger
```

`DriverConfig` is a simple Pydantic model capturing all browser parameters.
It is passed verbatim to `DriverFactory.create()` when a driver is needed.

---

## 4. Tool Methods

### 4.1 `plan_create`

```python
async def plan_create(
    self,
    url: str,
    objective: str,
    hints: Optional[Dict[str, Any]] = None,
    force_regenerate: bool = False,
) -> ScrapingPlan:
    """
    Generate a scraping plan for the given URL and objective using the LLM.

    Returns the plan as a structured JSON-serializable object WITHOUT
    executing any browser action.  The caller (agent or human) is
    responsible for reviewing and optionally modifying the plan before
    passing it to scrape() or crawl().

    If a plan for the same URL already exists in the registry AND
    force_regenerate is False, the cached plan is returned immediately
    without calling the LLM.

    Args:
        url:               Target URL.
        objective:         Natural language goal (e.g. 'extract all product
                           names and prices').
        hints:             Optional dict passed to the LLM prompt to bias
                           plan generation (e.g. known selectors, auth
                           requirements, pagination type).
        force_regenerate:  Ignore the registry cache and always call the LLM.

    Returns:
        ScrapingPlan — ready for human review and/or direct execution.
    """
```

**Internal flow:**

```
1. Ensure registry is loaded.
2. If not force_regenerate → registry.lookup(url)
   → If found: registry.touch(fingerprint); return ScrapingPlan from disk.
3. Fetch lightweight page snapshot:
   a. Open browser in headless mode.
   b. Navigate to url.
   c. Extract: page title, visible text (first 2000 chars), all element
      tag/id/class hints, link hrefs (up to 50).
   d. Close browser (or keep if session_based).
4. Build LLM prompt (see §4.1.1).
5. Call llm_client; parse JSON response into ScrapingPlan.
6. Return plan (NOT saved — saving is explicit via plan_save or the
   save_plan flag on scrape/crawl).
```

#### 4.1.1 LLM Prompt Template

```
You are a web scraping expert.  Given the following page snapshot, generate
a scraping plan to achieve the stated objective.

URL: {url}
OBJECTIVE: {objective}
HINTS: {hints}

PAGE SNAPSHOT:
Title: {title}
Text excerpt: {text_excerpt}
Element hints: {element_hints}
Available links: {links}

Respond ONLY with a valid JSON object matching this schema:
{schema_json}

Rules:
- Use CSS selectors unless an XPath is clearly more reliable.
- Prefer data-* attributes and IDs over class names.
- Include a wait step after every navigation.
- If pagination is needed, include a loop action.
- Set browser_config only if non-default settings are required.
```

The schema injected is the `ScrapingPlan` JSON Schema (via
`ScrapingPlan.model_json_schema()`).

---

### 4.2 `scrape`

```python
async def scrape(
    self,
    url: str,
    plan: Optional[Union[ScrapingPlan, Dict[str, Any]]] = None,
    objective: Optional[str] = None,
    save_plan: bool = False,
    browser_config_override: Optional[Dict[str, Any]] = None,
) -> ScrapingResult:
    """
    Execute a scraping operation on a single URL or multi-step flow.

    Plan resolution order:
      1. plan argument (explicit, highest priority).
      2. Registry cache lookup by URL.
      3. Auto-generate via plan_create() if objective is provided.
      4. Raise ValueError if none of the above yields a plan.

    Args:
        url:                    Entry point URL.
        plan:                   Pre-built ScrapingPlan or raw dict.
        objective:              Used only if plan must be auto-generated.
        save_plan:              Persist the plan to disk and registry after
                                successful execution.
        browser_config_override: Merge these settings into the plan's
                                 browser_config at execution time.

    Returns:
        ScrapingResult with extracted data, screenshots, and metadata.
    """
```

**Internal flow:**

```
1. Resolve plan (see priority order above).
2. Merge browser_config_override into resolved plan.
3. Acquire driver (session or fresh).
4. Execute plan.steps via execution engine (same engine used by legacy
   WebScrapingTool — zero duplication).
5. Run selectors against final DOM to extract ScrapingResult.data.
6. If save_plan: call plan_save(plan).
7. Release driver if not session_based.
8. Return ScrapingResult.
```

---

### 4.3 `crawl`

```python
async def crawl(
    self,
    start_url: str,
    depth: int = 1,
    max_pages: Optional[int] = None,
    follow_selector: Optional[str] = None,
    follow_pattern: Optional[str] = None,
    plan: Optional[Union[ScrapingPlan, Dict[str, Any]]] = None,
    objective: Optional[str] = None,
    save_plan: bool = False,
    concurrency: int = 1,
) -> CrawlResult:
    """
    Recursively scrape pages starting from start_url.

    The same extraction plan (steps + selectors) is applied to every
    discovered page.  Link discovery uses follow_selector to find next-page
    or child-page anchors, filtered by follow_pattern (regex).

    Args:
        start_url:       Root URL.
        depth:           Maximum recursion depth (1 = only start_url and its
                         direct links, no further traversal).
        max_pages:       Hard cap on total pages scraped (safety valve).
        follow_selector: CSS/XPath to locate links to follow.  Falls back to
                         plan.follow_selector, then to `a[href]`.
        follow_pattern:  Regex applied to discovered hrefs; non-matching URLs
                         are skipped.  Falls back to plan.follow_pattern.
        plan:            Extraction plan.  Resolved same as in scrape().
        objective:       Used if plan must be auto-generated.
        save_plan:       Persist plan after first successful page.
        concurrency:     Number of pages to scrape in parallel (>1 requires
                         session_based=False or multiple driver instances).

    Returns:
        CrawlResult aggregating per-page ScrapingResults, visited URLs, and
        a summary.
    """
```

**Crawl algorithm:**

```
frontier = deque([(start_url, 0)])
visited  = set()
results  = []

while frontier and (max_pages is None or len(results) < max_pages):
    url, current_depth = frontier.popleft()
    if url in visited: continue
    visited.add(url)

    page_result = await scrape(url, plan=resolved_plan)
    results.append(page_result)

    if current_depth < depth:
        links = discover_links(page_result.raw_html,
                               follow_selector, follow_pattern, base_url=url)
        for link in links:
            if link not in visited:
                frontier.append((link, current_depth + 1))

return CrawlResult(pages=results, visited_urls=list(visited), ...)
```

`concurrency > 1` replaces the sequential loop with `asyncio.gather` on
batches of `concurrency` pages, each with its own driver instance.

---

### 4.4 `plan_save`

```python
async def plan_save(
    self,
    plan: ScrapingPlan,
    overwrite: bool = False,
) -> PlanSaveResult:
    """
    Persist a plan to disk and register it in the index.

    If a plan with the same fingerprint already exists on disk and
    overwrite=False, the version number is bumped automatically
    (e.g. 1.0 → 1.1) and a new file is written.

    Args:
        plan:      Plan to save.
        overwrite: Replace existing file with the same fingerprint+version.

    Returns:
        PlanSaveResult(path, name, version, registered=True)
    """
```

---

### 4.5 `plan_load`

```python
async def plan_load(
    self,
    url_or_name: str,
) -> Optional[ScrapingPlan]:
    """
    Load a plan from disk by URL (registry lookup) or by name.

    Returns None if no matching plan is found.
    """
```

---

### 4.6 `plan_list`

```python
async def plan_list(
    self,
    domain_filter: Optional[str] = None,
    tag_filter: Optional[str] = None,
) -> List[PlanSummary]:
    """
    List all saved plans with summary metadata.

    Args:
        domain_filter: If set, only return plans for this domain.
        tag_filter:    If set, only return plans that include this tag.

    Returns:
        List of PlanSummary objects sorted by last_used_at desc.
    """
```

`PlanSummary` is a slim projection of `PlanRegistryEntry` without the file path:

```python
class PlanSummary(BaseModel):
    name: str
    version: str
    url: str
    domain: str
    created_at: datetime
    last_used_at: Optional[datetime]
    use_count: int
    tags: List[str]
```

---

### 4.7 `plan_delete`

```python
async def plan_delete(
    self,
    name: str,
    delete_file: bool = True,
) -> bool:
    """
    Remove a plan from the registry.

    Args:
        name:        Plan name to remove.
        delete_file: If True, also delete the JSON file from disk.
                     If False, only removes the registry entry
                     (file remains for manual recovery).

    Returns:
        True if the plan was found and removed; False otherwise.
    """
```

---

## 5. Result Models

### 5.1 `ScrapingResult` (existing, extended)

The existing model is kept; the toolkit adds `plan_used` metadata:

```python
class ScrapingResult(BaseModel):
    success: bool
    url: str
    data: Dict[str, Any]          # extracted content by selector name
    raw_html: Optional[str]
    screenshots: List[str]        # file paths
    error: Optional[str]
    elapsed_seconds: float
    plan_used: Optional[str]      # plan.name if a plan was resolved
    from_cache: bool = False      # True if plan came from registry
```

### 5.2 `CrawlResult`

```python
class CrawlResult(BaseModel):
    start_url: str
    depth: int
    pages: List[ScrapingResult]
    visited_urls: List[str]
    failed_urls: List[str]
    total_pages: int
    total_elapsed_seconds: float
    plan_used: Optional[str]

    @property
    def success_rate(self) -> float:
        if not self.total_pages:
            return 0.0
        return len([p for p in self.pages if p.success]) / self.total_pages
```

### 5.3 `PlanSaveResult`

```python
class PlanSaveResult(BaseModel):
    success: bool
    path: str
    name: str
    version: str
    registered: bool
    message: str
```

---

## 6. Session Management

```python
# session_based=True — driver persists across calls
toolkit = WebScrapingToolkit(session_based=True, driver_type="playwright")
await toolkit.start()          # inherited from AbstractToolkit; opens driver

result1 = await toolkit.scrape("https://example.com/page1")
result2 = await toolkit.scrape("https://example.com/page2")  # same browser

await toolkit.stop()           # closes driver

# session_based=False (default) — driver is per-operation
toolkit = WebScrapingToolkit()
result = await toolkit.scrape("https://example.com")  # opens, runs, closes
```

`start()` and `stop()` are overrides of `AbstractToolkit.start/stop`.
If `session_based=True` and `start()` has not been called, the driver is
initialized lazily on the first operation (with a logged warning).

---

## 7. Driver Acquisition Pattern

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def _driver_context(self, config_override=None):
    """Yield an active driver, managing lifecycle based on session_based."""
    if self._session_based:
        if self._driver is None:
            self._driver = await DriverFactory.create(self._driver_config)
        yield self._driver
    else:
        driver = await DriverFactory.create(
            self._driver_config.merge(config_override)
        )
        try:
            yield driver
        finally:
            await driver.quit()
```

All three operation methods (`scrape`, `crawl`, and the snapshot fetch inside
`plan_create`) use `async with self._driver_context() as driver`.

---

## 8. LLM Client Resolution

The toolkit resolves the LLM client in this order:

1. Explicit `llm_client` constructor argument.
2. `AIParrotConfig.default_client` (global configuration).
3. Environment variable `AIPARROT_DEFAULT_MODEL`.
4. Raise `RuntimeError` if none available and `plan_create` is called.

The client only needs to support:

```python
response: str = await client.complete(prompt: str) -> str
```

The toolkit wraps this in a thin adapter so any AI-Parrot LLM client works
without modification.

---

## 9. Backward Compatibility

`WebScrapingTool` is retained unchanged with a deprecation warning:

```python
import warnings

class WebScrapingTool(AbstractTool):
    def __init__(self, *args, **kwargs):
        warnings.warn(
            "WebScrapingTool is deprecated.  Use WebScrapingToolkit instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)
```

---

## 10. Public API Summary

| Method | Exposed as tool | Requires LLM | Mutates disk |
|--------|----------------|--------------|--------------|
| `plan_create` | ✓ | ✓ (unless cached) | ✗ |
| `scrape` | ✓ | Only if plan missing | Optional |
| `crawl` | ✓ | Only if plan missing | Optional |
| `plan_save` | ✓ | ✗ | ✓ |
| `plan_load` | ✓ | ✗ | ✗ |
| `plan_list` | ✓ | ✗ | ✗ |
| `plan_delete` | ✓ | ✗ | Optional |

---

## 11. Usage Examples

```python
from aiparrot.tools.scraping import WebScrapingToolkit

toolkit = WebScrapingToolkit(
    driver_type="playwright",
    browser="chrome",
    headless=True,
    session_based=False,
    plans_dir="./my_plans",
)

# 1. Generate plan for human review
plan = await toolkit.plan_create(
    url="https://shop.example.com/products",
    objective="Extract all product names, prices, and ratings",
)
print(plan.model_dump_json(indent=2))   # review / edit JSON
# ... user edits plan ...

# 2. Execute with confirmed plan, save for reuse
result = await toolkit.scrape(
    url="https://shop.example.com/products",
    plan=plan,
    save_plan=True,
)

# 3. Later: auto-uses cached plan (no LLM call)
result2 = await toolkit.scrape("https://shop.example.com/products")
assert result2.from_cache is True

# 4. Crawl with depth
crawl = await toolkit.crawl(
    start_url="https://news.example.com",
    depth=2,
    max_pages=20,
    follow_selector="a.article-link",
    objective="Extract article titles and summaries",
    save_plan=True,
)
print(f"Scraped {crawl.total_pages} pages, success rate: {crawl.success_rate:.0%}")

# 5. Plan management
plans = await toolkit.plan_list(domain_filter="shop.example.com")
await toolkit.plan_delete("shop_example_com")
```

---

## 12. Dependencies

No new dependencies beyond SPEC-01 requirements and the existing tool stack.

---

*Previous: [SPEC-01 — ScrapingPlan & PlanRegistry](./SPEC-01-ScrapingPlan-PlanRegistry.md)*  
*Next: [SPEC-03 — CrawlEngine](./SPEC-03-CrawlEngine.md)*
