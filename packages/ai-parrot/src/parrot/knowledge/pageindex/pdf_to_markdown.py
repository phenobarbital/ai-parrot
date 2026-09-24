"""PDF → per-page markdown extraction for PageIndex.

A thin, opinionated wrapper around
``pymupdf4llm.to_markdown(path, page_chunks=True)`` so the result lines
up with :func:`parrot.knowledge.pageindex.utils.get_page_tokens` (1-based, every
physical page represented). The output is consumed by
:func:`parrot.knowledge.pageindex.builder.build_page_index` to emit per-node
markdown via ``start_index``/``end_index`` slicing.

Choice of extractor: PageIndex already uses ``pymupdf4llm`` indirectly
via :class:`parrot_loaders.pdf.PDFLoader`. Calling it directly keeps the
page indexing aligned with ``get_page_tokens`` (no implicit reordering,
no page-filtering side effects).
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

try:
    import pymupdf
except ImportError:  # pragma: no cover — pyproject pins pymupdf.
    pymupdf = None  # type: ignore[assignment]

try:
    import pymupdf4llm
except ImportError:  # pragma: no cover — pyproject pins pymupdf4llm.
    pymupdf4llm = None  # type: ignore[assignment]


logger = logging.getLogger("parrot.knowledge.pageindex.pdf_to_markdown")


def extract_markdown_per_page(
    pdf_path: str | Path,
    *,
    images_dir: str | Path | None = None,
    image_format: str = "png",
    dpi: int = 150,
    image_size_limit: float = 0.05,
) -> list[tuple[int, str]]:
    """Extract per-physical-page markdown from a PDF.

    Args:
        pdf_path: Path to the source PDF on disk.
        images_dir: When set, ``pymupdf4llm`` also writes every raster image
            it finds to this directory and the returned markdown carries
            ``![](…)`` references to the written files. When ``None``
            (the default) the call is byte-identical to the pre-existing
            behaviour — no images are written and no extra kwargs are
            forwarded to ``pymupdf4llm.to_markdown``.
        image_format: Image file format forwarded to ``pymupdf4llm`` when
            ``images_dir`` is set. Ignored otherwise.
        dpi: Render resolution forwarded to ``pymupdf4llm`` when
            ``images_dir`` is set. Ignored otherwise.
        image_size_limit: Minimum image-to-page area ratio forwarded to
            ``pymupdf4llm`` when ``images_dir`` is set. Ignored otherwise.

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
            "extract_markdown_per_page requires pymupdf and pymupdf4llm; " "install them via the [pdf] extra."
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
    kwargs: dict[str, object] = {"page_chunks": True}
    if images_dir is not None:
        Path(images_dir).mkdir(parents=True, exist_ok=True)
        kwargs.update(
            write_images=True,
            image_path=os.fspath(images_dir),
            image_format=image_format,
            dpi=dpi,
            image_size_limit=image_size_limit,
        )
    chunks = pymupdf4llm.to_markdown(path_str, **kwargs)
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


class PageImage(BaseModel):
    """One raster image placed on a PDF page, with its bbox in page points."""

    page: int = Field(..., ge=1, description="1-based physical page")
    index: int = Field(..., ge=0, description="order of the image on its page")
    path: Path
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    sha256: str


def extract_page_images(
    pdf_path: str | Path,
    images_dir: str | Path,
    *,
    dpi: int = 150,
    min_area_ratio: float = 0.05,
) -> list[PageImage]:
    """Extract every sufficiently large page image with its bbox.

    Uses ``Page.get_image_info(xrefs=True)`` per page to locate raster
    images and their bbox, then renders a clipped pixmap of that bbox so
    the figure is captured exactly as laid out (including vector overlays
    such as callout numbers). Keeps the ``(page, text)`` contract of
    :func:`extract_markdown_per_page` intact — this is a sibling function,
    never called by it.

    Args:
        pdf_path: Source PDF.
        images_dir: Directory the PNG files are written to (created if
            missing).
        dpi: Render resolution for the clipped pixmap.
        min_area_ratio: Images whose bbox area is below this fraction of
            the page area are skipped.

    Returns:
        Images in (page, index) order.

    Raises:
        ImportError: pymupdf missing.
        FileNotFoundError: pdf_path missing.
    """
    if pymupdf is None:
        raise ImportError("extract_page_images requires pymupdf; install the [pdf] extra.")
    path_str = os.fspath(pdf_path)
    if not Path(path_str).is_file():
        raise FileNotFoundError(f"PDF not found: {path_str}")
    out_dir = Path(images_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[PageImage] = []
    doc = pymupdf.open(path_str)
    try:
        for page in doc:
            page_area = page.rect.width * page.rect.height
            for info in page.get_image_info(xrefs=True):
                bbox = pymupdf.Rect(info["bbox"])
                area = bbox.width * bbox.height
                if page_area <= 0 or (area / page_area) < min_area_ratio:
                    continue
                index = int(info.get("number", len(results)))
                pixmap = page.get_pixmap(clip=bbox, dpi=dpi)
                image_bytes = pixmap.tobytes("png")
                out_path = out_dir / f"p{page.number + 1:04d}-{index:02d}.png"
                out_path.write_bytes(image_bytes)
                results.append(
                    PageImage(
                        page=page.number + 1,
                        index=index,
                        path=out_path,
                        bbox=(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                        width=pixmap.width,
                        height=pixmap.height,
                        sha256=hashlib.sha256(image_bytes).hexdigest(),
                    )
                )
    finally:
        doc.close()
    logger.debug("extract_page_images: %d image(s) from %s", len(results), pdf_path)
    return results


def build_node_markdown_map(
    structure: object,
    pages: list[tuple[int, str]],
) -> dict[str, str]:
    """Walk a node tree and return ``{node_id: concatenated_markdown}``.

    Uses ``start_index``/``end_index`` semantics identical to
    :func:`parrot.knowledge.pageindex.utils.add_node_text` (1-based, inclusive
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
