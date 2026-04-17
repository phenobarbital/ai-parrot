# TASK-730: Rewrite `snapshot_from_driver` against `AbstractDriver`

**Feature**: fix-webscrapingtoolkit-executor
**Spec**: `sdd/specs/fix-webscrapingtoolkit-executor.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-728
**Assigned-to**: unassigned

---

## Context

`snapshot_from_driver` (`packages/ai-parrot-tools/src/parrot_tools/scraping/page_snapshot.py:483-523`)
reads `driver.current_url`, calls `driver.get(url)`, and reads `driver.page_source`
through `loop.run_in_executor(...)`. After TASK-728 the `driver` argument is
guaranteed to be an `AbstractDriver` — rewrite this helper accordingly.

Implements **Module 3** of the spec.

---

## Scope

- Replace the Selenium-style attribute access with awaited `AbstractDriver` calls:
  - `current = driver.current_url` (sync property — abstract drivers expose it)
  - `await driver.navigate(url, timeout=...)` instead of `driver.get(url)`
  - `html = await driver.get_page_source()` instead of `driver.page_source`
- Drop the `loop.run_in_executor(...)` plumbing (no longer needed — methods are async).
- Preserve `settle_seconds` (still wrapped in `await asyncio.sleep(settle_seconds)`).
- Preserve `Optional[PageSnapshot]` return contract — return `None` on driver failure with the same warning.
- Update the docstring: replace "Live Selenium WebDriver" with "Live AbstractDriver (Selenium or Playwright)".

**NOT in scope**:
- Modifying `fetch_snapshot` or `snapshot_from_html`
- Modifying any `PageSnapshot` model fields
- Adding a new helper for raw HTML capture
- Touching `executor.py` (TASK-729) or `toolkit.py` (TASK-731)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/page_snapshot.py` | MODIFY | Rewrite `snapshot_from_driver` (lines 483-523) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.drivers.abstract import AbstractDriver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py:11
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/page_snapshot.py:483
async def snapshot_from_driver(
    driver: Any,
    url: Optional[str] = None,
    *,
    settle_seconds: float = 1.0,
) -> Optional[PageSnapshot]: ...
# Public signature stays — only the type annotation tightens to AbstractDriver
# and the body is rewritten.

# packages/ai-parrot-tools/src/parrot_tools/scraping/page_snapshot.py
# (referenced helper, do NOT change)
def snapshot_from_html(html: str) -> Optional[PageSnapshot]: ...

# AbstractDriver methods used:
# - driver.current_url      (property)        line 238
# - driver.navigate(url, timeout)             line 47
# - driver.get_page_source()                  line 122
```

### Does NOT Exist
- ~~`AbstractDriver.get(url)`~~ — use `navigate(url)`
- ~~`AbstractDriver.page_source`~~ — use `await get_page_source()`
- ~~`asyncio.get_running_loop().run_in_executor(...)` is needed~~ — abstract methods are already async

---

## Implementation Notes

### Pattern to Follow

```python
async def snapshot_from_driver(
    driver: AbstractDriver,
    url: Optional[str] = None,
    *,
    settle_seconds: float = 1.0,
) -> Optional[PageSnapshot]:
    """Build a PageSnapshot from a live AbstractDriver (Selenium or Playwright).

    The driver should already have navigated to the target URL — we just
    read driver.get_page_source() here so the snapshot reflects the
    post-hydration DOM. ...
    """
    try:
        if url is not None and driver.current_url != url:
            await driver.navigate(url)
            if settle_seconds > 0:
                await asyncio.sleep(settle_seconds)
        html = await driver.get_page_source()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Driver-based snapshot failed: %s", exc)
        return None
    return snapshot_from_html(html)
```

### Key Constraints

- Public signature unchanged (caller in `WebScrapingToolkit.scrape()` at
  `toolkit.py:547` uses positional `(drv, url=url)`).
- Keep the broad `except Exception` + `logger.warning` rescue — driver issues
  shouldn't crash plan generation.
- Maintain the `settle_seconds > 0` check.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:547` — sole
  caller; uses `await snapshot_from_driver(drv, url=url)`.
- `packages/ai-parrot-tools/src/parrot_tools/scraping/page_snapshot.py:526-` —
  `fetch_snapshot` (kept as the no-driver path; not modified by this task).

---

## Acceptance Criteria

- [ ] `grep -nE "driver\.(get\b|page_source)" packages/ai-parrot-tools/src/parrot_tools/scraping/page_snapshot.py` → zero matches inside `snapshot_from_driver` body.
- [ ] `grep -n "run_in_executor" packages/ai-parrot-tools/src/parrot_tools/scraping/page_snapshot.py` → zero matches inside `snapshot_from_driver` body.
- [ ] Public signature `(driver, url=None, *, settle_seconds=1.0) -> Optional[PageSnapshot]` unchanged.
- [ ] Function returns `None` and logs warning on driver exception (regression check).
- [ ] No change to `fetch_snapshot` or `snapshot_from_html`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/scraping/test_page_snapshot.py — add cases

class TestSnapshotFromAbstractDriver:
    @pytest.mark.asyncio
    async def test_uses_get_page_source(self):
        driver = AsyncMock()
        type(driver).current_url = PropertyMock(return_value="https://example.com")
        driver.get_page_source = AsyncMock(return_value="<html><body><h1>Hi</h1></body></html>")
        snap = await snapshot_from_driver(driver, url="https://example.com")
        driver.get_page_source.assert_awaited_once()
        assert snap is not None

    @pytest.mark.asyncio
    async def test_navigates_when_url_differs(self):
        driver = AsyncMock()
        type(driver).current_url = PropertyMock(return_value="https://other.com")
        driver.get_page_source = AsyncMock(return_value="<html></html>")
        await snapshot_from_driver(driver, url="https://example.com", settle_seconds=0)
        driver.navigate.assert_awaited_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_returns_none_on_driver_error(self):
        driver = AsyncMock()
        type(driver).current_url = PropertyMock(side_effect=RuntimeError("boom"))
        snap = await snapshot_from_driver(driver, url="https://x.com")
        assert snap is None
```

---

## Agent Instructions

1. Read spec Module 3.
2. Confirm TASK-728 is complete (so the registry yields `AbstractDriver` and this rewrite is consistent end-to-end).
3. Implement the rewrite — only `snapshot_from_driver` body changes.
4. Move file to `sdd/tasks/completed/`.

---

## Completion Note

Completed 2026-04-17. Rewrote snapshot_from_driver to use AbstractDriver interface.
Also rewrote _scroll_sweep helper (called exclusively by snapshot_from_driver) to use
await driver.execute_script() instead of loop.run_in_executor. Removed driver.get()/
driver.page_source/run_in_executor. Public signature unchanged. Import smoke test passes.
page_snapshot.py was not present in the worktree (file was added to main repo after the
worktree was branched) so it was copied in from the main repo before modification.
