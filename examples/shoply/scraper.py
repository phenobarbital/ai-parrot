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
    seen_urls: set[str] = set()

    for link in product_links:
        href = link.get("href", "")
        if not href or href in seen_urls:
            continue
        # Skip anchors that are just images within a real card
        full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        name = ""
        # Look for a title element nearby
        title_el = link.find(class_=re.compile(r"title|name", re.I))
        if title_el:
            name = _clean_text(title_el.get_text())
        if not name:
            name = _clean_text(link.get_text()) or href.split("/")[-1].replace("-", " ").title()

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


def parse_product_page(html: str, url: str) -> dict[str, Any]:
    """Extract detailed product info from an individual product page.

    Args:
        html: Raw HTML of the product page.
        url: Product URL (for metadata).

    Returns:
        Dict with product details.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title_el = (
        soup.find("h1", class_=re.compile(r"product", re.I))
        or soup.find("h1")
    )
    name = _clean_text(title_el.get_text()) if title_el else url.split("/")[-1].replace("-", " ").title()

    # Description
    desc_el = (
        soup.find("div", class_=re.compile(r"product[-_]?desc", re.I))
        or soup.find("div", class_="rte")
        or soup.find("div", class_=re.compile(r"description", re.I))
    )
    description = _clean_text(desc_el.get_text(separator="\n")) if desc_el else ""

    # Price
    price_el = soup.find(class_=re.compile(r"product[-_]?price|current[-_]?price", re.I))
    price = _clean_text(price_el.get_text()) if price_el else ""

    # Images
    images: list[str] = []
    for img in soup.find_all("img", src=re.compile(r"cdn\.shopify|gorilla", re.I)):
        src = img.get("src", "") or img.get("data-src", "")
        if src:
            if src.startswith("//"):
                src = "https:" + src
            images.append(src)

    # Features / specs — look for lists in the description area
    features: list[str] = []
    specs: dict[str, str] = {}
    if desc_el:
        for li in desc_el.find_all("li"):
            text = _clean_text(li.get_text())
            if ":" in text:
                key, _, val = text.partition(":")
                specs[key.strip()] = val.strip()
            elif text:
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
    if product.get("description"):
        parts.append(f"\n{product['description']}")
    if product.get("features"):
        parts.append("\nFeatures:")
        for f in product["features"]:
            parts.append(f"  - {f}")
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
