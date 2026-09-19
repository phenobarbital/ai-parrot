"""Live end-to-end sample: WebBrowsingToolkit + JevClient on Best Buy.

1. ``WebBrowsingToolkit`` registers ``bestbuy.com`` in a local action
   catalog, saves a parameterized ``search-products`` script (BrowserAction
   DSL) and replays it deterministically: open the home page, search for
   "Epson Inks", scroll so the lazy product grid hydrates, and extract the
   result cards as rows (title, URL, price, savings, rating).
2. The first 5 results are handed to ``JevClient`` (TypeSafe System One).
   Jev is not a text generator and has no tool-calling loop — so it does not
   drive the browser. Instead each scraped product becomes Jev *state*, and
   a Pydantic model is translated into typed questions (choice / noul /
   score) that come back with calibrated probabilities.

Requirements:
    - ``JEV_API_KEY`` in ``env/.env`` (read through ``navconfig.config``).
    - ai-parrot-client-jev, ai-parrot-tools and ai-parrot-server installed,
      plus Playwright (only its client is used — no bundled browser needed).
    - The Obscura headless browser (https://github.com/h4ckf0r0day/obscura)
      instead of Chrome. The script spawns ``obscura serve --stealth`` and
      Playwright drives it over CDP (``driver_type="obscura"``). Settings:

        * ``OBSCURA_BINARY`` — binary path or ``PATH`` name (default ``obscura``).
        * ``OBSCURA_PORT`` — CDP port (default ``9222``).
        * ``OBSCURA_ATTACH=true`` — reuse an Obscura you already run (e.g.
          ``docker run -d -p 127.0.0.1:9222:9222 h4ckf0r0day/obscura``)
          instead of spawning one; it is left running on exit.

Usage::

    python examples/clients/jev_bestbuy_live.py
    python examples/clients/jev_bestbuy_live.py "epson 522 ink"
"""
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal

from navconfig import config
from pydantic import BaseModel, Field

from parrot.clients.jev import JevClient
from parrot.mcp.obscura import ObscuraProcessConfig, ObscuraProcessManager
from parrot_tools.browsing import WebBrowsingToolkit

CATALOG_DIR = Path(__file__).parent / "bestbuy_catalog"
SITE = "bestbuy"
TOP_N = 5

#: Result cards on the search page (verified live 2026-09-18). Only the
#: first few cards are hydrated on load; the rest render as the grid
#: scrolls into view, hence the scroll steps before extraction.
SEARCH_STEPS: List[Dict[str, Any]] = [
    {"action": "navigate", "url": "https://www.bestbuy.com/?intl=nosplash"},
    {
        "action": "wait",
        "condition": "textarea#autocomplete-search-bar",
        "condition_type": "selector",
        "timeout": 30,
    },
    {
        "action": "fill",
        "selector": "textarea#autocomplete-search-bar",
        "value": "{{query}}",
        "press_enter": True,
    },
    {
        "action": "wait",
        "condition": "li.product-list-item a.product-list-item-link",
        "condition_type": "selector",
        "timeout": 30,
    },
    {"action": "scroll", "direction": "down", "amount": 1500},
    {"action": "scroll", "direction": "down", "amount": 1500},
    {"action": "wait", "condition_type": "simple", "timeout": 2},
    {
        "action": "extract",
        "selector": "li.product-list-item",
        "multiple": True,
        "extract_name": "products",
        "fields": {
            "title": {"selector": "h3.product-title", "attribute": "title"},
            "url": {"selector": "a.product-list-item-link", "attribute": "href"},
            "price": {"selector": "[data-testid='price-block-customer-price'] span.sr-only"},
            "savings": {"selector": "[data-testid='price-block-total-savings-text']"},
            "rating": {"selector": ".c-ratings-reviews p.visually-hidden"},
        },
    },
]


class InkAssessment(BaseModel):
    """Typed questions Jev answers about one scraped product card."""

    ink_format: Literal["bottle", "cartridge", "printer", "other"] = Field(
        description="What kind of product this listing sells.",
        json_schema_extra={
            "criteria": {
                "bottle": "EcoTank-style refill ink bottles",
                "cartridge": "Ink cartridges for inkjet printers",
                "printer": "A printer or all-in-one device, not a consumable",
                "other": "Paper, accessories or anything else",
            }
        },
    )
    multipack: bool = Field(description="The listing bundles several inks or colors in one pack.")
    genuine_epson: bool = Field(description="The product is genuine Epson-branded ink, not third-party compatible.")
    deal_quality: int = Field(
        description="How good a deal the listing looks, judged from its price and savings.",
        json_schema_extra={
            "criteria": [
                "No discount shown",
                "Small discount (under 10%)",
                "Solid discount (10-25%)",
                "Big discount (over 25%)",
            ]
        },
    )


async def scrape_top_results(query: str) -> List[Dict[str, Any]]:
    """Search Best Buy through a catalogued WebBrowsingToolkit action.

    Args:
        query: Search text typed into the Best Buy search bar.

    Returns:
        The first ``TOP_N`` product rows that carry a title.
    """
    async with ObscuraProcessManager(
        ObscuraProcessConfig(
            binary_path=config.get("OBSCURA_BINARY", fallback="obscura"),
            port=int(config.get("OBSCURA_PORT", fallback=9222)),
            stealth=True,  # anti-fingerprinting: Best Buy blocks plain headless browsers
            attach_only=config.getboolean("OBSCURA_ATTACH", fallback=False),
        )
    ) as obscura:
        toolkit = WebBrowsingToolkit(
            catalog_dir=CATALOG_DIR,
            driver_type="obscura",
            cdp_endpoint_url=obscura.endpoint,
            confirm_runs=False,  # read-only public search, no HITL needed
            default_timeout=30,
        )
        try:
            await toolkit.register_site(
                base_url="https://www.bestbuy.com",
                name=SITE,
                title="Best Buy",
                aliases=["best buy", "bestbuy.com"],
            )
            await toolkit.save_site_action(
                site=SITE,
                name="search-products",
                description="Search the Best Buy catalog and extract the result cards",
                params={"query": {"description": "Text to search for"}},
                steps=SEARCH_STEPS,
                source="user",
                overwrite=True,
            )
            run = await toolkit.run_site_action(SITE, "search-products", params={"query": query})
        finally:
            await toolkit.close_browser()

    if not run["success"]:
        errors = [step["error"] for step in run["executed"] if step.get("error")]
        raise RuntimeError(f"Best Buy search failed: {errors}")
    rows = run["extracted_data"].get("products") or []
    return [row for row in rows if row.get("title")][:TOP_N]


async def assess(client: JevClient, product: Dict[str, Any]) -> Dict[str, Any]:
    """Ask Jev the ``InkAssessment`` questions about one product.

    Args:
        client: A configured ``JevClient``.
        product: One scraped product row (used verbatim as Jev state).

    Returns:
        The product row merged with Jev's typed answers.
    """
    result = await client.invoke("", output_type=InkAssessment, state=product)
    assessment: InkAssessment = result.output
    return {**product, **assessment.model_dump()}


async def main() -> None:
    query = " ".join(sys.argv[1:]) or "Epson Inks"
    api_key = config.get("JEV_API_KEY")
    if not api_key:
        raise SystemExit("JEV_API_KEY is not set (env/.env or environment)")

    print(f"Searching Best Buy for {query!r} ...")
    products = await scrape_top_results(query)
    if not products:
        raise SystemExit("No products were extracted — the page layout may have changed.")
    print(f"Extracted {len(products)} products, asking Jev ...\n")

    client = JevClient(api_key=api_key)
    try:
        results = await asyncio.gather(*(assess(client, product) for product in products))
    finally:
        await client.close()

    for idx, item in enumerate(results, start=1):
        print(f"{idx}. {item['title']}")
        print(f"   price: {item.get('price') or '-'}  {item.get('savings') or ''}")
        print(f"   rating: {item.get('rating') or '-'}")
        print(
            f"   jev: format={item['ink_format']} multipack={item['multipack']} "
            f"genuine_epson={item['genuine_epson']} deal_quality={item['deal_quality']}/3"
        )
        print(f"   {item.get('url')}\n")

    out = Path(__file__).parent / "jev_bestbuy_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Saved {out}")


if __name__ == "__main__":
    asyncio.run(main())
