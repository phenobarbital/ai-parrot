"""
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
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional, Tuple

import aiohttp
from bs4 import BeautifulSoup, NavigableString, Tag

logger = logging.getLogger(__name__)


DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

TEXT_EXCERPT_CHARS = 2000
MAX_ELEMENT_HINTS = 60
MAX_LINKS = 50
MAX_ATTR_LEN = 60

# Structural outline budgets
STRUCTURE_MAX_DEPTH = 12
STRUCTURE_MAX_CHARS = 14000
STRUCTURE_NODE_TEXT_CHARS = 80
STRUCTURE_REPEAT_SHOW = 2  # show first N identical siblings before collapsing

# Descendant tags that look like transparent carousel wrappers — we
# recurse through these without counting toward the depth budget so the
# actual card inside (``[data-comp='cardshell-duc']``) surfaces.
STRUCTURE_TRANSPARENT_CLASS_MARKERS = (
    "slick-slider", "slick-list", "slick-track", "slick-slide",
    "swiper", "swiper-wrapper", "swiper-slide",
    "carousel", "scroll-x-panel",
)

# Tags we never recurse into for the structural outline
STRUCTURE_SKIP_TAGS = {
    "script", "style", "noscript", "template", "svg", "path",
    "meta", "link", "br", "hr", "img", "source", "track", "canvas",
    "input",
}

# Tags worth showing at all. Anything else (generic divs/spans without
# distinguishing attributes) gets skipped unless it has children that
# qualify — i.e. we short-circuit through it.
STRUCTURE_INTERESTING_TAGS = {
    "main", "section", "article", "nav", "aside", "header", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tr", "td", "th",
    "form", "fieldset", "label", "button", "a",
    "details", "summary", "figure", "figcaption",
    "p", "blockquote",
}


class PageSnapshot:
    """Compact page data for LLM prompt building.

    Fields are plain strings so they interpolate cleanly into the
    ``PLAN_GENERATION_PROMPT`` template.

    Args:
        title: Page ``<title>`` or ``og:title``.
        text_excerpt: First ~2000 chars of visible text.
        element_hints: Newline-separated list of notable elements with
            their tag, id, class, data-*, aria-*, and role attributes.
        structure: Pruned DOM outline (indented, repetition-collapsed)
            showing the repeating-block patterns the LLM should anchor
            its selectors on.
        links: Newline-separated ``text -> href`` pairs (up to 50).
    """

    def __init__(
        self,
        title: str = "",
        text_excerpt: str = "",
        element_hints: str = "",
        structure: str = "",
        links: str = "",
    ) -> None:
        self.title = title
        self.text_excerpt = text_excerpt
        self.element_hints = element_hints
        self.structure = structure
        self.links = links


def _truncate(value: str, limit: int = MAX_ATTR_LEN) -> str:
    value = value.strip()
    if len(value) > limit:
        return value[:limit] + "…"
    return value


def _extract_title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()
    return ""


def _extract_text_excerpt(soup: BeautifulSoup) -> str:
    # Work on a shallow copy so we don't mutate the caller's tree
    soup = BeautifulSoup(str(soup), "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    collapsed = " ".join(text.split())
    return collapsed[:TEXT_EXCERPT_CHARS]


def _element_hints(soup: BeautifulSoup) -> str:
    """Produce a compact list of notable elements and their identifying attrs.

    Kept as a flat list — the structural outline in ``structure`` carries
    the hierarchical view; this is a quick lookup table of named landmarks.
    """
    interesting_tags = (
        "section", "article", "nav", "main", "aside", "header", "footer",
        "h1", "h2", "h3",
        "form", "button",
    )
    hints: list[str] = []
    seen: set[str] = set()

    for el in soup.find_all(interesting_tags):
        parts = [el.name]

        el_id = el.get("id")
        if el_id:
            parts.append(f"id={el_id}")

        classes = el.get("class")
        if classes:
            parts.append(f"class={' '.join(classes[:3])}")

        for attr, val in el.attrs.items():
            if not attr.startswith(("data-", "aria-")) and attr != "role":
                continue
            if attr == "class":
                continue
            val_str = val if isinstance(val, str) else " ".join(val)
            parts.append(f"{attr}={_truncate(val_str)}")

        text = el.get_text(" ", strip=True)
        if text:
            parts.append(f"text={_truncate(text, 80)!r}")

        line = " | ".join(parts)
        if line in seen:
            continue
        seen.add(line)
        hints.append(line)
        if len(hints) >= MAX_ELEMENT_HINTS:
            break

    return "\n".join(hints)


# ── Structural outline ────────────────────────────────────────────────

def _shallow_sig(el: Tag) -> str:
    """Signature components local to this element (tag + class + data-* + role).

    Values of data-* attributes are intentionally ignored — product
    cards differ only by data-id but are structurally the same.
    """
    classes = " ".join(sorted(el.get("class") or []))
    data_attrs = sorted(a for a in el.attrs if a.startswith("data-"))
    role = el.get("role", "")
    return f"{el.name}|{classes}|{','.join(data_attrs)}|{role}"


def _signature(el: Tag) -> str:
    """Structural fingerprint for detecting repeating siblings.

    Combines the element's own signature with a fingerprint of its
    direct children. Without the children check, wrappers that happen
    to share tag + classes but contain very different content (e.g.
    two ``<tr>`` rows on Hacker News — one a header, one a story) get
    incorrectly collapsed.
    """
    own = _shallow_sig(el)
    child_sigs = [
        _shallow_sig(c) for c in el.children if isinstance(c, Tag)
    ]
    return own + "::" + "|".join(child_sigs)


def _node_label(el: Tag) -> str:
    """Render one node on one line: tag#id.class[attr=val] "text"."""
    parts: List[str] = [el.name]

    el_id = el.get("id")
    if el_id:
        parts.append(f"#{el_id}")

    classes = el.get("class") or []
    if classes:
        parts.append("." + ".".join(classes[:3]))
        if len(classes) > 3:
            parts.append(f"(+{len(classes) - 3})")

    # data-* and aria-* (values truncated)
    attrs: List[str] = []
    for name, val in el.attrs.items():
        if name in ("id", "class"):
            continue
        if not (name.startswith("data-") or name.startswith("aria-")
                or name in ("role", "type", "href", "name")):
            continue
        val_str = val if isinstance(val, str) else " ".join(val)
        val_str = _truncate(val_str, MAX_ATTR_LEN)
        if name == "href" and len(val_str) > 40:
            val_str = val_str[:40] + "…"
        attrs.append(f"{name}={val_str!r}")
    if attrs:
        parts.append("[" + " ".join(attrs) + "]")

    # Only the direct text (not descendants) to avoid duplicating children
    own_text_parts: List[str] = []
    for child in el.children:
        if isinstance(child, NavigableString) and not isinstance(child, type(el)):
            s = str(child).strip()
            if s:
                own_text_parts.append(s)
    own_text = " ".join(own_text_parts)
    if own_text:
        parts.append(f'"{_truncate(own_text, STRUCTURE_NODE_TEXT_CHARS)}"')

    return " ".join(parts)


def _should_emit(el: Tag) -> bool:
    """Decide whether a node is worth a line in the outline.

    Rules:
    - Always emit landmark tags (``section``, ``article``, ``li``, ``h*``, etc.).
    - Emit any element with an ``id`` or a ``data-*`` attribute (they
      tend to be selector-worthy).
    - Emit any element with a class (may be selector-worthy).
    - Skip unnamed generic ``div`` / ``span`` with no distinguishing attrs.
    """
    if el.name in STRUCTURE_INTERESTING_TAGS:
        return True
    if el.get("id"):
        return True
    if any(a.startswith("data-") or a.startswith("aria-") for a in el.attrs):
        return True
    if el.get("role"):
        return True
    if el.get("class"):
        return True
    return False


def _is_transparent_wrapper(el: Tag) -> bool:
    """Carousel plumbing (``slick-track``, ``swiper-wrapper``, etc.) that
    should not count against the depth budget, so the card inside still
    reaches the outline.
    """
    classes = el.get("class") or []
    for cls in classes:
        cl = cls.lower()
        for marker in STRUCTURE_TRANSPARENT_CLASS_MARKERS:
            if marker in cl:
                return True
    return False


def _render_structure(root: Tag) -> str:
    """Render a repetition-collapsed, depth-bounded DOM outline."""
    lines: List[str] = []
    budget = STRUCTURE_MAX_CHARS
    truncated = False

    def walk(el: Tag, depth: int) -> bool:
        """Returns True if budget is exhausted and walking should stop."""
        nonlocal budget, truncated
        if budget <= 0:
            truncated = True
            return True
        if depth > STRUCTURE_MAX_DEPTH:
            return False

        # Group children into runs of identical signatures
        children = [c for c in el.children if isinstance(c, Tag)]
        i = 0
        while i < len(children):
            if budget <= 0:
                return True
            child = children[i]
            if child.name in STRUCTURE_SKIP_TAGS:
                i += 1
                continue

            # Find run of identical siblings
            sig = _signature(child)
            run_end = i
            while run_end < len(children) and _signature(children[run_end]) == sig:
                run_end += 1
            run_len = run_end - i

            emit_child = _should_emit(child)

            if emit_child:
                indent = "  " * depth
                label = _node_label(child)
                line = f"{indent}{label}"
                lines.append(line)
                budget -= len(line) + 1

                # Recurse into this first exemplar. Carousel plumbing
                # wrappers (``slick-track``, ``swiper-wrapper``, etc.)
                # don't count toward the depth budget so the actual
                # card inside still reaches the outline.
                next_depth = depth + 1
                if _is_transparent_wrapper(child):
                    next_depth = depth
                if walk(child, next_depth):
                    return True

                if run_len > 1:
                    # Show one more exemplar if small, else collapse
                    if run_len == 2:
                        next_child = children[i + 1]
                        label2 = _node_label(next_child)
                        line = f"{indent}{label2}"
                        lines.append(line)
                        budget -= len(line) + 1
                        if walk(next_child, depth + 1):
                            return True
                    else:
                        marker = f"{indent}  ⋯ (×{run_len - 1} more identical siblings)"
                        lines.append(marker)
                        budget -= len(marker) + 1
            else:
                # Short-circuit through uninteresting wrapper: recurse
                # into its children at the SAME depth, so the outline
                # doesn't bloat with pointless generic divs.
                if walk(child, depth):
                    return True

            i = run_end

        return False

    walk(root, 0)
    if truncated:
        lines.append("… (outline truncated: page-wide budget hit)")
    return "\n".join(lines)


CHROME_ROLES = {"banner", "navigation", "contentinfo", "search"}
CHROME_TAGS = {"header", "nav", "footer"}

# Patterns that commonly identify site-wide chrome when the page doesn't
# use semantic tags. Checked against id and class values at the top level.
CHROME_ID_CLASS_PATTERNS = (
    "gnav", "globalnav", "global-nav", "globalheader", "global-header",
    "site-header", "siteheader", "header-wrapper",
    "footer", "site-footer", "global-footer",
    "megamenu", "mega-menu", "topnav", "top-nav",
    "breadcrumb",
)


def _looks_like_chrome(tag: Tag) -> bool:
    """Best-effort detection of nav/header/footer wrappers without semantic tags."""
    if tag.name in CHROME_TAGS:
        return True
    role = tag.get("role") or ""
    if role in CHROME_ROLES:
        return True
    # Check id and class names against known patterns
    tokens: List[str] = []
    el_id = tag.get("id") or ""
    if el_id:
        tokens.append(el_id.lower())
    classes = tag.get("class") or []
    for cls in classes:
        tokens.append(cls.lower())
    for token in tokens:
        for pattern in CHROME_ID_CLASS_PATTERNS:
            if pattern in token:
                return True
    return False


def _strip_top_level_chrome(root: Tag) -> Tag:
    """Remove ``<header>``, ``<nav>``, ``<footer>`` and elements with the
    corresponding ARIA roles from the outline root. These rarely contain
    the target content and eat the outline's character budget.

    Operates on a shallow clone so we don't mutate the caller's tree.
    Only top-level chrome is removed — we don't descend into content
    containers because (a) it's rarely needed and (b) mass-decomposing
    descendants while iterating corrupts the tree.
    """
    clone = BeautifulSoup(str(root), "html.parser")
    inner = clone.find(root.name) or clone

    # First strip direct children that look like chrome
    for child in list(inner.children):
        if not isinstance(child, Tag):
            continue
        if _looks_like_chrome(child):
            child.decompose()

    # If the body wraps everything in a single SPA root (``<div id="__next">``,
    # ``<div id="root">``, ``<div id="app">``, ``<main>``), descend into it
    # and strip chrome from that level too — sites commonly put the nav
    # next to the content inside the SPA root rather than at body level.
    tag_children = [c for c in inner.children if isinstance(c, Tag)]
    if len(tag_children) == 1:
        sole = tag_children[0]
        sole_id = (sole.get("id") or "").lower()
        if sole.name == "main" or sole_id in {"__next", "root", "app", "content", "__nuxt"}:
            for child in list(sole.children):
                if isinstance(child, Tag) and _looks_like_chrome(child):
                    child.decompose()
            return sole

    return inner


def _choose_structure_root(soup: BeautifulSoup) -> Tag:
    """Pick a starting node for the outline.

    Prefer ``<main>`` (most semantically meaningful). Otherwise strip
    top-level chrome (``<header>``, ``<nav>``, ``<footer>``, elements
    with ``role='banner'|'navigation'|'contentinfo'``) from ``<body>``
    so the outline budget is spent on actual content instead of the
    site-wide navigation.
    """
    main = soup.find("main")
    if main:
        return main
    body = soup.find("body")
    if body:
        return _strip_top_level_chrome(body)
    return soup


def _link_list(soup: BeautifulSoup) -> str:
    rows: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "#")):
            continue
        if href in seen:
            continue
        seen.add(href)
        text = _truncate(a.get_text(" ", strip=True), 60) or "(no text)"
        rows.append(f"{text} -> {href}")
        if len(rows) >= MAX_LINKS:
            break
    return "\n".join(rows)


def snapshot_from_html(html: str) -> PageSnapshot:
    """Build a ``PageSnapshot`` from raw HTML without any network call.

    Args:
        html: Raw HTML document.

    Returns:
        Populated ``PageSnapshot``.
    """
    soup = BeautifulSoup(html, "html.parser")
    # Drop noise before any traversal — keeps structure + text clean
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()

    structure_root = _choose_structure_root(soup)
    structure = _render_structure(structure_root) if structure_root else ""

    return PageSnapshot(
        title=_extract_title(soup),
        text_excerpt=_extract_text_excerpt(soup),
        element_hints=_element_hints(soup),
        structure=structure,
        links=_link_list(soup),
    )


async def _scroll_sweep(driver: Any, steps: int = 4, pause: float = 0.6) -> None:
    """Scroll the page top→bottom in chunks so lazy-loaded content hydrates.

    Many SPA pages only render below-the-fold sections (FAQ accordions,
    carousels of additional cards) after an intersection observer fires.
    Grabbing ``page_source`` without scrolling would miss those regions
    entirely — exactly what makes the LLM guess selectors instead of
    reading them from the snapshot.
    """
    loop = asyncio.get_running_loop()
    try:
        height = await loop.run_in_executor(
            None,
            lambda: driver.execute_script("return document.body.scrollHeight"),
        )
        if not height or height <= 0:
            return
        chunk = max(1, height // steps)
        for i in range(1, steps + 1):
            y = min(chunk * i, height)
            await loop.run_in_executor(
                None,
                lambda y=y: driver.execute_script(f"window.scrollTo(0, {y});"),
            )
            await asyncio.sleep(pause)
        # Return to top — some pages show different behavior based on
        # scroll position when querying elements.
        await loop.run_in_executor(
            None, lambda: driver.execute_script("window.scrollTo(0, 0);"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("scroll sweep failed (continuing): %s", exc)


async def snapshot_from_driver(
    driver: Any,
    url: Optional[str] = None,
    *,
    settle_seconds: float = 1.0,
    scroll_sweep: bool = True,
) -> Optional[PageSnapshot]:
    """Build a ``PageSnapshot`` from a live Selenium driver.

    The driver should already have navigated to the target URL — we just
    read ``driver.page_source`` here so the snapshot reflects the
    post-hydration DOM (i.e. what the user actually sees on SPA pages
    like React/Next.js/Vue apps where server HTML is mostly empty).

    When ``scroll_sweep`` is True (default), the page is scrolled
    top→bottom in ~4 chunks before snapshotting so intersection-observer
    -driven content (below-fold carousels, FAQ accordions) hydrates.

    Use this in preference to ``fetch_snapshot`` whenever a driver is
    available: most modern sites hydrate content client-side, making
    aiohttp-based snapshots sparse and misleading to the LLM.

    Args:
        driver: Live Selenium WebDriver, already on the target page.
        url: Optional URL to navigate to before snapshotting. If provided
            and the driver's current URL differs, ``driver.get(url)`` is
            called first.
        settle_seconds: Grace period after navigation to let async content
            hydrate. Default 1.0s — adjust up for heavy SPA pages.
        scroll_sweep: Scroll top→bottom to force below-fold hydration.

    Returns:
        Populated ``PageSnapshot``, or ``None`` if the driver call fails.
    """
    loop = asyncio.get_running_loop()
    try:
        if url is not None:
            current = await loop.run_in_executor(None, lambda: driver.current_url)
            if current != url:
                await loop.run_in_executor(None, driver.get, url)
                if settle_seconds > 0:
                    await asyncio.sleep(settle_seconds)
        if scroll_sweep:
            await _scroll_sweep(driver)
        html = await loop.run_in_executor(None, lambda: driver.page_source)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Driver-based snapshot failed: %s", exc)
        return None
    return snapshot_from_html(html)


async def fetch_snapshot(
    url: str,
    *,
    timeout: float = 10.0,
    user_agent: str = DEFAULT_UA,
    session: Optional[aiohttp.ClientSession] = None,
) -> Optional[PageSnapshot]:
    """Fetch a URL via ``aiohttp`` and build a ``PageSnapshot``.

    Returns ``None`` on any fetch failure — plan generation should then
    fall back to an empty snapshot rather than crashing. JS-rendered
    pages will produce a sparse snapshot; capture HTML via the browser
    driver and call ``snapshot_from_html`` directly for those.

    Args:
        url: Target URL to fetch.
        timeout: Request timeout in seconds.
        user_agent: User-Agent header.
        session: Optional pre-existing ``aiohttp.ClientSession`` to reuse.

    Returns:
        A ``PageSnapshot`` or ``None`` if the fetch failed.
    """
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    own_session = session is None
    client_timeout = aiohttp.ClientTimeout(total=timeout)

    try:
        sess = session or aiohttp.ClientSession(timeout=client_timeout)
        try:
            async with sess.get(url, headers=headers, allow_redirects=True) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "Snapshot fetch for %s returned HTTP %d", url, resp.status
                    )
                    return None
                html = await resp.text(errors="replace")
        finally:
            if own_session:
                await sess.close()
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.warning("Snapshot fetch for %s failed: %s", url, exc)
        return None

    return snapshot_from_html(html)
