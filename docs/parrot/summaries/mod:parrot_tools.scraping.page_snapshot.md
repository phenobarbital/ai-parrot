---
type: Wiki Summary
title: parrot_tools.scraping.page_snapshot
id: mod:parrot_tools.scraping.page_snapshot
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Page snapshot builder for LLM-based plan generation.
relates_to:
- concept: class:parrot_tools.scraping.page_snapshot.PageSnapshot
  rel: defines
- concept: func:parrot_tools.scraping.page_snapshot.fetch_snapshot
  rel: defines
- concept: func:parrot_tools.scraping.page_snapshot.snapshot_from_driver
  rel: defines
- concept: func:parrot_tools.scraping.page_snapshot.snapshot_from_html
  rel: defines
---

# `parrot_tools.scraping.page_snapshot`

Page snapshot builder for LLM-based plan generation.

Produces a compact textual summary of a target page that the
``PlanGenerator`` feeds into the prompt so the LLM can choose real
selectors instead of guessing (``[data-testid='...']``, ``.plan-card``).

The key piece is ``structure`` — a pruned DOM outline where repeating
siblings are collapsed to a single exemplar plus a ``(×N more identical)``
marker. This exposes the repeating-block patterns (card carousels, FAQ
accordions) the LLM needs to pick a precise row selector.

Two fetch strategies are provided:

- ``fetch_snapshot`` (default): a lightweight ``aiohttp`` GET. Fast and
  cheap; suitable for server-rendered pages. Misses JS-hydrated content.
- ``snapshot_from_html``: accepts raw HTML (e.g. already captured via a
  browser driver) and builds the snapshot without any network call.

## Classes

- **`PageSnapshot`** — Compact page data for LLM prompt building.

## Functions

- `def snapshot_from_html(html: str) -> PageSnapshot` — Build a ``PageSnapshot`` from raw HTML without any network call.
- `async def snapshot_from_driver(driver: Any, url: Optional[str]=None, *, settle_seconds: float=1.0, scroll_sweep: bool=True) -> Optional[PageSnapshot]` — Build a ``PageSnapshot`` from a live AbstractDriver (Selenium or Playwright).
- `async def fetch_snapshot(url: str, *, timeout: float=10.0, user_agent: str=DEFAULT_UA, session: Optional[aiohttp.ClientSession]=None) -> Optional[PageSnapshot]` — Fetch a URL via ``aiohttp`` and build a ``PageSnapshot``.
