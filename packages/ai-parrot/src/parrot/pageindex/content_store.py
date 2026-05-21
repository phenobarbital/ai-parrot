"""Per-node markdown content store for PageIndex trees.

Each PageIndex node references markdown content stored alongside the
tree JSON in a sibling directory::

    <storage_dir>/
        <tree_name>.json          ← INDEX (lean ToC tree)
        <tree_name>/              ← CONTENT (one .md per node)
            0000.md
            0001.md
            …

The store fronts disk reads with a bounded LRU cache keyed by
``(tree_name, node_id)`` so repeated retrieval of the same node is
served from memory. Cache entries are evicted on save/delete so writers
and readers never observe stale content.

This module deliberately uses only the standard library — file I/O is
fast enough for the access patterns PageIndex exercises, and wrapping
small reads in async would add noise without benefit.
"""
from __future__ import annotations

import logging
import re
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Optional


logger = logging.getLogger("parrot.pageindex")

_TREE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class NodeContentStore:
    """On-disk per-node markdown content store with a bounded LRU cache.

    Args:
        storage_dir: Directory that contains tree JSON files and the
            sibling ``<tree_name>/`` content directories. Created if it
            does not exist.
        cache_size: Maximum number of ``(tree_name, node_id)`` entries
            held in memory.

    Notes:
        * Tree and node names are validated to keep the on-disk layout
          flat and safe from path-escape inputs.
        * The cache is per-instance; each ``PageIndexToolkit`` owns its
          own store and therefore its own cache.
    """

    def __init__(
        self,
        storage_dir: str | Path,
        cache_size: int = 256,
    ) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache_size = max(1, int(cache_size))
        self._cache: "OrderedDict[tuple[str, str], str]" = OrderedDict()

    # ---- validation / paths -------------------------------------------

    @staticmethod
    def _validate_tree_name(tree_name: str) -> None:
        if not isinstance(tree_name, str) or not _TREE_NAME_RE.match(tree_name):
            raise ValueError(
                f"Invalid tree_name {tree_name!r}; "
                "expected 1-128 chars from [A-Za-z0-9_-]."
            )

    @staticmethod
    def _validate_node_id(node_id: str) -> None:
        if not isinstance(node_id, str) or not _NODE_ID_RE.match(node_id):
            raise ValueError(
                f"Invalid node_id {node_id!r}; "
                "expected 1-64 chars from [A-Za-z0-9_-]."
            )

    def _tree_dir(self, tree_name: str) -> Path:
        self._validate_tree_name(tree_name)
        return self._dir / tree_name

    def _node_path(self, tree_name: str, node_id: str) -> Path:
        self._validate_node_id(node_id)
        return self._tree_dir(tree_name) / f"{node_id}.md"

    # ---- cache helpers ------------------------------------------------

    def _cache_get(self, key: tuple[str, str]) -> Optional[str]:
        value = self._cache.get(key)
        if value is not None:
            self._cache.move_to_end(key)
        return value

    def _cache_put(self, key: tuple[str, str], value: str) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
            self._cache[key] = value
            return
        self._cache[key] = value
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    def _cache_evict(self, key: tuple[str, str]) -> None:
        self._cache.pop(key, None)

    def _cache_evict_tree(self, tree_name: str) -> None:
        for key in [k for k in self._cache if k[0] == tree_name]:
            del self._cache[key]

    # ---- public CRUD --------------------------------------------------

    def save(self, tree_name: str, node_id: str, markdown: str) -> None:
        """Persist ``markdown`` for ``node_id`` under ``tree_name``."""
        path = self._node_path(tree_name, node_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown or "", encoding="utf-8")
        self._cache_put((tree_name, node_id), markdown or "")

    def load(self, tree_name: str, node_id: str) -> Optional[str]:
        """Return the markdown for ``node_id`` or ``None`` if missing."""
        key = (tree_name, node_id)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        path = self._node_path(tree_name, node_id)
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "NodeContentStore.load failed for %s/%s: %s", tree_name, node_id, exc
            )
            return None
        self._cache_put(key, text)
        return text

    def has(self, tree_name: str, node_id: str) -> bool:
        """Return whether the sidecar markdown file for ``node_id`` exists."""
        if (tree_name, node_id) in self._cache:
            return True
        return self._node_path(tree_name, node_id).is_file()

    def delete_node(self, tree_name: str, node_id: str) -> bool:
        """Remove the sidecar for ``node_id``. Returns ``True`` if removed."""
        path = self._node_path(tree_name, node_id)
        self._cache_evict((tree_name, node_id))
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def delete_tree(self, tree_name: str) -> int:
        """Remove every sidecar for ``tree_name``; return file count removed.

        Also evicts every cache entry belonging to that tree.
        """
        self._cache_evict_tree(tree_name)
        tree_dir = self._tree_dir(tree_name)
        if not tree_dir.is_dir():
            return 0
        count = 0
        for entry in tree_dir.iterdir():
            if entry.is_file() and entry.suffix == ".md":
                try:
                    entry.unlink()
                    count += 1
                except FileNotFoundError:
                    pass
        try:
            tree_dir.rmdir()
        except OSError:
            # Directory not empty (foreign files) or already gone — leave it.
            pass
        return count

    def list_node_ids(self, tree_name: str) -> list[str]:
        """Return node ids that currently have a sidecar on disk, sorted."""
        tree_dir = self._tree_dir(tree_name)
        if not tree_dir.is_dir():
            return []
        ids = [
            entry.stem
            for entry in tree_dir.iterdir()
            if entry.is_file() and entry.suffix == ".md"
            and _NODE_ID_RE.match(entry.stem)
        ]
        return sorted(ids)

    # ---- loader closure ----------------------------------------------

    def loader_for(self, tree_name: str) -> Callable[[str], Optional[str]]:
        """Return a closure ``node_id -> Optional[str]`` for ``tree_name``.

        Hand this to :class:`HybridPageIndexSearch` (via the new
        ``content_loader`` constructor parameter) so the engine can read
        per-node markdown without taking a hard dependency on this store.
        """
        self._validate_tree_name(tree_name)

        def _load(node_id: str) -> Optional[str]:
            try:
                return self.load(tree_name, node_id)
            except ValueError:
                # Bad node_id from corrupt data — skip silently.
                return None

        return _load
