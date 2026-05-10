"""JSON-LD extractor functions and data model for WebScrapingLoader.

This module provides:
- ``JsonLdItem`` — dataclass representing a single extracted JSON-LD item
- ``strip_html_text`` — utility to decode HTML entities and strip tags
- One extractor function per supported schema.org ``@type``
- ``EXTRACTOR_REGISTRY`` — dict mapping ``@type`` strings to extractor callables

Extractor functions are pure data transformations: they receive a parsed
JSON-LD node (a ``dict``) and return ``List[JsonLdItem]``.  They have no
dependency on WebScrapingLoader or BeautifulSoup beyond tag-stripping.

Dispatch into the loader's pipeline happens in ``webscraping.py`` via
``_extract_jsonld`` and ``_walk_jsonld_node``.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class JsonLdItem:
    """A single structured item extracted from a JSON-LD block.

    Attributes:
        content_kind: Semantic type label (e.g. ``"faq"``, ``"jsonld-product"``).
        source_type: Provenance label (e.g. ``"faq-jsonld"``, ``"product-jsonld"``).
        page_content: Plain-text representation optimised for embedding.
        row_data: Raw key/value data for downstream metadata.
        selector_name: Human-readable name used as the ``selector_name`` metadata
            field.  Defaults to ``content_kind`` when not explicitly set.
    """

    content_kind: str
    source_type: str
    page_content: str
    row_data: Dict[str, Any] = field(default_factory=dict)
    selector_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def strip_html_text(text: Any) -> str:
    """Render arbitrary text as clean plain text.

    Replicates ``WebScrapingLoader._strip_html`` exactly:
    1. HTML-unescape entities (``&amp;`` → ``&``, ``&nbsp;`` → space, …).
    2. Strip HTML tags via BeautifulSoup so nested anchors/lists collapse
       to their visible text.
    3. Collapse whitespace runs (including ``\\xa0`` from ``&nbsp;``) to a
       single space and strip leading/trailing whitespace.

    Args:
        text: Any value.  ``None`` returns ``""``; non-strings are coerced
            to ``str`` before processing.

    Returns:
        Cleaned plain-text string.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    decoded = _html.unescape(text)
    soup = BeautifulSoup(decoded, "html.parser")
    flat = soup.get_text(separator=" ", strip=False)
    return re.sub(r"\s+", " ", flat).strip()


def _get_name(node: Dict[str, Any]) -> str:
    """Return the ``name`` field from a JSON-LD node as clean text."""
    return strip_html_text(node.get("name", ""))


def _get_description(node: Dict[str, Any]) -> str:
    """Return the ``description`` field from a JSON-LD node as clean text."""
    return strip_html_text(node.get("description", ""))


# ---------------------------------------------------------------------------
# Extractor functions
# ---------------------------------------------------------------------------


def faq_extractor(node: Dict[str, Any]) -> List[JsonLdItem]:
    """Extract FAQ Q&A pairs from a FAQPage JSON-LD node.

    Yields one ``JsonLdItem`` per Question/Answer pair with:
    - ``content_kind="faq"``
    - ``source_type="faq-jsonld"``
    - ``page_content="Q: <question>\\n\\nA: <answer>"``

    Backward-compatible with the original ``_iter_faqpage_pairs`` /
    ``_docs_from_faqpage`` pipeline.

    Args:
        node: Parsed JSON-LD dict with ``@type="FAQPage"``.

    Returns:
        List of ``JsonLdItem`` instances (empty if no valid Q&A pairs found).
    """
    items: List[JsonLdItem] = []
    main_entity = node.get("mainEntity") or []
    if isinstance(main_entity, dict):
        main_entity = [main_entity]

    for q_node in main_entity:
        if not isinstance(q_node, dict):
            continue
        question = strip_html_text(q_node.get("name", "")).strip()
        answer_node = q_node.get("acceptedAnswer") or {}
        if isinstance(answer_node, list):
            answer_raw = "\n\n".join(
                str(a.get("text", "")) for a in answer_node
                if isinstance(a, dict)
            )
        elif isinstance(answer_node, dict):
            answer_raw = answer_node.get("text", "")
        else:
            answer_raw = ""
        answer = strip_html_text(answer_raw)
        if not question or not answer:
            continue
        page_content = f"Q: {question}\n\nA: {answer}"
        items.append(JsonLdItem(
            content_kind="faq",
            source_type="faq-jsonld",
            page_content=page_content,
            row_data={"question": question, "answer": answer},
            selector_name="faq",
        ))
    return items


def product_extractor(node: Dict[str, Any]) -> List[JsonLdItem]:
    """Extract Product data from a JSON-LD node.

    Args:
        node: Parsed JSON-LD dict with ``@type="Product"`` or similar.

    Returns:
        List with one ``JsonLdItem`` (empty list if ``name`` is absent).
    """
    name = _get_name(node)
    if not name:
        return []

    description = _get_description(node)

    # Offers
    offers = node.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = strip_html_text(offers.get("price", ""))
    currency = strip_html_text(offers.get("priceCurrency", ""))
    price_str = f"{price} {currency}".strip() if price else ""

    # Brand
    brand_node = node.get("brand") or {}
    brand = strip_html_text(
        brand_node.get("name", "") if isinstance(brand_node, dict) else brand_node
    )

    # Rating
    rating_node = node.get("aggregateRating") or {}
    rating = ""
    if isinstance(rating_node, dict):
        rv = strip_html_text(rating_node.get("ratingValue", ""))
        rc = strip_html_text(rating_node.get("reviewCount", ""))
        if rv:
            rating = f"{rv}/5" + (f" ({rc} reviews)" if rc else "")

    row_data: Dict[str, Any] = {
        "name": name,
        "description": description,
        "price": price_str,
        "brand": brand,
        "rating": rating,
    }

    parts = [f"# {name}"]
    if description:
        parts.append(f"\n{description}")
    if price_str:
        parts.append(f"\nPrice: {price_str}")
    if brand:
        parts.append(f"Brand: {brand}")
    if rating:
        parts.append(f"Rating: {rating}")

    return [JsonLdItem(
        content_kind="jsonld-product",
        source_type="product-jsonld",
        page_content="\n".join(parts),
        row_data=row_data,
        selector_name="product",
    )]


def event_extractor(node: Dict[str, Any]) -> List[JsonLdItem]:
    """Extract Event data from a JSON-LD node.

    Args:
        node: Parsed JSON-LD dict with ``@type="Event"``.

    Returns:
        List with one ``JsonLdItem`` (empty list if ``name`` is absent).
    """
    name = _get_name(node)
    if not name:
        return []

    description = _get_description(node)
    start_date = strip_html_text(node.get("startDate", ""))
    end_date = strip_html_text(node.get("endDate", ""))

    # Location
    location_node = node.get("location") or {}
    if isinstance(location_node, dict):
        location = strip_html_text(location_node.get("name", ""))
    else:
        location = strip_html_text(location_node)

    # Performer
    performer_node = node.get("performer") or {}
    if isinstance(performer_node, dict):
        performer = strip_html_text(performer_node.get("name", ""))
    elif isinstance(performer_node, list):
        performer = ", ".join(
            strip_html_text(p.get("name", "") if isinstance(p, dict) else p)
            for p in performer_node
        )
    else:
        performer = strip_html_text(performer_node)

    row_data: Dict[str, Any] = {
        "name": name,
        "description": description,
        "start_date": start_date,
        "end_date": end_date,
        "location": location,
        "performer": performer,
    }

    parts = [f"# {name}"]
    if description:
        parts.append(f"\n{description}")
    if start_date:
        parts.append(f"Start: {start_date}")
    if end_date:
        parts.append(f"End: {end_date}")
    if location:
        parts.append(f"Location: {location}")
    if performer:
        parts.append(f"Performer: {performer}")

    return [JsonLdItem(
        content_kind="jsonld-event",
        source_type="event-jsonld",
        page_content="\n".join(parts),
        row_data=row_data,
        selector_name="event",
    )]


def person_extractor(node: Dict[str, Any]) -> List[JsonLdItem]:
    """Extract Person data from a JSON-LD node.

    Args:
        node: Parsed JSON-LD dict with ``@type="Person"``.

    Returns:
        List with one ``JsonLdItem`` (empty list if ``name`` is absent).
    """
    name = _get_name(node)
    if not name:
        return []

    job_title = strip_html_text(node.get("jobTitle", ""))
    email = strip_html_text(node.get("email", ""))
    url = strip_html_text(node.get("url", ""))

    # Affiliation
    affiliation_node = node.get("affiliation") or {}
    if isinstance(affiliation_node, dict):
        affiliation = strip_html_text(affiliation_node.get("name", ""))
    else:
        affiliation = strip_html_text(affiliation_node)

    row_data: Dict[str, Any] = {
        "name": name,
        "job_title": job_title,
        "affiliation": affiliation,
        "email": email,
        "url": url,
    }

    parts = [f"# {name}"]
    if job_title:
        parts.append(f"Job Title: {job_title}")
    if affiliation:
        parts.append(f"Affiliation: {affiliation}")
    if email:
        parts.append(f"Email: {email}")
    if url:
        parts.append(f"URL: {url}")

    return [JsonLdItem(
        content_kind="jsonld-person",
        source_type="person-jsonld",
        page_content="\n".join(parts),
        row_data=row_data,
        selector_name="person",
    )]


def place_extractor(node: Dict[str, Any]) -> List[JsonLdItem]:
    """Extract Place / LocalBusiness data from a JSON-LD node.

    Args:
        node: Parsed JSON-LD dict with ``@type`` in
            ``{"Place", "LocalBusiness", "Restaurant"}``.

    Returns:
        List with one ``JsonLdItem`` (empty list if ``name`` is absent).
    """
    name = _get_name(node)
    if not name:
        return []

    description = _get_description(node)
    url = strip_html_text(node.get("url", ""))
    telephone = strip_html_text(node.get("telephone", ""))

    # Address
    address_node = node.get("address") or {}
    if isinstance(address_node, dict):
        street = strip_html_text(address_node.get("streetAddress", ""))
        city = strip_html_text(address_node.get("addressLocality", ""))
        state = strip_html_text(address_node.get("addressRegion", ""))
        postal = strip_html_text(address_node.get("postalCode", ""))
        country = strip_html_text(address_node.get("addressCountry", ""))
        address_parts = [p for p in [street, city, state, postal, country] if p]
        address = ", ".join(address_parts)
    else:
        address = strip_html_text(address_node)

    # Geo — coerce to str so dicts like {"@value": "37.77"} are handled safely;
    # use str(...) before strip_html_text to avoid falsy zero-coordinate values
    # (latitude=0 or longitude=0 are valid equator/prime-meridian coordinates).
    geo_node = node.get("geo") or {}
    geo = ""
    if isinstance(geo_node, dict):
        lat_raw = geo_node.get("latitude")
        lng_raw = geo_node.get("longitude")
        if lat_raw is not None and lng_raw is not None:
            lat = strip_html_text(str(lat_raw))
            lng = strip_html_text(str(lng_raw))
            if lat and lng:
                geo = f"{lat},{lng}"

    row_data: Dict[str, Any] = {
        "name": name,
        "description": description,
        "address": address,
        "geo": geo,
        "telephone": telephone,
        "url": url,
    }

    parts = [f"# {name}"]
    if description:
        parts.append(f"\n{description}")
    if address:
        parts.append(f"Address: {address}")
    if telephone:
        parts.append(f"Phone: {telephone}")
    if url:
        parts.append(f"URL: {url}")
    if geo:
        parts.append(f"Geo: {geo}")

    return [JsonLdItem(
        content_kind="jsonld-place",
        source_type="place-jsonld",
        page_content="\n".join(parts),
        row_data=row_data,
        selector_name="place",
    )]


def recipe_extractor(node: Dict[str, Any]) -> List[JsonLdItem]:
    """Extract Recipe data from a JSON-LD node.

    Args:
        node: Parsed JSON-LD dict with ``@type="Recipe"``.

    Returns:
        List with one ``JsonLdItem`` (empty list if ``name`` is absent).
    """
    name = _get_name(node)
    if not name:
        return []

    description = _get_description(node)
    cook_time = strip_html_text(node.get("cookTime", ""))
    prep_time = strip_html_text(node.get("prepTime", ""))
    total_time = strip_html_text(node.get("totalTime", ""))
    recipe_yield = strip_html_text(node.get("recipeYield", ""))

    # Ingredients
    ingredients_raw = node.get("recipeIngredient") or []
    if isinstance(ingredients_raw, str):
        ingredients_raw = [ingredients_raw]
    ingredients = [strip_html_text(i) for i in ingredients_raw if i]

    # Instructions
    instructions_raw = node.get("recipeInstructions") or []
    if isinstance(instructions_raw, str):
        instructions_raw = [instructions_raw]
    steps: List[str] = []
    for step in instructions_raw:
        if isinstance(step, dict):
            text = strip_html_text(step.get("text", step.get("name", "")))
        else:
            text = strip_html_text(step)
        if text:
            steps.append(text)

    row_data: Dict[str, Any] = {
        "name": name,
        "description": description,
        "cook_time": cook_time,
        "prep_time": prep_time,
        "total_time": total_time,
        "recipe_yield": recipe_yield,
        "ingredients": ingredients,
        "instructions": steps,
    }

    parts = [f"# {name}"]
    if description:
        parts.append(f"\n{description}")
    if total_time:
        parts.append(f"Total time: {total_time}")
    elif cook_time or prep_time:
        times = []
        if prep_time:
            times.append(f"Prep: {prep_time}")
        if cook_time:
            times.append(f"Cook: {cook_time}")
        parts.append(" | ".join(times))
    if recipe_yield:
        parts.append(f"Yield: {recipe_yield}")
    if ingredients:
        parts.append("\n## Ingredients")
        parts.extend(f"- {ing}" for ing in ingredients)
    if steps:
        parts.append("\n## Instructions")
        for i, step_text in enumerate(steps, 1):
            parts.append(f"{i}. {step_text}")

    return [JsonLdItem(
        content_kind="jsonld-recipe",
        source_type="recipe-jsonld",
        page_content="\n".join(parts),
        row_data=row_data,
        selector_name="recipe",
    )]


def article_extractor(node: Dict[str, Any]) -> List[JsonLdItem]:
    """Extract Article / NewsArticle / BlogPosting data from a JSON-LD node.

    Args:
        node: Parsed JSON-LD dict with ``@type`` in
            ``{"Article", "NewsArticle", "BlogPosting"}``.

    Returns:
        List with one ``JsonLdItem`` (empty list if neither ``headline``
        nor ``name`` is present).
    """
    headline = strip_html_text(node.get("headline", "") or node.get("name", ""))
    if not headline:
        return []

    description = _get_description(node)
    date_published = strip_html_text(node.get("datePublished", ""))
    date_modified = strip_html_text(node.get("dateModified", ""))

    # Author
    author_node = node.get("author") or {}
    if isinstance(author_node, dict):
        author = strip_html_text(author_node.get("name", ""))
    elif isinstance(author_node, list):
        author = ", ".join(
            strip_html_text(a.get("name", "") if isinstance(a, dict) else a)
            for a in author_node
        )
    else:
        author = strip_html_text(author_node)

    # Publisher
    publisher_node = node.get("publisher") or {}
    if isinstance(publisher_node, dict):
        publisher = strip_html_text(publisher_node.get("name", ""))
    else:
        publisher = strip_html_text(publisher_node)

    body = strip_html_text(node.get("articleBody", ""))

    row_data: Dict[str, Any] = {
        "headline": headline,
        "description": description,
        "author": author,
        "publisher": publisher,
        "date_published": date_published,
        "date_modified": date_modified,
        "body": body,
    }

    parts = [f"# {headline}"]
    if description:
        parts.append(f"\n{description}")
    if author:
        parts.append(f"Author: {author}")
    if publisher:
        parts.append(f"Publisher: {publisher}")
    if date_published:
        parts.append(f"Published: {date_published}")
    if body:
        parts.append(f"\n{body}")

    return [JsonLdItem(
        content_kind="jsonld-article",
        source_type="article-jsonld",
        page_content="\n".join(parts),
        row_data=row_data,
        selector_name="article",
    )]


def organization_extractor(node: Dict[str, Any]) -> List[JsonLdItem]:
    """Extract Organization data from a JSON-LD node.

    Args:
        node: Parsed JSON-LD dict with ``@type="Organization"``.

    Returns:
        List with one ``JsonLdItem`` (empty list if ``name`` is absent).
    """
    name = _get_name(node)
    if not name:
        return []

    description = _get_description(node)
    url = strip_html_text(node.get("url", ""))
    email = strip_html_text(node.get("email", ""))
    telephone = strip_html_text(node.get("telephone", ""))

    # Address
    address_node = node.get("address") or {}
    if isinstance(address_node, dict):
        street = strip_html_text(address_node.get("streetAddress", ""))
        city = strip_html_text(address_node.get("addressLocality", ""))
        country = strip_html_text(address_node.get("addressCountry", ""))
        address_parts = [p for p in [street, city, country] if p]
        address = ", ".join(address_parts)
    else:
        address = strip_html_text(address_node)

    row_data: Dict[str, Any] = {
        "name": name,
        "description": description,
        "url": url,
        "email": email,
        "telephone": telephone,
        "address": address,
    }

    parts = [f"# {name}"]
    if description:
        parts.append(f"\n{description}")
    if url:
        parts.append(f"URL: {url}")
    if email:
        parts.append(f"Email: {email}")
    if telephone:
        parts.append(f"Phone: {telephone}")
    if address:
        parts.append(f"Address: {address}")

    return [JsonLdItem(
        content_kind="jsonld-organization",
        source_type="organization-jsonld",
        page_content="\n".join(parts),
        row_data=row_data,
        selector_name="organization",
    )]


def howto_extractor(node: Dict[str, Any]) -> List[JsonLdItem]:
    """Extract HowTo data from a JSON-LD node.

    Args:
        node: Parsed JSON-LD dict with ``@type="HowTo"``.

    Returns:
        List with one ``JsonLdItem`` (empty list if ``name`` is absent).
    """
    name = _get_name(node)
    if not name:
        return []

    description = _get_description(node)
    total_time = strip_html_text(node.get("totalTime", ""))

    # Steps
    steps_raw = node.get("step") or []
    if isinstance(steps_raw, dict):
        steps_raw = [steps_raw]
    steps: List[str] = []
    for step in steps_raw:
        if isinstance(step, dict):
            text = strip_html_text(step.get("text", step.get("name", "")))
        else:
            text = strip_html_text(step)
        if text:
            steps.append(text)

    row_data: Dict[str, Any] = {
        "name": name,
        "description": description,
        "total_time": total_time,
        "steps": steps,
    }

    parts = [f"# {name}"]
    if description:
        parts.append(f"\n{description}")
    if total_time:
        parts.append(f"Time: {total_time}")
    if steps:
        parts.append("\n## Steps")
        for i, step_text in enumerate(steps, 1):
            parts.append(f"{i}. {step_text}")

    return [JsonLdItem(
        content_kind="jsonld-howto",
        source_type="howto-jsonld",
        page_content="\n".join(parts),
        row_data=row_data,
        selector_name="howto",
    )]


def breadcrumb_extractor(node: Dict[str, Any]) -> List[JsonLdItem]:
    """Extract BreadcrumbList data from a JSON-LD node.

    Emits ONE item with the full breadcrumb path as ``page_content``
    (e.g. ``"Home > Products > Widget Pro"``).

    Args:
        node: Parsed JSON-LD dict with ``@type="BreadcrumbList"``.

    Returns:
        List with one ``JsonLdItem`` (empty list if no crumbs found).
    """
    items_raw = node.get("itemListElement") or []
    if isinstance(items_raw, dict):
        items_raw = [items_raw]

    # Sort by position, fall back to order of appearance
    crumbs = []
    for item in items_raw:
        if not isinstance(item, dict):
            continue
        crumb_name = strip_html_text(item.get("name", "") or item.get("item", {}).get("name", ""))
        if crumb_name:
            # Coerce position to int to guarantee numeric sort (real-world JSON-LD
            # sometimes encodes position as a string, e.g. "3" instead of 3,
            # which would cause lexicographic ordering for 10+ item lists).
            try:
                position = int(item.get("position", len(crumbs) + 1))
            except (TypeError, ValueError):
                position = len(crumbs) + 1
            crumbs.append((position, crumb_name))

    if not crumbs:
        return []

    crumbs.sort(key=lambda x: x[0])
    path = " > ".join(name for _, name in crumbs)

    row_data: Dict[str, Any] = {
        "path": path,
        "crumbs": [name for _, name in crumbs],
    }

    return [JsonLdItem(
        content_kind="jsonld-breadcrumb",
        source_type="breadcrumb-jsonld",
        page_content=path,
        row_data=row_data,
        selector_name="breadcrumb",
    )]


def question_extractor(node: Dict[str, Any]) -> List[JsonLdItem]:
    """Extract a bare top-level ``Question`` node.

    The JSON-LD spec permits a ``@type="Question"`` node to appear at the
    top level of a block (i.e. not nested inside a ``FAQPage.mainEntity``).
    This extractor preserves backward compatibility with the legacy
    ``_iter_faqpage_pairs`` behaviour that handled this case explicitly.

    Produces one ``JsonLdItem`` with the same ``content_kind="faq"`` and
    ``source_type="faq-jsonld"`` as :func:`faq_extractor` so downstream
    consumers see a uniform FAQ item regardless of nesting shape.

    Args:
        node: Parsed JSON-LD dict with ``@type="Question"``.

    Returns:
        List with one ``JsonLdItem`` (empty list if question or answer is
        absent or blank).
    """
    question = strip_html_text(node.get("name", "")).strip()
    answer_node = node.get("acceptedAnswer") or {}
    if isinstance(answer_node, list):
        answer_raw = "\n\n".join(
            str(a.get("text", "")) for a in answer_node
            if isinstance(a, dict)
        )
    elif isinstance(answer_node, dict):
        answer_raw = answer_node.get("text", "")
    else:
        answer_raw = ""
    answer = strip_html_text(answer_raw)
    if not question or not answer:
        return []
    return [JsonLdItem(
        content_kind="faq",
        source_type="faq-jsonld",
        page_content=f"Q: {question}\n\nA: {answer}",
        row_data={"question": question, "answer": answer},
        selector_name="faq",
    )]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: Maps JSON-LD ``@type`` strings (including aliases) to extractor callables.
#:
#: **Declaration order matters**: when a node carries multiple ``@type`` values
#: (a valid JSON-LD construct), the first matching key in this dict wins.
#: Aliases map to the same function as their canonical type:
#:
#: - ``"IndividualProduct"`` → :func:`product_extractor`
#: - ``"LocalBusiness"`` / ``"Restaurant"`` → :func:`place_extractor`
#: - ``"NewsArticle"`` / ``"BlogPosting"`` → :func:`article_extractor`
#: - ``"Question"`` → :func:`question_extractor` (bare top-level Question node)
#:
#: Note: ``jsonld_types`` filtering in ``WebScrapingLoader`` matches against
#: these exact key strings.  Alias types must be listed explicitly when
#: filtering — e.g. ``jsonld_types=["Product", "IndividualProduct"]``.
EXTRACTOR_REGISTRY: Dict[str, Callable[[Dict[str, Any]], List[JsonLdItem]]] = {
    "FAQPage": faq_extractor,
    "Question": question_extractor,
    "Product": product_extractor,
    "IndividualProduct": product_extractor,
    "Event": event_extractor,
    "Person": person_extractor,
    "Place": place_extractor,
    "LocalBusiness": place_extractor,
    "Restaurant": place_extractor,
    "Recipe": recipe_extractor,
    "Article": article_extractor,
    "NewsArticle": article_extractor,
    "BlogPosting": article_extractor,
    "Organization": organization_extractor,
    "HowTo": howto_extractor,
    "BreadcrumbList": breadcrumb_extractor,
}
