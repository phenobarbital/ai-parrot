"""
Disk storage for archived RSS articles.

Layout::

    {base_dir}/{feed_slug}/{item_id}/page.html     raw fetched HTML
    {base_dir}/{feed_slug}/{item_id}/content.txt   extracted main text
    {base_dir}/{feed_slug}/{item_id}/item.json     FeedItemMetadata dump
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .models import FeedItemMetadata, is_item_id

HTML_FILENAME = "page.html"
TEXT_FILENAME = "content.txt"
META_FILENAME = "item.json"

_FORMAT_FILES = {"html": HTML_FILENAME, "text": TEXT_FILENAME}


class RSSStorage:
    """Filesystem archive for fetched feed items.

    All blocking I/O is dispatched through ``asyncio.to_thread`` in the
    async methods; the sync helpers are cheap path/metadata operations.
    """

    def __init__(self, base_dir: Union[str, Path]):
        """Initialize the storage root.

        Args:
            base_dir: Directory under which all feed content is archived.
                Created if missing.
        """
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)

    def item_dir(self, feed_slug: str, item_id: str) -> Path:
        """Return the directory for a feed item (not created)."""
        return self.base_dir / feed_slug / item_id

    def has_item(self, feed_slug: str, item_id: str) -> bool:
        """Check whether an item is already archived (dedup check)."""
        return (self.item_dir(feed_slug, item_id) / META_FILENAME).exists()

    async def save_item(
        self, meta: FeedItemMetadata, html: str, text: str
    ) -> FeedItemMetadata:
        """Persist an item's content and metadata to disk.

        Sets ``html_path``/``text_path`` on the metadata (when the
        corresponding content is non-empty) before writing ``item.json``.

        Args:
            meta: Item metadata to persist.
            html: Raw page HTML.
            text: Extracted main text.

        Returns:
            The updated metadata (paths filled in).
        """
        target = self.item_dir(meta.feed, meta.item_id)

        def _write() -> None:
            target.mkdir(parents=True, exist_ok=True)
            if html:
                html_file = target / HTML_FILENAME
                html_file.write_text(html, encoding="utf-8")
                meta.html_path = str(html_file)
            if text:
                text_file = target / TEXT_FILENAME
                text_file.write_text(text, encoding="utf-8")
                meta.text_path = str(text_file)
            meta_file = target / META_FILENAME
            meta_file.write_text(
                json.dumps(meta.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        await asyncio.to_thread(_write)
        return meta

    def load_metadata(self, feed_slug: str, item_id: str) -> Optional[FeedItemMetadata]:
        """Load archived metadata for an item, or None when absent/corrupt."""
        meta_file = self.item_dir(feed_slug, item_id) / META_FILENAME
        if not meta_file.exists():
            return None
        try:
            return FeedItemMetadata(**json.loads(meta_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            self.logger.warning("Corrupt item metadata at %s: %s", meta_file, exc)
            return None

    def find_item(self, item_id: str) -> Optional[Path]:
        """Locate an item directory by id across all feeds.

        Args:
            item_id: 16-hex item identifier.

        Returns:
            The item directory, or None when not archived.
        """
        for meta_file in self.base_dir.glob(f"*/{item_id}/{META_FILENAME}"):
            return meta_file.parent
        return None

    def list_saved(
        self, feed_slug: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List archived item metadata, newest first.

        Args:
            feed_slug: Restrict to a single feed when provided.
            limit: Maximum number of records returned.

        Returns:
            Metadata dicts (``FeedItemMetadata`` shape) sorted by
            archive-file mtime, descending.
        """
        pattern = f"{feed_slug}/*/{META_FILENAME}" if feed_slug else f"*/*/{META_FILENAME}"
        meta_files = sorted(
            self.base_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        results: List[Dict[str, Any]] = []
        for meta_file in meta_files[:limit]:
            meta = self.load_metadata(meta_file.parent.parent.name, meta_file.parent.name)
            if meta is not None:
                results.append(meta.to_llm_dict())
        return results

    def resolve_content_path(self, ref: str, fmt: str = "text") -> Path:
        """Resolve an item reference to a readable content file.

        Args:
            ref: A 16-hex ``item_id``, an item directory path, or a direct
                path to an archived file.
            fmt: ``"text"`` or ``"html"`` — which representation to read
                when the ref is an item id or directory.

        Returns:
            Path to the content file, guaranteed to live under ``base_dir``.

        Raises:
            ValueError: On unknown format, unknown item id, missing file, or
                any path escaping the storage root (traversal/symlink guard).
        """
        if fmt not in _FORMAT_FILES:
            raise ValueError(f"Unknown format {fmt!r}; expected 'text' or 'html'")

        if is_item_id(ref):
            item_dir = self.find_item(ref)
            if item_dir is None:
                raise ValueError(f"No archived item with id {ref!r}")
            path = item_dir / _FORMAT_FILES[fmt]
        else:
            path = Path(ref)
            if not path.is_absolute():
                path = self.base_dir / path
            if path.is_dir():
                path = path / _FORMAT_FILES[fmt]

        resolved = path.resolve()
        if not resolved.is_relative_to(self.base_dir):
            raise ValueError(f"Refusing to read outside the RSS storage dir: {ref!r}")
        if not resolved.is_file():
            raise ValueError(f"No archived content at {ref!r} (format={fmt})")
        return resolved

    async def read_content(self, ref: str, fmt: str = "text") -> str:
        """Read archived content for an item reference.

        Args:
            ref: Item id or path (see :meth:`resolve_content_path`).
            fmt: ``"text"`` or ``"html"``.

        Returns:
            The file content.

        Raises:
            ValueError: Propagated from :meth:`resolve_content_path`.
        """
        path = self.resolve_content_path(ref, fmt)
        return await asyncio.to_thread(path.read_text, encoding="utf-8")
