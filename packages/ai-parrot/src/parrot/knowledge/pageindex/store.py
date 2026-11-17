"""On-disk JSON persistence for PageIndex trees.

Each tree is stored as ``<storage_dir>/<tree_name>.json`` and is written
atomically (temp file in the same directory followed by ``os.replace``)
so a crash mid-write cannot leave a half-written tree on disk.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("parrot.knowledge.pageindex.store")

_TREE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class JSONTreeStore:
    """File-system backed registry of PageIndex trees.

    Args:
        storage_dir: Directory that will hold one ``<name>.json`` file per
            tree. Created if missing.
    """

    def __init__(self, storage_dir: str | Path):
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_name(tree_name: str) -> None:
        if not isinstance(tree_name, str) or not _TREE_NAME_RE.fullmatch(tree_name):
            raise ValueError(f"Invalid tree_name {tree_name!r}; expected 1-128 chars from [A-Za-z0-9_-].")

    def _path_for(self, tree_name: str) -> Path:
        self._validate_name(tree_name)
        return self._dir / f"{tree_name}.json"

    def list_names(self) -> list[str]:
        """Return tree names currently present on disk, sorted."""
        names: list[str] = []
        for entry in self._dir.iterdir():
            if entry.is_file() and entry.suffix == ".json":
                stem = entry.stem
                if _TREE_NAME_RE.fullmatch(stem):
                    names.append(stem)
        return sorted(names)

    def exists(self, tree_name: str) -> bool:
        return self._path_for(tree_name).is_file()

    def load(self, tree_name: str) -> dict[str, Any]:
        """Load a tree dict. Raises ``FileNotFoundError`` if absent."""
        path = self._path_for(tree_name)
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, tree_name: str, tree: dict[str, Any]) -> tuple[int, int]:
        """Atomically persist a tree to disk and return its signature.

        Strips reserved keys like ``_node_markdown`` before serialising —
        per-node markdown lives in :class:`NodeContentStore`, not inside
        the ToC tree. Defensive: the toolkit pops it before calling here.
        """
        path = self._path_for(tree_name)
        if isinstance(tree, dict) and "_node_markdown" in tree:
            tree = {k: v for k, v in tree.items() if k != "_node_markdown"}
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f".{tree_name}.",
            suffix=".json.tmp",
            dir=str(self._dir),
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(tree, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        try:
            dir_fd = os.open(self._dir, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            logger.debug("Failed to fsync PageIndex tree directory %s", self._dir, exc_info=True)

        signature = self.signature(tree_name)
        if signature is None:
            raise FileNotFoundError(f"tree {tree_name!r} vanished right after being saved")
        return signature

    def signature(self, tree_name: str) -> tuple[int, int] | None:
        """Return ``(st_mtime_ns, st_size)`` of the tree JSON, or ``None`` when it is missing."""
        try:
            st = self._path_for(tree_name).stat()
        except FileNotFoundError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def read_generation(self, tree_name: str) -> Optional[int]:
        """Return ``tree["generation"]["id"]``, or ``None`` for a missing, legacy or malformed tree."""
        try:
            tree = self.load(tree_name)
        except FileNotFoundError:
            return None

        generation = tree.get("generation")
        if not isinstance(generation, dict):
            return None
        generation_id = generation.get("id")
        if type(generation_id) is not int or generation_id < 1:
            return None
        return generation_id

    def delete(self, tree_name: str) -> bool:
        path = self._path_for(tree_name)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def rename(self, src: str, dst: str) -> None:
        """Move a tree JSON without overwriting another tree.

        Raises:
            ValueError: A name is invalid.
            FileNotFoundError: Source JSON does not exist.
            FileExistsError: Destination already exists.
        """
        src_path = self._path_for(src)
        dst_path = self._path_for(dst)
        if not src_path.is_file():
            raise FileNotFoundError(src_path)
        if dst_path.exists():
            raise FileExistsError(dst_path)
        os.replace(src_path, dst_path)
