"""Generation publication primitives for PageIndex trees (FEAT-831)."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel

from parrot.knowledge.okf.utils import flatten_concept_id_for_filename
from parrot.knowledge.pageindex.okf.concept_id import derive_concept_id
from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.locks import TreeLockTimeout, tree_lock  # noqa: F401
from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.utils import structure_to_list

_FLAT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SHA16_RE = re.compile(r"^[0-9a-f]{16}$")


class GenerationInfo(BaseModel):
    """Stored under ``tree[\"generation\"]`` for published trees."""

    id: int
    published_at: str
    parent: Optional[int] = None


class BodyRef(BaseModel):
    """Address of an immutable body blob: ``<flat_concept_id>.<sha16>``."""

    flat_concept_id: str
    sha16: str

    @property
    def key(self) -> str:
        """Return the serialized body reference."""
        return f"{self.flat_concept_id}.{self.sha16}"

    @classmethod
    def parse(cls, value: str) -> "BodyRef":
        """Parse ``value`` and validate both components of its key."""
        flat_concept_id, separator, sha16 = value.rpartition(".")
        if not separator or not _FLAT_RE.fullmatch(flat_concept_id) or not _SHA16_RE.fullmatch(sha16):
            raise ValueError(f"Invalid body reference: {value!r}")
        return cls(flat_concept_id=flat_concept_id, sha16=sha16)


class PublishReport(BaseModel):
    """Returned by publication operations."""

    tree_name: str
    generation: int
    bodies_written: int = 0
    bodies_swept: int = 0
    okf_projected: bool = False


class StaleGenerationError(RuntimeError):
    """The candidate's base generation is no longer the live one."""


def flatten_concept_id(concept_id: str) -> str:
    """Flatten ``concept_id`` exactly like OKF sidecar filenames."""
    return flatten_concept_id_for_filename(concept_id)


def body_sha16(markdown: str) -> str:
    """Return the first 16 hex characters of the markdown's SHA-256 digest."""
    return hashlib.sha256((markdown or "").encode("utf-8")).hexdigest()[:16]


def generation_of(tree: dict[str, Any]) -> Optional[GenerationInfo]:
    """Return generation metadata, or ``None`` for a legacy tree."""
    raw = tree.get("generation")
    return GenerationInfo.model_validate(raw) if isinstance(raw, dict) else None


def next_generation(base: Optional[GenerationInfo]) -> GenerationInfo:
    """Return the next UTC generation after ``base`` or a new tree."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return GenerationInfo(id=base.id + 1 if base else 1, published_at=now, parent=base.id if base else None)


def ensure_concept_ids(tree: dict[str, Any]) -> int:
    """Assign missing concept ids depth-first and return the number assigned.

    Existing ids are preserved, and each child derives its id from its
    parent's concept id.
    """
    assigned = 0

    def walk(nodes: list[dict[str, Any]], parent_path: str) -> None:
        nonlocal assigned
        for node in nodes:
            if not node.get("concept_id"):
                node["concept_id"] = derive_concept_id(node.get("title", ""), parent_path)
                assigned += 1
            children = node.get("nodes") or []
            if children:
                walk(children, node["concept_id"])

    structure = tree.get("structure") or []
    walk(structure, "")
    return assigned


class WriteTransaction:
    """Copy-on-write unit of work for one tree; created only by ``PageIndexToolkit``."""

    def __init__(
        self,
        *,
        tree_name: str,
        base_tree: dict[str, Any],
        base_signature: tuple[int, int] | None,
        store: JSONTreeStore,
        content_store: NodeContentStore,
        storage_dir: Path,
        lock_timeout_s: float,
        grace_s: int,
        projector: Callable[[dict[str, Any], str], bool],
    ) -> None:
        self.tree_name = tree_name
        self.tree: dict[str, Any] = copy.deepcopy(base_tree)
        self.base_generation: Optional[GenerationInfo] = generation_of(base_tree)
        self.base_signature = base_signature
        self.published_signature: tuple[int, int] | None = None
        self._store = store
        self._content = content_store
        self._storage_dir = Path(storage_dir)
        self._lock_timeout_s = lock_timeout_s
        self._grace_s = grace_s
        self._projector = projector
        self._staged: dict[str, str] = {}
        self._published = False
        #: Set by a mutator that changed nothing; the outermost ``_write`` then skips publication.
        self.noop = False
        base_nodes = structure_to_list(base_tree.get("structure", []))
        # Bodies the base generation served; restarted in the sweep clock when superseded.
        self._base_body_keys: set[str] = {n["body_ref"] for n in base_nodes if isinstance(n.get("body_ref"), str)}
        # Pre-FEAT-831 nodes still served from legacy ``<node_id>.md`` files.
        self._base_legacy_ids: set[str] = {
            n["node_id"]
            for n in base_nodes
            if not n.get("body_ref") and isinstance(n.get("node_id"), str) and n["node_id"]
        }

    def set_body(self, node: dict[str, Any], markdown: str) -> BodyRef:
        """Stage ``markdown`` for ``node`` and set its immutable body reference."""
        if not node.get("concept_id"):
            ensure_concept_ids(self.tree)
        concept_id = node.get("concept_id")
        if not isinstance(concept_id, str) or not concept_id:
            raise ValueError("node must have a concept_id before staging a body")
        try:
            body_ref = BodyRef.parse(f"{flatten_concept_id(concept_id)}.{body_sha16(markdown)}")
        except ValueError as exc:
            raise ValueError(f"concept_id {concept_id!r} cannot be used as a body reference") from exc
        self._staged[body_ref.key] = markdown or ""
        node["body_ref"] = body_ref.key
        return body_ref

    def drop_body(self, node: dict[str, Any]) -> None:
        """Remove ``body_ref`` from ``node``; the blob is left for the sweep."""
        node.pop("body_ref", None)

    def live_body_keys(self) -> set[str]:
        """Return every ``body_ref`` in ``self.tree``."""
        return {node["body_ref"] for node in structure_to_list(self.tree.get("structure", [])) if node.get("body_ref")}

    @staticmethod
    def _fsync_bodies_dir(path: Path) -> None:
        """Fsync the directory containing staged body blobs."""
        if not path.is_dir():
            return
        directory_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    async def publish(self) -> PublishReport:
        """Publish the candidate under the tree lock."""
        if self._published:
            raise RuntimeError("transaction already published")

        async with tree_lock(self._storage_dir, self.tree_name, timeout=self._lock_timeout_s):
            return await self._publish_locked()

    async def publish_locked(self) -> PublishReport:
        """Publish when the caller already holds ``tree_lock`` for this tree.

        Use this when an existence check or cleanup must be atomic with the
        publication itself (``create_tree``); the lock is not re-entrant.
        """
        if self._published:
            raise RuntimeError("transaction already published")
        return await self._publish_locked()

    async def _publish_locked(self) -> PublishReport:
        """Steps 2-8 of publication; the tree lock is held by the caller."""
        current_signature = self._store.signature(self.tree_name)
        current_generation = self._store.read_generation(self.tree_name)
        base_id = self.base_generation.id if self.base_generation else None
        if current_signature != self.base_signature:
            if self.base_signature is None or base_id is None or current_generation != base_id:
                raise StaleGenerationError(f"tree {self.tree_name!r} changed since transaction construction")
        elif base_id is not None and current_generation != base_id:
            # Equal signatures can still hide a publish that landed between the
            # snapshot's load and its stat; the generation id is authoritative.
            raise StaleGenerationError(f"tree {self.tree_name!r} changed since transaction construction")

        ensure_concept_ids(self.tree)
        for node in structure_to_list(self.tree.get("structure", [])):
            raw_ref = node.get("body_ref")
            if not raw_ref:
                continue
            try:
                body_ref = BodyRef.parse(raw_ref)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid body_ref for node {node.get('node_id', '<unknown>')!r}") from exc
            if (
                body_ref.key not in self._staged
                and not self._content.body_path(self.tree_name, body_ref.key).is_file()
            ):
                raise ValueError(f"missing body for node {node.get('node_id', '<unknown>')!r}")

        staged_keys = [key for key in self._staged if not self._content.body_path(self.tree_name, key).is_file()]
        await asyncio.gather(
            *(
                asyncio.to_thread(self._content.save_body, self.tree_name, key, self._staged[key])
                for key in self._staged
            )
        )
        await asyncio.to_thread(self._fsync_bodies_dir, self._content.bodies_dir(self.tree_name))

        okf_projected = await asyncio.to_thread(self._projector, self.tree, self.tree_name)
        generation = next_generation(self.base_generation)
        self.tree["generation"] = generation.model_dump()
        self.published_signature = self._store.save(self.tree_name, self.tree)
        self._published = True
        # Grace runs from supersession: restart the clock of everything this
        # generation stopped referencing before the sweep ages files by mtime.
        await asyncio.to_thread(
            self._content.mark_superseded,
            self.tree_name,
            self._base_body_keys - self.live_body_keys(),
            self._base_legacy_ids,
        )
        bodies_swept = await asyncio.to_thread(
            self._content.sweep_unreferenced, self.tree_name, self.tree, max_age_s=self._grace_s
        )

        return PublishReport(
            tree_name=self.tree_name,
            generation=generation.id,
            bodies_written=len(staged_keys),
            bodies_swept=bodies_swept,
            okf_projected=okf_projected,
        )
