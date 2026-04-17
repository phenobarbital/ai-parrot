# TASK-731: Tighten `WebScrapingToolkit` typing for `AbstractDriver`

**Feature**: fix-webscrapingtoolkit-executor
**Spec**: `sdd/specs/fix-webscrapingtoolkit-executor.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-728, TASK-729, TASK-730
**Assigned-to**: unassigned

---

## Context

After TASK-728/729/730 every driver yielded by the registry is an
`AbstractDriver`, the executor consumes only that surface, and
`snapshot_from_driver` does the same. `WebScrapingToolkit` doesn't need
behavior changes — `start()`, `stop()`, `scrape()`, and `crawl()` already
delegate to `DriverRegistry` / `_quit_driver` / `driver_context` /
`execute_plan_steps`. Tighten the type annotations so the toolkit reflects
the new contract.

Implements **Module 5** of the spec.

---

## Scope

- Update `_session_driver` annotation in `WebScrapingToolkit.__init__` (toolkit.py:138) from `Optional[Any]` to `Optional[AbstractDriver]`.
- Add `from .drivers.abstract import AbstractDriver` import at the top of `toolkit.py`.
- Update `start()` (toolkit.py:146) docstring: replace "browser instance" wording with "AbstractDriver instance" so users know what `_session_driver` is.
- Verify (no code change) that `scrape()` and `crawl()` continue to pass the driver through to `execute_plan_steps` and `snapshot_from_driver` — they don't reach into `_session_driver` for any Selenium-specific attribute.
- No change to `__init__` parameter list, no change to `DriverConfig`, no change to public API.

**NOT in scope**:
- Modifying `executor.py` / `page_snapshot.py` / `driver_context.py`
- Adding new public methods to `WebScrapingToolkit`
- Updating `WebScrapingTool` (legacy)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py` | MODIFY | Tighten `_session_driver` typing; small docstring tweaks |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.drivers.abstract import AbstractDriver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py:11

# already in toolkit.py — leave them
from .driver_context import DriverRegistry, driver_context, _quit_driver
from .executor import execute_plan_steps
from .page_snapshot import PageSnapshot, snapshot_from_driver
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py
class WebScrapingToolkit(AbstractToolkit):
    _config: DriverConfig                                    # line 123
    _session_based: bool                                     # line 137
    _session_driver: Optional[Any]                           # line 138 — RETYPE
    _registry: Optional[PlanRegistry]                        # line 139
    _llm_client: Optional[Any]                               # line 140
    _plans_dir: Path                                         # line 141

    async def start(self) -> None: ...                       # line 146
    async def stop(self) -> None: ...                        # line 160
    async def scrape(self, url, plan=None, objective=None,
                     steps=None, selectors=None, save_plan=False,
                     browser_config_override=None) -> ScrapingResult: ...  # ~line 488
    async def crawl(self, url, ...) -> CrawlResult: ...       # see file
```

### Does NOT Exist
- ~~`AbstractDriver.is_started` / `.driver_type`~~ — not on the abstract surface; do not check
- ~~`WebScrapingToolkit.driver` / `.get_driver()`~~ — internal `_session_driver` is the only handle
- ~~The toolkit needs to import `SeleniumDriver` or `PlaywrightDriver` directly~~ — it must NOT; everything goes through the registry

---

## Implementation Notes

### Pattern to Follow

```python
# Top of toolkit.py
from .drivers.abstract import AbstractDriver

# In WebScrapingToolkit.__init__
self._session_driver: Optional[AbstractDriver] = None
```

### Key Constraints

- Do not import `SeleniumDriver` or `PlaywrightDriver` from `toolkit.py` —
  the toolkit must remain backend-agnostic. `AbstractDriver` is the only
  driver-side import allowed.
- Do not add a `@property` exposing `_session_driver`; it's intentionally
  internal.
- Do not change the constructor's `driver_type` / `browser` parameters —
  they still feed `DriverConfig`.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:154-158` — `start()` lifecycle
- `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:160-165` — `stop()` lifecycle
- `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:519-553` — `scrape()` driver use

---

## Acceptance Criteria

- [ ] `_session_driver: Optional[AbstractDriver]` annotation present.
- [ ] `from .drivers.abstract import AbstractDriver` added.
- [ ] No new imports from `selenium_driver` or `playwright_driver` in `toolkit.py`.
- [ ] `pytest packages/ai-parrot-tools/tests/scraping/test_toolkit.py` continues to pass (after TASK-732 fixture updates if needed).
- [ ] `python -c "from parrot_tools.scraping.toolkit import WebScrapingToolkit"` succeeds.

---

## Test Specification

No new tests in this task — TASK-732 covers test updates. This task is
type-tightening only. Run the existing toolkit suite to confirm no regression.

---

## Agent Instructions

1. Read spec Module 5.
2. Confirm TASK-728/729/730 are complete.
3. Make the small annotation/import changes.
4. Run `pytest packages/ai-parrot-tools/tests/scraping/test_toolkit.py -q` to confirm.
5. Move file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*
