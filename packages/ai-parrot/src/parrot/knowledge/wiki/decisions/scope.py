"""Typed target resolution and scope for decision targets (FEAT-784 Module 4)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path, PurePosixPath
from typing import Literal

from parrot.knowledge.wiki.decisions.evidence import _resolve_confined
from parrot.knowledge.wiki.decisions.models import (
    SCOPE_INCOMPLETE,
    TARGET_FOREIGN,
    TARGET_UNRESOLVED,
    DecisionDiagnostic,
    DecisionError,
    DecisionTarget,
    _Strict,
)
from parrot.knowledge.wiki.repo_scan import dir_concept_id, discover_repo_files, file_concept_id
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.structural.service import StructuralService

_KINDS = {"sym:": "symbol", "file:": "file", "dir:": "dir"}


class ResolvedTarget(_Strict):
    """Outcome of resolving one exact target id."""

    target: DecisionTarget
    page_id: str | None
    ancestors: list[str]
    descendants: list[str]
    state: Literal["resolved", "missing", "unsupported", "stale", "incomplete"]


def _split(target_id: str) -> tuple[str, str] | None:
    """Return ``(kind, rel_path)`` or ``None`` for an unsupported prefix.

    Args:
        target_id: Exact typed target id.

    Returns:
        ``(kind, rel_path)``; ``rel_path`` is ``"."`` for the repository root.
    """
    if "::" in target_id:
        return None
    for prefix, kind in _KINDS.items():
        if not target_id.startswith(prefix):
            continue
        rest = target_id[len(prefix) :]
        if kind == "symbol":
            rel, sep, qual = rest.partition("#")
            if not sep or not rel or not qual:
                return None
        else:
            if "#" in rest:
                return None
            rel = rest
        if kind == "dir":
            rel = rel or "."
        elif not rel:
            return None
        return kind, rel
    return None


def _parent_dir(rel: str) -> str:
    """Return the parent directory of a repo-relative path (``"."`` for top level)."""
    parent = str(PurePosixPath(rel).parent)
    return parent if parent not in ("", ".") else "."


class TargetResolver:
    """Exact-id validation against the structural plane and the confined repository root."""

    def __init__(self, store: BaseWikiStore, root: Path, structural: StructuralService) -> None:
        self._store = store
        self._root = root
        self._structural = structural
        self.logger = logging.getLogger(__name__)

    async def resolve(self, target_id: str) -> tuple[ResolvedTarget | None, list[DecisionDiagnostic]]:
        """Exact id only; missing ⇒ TARGET_UNRESOLVED (+ suggestions); foreign/outside root ⇒ TARGET_FOREIGN.

        Args:
            target_id: Exact typed target id.

        Returns:
            The resolved target (or ``None`` when foreign) plus diagnostics.
        """
        parts = _split(target_id)
        if parts is None:
            return None, [DecisionDiagnostic(code=TARGET_FOREIGN, message=f"unsupported target id {target_id!r}")]
        kind, rel = parts
        try:
            _resolve_confined(self._root, rel)
        except DecisionError as exc:
            return None, [DecisionDiagnostic(code=TARGET_FOREIGN, message=str(exc))]
        target = DecisionTarget(target_id=target_id, kind=kind)
        ancestors = await self.ancestors_of(target_id)
        page = await self._store.get_page(target_id, include_body=False)
        if page is None:
            if kind == "symbol":
                query = target_id.partition("#")[2]
            else:
                query = PurePosixPath(rel).name or rel
            suggestions: list[str] = []
            try:
                found = await self._structural.lookup(query, limit=3)
                suggestions = [h.symbol_id for h in found.hits][:3]
            except Exception as exc:  # suggestions are best-effort, never acceptance
                self.logger.debug("suggestion lookup failed for %r: %s", target_id, exc)
            message = f"target {target_id!r} does not exist in the structural plane"
            if suggestions:
                message += "; did you mean: " + ", ".join(suggestions)
            resolved = ResolvedTarget(target=target, page_id=None, ancestors=ancestors, descendants=[], state="missing")
            return resolved, [DecisionDiagnostic(code=TARGET_UNRESOLVED, message=message)]
        descendants: list[str] = []
        diagnostics: list[DecisionDiagnostic] = []
        state: Literal["resolved", "incomplete"] = "resolved"
        if kind == "dir":
            descendants, complete = await self.expand_dir(target_id)
            if not complete:
                state = "incomplete"
                diagnostics.append(
                    DecisionDiagnostic(
                        code=SCOPE_INCOMPLETE,
                        message=f"directory {target_id!r} has descendant files without structural pages",
                    )
                )
        resolved = ResolvedTarget(
            target=target, page_id=target_id, ancestors=ancestors, descendants=descendants, state=state
        )
        return resolved, diagnostics

    async def ancestors_of(self, page_id: str) -> list[str]:
        """file: then every dir: ancestor up to the repo root (``dir:.``).

        Args:
            page_id: A ``sym:``, ``file:`` or ``dir:`` id.

        Returns:
            Ancestor ids, nearest first; empty for an unsupported id or ``dir:.``.
        """
        parts = _split(page_id)
        if parts is None:
            return []
        kind, rel = parts
        out: list[str] = []
        if kind == "symbol":
            out.append(file_concept_id(rel))
            current = _parent_dir(rel)
        elif kind == "file":
            current = _parent_dir(rel)
        else:
            norm = str(PurePosixPath(rel))
            if norm == ".":
                return []
            current = _parent_dir(norm)
        while True:
            out.append(dir_concept_id("" if current == "." else current))
            if current == ".":
                break
            current = _parent_dir(current)
        return out

    async def expand_dir(self, dir_id: str) -> tuple[list[str], bool]:
        """(descendant page ids, complete) — complete=False when scan coverage is partial.

        Args:
            dir_id: A ``dir:`` id.

        Returns:
            Sorted descendant ``file:`` ids and whether every one has a hashed page.
        """
        parts = _split(dir_id)
        if parts is None or parts[0] != "dir":
            return [], False
        rel = str(PurePosixPath(parts[1]))
        files = await asyncio.to_thread(discover_repo_files, self._root)
        if rel == ".":
            kept = list(files)
        else:
            kept = [f for f in files if f == rel or f.startswith(rel + "/")]
        ids = sorted({file_concept_id(f) for f in kept})
        if not ids:
            return [], True
        hashes = await self._store.page_hashes(ids)
        complete = all(hashes.get(i) is not None for i in ids)
        return ids, complete
