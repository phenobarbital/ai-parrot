#!/usr/bin/env python3
"""
Gorilla Sheds Scraper & PageIndex Builder.

Scrapes the Gorilla Sheds website (about, FAQ, installation, product collection)
and produces:
  - data/page_index.json — hierarchical PageIndex tree for PageIndexRetriever
  - data/products.json   — flat list of product dicts for reference/debugging

Usage:
    python examples/shoply/scraper.py

Requires:
    - aiohttp
    - beautifulsoup4 (with lxml or html.parser backend)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import aiohttp
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

BASE_URL = "https://gorillashed.com"
PAGES = {
    "about": "/pages/about",
    "faq": "/pages/faq",
    "installation": "/pages/shed-installation-process",
    "collection": "/collections/sheds",
}
DATA_DIR = Path(__file__).parent / "data"
REQUEST_DELAY = 1.5  # seconds between requests (polite crawling)
USER_AGENT = (
    "Mozilla/5.0 (compatible; GorillaAdvisorBot/1.0; "
    "+https://github.com/phenobarbital/ai-parrot)"
)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

async def fetch_page(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch a page and return its HTML text.

    Args:
        session: Active aiohttp client session.
        url: Full URL to fetch.

    Returns:
        HTML body as a string.

    Raises:
        aiohttp.ClientResponseError: On non-2xx status codes.
    """
    headers = {"User-Agent": USER_AGENT}
    async with session.get(url, headers=headers) as resp:
        resp.raise_for_status()
        return await resp.text()


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Normalise whitespace in scraped text."""
    return re.sub(r"\s+", " ", text).strip()


def parse_content_page(html: str) -> str:
    """Extract the main textual content from an informational page.

    Args:
        html: Raw HTML of the page.

    Returns:
        Cleaned text content.
    """
    soup = BeautifulSoup(html, "html.parser")
    # Try common Shopify content selectors
    main = (
        soup.find("div", class_="page-content")
        or soup.find("div", class_="rte")
        or soup.find("article")
        or soup.find("main")
        or soup.find("div", id="MainContent")
    )
    if main:
        return _clean_text(main.get_text(separator="\n"))
    # Fallback: use full body
    body = soup.find("body")
    return _clean_text(body.get_text(separator="\n")) if body else ""


def parse_faq_page(html: str) -> str:
    """Extract FAQ content, attempting to preserve Q/A structure.

    Args:
        html: Raw HTML of the FAQ page.

    Returns:
        Cleaned text with Q/A pairs.
    """
    soup = BeautifulSoup(html, "html.parser")
    # Try accordion / FAQ-specific containers
    faq_container = (
        soup.find("div", class_=re.compile(r"faq", re.I))
        or soup.find("div", class_="rte")
        or soup.find("main")
    )
    if faq_container:
        return _clean_text(faq_container.get_text(separator="\n"))
    return parse_content_page(html)


def parse_collection_page(html: str) -> list[dict[str, str]]:
    """Extract product links and basic info from a Shopify collection page.

    Args:
        html: Raw HTML of the collection page.

    Returns:
        List of dicts with keys: ``name``, ``url``, ``image``, ``price``.
    """
    soup = BeautifulSoup(html, "html.parser")
    products: list[dict[str, str]] = []

    # Strategy 1: Shopify product-card / product-item links
    product_links = soup.find_all("a", href=re.compile(r"/products/"))
    seen_slugs: set[str] = set()

    for link in product_links:
        href = link.get("href", "")
        if not href:
            continue
        # Deduplicate by product slug (last path segment) to handle
        # /products/imperial vs /collections/sheds/products/imperial
        slug = href.rstrip("/").split("/")[-1]
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        full_url = f"{BASE_URL}/products/{slug}"

        name = ""
        # Look for a title element nearby
        title_el = link.find(class_=re.compile(r"title|name", re.I))
        if title_el:
            name = _clean_text(title_el.get_text())
        if not name:
            name = _clean_text(link.get_text()) or slug.replace("-", " ").title()
        # Skip non-product links (e.g. "Learn More")
        if name.lower() in ("learn more", ""):
            continue

        img_tag = link.find("img")
        image = ""
        if img_tag:
            image = img_tag.get("src", "") or img_tag.get("data-src", "")
            if image.startswith("//"):
                image = "https:" + image

        price_el = link.find(class_=re.compile(r"price", re.I))
        price = _clean_text(price_el.get_text()) if price_el else ""

        products.append({
            "name": name,
            "url": full_url,
            "image": image,
            "price": price,
        })

    return products


def _parse_variant_json(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Extract Shopify variant data and merge with real prices.

    Gorilla Sheds uses two separate inline scripts:
    - ``<script class="variantsJSON-*">``: variant id, title (size), sku.
    - An anonymous ``<script>`` containing a JSON array with
      ``{id, price_p-2, price_p-1}`` for each variant — these hold the
      actual displayed prices (the variant JSON ``price`` field stores
      an internal Shopify value, *not* the customer-visible price).

    This function joins both sources by variant id.

    Args:
        soup: Parsed product page.

    Returns:
        List of enriched variant dicts with ``real_price`` and
        ``compare_price`` fields, or empty list if not found.
    """
    variants: list[dict[str, Any]] = []
    for script in soup.find_all("script", class_=re.compile(r"variantsJSON", re.I)):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                variants = data
                break
        except (json.JSONDecodeError, TypeError):
            pass

    if not variants:
        return []

    # Build a price lookup from the real-price script (keyed by variant id)
    price_map: dict[str, dict[str, str]] = {}
    for script in soup.find_all("script"):
        text = script.string or ""
        if "price_p-2" not in text:
            continue
        match = re.search(r"\[(\s*\{[^]]+\})\s*\]", text)
        if match:
            try:
                price_data = json.loads("[" + match.group(1) + "]")
                for entry in price_data:
                    vid = str(entry.get("id", ""))
                    if vid:
                        price_map[vid] = entry
            except (json.JSONDecodeError, TypeError):
                pass
        break

    # Merge real prices into variants
    for v in variants:
        vid = str(v.get("id", ""))
        real = price_map.get(vid, {})
        v["real_price"] = real.get("price_p-2", "")
        v["compare_price"] = real.get("price_p-1", "")

    return variants


def _parse_specs_tables(soup: BeautifulSoup) -> dict[str, str]:
    """Extract specifications from all ``<table>`` elements in the specs tab.

    Gorilla Sheds pages use ``<th>key</th><td>value</td>`` rows spread across
    multiple tables grouped by category (dimensions, roof, floor, walls, doors).

    Args:
        soup: Parsed product page.

    Returns:
        Flat dict of spec_name → spec_value.
    """
    specs: dict[str, str] = {}
    tabs_section = soup.find("section", class_="tabs-section")
    container = tabs_section if tabs_section else soup
    for table in container.find_all("table"):
        for row in table.find_all("tr"):
            th = row.find("th")
            td = row.find("td")
            if th and td:
                key = _clean_text(th.get_text())
                val = _clean_text(td.get_text())
                if key and val:
                    specs[key] = val
    return specs


def _parse_tab_features(soup: BeautifulSoup) -> list[str]:
    """Extract feature descriptions from the Features tab.

    The features tab contains cards with ``<h3>`` headings and ``<p>``
    descriptions.  We combine heading + paragraph into a single line.

    Args:
        soup: Parsed product page.

    Returns:
        List of feature strings.
    """
    features: list[str] = []
    tabs_section = soup.find("section", class_="tabs-section")
    if not tabs_section:
        return features
    # First tab pane is Features
    panes = tabs_section.find_all("div", class_="tab-pane")
    if not panes:
        return features
    feat_pane = panes[0]
    for p_tag in feat_pane.find_all("p"):
        text = _clean_text(p_tag.get_text())
        if text and len(text) > 5:
            features.append(text)
    return features


def parse_product_page(html: str, url: str) -> dict[str, Any]:
    """Extract detailed product info from an individual product page.

    Extracts price from Shopify variant JSON (cents → dollars), sizes from
    the variant/option select, and specs from the tabbed specification tables.

    Args:
        html: Raw HTML of the product page.
        url: Product URL (for metadata).

    Returns:
        Dict with product details.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Title — product-title heading, product-name element, or og:title meta
    title_el = (
        soup.find(class_=re.compile(r"product[-_]?title", re.I))
        or soup.find(class_=re.compile(r"product[-_]?name", re.I))
    )
    if title_el:
        name = _clean_text(title_el.get_text())
    else:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            # Strip site suffix (e.g. "Imperial 8x8 ... | Gorilla Shed")
            name = og["content"].split("|")[0].strip()
        else:
            name = url.split("/")[-1].replace("-", " ").title()

    # Description — from RTE or description div
    desc_el = (
        soup.find("div", class_=re.compile(r"product[-_]?desc", re.I))
        or soup.find("div", class_="rte")
        or soup.find("div", class_=re.compile(r"description", re.I))
    )
    description = _clean_text(desc_el.get_text(separator="\n")) if desc_el else ""

    # ── Price & sizes from variant JSON + real-price script ────────────
    variants = _parse_variant_json(soup)
    price = ""
    sizes: list[dict[str, Any]] = []
    if variants:
        real_prices = [
            float(v["real_price"]) for v in variants
            if v.get("real_price")
        ]
        if real_prices:
            min_p, max_p = min(real_prices), max(real_prices)
            price = f"${min_p:,.2f}"
            if max_p != min_p:
                price = f"${min_p:,.2f} – ${max_p:,.2f}"
        for v in variants:
            size_entry: dict[str, Any] = {
                "label": v.get("title", ""),
                "sku": v.get("sku", ""),
                "price": f"${v['real_price']}" if v.get("real_price") else "",
            }
            if v.get("compare_price"):
                size_entry["compare_at_price"] = f"${v['compare_price']}"
            sizes.append(size_entry)

    # Fallback: price from the visible price element
    if not price:
        price_el = soup.find("span", class_=re.compile(r"price.*money", re.I))
        if price_el:
            price = _clean_text(price_el.get_text())

    # Fallback: sizes from <select name="options[Size]">
    if not sizes:
        size_select = soup.find("select", {"name": re.compile(r"options\[Size\]", re.I)})
        if size_select:
            for opt in size_select.find_all("option"):
                label = opt.get_text(strip=True)
                if label:
                    sizes.append({"label": label, "sku": "", "price": ""})

    # Images
    images: list[str] = []
    for img in soup.find_all("img", src=re.compile(r"cdn\.shopify|gorilla", re.I)):
        src = img.get("src", "") or img.get("data-src", "")
        if src:
            if src.startswith("//"):
                src = "https:" + src
            images.append(src)

    # ── Specs from tabbed tables ─────────────────────────────────────────
    specs = _parse_specs_tables(soup)

    # ── Features from tab pane ───────────────────────────────────────────
    features = _parse_tab_features(soup)

    # Fallback: features from description list items
    if not features and desc_el:
        for li in desc_el.find_all("li"):
            text = _clean_text(li.get_text())
            if text:
                features.append(text)

    # Build slug for product_id
    slug = url.rstrip("/").split("/")[-1]

    return {
        "product_id": f"gorillashed-{slug}",
        "name": name,
        "description": description,
        "category": "sheds",
        "features": features,
        "specs": specs,
        "sizes": sizes,
        "price": price,
        "images": images[:5],  # cap to 5
        "url": url,
        "slug": slug,
    }


# ---------------------------------------------------------------------------
# PageIndex builder
# ---------------------------------------------------------------------------

def build_page_index(
    about_text: str,
    faq_text: str,
    installation_text: str,
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a hierarchical PageIndex tree from scraped content.

    The tree follows the structure expected by ``PageIndexRetriever``:
    each node has ``node_id``, ``title``, ``summary``, ``text``, and
    optionally ``children`` (mapped to ``nodes`` for the tree).

    Args:
        about_text: Scraped text from the About page.
        faq_text: Scraped text from the FAQ page.
        installation_text: Scraped text from the Installation page.
        products: List of product dicts from ``parse_product_page()``.

    Returns:
        PageIndex tree dict compatible with ``PageIndexRetriever.from_json()``.
    """
    product_children = []
    for p in products:
        child = {
            "node_id": f"product-{p.get('slug', p.get('product_id', 'unknown'))}",
            "title": p.get("name", "Unknown Product"),
            "summary": (p.get("description", "") or "")[:200],
            "text": _build_product_text(p),
        }
        product_children.append(child)

    tree: dict[str, Any] = {
        "doc_name": "Gorilla Sheds",
        "doc_description": "Product catalog and company information for Gorilla Sheds.",
        "structure": [
            {
                "node_id": "company-info",
                "title": "About Gorilla Sheds",
                "summary": "Company background, values, and mission.",
                "text": about_text or "About page content not available.",
            },
            {
                "node_id": "faq",
                "title": "Frequently Asked Questions",
                "summary": "Common questions about sheds, ordering, and delivery.",
                "text": faq_text or "FAQ content not available.",
            },
            {
                "node_id": "installation",
                "title": "Shed Installation Process",
                "summary": "Post-sale installation service details and requirements.",
                "text": installation_text or "Installation page content not available.",
            },
            {
                "node_id": "products",
                "title": "Sheds Collection",
                "summary": "All available shed products from Gorilla Sheds.",
                "nodes": product_children,
            },
        ],
    }
    return tree


def _build_product_text(product: dict[str, Any]) -> str:
    """Build a human-readable text block for a product node.

    Args:
        product: Product dict from ``parse_product_page()``.

    Returns:
        Formatted product text.
    """
    parts: list[str] = []
    parts.append(f"Product: {product.get('name', 'N/A')}")
    if product.get("price"):
        parts.append(f"Price: {product['price']}")
    if product.get("sizes"):
        parts.append("\nAvailable Sizes:")
        for s in product["sizes"]:
            line = f"  - {s['label']}"
            if s.get("price"):
                line += f": {s['price']}"
            if s.get("sku"):
                line += f" (SKU: {s['sku']})"
            parts.append(line)
    if product.get("description"):
        parts.append(f"\n{product['description']}")
    if product.get("features"):
        parts.append("\nFeatures:")
        for feat in product["features"]:
            parts.append(f"  - {feat}")
    if product.get("specs"):
        parts.append("\nSpecifications:")
        for k, v in product["specs"].items():
            parts.append(f"  {k}: {v}")
    if product.get("url"):
        parts.append(f"\nMore info: {product['url']}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main scrape pipeline
# ---------------------------------------------------------------------------

async def scrape_gorillasheds() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Scrape Gorilla Sheds site and build PageIndex + products list.

    Returns:
        Tuple of (page_index_tree, products_list).
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # 1. Fetch informational pages
        print("[1/4] Fetching About page...")
        try:
            about_html = await fetch_page(session, f"{BASE_URL}{PAGES['about']}")
            about_text = parse_content_page(about_html)
        except Exception as exc:
            logger.warning("Failed to fetch About page: %s", exc)
            about_text = ""
        await asyncio.sleep(REQUEST_DELAY)

        print("[2/4] Fetching FAQ page...")
        try:
            faq_html = await fetch_page(session, f"{BASE_URL}{PAGES['faq']}")
            faq_text = parse_faq_page(faq_html)
        except Exception as exc:
            logger.warning("Failed to fetch FAQ page: %s", exc)
            faq_text = ""
        await asyncio.sleep(REQUEST_DELAY)

        print("[3/4] Fetching Installation page...")
        try:
            install_html = await fetch_page(session, f"{BASE_URL}{PAGES['installation']}")
            installation_text = parse_content_page(install_html)
        except Exception as exc:
            logger.warning("Failed to fetch Installation page: %s", exc)
            installation_text = ""
        await asyncio.sleep(REQUEST_DELAY)

        # 2. Fetch collection page to discover products
        print("[4/4] Fetching Sheds collection...")
        try:
            collection_html = await fetch_page(session, f"{BASE_URL}{PAGES['collection']}")
            product_links = parse_collection_page(collection_html)
        except Exception as exc:
            logger.warning("Failed to fetch collection page: %s", exc)
            product_links = []

        # 3. Fetch individual product pages
        products: list[dict[str, Any]] = []
        total = len(product_links)
        for i, plink in enumerate(product_links, 1):
            await asyncio.sleep(REQUEST_DELAY)
            url = plink["url"]
            print(f"  Fetching product {i}/{total}: {plink.get('name', url)}")
            try:
                html = await fetch_page(session, url)
                product = parse_product_page(html, url)
                # Merge collection-level data where individual page may lack it
                if not product.get("price") and plink.get("price"):
                    product["price"] = plink["price"]
                if not product.get("images") and plink.get("image"):
                    product["images"] = [plink["image"]]
                products.append(product)
            except Exception as exc:
                logger.warning("Failed to fetch product %s: %s", url, exc)
                # Still add a basic entry from collection data
                slug = url.rstrip("/").split("/")[-1]
                products.append({
                    "product_id": f"gorillashed-{slug}",
                    "name": plink.get("name", slug.replace("-", " ").title()),
                    "description": "",
                    "category": "sheds",
                    "features": [],
                    "specs": {},
                    "price": plink.get("price", ""),
                    "images": [plink["image"]] if plink.get("image") else [],
                    "url": url,
                    "slug": slug,
                })

    # 4. Build PageIndex tree
    page_index = build_page_index(about_text, faq_text, installation_text, products)

    # 5. Persist outputs
    page_index_path = DATA_DIR / "page_index.json"
    page_index_path.write_text(
        json.dumps(page_index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nSaved: {page_index_path}")

    products_path = DATA_DIR / "products.json"
    products_path.write_text(
        json.dumps(products, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Saved: {products_path}")

    print(f"\nDone! Scraped {len(products)} products.")
    return page_index, products


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    asyncio.run(scrape_gorillasheds())
