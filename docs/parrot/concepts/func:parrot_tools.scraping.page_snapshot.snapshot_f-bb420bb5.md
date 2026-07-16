---
type: Concept
title: snapshot_from_driver()
id: func:parrot_tools.scraping.page_snapshot.snapshot_from_driver
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build a ``PageSnapshot`` from a live AbstractDriver (Selenium or Playwright).
---

# snapshot_from_driver

```python
async def snapshot_from_driver(driver: Any, url: Optional[str]=None, *, settle_seconds: float=1.0, scroll_sweep: bool=True) -> Optional[PageSnapshot]
```

Build a ``PageSnapshot`` from a live AbstractDriver (Selenium or Playwright).

The driver should already have navigated to the target URL — we just
read ``driver.get_page_source()`` here so the snapshot reflects the
post-hydration DOM (i.e. what the user actually sees on SPA pages
like React/Next.js/Vue apps where server HTML is mostly empty).

When ``scroll_sweep`` is True (default), the page is scrolled
top→bottom in ~4 chunks before snapshotting so intersection-observer
-driven content (below-fold carousels, FAQ accordions) hydrates.

Use this in preference to ``fetch_snapshot`` whenever a driver is
available: most modern sites hydrate content client-side, making
aiohttp-based snapshots sparse and misleading to the LLM.

Args:
    driver: Live AbstractDriver (Selenium or Playwright), already on the
        target page.
    url: Optional URL to navigate to before snapshotting. If provided
        and the driver's current URL differs, ``driver.navigate(url)`` is
        called first.
    settle_seconds: Grace period after navigation to let async content
        hydrate. Default 1.0s — adjust up for heavy SPA pages.
    scroll_sweep: Scroll top→bottom to force below-fold hydration.

Returns:
    Populated ``PageSnapshot``, or ``None`` if the driver call fails.
