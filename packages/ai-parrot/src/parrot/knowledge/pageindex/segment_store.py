"""Immutable document-revision files for PageIndex trees (FEAT-840)."""

from __future__ import annotations

import logging
import re
import shutil
import time
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable, Optional

from parrot.knowledge.pageindex.content_store import _atomic_write
from parrot.knowledge.pageindex.segments import DocumentRevision
from parrot.knowledge.pageindex.utils import structure_to_list

logger = logging.getLogger("parrot.knowledge.pageindex.segment_store")

_TREE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DOC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{16}$")


class SegmentStore:
    """``<storage_dir>/<tree>/segments/<doc_id>.<revision>.json``, written once, read through an LRU."""

    def __init__(self, storage_dir: str | Path, cache_size: int = 8) -> None:
        self._dir = Path(storage_dir)
        self._cache_size = max(1, int(cache_size))
        self._cache: "OrderedDict[tuple[str, str, str], DocumentRevision]" = OrderedDict()

    def segments_dir(self, tree_name: str) -> Path:
        """Return ``<storage_dir>/<tree_name>/segments``; ValueError on a bad name."""
        if not isinstance(tree_name, str) or not _TREE_NAME_RE.fullmatch(tree_name):
            raise ValueError(f"Invalid tree_name {tree_name!r}")
        return self._dir / tree_name / "segments"

    def revision_path(self, tree_name: str, doc_id: str, revision: str) -> Path:
        """Path of one revision file; ValueError on a malformed doc_id or revision."""
        directory = self.segments_dir(tree_name)
        if not isinstance(doc_id, str) or not _DOC_ID_RE.fullmatch(doc_id):
            raise ValueError(f"Invalid doc_id {doc_id!r}")
        if not isinstance(revision, str) or not _REVISION_RE.fullmatch(revision):
            raise ValueError(f"Invalid revision {revision!r}")
        return directory / f"{doc_id}.{revision}.json"

    def _cache_put(self, key: tuple[str, str, str], rev: DocumentRevision) -> None:
        self._cache[key] = rev
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    def _cache_evict(self, key: tuple[str, str, str]) -> None:
        self._cache.pop(key, None)

    def save_revision(self, tree_name: str, rev: DocumentRevision) -> Path:
        """Write ``rev`` atomically; no-op when the file already exists."""
        path = self.revision_path(tree_name, rev.doc_id, rev.revision)
        if not path.is_file():
            _atomic_write(path, rev.model_dump_json())
        return path

    def load_revision(self, tree_name: str, doc_id: str, revision: str) -> Optional[DocumentRevision]:
        """Return the cached/parsed revision, or ``None`` when the file is absent."""
        path = self.revision_path(tree_name, doc_id, revision)
        key = (tree_name, doc_id, revision)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        rev = DocumentRevision.model_validate_json(text)
        self._cache_put(key, rev)
        return rev

    def has_revision(self, tree_name: str, doc_id: str, revision: str) -> bool:
        return self.revision_path(tree_name, doc_id, revision).is_file()

    def list_revisions(self, tree_name: str) -> list[tuple[str, str]]:
        """``(doc_id, revision)`` of every file on disk, sorted."""
        directory = self.segments_dir(tree_name)
        if not directory.is_dir():
            return []
        pairs: list[tuple[str, str]] = []
        for entry in directory.iterdir():
            if not entry.is_file() or entry.suffix != ".json":
                continue
            doc_id, _, revision = entry.stem.rpartition(".")
            if _DOC_ID_RE.fullmatch(doc_id) and _REVISION_RE.fullmatch(revision):
                pairs.append((doc_id, revision))
        return sorted(pairs)

    @staticmethod
    def live_revisions(tree: dict[str, Any]) -> set[tuple[str, str]]:
        """Every ``(doc_id, revision)`` named by a node of ``tree``."""
        return {
            (n["doc_id"], n["revision"])
            for n in structure_to_list(tree.get("structure", []))
            if isinstance(n.get("doc_id"), str) and isinstance(n.get("revision"), str)
        }

    def mark_superseded(self, tree_name: str, pairs: Iterable[tuple[str, str]]) -> int:
        """Restart the grace clock (``os.utime``) of revisions a new generation stopped referencing."""
        touched = 0
        for doc_id, revision in pairs:
            try:
                path = self.revision_path(tree_name, doc_id, revision)
            except ValueError:
                continue
            try:
                os.utime(path, None)
                touched += 1
            except FileNotFoundError:
                continue
            except OSError as exc:
                logger.warning("could not mark %s superseded: %s", path, exc)
        return touched

    def sweep_unreferenced(self, tree_name: str, tree: dict[str, Any], *, max_age_s: int) -> int:
        """Delete non-live revision files older than ``max_age_s``; return the count."""
        live = self.live_revisions(tree)
        cutoff = time.time() - max_age_s
        count = 0
        for doc_id, revision in self.list_revisions(tree_name):
            if (doc_id, revision) in live:
                continue
            path = self.revision_path(tree_name, doc_id, revision)
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                logger.warning("sweep could not remove %s: %s", path, exc)
                continue
            self._cache_evict((tree_name, doc_id, revision))
            count += 1
        return count

    def delete_tree(self, tree_name: str) -> int:
        """Remove ``segments/`` for ``tree_name`` and evict its cache entries; return files removed."""
        directory = self.segments_dir(tree_name)
        count = sum(1 for e in directory.iterdir() if e.is_file()) if directory.is_dir() else 0
        shutil.rmtree(directory, ignore_errors=True)
        for key in [k for k in self._cache if k[0] == tree_name]:
            self._cache_evict(key)
        return count
