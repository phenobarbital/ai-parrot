"""Generation publication primitives for PageIndex trees (FEAT-831)."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel

from parrot.knowledge.okf.utils import flatten_concept_id_for_filename
from parrot.knowledge.pageindex.okf.concept_id import derive_concept_id

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
