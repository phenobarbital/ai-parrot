"""Scrape https://www.odoo.com/documentation/19.0/ into bookstore-ready Markdown.

The site is a static Sphinx build: every page has ``<article id="o_content">``
with nested ``<section>`` blocks and h1..h6 headings, so no browser is needed
— plain aiohttp + markdownify. Pages are grouped into one "book" per
sub-section (``developer/reference/backend``, ``developer/tutorials``,
``applications/sales`` ...), each page becoming a ``##`` chapter whose own
headings are demoted one level. Hash comments inside code blocks are rewritten
``# x`` -> ``#: x`` because the PageIndex Markdown parser is not fence-aware.

Usage::

    python agents/odoo_hd/scrape_odoo_docs.py --section developer \\
        --out agents/odoo_hd/library_sources/odoo-docs [--max-pages 80] [--concurrency 4]
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urldefrag

import aiohttp
from bs4 import BeautifulSoup
from markdownify import markdownify

BASE = "https://www.odoo.com/documentation/19.0/"
LANG = {
    "python": "python",
    "xml": "xml",
    "javascript": "javascript",
    "js": "javascript",
    "css": "css",
    "scss": "scss",
    "console": "bash",
    "bash": "bash",
    "sh": "bash",
    "shell": "bash",
    "text": "text",
    "html": "html",
    "json": "json",
    "ini": "ini",
    "sql": "sql",
    "yaml": "yaml",
    "default": "",
    "none": "",
}


def neutralize_hash_comments(code: str) -> str:
    """``# comment`` -> ``#: comment`` (PageIndex would read it as a heading)."""
    return re.sub(r"^([ \t]*#+)([ \t]+)", r"\1:\2", code, flags=re.M)


def demote(md: str, levels: int) -> str:
    return re.sub(r"^(#{1,6})(?=\s)", lambda m: "#" * min(6, len(m.group(1)) + levels), md, flags=re.M)


def _fence_code_blocks(article: BeautifulSoup) -> None:
    """Replace Sphinx ``div.highlight-<lang> > pre`` with fenced Markdown blocks."""
    for div in article.select("div[class*=highlight-]"):
        pre = div.find("pre")
        if pre is None:
            continue
        lang = next((c.split("highlight-", 1)[1] for c in div.get("class", []) if c.startswith("highlight-")), "")
        code = neutralize_hash_comments(pre.get_text().rstrip("\n"))
        div.replace_with(f"\n\n```{LANG.get(lang, lang)}\n{code}\n```\n\n")


def page_to_markdown(html: str, url: str) -> tuple[str, str]:
    """Return ``(title, markdown)`` for one documentation page."""
    soup = BeautifulSoup(html, "lxml")
    article = soup.select_one("article#o_content") or soup.body
    if article is None:  # redirect stubs / non-HTML answers carry no body
        return url.rsplit("/", 1)[-1], ""
    for sel in (
        "nav",
        "header",
        "footer",
        "script",
        "style",
        ".o_page_toc",
        "#o_side_toc",
        ".headerlink",
        "a.headerlink",
        "form",
        ".o_content_footer",
        ".o_feedback",
        "#o_feedback",
    ):
        for node in article.select(sel):
            node.decompose()
    for a in article.select('a[href*="github.com/odoo/documentation/edit"]'):
        a.decompose()
    _fence_code_blocks(article)
    for a in article.select("a[href]"):  # relative links -> absolute, so citations stay usable
        a["href"] = urljoin(url, a["href"])
    h1 = article.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else url.rsplit("/", 1)[-1]
    md = markdownify(str(article), heading_style="ATX", bullets="-", strip=["img"])
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return title, md


def section_links(index_html: str, section: str) -> list[str]:
    """Every ``<section>/…html`` link on the index page, in document order, deduplicated."""
    soup = BeautifulSoup(index_html, "lxml")
    seen: dict[str, None] = {}
    for a in soup.select("a[href]"):
        href = urldefrag(urljoin(BASE, a["href"].strip()))[0]
        if href.startswith(BASE + section + "/") and href.endswith(".html"):
            seen.setdefault(href, None)
    return list(seen)


def book_key(url: str) -> str:
    """``developer/reference/backend/orm.html`` -> ``developer/reference/backend``."""
    rel = url[len(BASE) :].rsplit(".html", 1)[0]
    parts = rel.split("/")
    depth = 3 if parts[0] == "developer" else 2
    return "/".join(parts[:depth]) if len(parts) > depth else "/".join(parts[:-1]) or parts[0]


async def fetch(session: aiohttp.ClientSession, url: str, sem: asyncio.Semaphore) -> tuple[str, str]:
    async with sem:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return url, await resp.text()


async def run(section: str, out: Path, max_pages: int | None, concurrency: int) -> int:
    await asyncio.to_thread(out.mkdir, parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    timeout = aiohttp.ClientTimeout(total=60)
    headers = {"User-Agent": "ai-parrot-odoo-docs/1.0 (+https://github.com/phenobarbital/ai-parrot)"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        _, index_html = await fetch(session, BASE, sem)
        urls = section_links(index_html, section)
        if max_pages:
            urls = urls[:max_pages]
        print(f"{section}: {len(urls)} pages", file=sys.stderr)
        results = await asyncio.gather(*(fetch(session, u, sem) for u in urls), return_exceptions=True)
    books: dict[str, list[str]] = {}
    failed = 0
    for url, res in zip(urls, results, strict=True):
        if isinstance(res, BaseException):
            failed += 1
            print(f"FAILED {url}: {res}", file=sys.stderr)
            continue
        title, md = page_to_markdown(res[1], url)
        if not md:
            print(f"EMPTY {url}", file=sys.stderr)
            continue
        body = demote(re.sub(r"^# .*\n?", "", md, count=1, flags=re.M), 1)
        books.setdefault(book_key(url), []).append(f"## {title}\n\nSource: {url}\n\n{body}\n")
    for key, chapters in books.items():
        name = key.replace("/", "-")
        head = (
            f"# Odoo 19 documentation — {key.replace('/', ' / ')}\n\n"
            f"Scraped from {BASE}{key}/ ({len(chapters)} pages). Each section below is one page of the official docs.\n\n"
        )
        path = out / f"odoo19-docs-{name}.md"
        path.write_text(head + "\n".join(chapters), encoding="utf-8")
        print(f"{path.name}: {len(chapters)} pages, {path.stat().st_size // 1024} KB")
    print(f"books: {len(books)}, pages: {len(urls) - failed}, failed: {failed}", file=sys.stderr)
    return failed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--section", default="developer", choices=["developer", "applications", "administration", "contributing"]
    )
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "library_sources" / "odoo-docs")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()
    return 1 if asyncio.run(run(args.section, args.out, args.max_pages, args.concurrency)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
