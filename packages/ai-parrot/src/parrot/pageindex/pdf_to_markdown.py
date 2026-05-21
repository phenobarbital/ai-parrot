"""PDF → per-page markdown extraction for PageIndex.

A thin, opinionated wrapper around
``pymupdf4llm.to_markdown(path, page_chunks=True)`` so the result lines
up with :func:`parrot.pageindex.utils.get_page_tokens` (1-based, every
physical page represented). The output is consumed by
:func:`parrot.pageindex.builder.build_page_index` to emit per-node
markdown via ``start_index``/``end_index`` slicing.

Choice of extractor: PageIndex already uses ``pymupdf4llm`` indirectly
via :class:`parrot_loaders.pdf.PDFLoader`. Calling it directly keeps the
page indexing aligned with ``get_page_tokens`` (no implicit reordering,
no page-filtering side effects).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

try:
    import pymupdf
except ImportError:  # pragma: no cover — pyproject pins pymupdf.
    pymupdf = None  # type: ignore[assignment]

try:
    import pymupdf4llm
except ImportError:  # pragma: no cover — pyproject pins pymupdf4llm.
    pymupdf4llm = None  # type: ignore[assignment]


logger = logging.getLogger("parrot.pageindex")


def extract_markdown_per_page(pdf_path: str | Path) -> list[tuple[int, str]]:
    """Extract per-physical-page markdown from a PDF.

    Args:
        pdf_path: Path to the source PDF on disk.

    Returns:
        ``[(physical_page_1based, markdown_text), ...]`` covering every
        physical page in the document. Empty pages are emitted as
        ``(page_num, "")`` so the returned list is dense and the index
        space matches :func:`get_page_tokens`.

    Raises:
        FileNotFoundError: If ``pdf_path`` does not exist.
        ImportError: If ``pymupdf`` / ``pymupdf4llm`` are not installed.
        ValueError: If the page count emitted by ``pymupdf4llm`` does
            not match ``pymupdf.open(path).page_count``. Mis-alignment
            here would silently mis-slice every downstream node.
    """
    if pymupdf is None or pymupdf4llm is None:
        raise ImportError(
            "extract_markdown_per_page requires pymupdf and pymupdf4llm; "
            "install them via the [pdf] extra."
        )

    path_str = os.fspath(pdf_path)
    if not Path(path_str).is_file():
        raise FileNotFoundError(f"PDF not found: {path_str}")

    doc = pymupdf.open(path_str)
    try:
        expected_pages = doc.page_count
    finally:
        doc.close()

    # NB: NEVER pass ``pages=`` here — restricting the page set would
    # decouple the returned index from ``get_page_tokens``' index space.
    chunks = pymupdf4llm.to_markdown(path_str, page_chunks=True)
    if not isinstance(chunks, list):
        raise ValueError(
            "pymupdf4llm.to_markdown returned a non-list result with "
            "page_chunks=True; refusing to mis-align node ranges."
        )

    if len(chunks) != expected_pages:
        raise ValueError(
            f"Page count mismatch for {path_str}: pymupdf reports "
            f"{expected_pages} pages but pymupdf4llm returned "
            f"{len(chunks)} chunks."
        )

    pages: list[tuple[int, str]] = []
    for i, chunk in enumerate(chunks):
        text = ""
        if isinstance(chunk, dict):
            text = chunk.get("text") or ""
        elif isinstance(chunk, str):
            text = chunk
        pages.append((i + 1, text))
    return pages


def build_node_markdown_map(
    structure: object,
    pages: list[tuple[int, str]],
) -> dict[str, str]:
    """Walk a node tree and return ``{node_id: concatenated_markdown}``.

    Uses ``start_index``/``end_index`` semantics identical to
    :func:`parrot.pageindex.utils.add_node_text` (1-based, inclusive
    range). Folder/synthetic nodes without page ranges contribute the
    empty string.
    """
    out: dict[str, str] = {}

    def _slice(start: int, end: int) -> str:
        if not (isinstance(start, int) and isinstance(end, int)):
            return ""
        if start < 1 or end < start:
            return ""
        parts: list[str] = []
        for page_num, text in pages:
            if start <= page_num <= end:
                if text:
                    parts.append(text)
        return "".join(parts)

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            node_id = node.get("node_id")
            if node_id:
                start = node.get("start_index")
                end = node.get("end_index")
                out[str(node_id)] = _slice(start, end)
            children = node.get("nodes")
            if children:
                _walk(children)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(structure)
    return out
