"""Offline, deterministic demo of the WebBrowsingToolkit catalog.

Serves a minimal local replica of quotes.toscrape.com (same DOM structure
and selectors: login form with #username/#password, div.quote rows, tag
pages, the Top-Ten-tags sidebar) and runs the SAME catalogued scripts as
``seed_catalog.py`` against it — no network and no LLM required, so it
doubles as an end-to-end smoke test of the catalog.

Usage::

    python examples/webbrowsing/local_demo.py
"""
import asyncio
import json
import tempfile

from aiohttp import web

from parrot_tools.browsing import WebBrowsingToolkit

from seed_catalog import seed_catalog

QUOTES = [
    {
        "text": "“It is our choices that show what we truly are.”",
        "author": "J.K. Rowling",
        "tags": ["choices", "life"],
    },
    {
        "text": "“Try not to become a man of success, but a man of value.”",
        "author": "Albert Einstein",
        "tags": ["success", "value", "life"],
    },
]

TOP_TAGS = ["love", "inspirational", "life", "humor", "books"]


def _quote_divs(quotes: list[dict]) -> str:
    blocks = []
    for q in quotes:
        tags = "".join(
            f'<a class="tag" href="/tag/{t}/">{t}</a>' for t in q["tags"]
        )
        blocks.append(
            f'<div class="quote"><span class="text">{q["text"]}</span>'
            f'<small class="author">{q["author"]}</small>'
            f'<div class="tags">{tags}</div></div>'
        )
    return "".join(blocks)


def _page(body: str, logged_in: bool) -> str:
    session = (
        '<a href="/logout">Logout</a>' if logged_in else '<a href="/login">Login</a>'
    )
    sidebar = "".join(
        f'<span class="tag-item"><a class="tag" href="/tag/{t}/">{t}</a></span>'
        for t in TOP_TAGS
    )
    return (
        f"<html><body><header>{session}</header>{body}"
        f"<aside>{sidebar}</aside></body></html>"
    )


LOGIN_FORM = """
<form action="/login-submit" method="get">
  <input id="username" name="username"/>
  <input id="password" name="password"/>
  <input type="submit" value="Login"/>
</form>
"""


def build_app() -> web.Application:
    """Build the offline replica of quotes.toscrape.com."""
    state = {"logged_in": False}

    async def home(_request: web.Request) -> web.Response:
        return web.Response(
            text=_page(_quote_divs(QUOTES), state["logged_in"]),
            content_type="text/html",
        )

    async def login(_request: web.Request) -> web.Response:
        return web.Response(
            text=_page(LOGIN_FORM, state["logged_in"]),
            content_type="text/html",
        )

    async def login_submit(_request: web.Request) -> web.Response:
        state["logged_in"] = True
        raise web.HTTPFound("/")

    async def tag(request: web.Request) -> web.Response:
        name = request.match_info["tag"]
        rows = [q for q in QUOTES if name in q["tags"]]
        return web.Response(
            text=_page(_quote_divs(rows), state["logged_in"]),
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", home)
    app.router.add_get("/login", login)
    app.router.add_get("/login-submit", login_submit)
    app.router.add_get("/tag/{tag}/", tag)
    return app


async def main() -> None:
    runner = web.AppRunner(build_app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8974)
    await site.start()

    with tempfile.TemporaryDirectory(prefix="browsing_demo_") as catalog_dir:
        toolkit = WebBrowsingToolkit(
            catalog_dir=catalog_dir,
            driver_type="playwright",
            browser="chrome",
            headless=True,
            delay_between_actions=0.0,
            confirm_runs=False,
        )
        try:
            # Same scripts as the live catalog, pointed at the replica.
            slug = await seed_catalog(
                toolkit, base_url="http://127.0.0.1:8974", aliases=["demo"]
            )
            print(f"Catalog seeded for site '{slug}'. Running flows...\n")

            # "inicia sesión y dime qué citas hay" -> one composite action
            result = await toolkit.run_site_action("quotes", "login-and-list")
            print("login-and-list:")
            print(json.dumps(result["extracted_data"], indent=2, ensure_ascii=False))
            assert result["success"], result
            assert [e["action"] for e in result["executed"]] == [
                "login", "list-quotes",
            ]

            # "citas del tag life" -> parameterized action; login NOT re-run
            # (already satisfied in... a new sequence, so it IS injected only
            # if the action requires it — quotes-by-tag does not).
            result = await toolkit.run_site_action(
                "quotes", "quotes-by-tag", params={"tag": "life"}
            )
            print("\nquotes-by-tag(tag=life):")
            print(json.dumps(result["extracted_data"], indent=2, ensure_ascii=False))
            assert result["success"], result
            assert len(result["extracted_data"]["quotes"]) == 2

            # Multi-step plan on one browser session
            result = await toolkit.run_site_sequence(
                "quotes", plan=["top-tags", {"action": "quotes-by-tag",
                                             "params": {"tag": "success"}}],
            )
            print("\nsequence [top-tags, quotes-by-tag(success)]:")
            print(json.dumps(result["extracted_data"], indent=2, ensure_ascii=False))
            assert result["success"], result
            assert result["extracted_data"]["top_tags"] == TOP_TAGS

            print("\nDemo OK — catalog scripts executed deterministically.")
        finally:
            await toolkit.close_browser()
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
