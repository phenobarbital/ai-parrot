"""Seed a WebBrowsingToolkit action catalog for quotes.toscrape.com.

quotes.toscrape.com is a public, purpose-built scraping sandbox: it has a
login form (any username/password is accepted), quote listings, tag pages
and author pages — stable selectors, perfect for a catalog demo.

Run directly to (re)generate the pre-built catalog shipped next to this
file (``examples/webbrowsing/catalog/``)::

    python examples/webbrowsing/seed_catalog.py

The ``seed_catalog()`` coroutine is also importable with a different
``base_url`` — ``local_demo.py`` uses it to run the SAME scripts against
an offline replica of the site.
"""
import asyncio
from pathlib import Path

from parrot_tools.browsing import WebBrowsingToolkit

CATALOG_DIR = Path(__file__).parent / "catalog"
LIVE_BASE_URL = "https://quotes.toscrape.com"

#: Row extraction shared by every quote-listing action.
QUOTE_FIELDS = {
    "text": {"selector": "span.text"},
    "author": {"selector": "small.author"},
    "tags": {"selector": "div.tags a.tag", "multiple": True},
}


async def seed_catalog(
    toolkit: WebBrowsingToolkit,
    base_url: str = LIVE_BASE_URL,
    *,
    aliases: list[str] | None = None,
) -> str:
    """Register the site and its catalogued actions on *toolkit*.

    Args:
        toolkit: The toolkit whose catalog receives the scripts.
        base_url: Site root — the live sandbox by default; ``local_demo``
            passes a localhost replica instead.
        aliases: Extra natural-language aliases for the site.

    Returns:
        The registered site slug.
    """
    site = await toolkit.register_site(
        base_url=base_url,
        title="Quotes to Scrape",
        description=(
            "Sandbox site with famous quotes, tags, authors and a demo "
            "login (any credentials are accepted)."
        ),
        aliases=["quotes", "toscrape", *(aliases or [])],
    )
    slug = site["site"]

    # ── login (operation) ─────────────────────────────────────────────
    # The sandbox accepts ANY username/password, so harmless defaults are
    # provided. For a real site, use an `authenticate` step with
    # credential_provider — save_site_action refuses literal passwords.
    await toolkit.save_site_action(
        site=slug,
        name="login",
        title="Iniciar sesión",
        description=(
            "Log in to Quotes to Scrape. The demo accepts any "
            "username/password combination."
        ),
        params={
            "username": {
                "description": "Username for the login form",
                "default": "parrot",
            },
            "password": {
                "description": "Password for the login form",
                "default": "parrot",
            },
        },
        steps=[
            {"action": "navigate", "url": f"{base_url}/login"},
            {"action": "fill", "selector": "#username", "value": "{{username}}"},
            {"action": "fill", "selector": "#password", "value": "{{password}}"},
            {
                "action": "click",
                "selector": 'input[type="submit"]',
                "wait_after_click": 'a[href="/logout"]',
                "wait_timeout": 10,
            },
        ],
        overwrite=True,
    )

    # ── list-quotes (operation) ───────────────────────────────────────
    await toolkit.save_site_action(
        site=slug,
        name="list-quotes",
        title="Listar citas",
        description=(
            "Open the home page and extract every quote on it: text, "
            "author and tags."
        ),
        steps=[
            {"action": "navigate", "url": f"{base_url}/"},
            {
                "action": "extract",
                "selector": "div.quote",
                "multiple": True,
                "extract_name": "quotes",
                "fields": QUOTE_FIELDS,
            },
        ],
        overwrite=True,
    )

    # ── quotes-by-tag (operation, parameterized) ──────────────────────
    await toolkit.save_site_action(
        site=slug,
        name="quotes-by-tag",
        title="Citas por etiqueta",
        description=(
            "Open the listing for one tag (e.g. 'love', 'inspirational', "
            "'life') and extract its quotes."
        ),
        params={
            "tag": {
                "description": "Tag slug to browse",
                "example": "love",
            }
        },
        steps=[
            {"action": "navigate", "url": f"{base_url}/tag/{{{{tag}}}}/"},
            {
                "action": "extract",
                "selector": "div.quote",
                "multiple": True,
                "extract_name": "quotes",
                "fields": QUOTE_FIELDS,
            },
        ],
        overwrite=True,
    )

    # ── top-tags (operation) ──────────────────────────────────────────
    await toolkit.save_site_action(
        site=slug,
        name="top-tags",
        title="Etiquetas populares",
        description="Read the 'Top Ten tags' sidebar from the home page.",
        steps=[
            {"action": "navigate", "url": f"{base_url}/"},
            {
                "action": "extract",
                "selector": "span.tag-item a.tag",
                "extract_type": "text",
                "multiple": True,
                "extract_name": "top_tags",
            },
        ],
        overwrite=True,
    )

    # ── author-info (operation, parameterized) ────────────────────────
    await toolkit.save_site_action(
        site=slug,
        name="author-info",
        title="Ficha de autor",
        description=(
            "Open an author page and extract name, birth date and bio. "
            "The author parameter is the URL slug, e.g. 'Albert-Einstein'."
        ),
        params={
            "author": {
                "description": "Author URL slug",
                "example": "Albert-Einstein",
            }
        },
        steps=[
            {"action": "navigate", "url": f"{base_url}/author/{{{{author}}}}/"},
            {
                "action": "extract",
                "selector": "div.author-details",
                "extract_name": "author",
                "fields": {
                    "name": {"selector": "h3.author-title"},
                    "born": {"selector": "span.author-born-date"},
                    "description": {"selector": "div.author-description"},
                },
            },
        ],
        overwrite=True,
    )

    # ── login-and-list (composite with prerequisite) ──────────────────
    await toolkit.save_site_action(
        site=slug,
        name="login-and-list",
        title="Sesión + listado",
        description=(
            "Full flow: make sure we are logged in, then list the quotes "
            "on the home page. 'login' is injected as a prerequisite and "
            "runs at most once per sequence."
        ),
        kind="composite",
        requires=["login"],
        compose=[{"action": "list-quotes"}],
        params={
            "username": {
                "description": "Forwarded to the login prerequisite",
                "default": "parrot",
            },
            "password": {
                "description": "Forwarded to the login prerequisite",
                "default": "parrot",
            },
        },
        overwrite=True,
    )

    return slug


async def main() -> None:
    """Regenerate the pre-built catalog shipped with this example."""
    toolkit = WebBrowsingToolkit(catalog_dir=CATALOG_DIR)
    slug = await seed_catalog(toolkit)
    actions = await toolkit.list_site_actions(slug)
    print(f"Catalog seeded at {CATALOG_DIR}/{slug}:")
    for action in actions:
        print(f"  - {action['name']:<15} [{action['kind']}] {action['title']}")


if __name__ == "__main__":
    asyncio.run(main())
