"""Worktree-aware resolution and opening of the wiki retrieval plane.

Backs the graph-backed `search_code` / `related_code` tools (spec §3
Module 4, §8 Q5). The plane is rooted at a checkout and can be large, so a
per-worktree build is a non-starter — when `repo_root` is a git worktree,
this module resolves the checkout the plane should be shared from instead
of rebuilding it.

Both functions are module-level `async def`s, not toolkit methods —
`AbstractToolkit._generate_tools()` (`tools/toolkit.py:537`) turns every
public `async def` *method* into an LLM-callable tool, so this plumbing
stays outside the class entirely.

This module never builds the plane (spec §1 Non-Goals: "this toolkit is a
pure consumer") and never raises: any failure degrades to a `(None,
reason)` pair or, for `resolve_plane_root`, to `repo_root` unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .models import RepoSearchHit

logger = logging.getLogger(__name__)


async def resolve_plane_root(repo_root: Path) -> Path:
    """Return the checkout whose wiki plane should be queried.

    For a git worktree this is the MAIN checkout, so the (large) plane is
    shared rather than rebuilt per worktree — spec §8 Q5. For a plain
    checkout, and for anything that is not a git repository at all, this is
    ``repo_root`` itself.

    Never raises: a missing ``git``, a non-repo directory, or an unexpected
    git version all fall back to ``repo_root``.

    Args:
        repo_root: The checkout the toolkit is confined to.

    Returns:
        The directory to resolve the wiki project config against.
    """
    root = Path(repo_root).resolve()
    for argv in (
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        ["git", "rev-parse", "--git-common-dir"],  # git < 2.31 fallback
    ):
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(root),
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except (FileNotFoundError, TimeoutError, OSError) as exc:
            logger.debug("resolve_plane_root: %s failed: %s", argv, exc)
            continue
        if proc.returncode != 0:
            continue
        raw = out.decode("utf-8", "replace").strip()
        if not raw:
            continue
        common = Path(raw)
        if not common.is_absolute():
            common = (root / common).resolve()
        plane_root = common.parent
        if plane_root != root:
            logger.info(
                "resolve_plane_root: %s is a worktree — sharing the plane at %s",
                root,
                plane_root,
            )
        return plane_root
    logger.debug("resolve_plane_root: not a git repo — using %s", root)
    return root


async def open_plane(repo_root: Path) -> tuple[Any | None, str]:
    """Open the wiki retrieval plane for ``repo_root``, worktree-aware.

    NEVER builds the plane — spec §1 Non-Goals. When the plane is absent,
    unbuilt, or fails to open, returns ``(None, <reason>)`` so the caller
    can degrade with a reason the model can read.

    Args:
        repo_root: The checkout the toolkit is confined to.

    Returns:
        ``(store, wiki_name)`` on success; ``(None, reason)`` otherwise.
    """
    try:
        from parrot.knowledge.wiki.project import (
            WikiProjectConfig,
            load_project_config,
        )
        from parrot.knowledge.wiki.store import create_wiki_store
    except ImportError as exc:
        return None, f"wiki modules unavailable: {exc}"

    try:
        plane_root = await resolve_plane_root(repo_root)
        config: WikiProjectConfig = load_project_config(plane_root)
        if not config.is_built(plane_root):
            return None, (f"wiki plane not built at {config.storage_path(plane_root)}")
        store = create_wiki_store(
            config.storage_path(plane_root),
            wiki_name=config.wiki_name,
            backend=config.backend,
        )
        return store, config.wiki_name
    except Exception as exc:  # noqa: BLE001
        logger.warning("open_plane failed: %s", exc)
        return None, f"wiki plane unavailable: {exc}"


def map_search_hit(result: Any) -> RepoSearchHit:
    """Map a `WikiSearchResult` onto the toolkit's `RepoSearchHit` shape.

    Field names do NOT line up between the two models: `page_id` comes
    from `node_id` (not `page_id`, which does not exist on the search
    result), `path` comes from `title`, and `summary` comes from
    `snippet` (not `summary`, which likewise does not exist there).
    `outline` is always empty — an API outline needs a page read, which
    a search result does not carry.

    Args:
        result: A `WikiSearchResult`-shaped object (duck-typed via `Any`
            so this module has no import-time dependency on the wiki
            package).

    Returns:
        The equivalent `RepoSearchHit`.
    """
    return RepoSearchHit(
        page_id=result.node_id,
        path=result.title,
        summary=result.snippet,
        outline=[],
        score=result.score,
        approx_tokens=result.token_count or 0,
    )


def map_neighbor_hit(edge: dict[str, Any]) -> RepoSearchHit:
    """Map one `store.neighbors()` edge dict onto `RepoSearchHit`.

    Args:
        edge: A dict as returned by `BaseWikiStore.neighbors()` — carries
            `concept_id`, `rel`, `direction`, and — when the target is a
            known page — `title`/`summary`/`token_count`.

    Returns:
        The equivalent `RepoSearchHit`. No score is available from a
        neighbor edge, so `score` is always `0.0`.
    """
    return RepoSearchHit(
        page_id=str(edge.get("concept_id") or ""),
        path=str(edge.get("title") or ""),
        summary=str(edge.get("summary") or edge.get("rel") or ""),
        outline=[],
        score=0.0,
        approx_tokens=int(edge.get("token_count") or 0),
    )
