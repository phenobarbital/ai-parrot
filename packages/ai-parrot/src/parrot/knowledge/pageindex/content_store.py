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

import json
import logging
import os
import re
import shutil
import tempfile
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from parrot.knowledge.okf.utils import flatten_concept_id_for_filename
from parrot.knowledge.pageindex.utils import structure_to_list

logger = logging.getLogger("parrot.knowledge.pageindex.content_store")

_TREE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_BODY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\.[0-9a-f]{16}$")


def _tree_nodes(tree: Any) -> list[dict]:
    """Flatten ``tree`` (``{"structure": [...]}`` or a bare structure) into nodes."""
    if isinstance(tree, dict) and "structure" in tree:
        tree = tree["structure"]
    return structure_to_list(tree)


def _flat_id(node: dict[str, Any]) -> Optional[str]:
    """Return the node's flat concept id when it has a usable one."""
    concept_id = node.get("concept_id")
    if not isinstance(concept_id, str) or not concept_id:
        return None
    flat = flatten_concept_id_for_filename(concept_id)
    return flat if _NODE_ID_RE.fullmatch(flat) else None


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via temp file + fsync + ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


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
        self._live: dict[str, tuple[tuple[int, int], dict[str, str]]] = {}

    # ---- validation / paths -------------------------------------------

    @staticmethod
    def _validate_tree_name(tree_name: str) -> None:
        if not isinstance(tree_name, str) or not _TREE_NAME_RE.fullmatch(tree_name):
            raise ValueError(f"Invalid tree_name {tree_name!r}; " "expected 1-128 chars from [A-Za-z0-9_-].")

    @staticmethod
    def _validate_node_id(node_id: str) -> None:
        if not isinstance(node_id, str) or not _NODE_ID_RE.fullmatch(node_id):
            raise ValueError(f"Invalid node_id {node_id!r}; " "expected 1-64 chars from [A-Za-z0-9_-].")

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
        _atomic_write(path, markdown or "")
        self._cache_put((tree_name, node_id), markdown or "")

    # ---- immutable body blobs (FEAT-831) -------------------------------

    def bodies_dir(self, tree_name: str) -> Path:
        """Return ``<storage_dir>/<tree_name>/bodies``."""
        return self._tree_dir(tree_name) / "bodies"

    def body_path(self, tree_name: str, key: str) -> Path:
        """Return the path of blob ``key``; raise ``ValueError`` for a malformed key."""
        if not isinstance(key, str) or not _BODY_KEY_RE.fullmatch(key):
            raise ValueError(f"invalid body key {key!r}")
        return self.bodies_dir(tree_name) / f"{key}.md"

    def save_body(self, tree_name: str, key: str, markdown: str) -> Path:
        """Write blob ``key`` atomically (temp + fsync + os.replace); no-op when it exists."""
        path = self.body_path(tree_name, key)
        if path.is_file():
            return path
        _atomic_write(path, markdown or "")
        return path

    def load_body(self, tree_name: str, key: str) -> Optional[str]:
        """Return blob ``key`` (cached) or ``None`` when absent."""
        path = self.body_path(tree_name, key)
        cache_key = (tree_name, f"bodies/{key}")
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("NodeContentStore.load_body failed for %s/%s: %s", tree_name, key, exc)
            return None
        self._cache_put(cache_key, text)
        return text

    def _read_legacy(self, tree_name: str, name: str) -> Optional[str]:
        """Read ``<tree>/<name>.md`` directly (no live resolution); ``None`` when absent."""
        try:
            path = self._node_path(tree_name, name)
        except ValueError:
            return None
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("NodeContentStore legacy read failed for %s/%s: %s", tree_name, name, exc)
            return None

    def load_node(self, tree_name: str, node: dict[str, Any]) -> Optional[str]:
        """Resolve ``body_ref`` → ``<flat_concept_id>.md`` → ``<node_id>.md``; first hit wins."""
        ref = node.get("body_ref")
        if isinstance(ref, str) and ref:
            try:
                text = self.load_body(tree_name, ref)
            except ValueError:
                text = None
            if text is not None:
                return text
        flat = _flat_id(node)
        if flat:
            text = self._read_legacy(tree_name, flat)
            if text is not None:
                return text
        node_id = node.get("node_id")
        if isinstance(node_id, str) and node_id:
            return self._read_legacy(tree_name, node_id)
        return None

    def _live_index(self, tree_name: str) -> dict[str, str]:
        """Map node_id and flat concept id → body_ref from the live tree JSON (cached by signature)."""
        self._validate_tree_name(tree_name)
        json_path = self._dir / f"{tree_name}.json"
        try:
            st = json_path.stat()
        except OSError:
            self._live.pop(tree_name, None)
            return {}
        signature = (st.st_mtime_ns, st.st_size)
        cached = self._live.get(tree_name)
        if cached is not None and cached[0] == signature:
            return cached[1]
        try:
            with open(json_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            logger.warning("NodeContentStore live index unreadable for %s: %s", tree_name, exc)
            self._live.pop(tree_name, None)
            return {}
        by_flat: dict[str, str] = {}
        by_id: dict[str, str] = {}
        for node in _tree_nodes(data):
            ref = node.get("body_ref")
            if not isinstance(ref, str) or not _BODY_KEY_RE.fullmatch(ref):
                continue
            flat = _flat_id(node)
            if flat:
                by_flat[flat] = ref
            node_id = node.get("node_id")
            if isinstance(node_id, str) and node_id:
                by_id[node_id] = ref
        index = {**by_flat, **by_id}  # node_id wins on collision
        self._live[tree_name] = (signature, index)
        return index

    def _live_body(self, tree_name: str, node_id: str) -> Optional[str]:
        ref = self._live_index(tree_name).get(node_id)
        return self.load_body(tree_name, ref) if ref else None

    def load_current(self, tree_name: str, node_id: str) -> Optional[str]:
        """Return ``node_id``'s body from the *live* generation, falling back to legacy files.

        Unlike :meth:`load`, which prefers a legacy ``<node_id>.md`` for
        backwards compatibility, this prefers the body the published tree
        points at. Use it where a stale leftover file must never be served for
        a node whose id was reused by a newer tree (reindex, rename over a
        legacy destination).
        """
        try:
            live = self._live_body(tree_name, node_id)
        except ValueError:
            live = None
        return live if live is not None else self.load(tree_name, node_id)

    def mark_superseded(self, tree_name: str, body_keys: Iterable[str], node_ids: Iterable[str]) -> int:
        """Restart the grace clock of bodies a new generation just stopped referencing.

        The sweep ages files by mtime, i.e. from creation. A body written long
        ago and superseded only now must still stay readable for the full grace
        period, so its mtime is reset to *now* at supersession time.

        Args:
            tree_name: Tree whose files are touched.
            body_keys: ``body_ref`` blobs the previous generation referenced.
            node_ids: Legacy ``<node_id>.md`` files the previous generation used.

        Returns:
            Number of files whose clock was restarted.
        """
        tree_dir = self._tree_dir(tree_name)
        if not tree_dir.is_dir():
            return 0
        paths: list[Path] = []
        for key in body_keys:
            if isinstance(key, str) and _BODY_KEY_RE.fullmatch(key):
                paths.append(self.bodies_dir(tree_name) / f"{key}.md")
        for node_id in node_ids:
            if isinstance(node_id, str) and _NODE_ID_RE.fullmatch(node_id):
                paths.append(tree_dir / f"{node_id}.md")
        touched = 0
        for path in paths:
            try:
                os.utime(path, None)
                touched += 1
            except FileNotFoundError:
                continue
            except OSError as exc:
                logger.warning("could not mark %s superseded: %s", path, exc)
        return touched

    def sweep_unreferenced(self, tree_name: str, tree: dict[str, Any], *, max_age_s: int) -> int:
        """Delete unreferenced blobs and superseded ``<node_id>.md`` files older than ``max_age_s``."""
        tree_dir = self._tree_dir(tree_name)
        if not tree_dir.is_dir():
            return 0
        nodes = _tree_nodes(tree)
        live_refs = {n["body_ref"] for n in nodes if isinstance(n.get("body_ref"), str)}
        superseded: set[str] = set()
        for node in nodes:
            if not isinstance(node.get("body_ref"), str):
                continue
            node_id = node.get("node_id")
            if isinstance(node_id, str) and node_id and node_id != _flat_id(node):
                superseded.add(node_id)
        cutoff = time.time() - max_age_s
        count = 0

        def _remove(entry: Path) -> bool:
            try:
                if entry.stat().st_mtime >= cutoff:
                    return False
                entry.unlink()
                return True
            except FileNotFoundError:
                return False
            except OSError as exc:
                logger.warning("sweep could not remove %s: %s", entry, exc)
                return False

        bodies = self.bodies_dir(tree_name)
        if bodies.is_dir():
            for entry in bodies.iterdir():
                if not entry.is_file() or entry.suffix != ".md":
                    continue
                if not _BODY_KEY_RE.fullmatch(entry.stem) or entry.stem in live_refs:
                    continue
                if _remove(entry):
                    self._cache_evict((tree_name, f"bodies/{entry.stem}"))
                    count += 1
        for node_id in superseded:
            if not _NODE_ID_RE.fullmatch(node_id):
                continue
            entry = tree_dir / f"{node_id}.md"
            if entry.is_file() and _remove(entry):
                self._cache_evict((tree_name, node_id))
                count += 1
        return count

    def load(self, tree_name: str, node_id: str) -> Optional[str]:
        """Return the markdown for ``node_id`` or ``None`` if missing."""
        key = (tree_name, node_id)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        path = self._node_path(tree_name, node_id)
        if not path.is_file():
            return self._live_body(tree_name, node_id)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("NodeContentStore.load failed for %s/%s: %s", tree_name, node_id, exc)
            return None
        self._cache_put(key, text)
        return text

    def has(self, tree_name: str, node_id: str) -> bool:
        """Return whether the sidecar markdown file for ``node_id`` exists."""
        if (tree_name, node_id) in self._cache:
            return True
        if self._node_path(tree_name, node_id).is_file():
            return True
        ref = self._live_index(tree_name).get(node_id)
        return bool(ref) and self.body_path(tree_name, ref).is_file()

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
        self._live.pop(tree_name, None)
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
        for sub in ("bodies", "embeddings", "segments"):
            shutil.rmtree(tree_dir / sub, ignore_errors=True)
        try:
            tree_dir.rmdir()
        except OSError:
            # Directory not empty (foreign files) or already gone — leave it.
            pass
        return count

    def rename_tree(self, src: str, dst: str) -> bool:
        """Move all content and evict source/destination cache entries.

        Returns:
            False when the source directory is absent; True after moving it.

        Raises:
            ValueError: A name is invalid.
            FileExistsError: Destination directory already exists.
        """
        src_dir = self._tree_dir(src)
        dst_dir = self._tree_dir(dst)
        if not src_dir.is_dir():
            self._cache_evict_tree(src)
            self._cache_evict_tree(dst)
            return False
        if dst_dir.exists():
            raise FileExistsError(dst_dir)
        os.replace(src_dir, dst_dir)
        self._cache_evict_tree(src)
        self._cache_evict_tree(dst)
        return True

    def list_node_ids(self, tree_name: str) -> list[str]:
        """Return node ids that currently have a sidecar on disk, sorted."""
        tree_dir = self._tree_dir(tree_name)
        if not tree_dir.is_dir():
            return []
        ids = [
            entry.stem
            for entry in tree_dir.iterdir()
            if entry.is_file() and entry.suffix == ".md" and _NODE_ID_RE.fullmatch(entry.stem)
        ]
        return sorted(ids)

    # ---- loader closure ----------------------------------------------

    def loader_for(self, tree_name: str, tree: Optional[dict[str, Any]] = None) -> Callable[[str], Optional[str]]:
        """Return a closure ``node_id -> Optional[str]`` for ``tree_name``.

        Hand this to :class:`HybridPageIndexSearch` (via the new
        ``content_loader`` constructor parameter) so the engine can read
        per-node markdown without taking a hard dependency on this store.

        The returned closure accepts both plain ``node_id`` values
        (``"0042"``) and **flattened concept_id** values (``"controls--nist-ir-4"``).
        When a caller passes a flattened concept_id, the closure attempts to
        load that key directly; it falls back to treating the argument as a
        plain ``node_id`` only when the first attempt returns ``None``.

        This dual-key behaviour supports the OKF migration transition period
        where some sidecars have already been renamed to
        ``<flattened_concept_id>.md`` while others remain keyed by
        ``node_id``.

        With ``tree``, ids resolve against that tree (pinned) via
        :meth:`load_node`, regardless of later changes to the JSON on disk.
        """
        self._validate_tree_name(tree_name)

        if tree is not None:
            pinned: dict[str, dict[str, Any]] = {}
            for node in _tree_nodes(tree):
                flat = _flat_id(node)
                if flat:
                    pinned.setdefault(flat, node)
            for node in _tree_nodes(tree):
                node_id = node.get("node_id")
                if isinstance(node_id, str) and node_id:
                    pinned[node_id] = node  # node_id wins over a flat id

            def _load_pinned(key: str) -> Optional[str]:
                node = pinned.get(key)
                if node is None:
                    return None
                return self.load_node(tree_name, node)

            return _load_pinned

        def _load(node_id: str) -> Optional[str]:
            try:
                result = self.load(tree_name, node_id)
            except ValueError:
                # Bad node_id from corrupt data — skip silently.
                return None
            return result

        return _load
