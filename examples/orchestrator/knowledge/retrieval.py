"""Retrieval tools backed by PageIndex and FAISS, with safe fallbacks.

The orchestrator example aims to be runnable as-is, while still
demonstrating the real PageIndex + Vector-store wiring AI-Parrot offers.
Both tools below try the real backend first and degrade gracefully to a
substring scan over the markdown sources when the index is not present.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Optional

from parrot.tools import tool


_LOG = logging.getLogger("orchestrator.knowledge")
_HERE = Path(__file__).parent
MANUALS_DIR = _HERE / "manuals"
HANDBOOKS_DIR = _HERE / "handbooks"
STORAGE_DIR = _HERE / ".storage"
PAGEINDEX_DIR = STORAGE_DIR / "pageindex"
FAISS_DIR = STORAGE_DIR / "faiss"

# Lazy singletons populated by :file:`ingest.py` and reused by the tools.
_pageindex_toolkit: Optional[Any] = None
_pageindex_tree_names: list[str] = []
_faiss_store: Optional[Any] = None


def attach_pageindex(toolkit: Any, tree_names: list[str]) -> None:
    """Wire a built :class:`PageIndexToolkit` for use by ``pageindex_lookup``."""
    global _pageindex_toolkit, _pageindex_tree_names
    _pageindex_toolkit = toolkit
    _pageindex_tree_names = list(tree_names)


def attach_faiss(store: Any) -> None:
    """Wire a built :class:`FAISSStore` for use by ``handbook_search``."""
    global _faiss_store
    _faiss_store = store


# ---------------------------------------------------------------------------
# Fallback: simple substring/section scanner over markdown.
# ---------------------------------------------------------------------------

def split_into_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into ``(heading, body)`` chunks by ``##``/``###`` headings."""
    chunks: list[tuple[str, str]] = []
    current_heading = "Preamble"
    current_body: list[str] = []
    for line in text.splitlines():
        if line.startswith(("## ", "### ")):
            if current_body:
                chunks.append((current_heading, "\n".join(current_body).strip()))
            current_heading = line.lstrip("# ").strip()
            current_body = []
        else:
            current_body.append(line)
    if current_body:
        chunks.append((current_heading, "\n".join(current_body).strip()))
    return chunks


def _fallback_search(directory: Path, query: str, k: int = 3) -> list[dict[str, str]]:
    """Score sections by overlapping query terms and return the top-``k``."""
    terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
    if not terms:
        return []

    scored: list[tuple[int, dict[str, str]]] = []
    for md_path in sorted(directory.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        for heading, body in split_into_sections(text):
            hay = (heading + "\n" + body).lower()
            score = sum(hay.count(term) for term in terms)
            if score == 0:
                continue
            scored.append((score, {
                "source": md_path.name,
                "section": heading,
                "excerpt": body[:600],
            }))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:k]]


def _format_hits(hits: list[dict[str, Any]], header: str) -> str:
    if not hits:
        return f"{header} — no matching section found."
    lines = [header]
    for hit in hits:
        src = hit.get("source") or hit.get("doc_name", "?")
        section = hit.get("section") or hit.get("title", "?")
        excerpt = hit.get("excerpt") or hit.get("text", "")
        lines.append(f"\n• [{src} → {section}]\n{excerpt.strip()}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public tools — registered onto specialist agents.
# ---------------------------------------------------------------------------

@tool
async def pageindex_lookup(query: str) -> str:
    """Search the training manuals (PageIndex tree) for relevant sections.

    Use this for IT troubleshooting steps and onboarding policies. Pass a
    focused natural-language question — the tool walks the tree and
    returns the most relevant section bodies.

    Args:
        query: A concise natural-language question.

    Returns:
        Markdown-formatted excerpts citing the source manual and section.
    """
    if _pageindex_toolkit is not None and _pageindex_tree_names:
        try:
            collected: list[dict[str, str]] = []
            for tree_name in _pageindex_tree_names:
                body = await _pageindex_toolkit.retrieve(
                    tree_name=tree_name, query=query, top_k=2
                )
                if body:
                    collected.append({
                        "source": tree_name,
                        "section": "(see headings below)",
                        "excerpt": body,
                    })
            return _format_hits(collected, "📚 PageIndex results")
        except Exception as exc:
            _LOG.warning("PageIndex query failed (%s); using fallback.", exc)

    hits = _fallback_search(MANUALS_DIR, query, k=3)
    return _format_hits(hits, "📚 Manual results (substring fallback)")


@tool
async def handbook_search(query: str) -> str:
    """Search the company handbook (vector RAG) for policy details.

    Use this for expense, travel, procurement, and code-of-conduct
    questions. Pass a natural-language query — top matches are returned
    with the section title.

    Args:
        query: A concise natural-language question.

    Returns:
        Markdown-formatted excerpts citing the source handbook section.
    """
    if _faiss_store is not None:
        try:
            async with _faiss_store as store:
                results = await store.similarity_search(query=query, limit=3)
            hits = []
            for r in results:
                metadata = getattr(r, "metadata", {}) or {}
                hits.append({
                    "source": metadata.get("source", "handbook"),
                    "section": metadata.get("section", "?"),
                    "excerpt": getattr(r, "page_content", "") or str(r),
                })
            return _format_hits(hits, "🧾 Handbook results")
        except Exception as exc:
            _LOG.warning("FAISS query failed (%s); using fallback.", exc)

    hits = _fallback_search(HANDBOOKS_DIR, query, k=3)
    return _format_hits(hits, "🧾 Handbook results (substring fallback)")


# Bridge for the ingest script to run a quick smoke-test.
async def _smoke() -> None:
    print(await pageindex_lookup("how do I reset my password"))
    print(await handbook_search("expense receipts"))


if __name__ == "__main__":
    asyncio.run(_smoke())
