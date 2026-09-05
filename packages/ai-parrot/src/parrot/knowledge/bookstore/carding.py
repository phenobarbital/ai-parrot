"""Card derivation helpers — slugs, ToC digests, and LLM carding.

Pure functions plus one LLM call (:func:`generate_card_fields`) with a
deterministic no-LLM fallback (:func:`fallback_card_fields`), so a
library stays usable without any model configured.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Optional

from .models import CardDraft, TocEntry

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LEN = 64
_SAMPLE_CHAR_CAP = 2000

_CARD_PROMPT = """You are a librarian writing the catalog card (ficha) for a book
that was just indexed. Using ONLY the material below, fill the card fields.

Filename: {filename}
Document description: {doc_description}

Table of contents:
{toc_digest}

Content samples:
{samples}

Rules:
- `title`: the real book title (not the filename) when identifiable.
- `authors`: only names you actually see; empty list otherwise.
- `year`: publication year if visible, else null.
- `language`: ISO 639-1 code of the main text.
- `topics`: 5-10 short research topics a reader would search this book for.
- `summary`: ONE paragraph — what the book covers and which questions it
  can answer. Write it as guidance for choosing between books.
"""


def slugify(text: str) -> str:
    """Turn ``text`` into a filesystem/tree-safe slug.

    NFKD-normalizes, strips diacritics, lowercases, and collapses any
    non-alphanumeric run into a single ``-``. Result is capped at 64
    chars and never empty (falls back to ``"book"``).

    Args:
        text: Free-form title or filename stem.

    Returns:
        A slug matching ``[a-z0-9-]+`` (also valid for
        :class:`~parrot.knowledge.pageindex.store.JSONTreeStore` names).
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_RE.sub("-", ascii_text).strip("-")
    slug = slug[:_MAX_SLUG_LEN].strip("-")
    return slug or "book"


def unique_slug(base: str, taken: set[str]) -> str:
    """Return ``base`` or the first free ``base-N`` (N >= 2) variant.

    Args:
        base: Candidate slug (already slugified).
        taken: Slugs already in use (catalog rows and trees on disk).
    """
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def derive_toc(
    tree: dict[str, Any], max_depth: int = 2
) -> tuple[list[TocEntry], str]:
    """Walk a PageIndex tree dict into ToC entries plus a text digest.

    Args:
        tree: A tree as returned by ``PageIndexToolkit.get_tree`` —
            ``{doc_name, doc_description?, structure: [nodes]}`` where
            each node carries ``title / node_id / start_index /
            end_index / nodes``.
        max_depth: Deepest level included (1 = chapters only).

    Returns:
        ``(entries, digest)`` — the structured entries and a rendered
        digest with one ``"1.2 Title (pp. 34-58)"`` style line per
        entry, suitable for FTS indexing and LLM prompts.
    """
    entries: list[TocEntry] = []

    def _walk(nodes: Any, depth: int) -> None:
        if not isinstance(nodes, list) or depth > max_depth:
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            entries.append(
                TocEntry(
                    node_id=str(node.get("node_id") or ""),
                    title=str(node.get("title") or "Untitled"),
                    depth=depth,
                    start_page=node.get("start_index"),
                    end_page=node.get("end_index"),
                )
            )
            _walk(node.get("nodes"), depth + 1)

    _walk(tree.get("structure"), 1)

    lines: list[str] = []
    numbering: list[int] = []
    for entry in entries:
        while len(numbering) < entry.depth:
            numbering.append(0)
        del numbering[entry.depth:]
        numbering[entry.depth - 1] += 1
        number = ".".join(str(n) for n in numbering)
        pages = ""
        if entry.start_page is not None:
            end = entry.end_page if entry.end_page is not None else entry.start_page
            pages = f" (pp. {entry.start_page}-{end})"
        indent = "  " * (entry.depth - 1)
        lines.append(f"{indent}{number} {entry.title}{pages}")
    return entries, "\n".join(lines)


def fallback_card_fields(file_path: Path, toc_entries: list[TocEntry]) -> CardDraft:
    """Deterministic card draft when no LLM is configured.

    Title comes from the de-slugified filename stem; topics from the
    top-level chapter titles.

    Args:
        file_path: The ingested source file.
        toc_entries: Structured ToC from :func:`derive_toc`.
    """
    stem = file_path.stem.replace("_", " ").replace("-", " ").strip()
    title = " ".join(part.capitalize() for part in stem.split()) or file_path.name
    topics = [e.title for e in toc_entries if e.depth == 1][:10]
    return CardDraft(title=title, topics=topics)


async def generate_card_fields(
    adapter: Any,
    *,
    filename: str,
    doc_description: str,
    toc_digest: str,
    samples: list[str],
) -> CardDraft:
    """LLM-generate the descriptive card fields via structured output.

    Args:
        adapter: A :class:`~parrot.knowledge.pageindex.llm_adapter.PageIndexLLMAdapter`
            (or compatible) exposing ``ask_structured(prompt, schema)``.
        filename: Source filename (context only, never trusted as title).
        doc_description: PageIndex ``doc_description`` when available.
        toc_digest: Rendered ToC from :func:`derive_toc`.
        samples: Content excerpts (each capped to ~2000 chars here).

    Returns:
        The LLM-filled :class:`CardDraft`.
    """
    capped = [s[:_SAMPLE_CHAR_CAP] for s in samples if s]
    prompt = _CARD_PROMPT.format(
        filename=filename,
        doc_description=doc_description or "(none)",
        toc_digest=toc_digest or "(no table of contents)",
        samples="\n\n---\n\n".join(capped) or "(no samples)",
    )
    draft = await adapter.ask_structured(prompt, CardDraft)
    if isinstance(draft, CardDraft):
        return draft
    # Some adapters return the raw dict for structured calls.
    return CardDraft.model_validate(draft)


def sample_sections(
    content_loader: Any, node_ids: list[str], max_samples: int = 2
) -> list[str]:
    """Load up to ``max_samples`` representative sidecar bodies.

    Picks the first node and one from the middle of the book, which is
    usually enough signal for carding without paying for a full read.

    Args:
        content_loader: ``NodeContentStore.loader_for(tree)`` callable
            mapping ``node_id`` → markdown (or ``None``).
        node_ids: Candidate node ids in reading order.
        max_samples: Upper bound on returned samples.
    """
    if not node_ids:
        return []
    picks = [node_ids[0]]
    if len(node_ids) > 2:
        picks.append(node_ids[len(node_ids) // 2])
    samples: list[str] = []
    for node_id in picks[:max_samples]:
        try:
            body = content_loader(node_id)
        except Exception:  # noqa: BLE001 — sampling is best-effort
            body = None
        if body:
            samples.append(body)
    return samples
