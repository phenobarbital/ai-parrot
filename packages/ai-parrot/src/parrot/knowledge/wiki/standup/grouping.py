"""Deterministic project lookup, sections and activity ordering."""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.models import BriefItem, BriefSection, ProjectSlice

logger = logging.getLogger(__name__)

INTERNAL = "Internal"
SECTION_ORDER = ("blocked", "tickets", "recent", "upcoming", "decisions", "drafts", "tasks", "memories")
_SDD_SOURCES = frozenset({"sdd", "tasks", "task", "task-index"})
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    """Normalise a title or hint to a comparable slug."""
    return _SLUG_RE.sub("-", value.strip().lower()).strip("-")


async def _project_pages(ctx: CollectContext) -> list[dict[str, Any]]:
    """Read project page stubs through the attrs seam; empty when unsupported."""
    store = ctx.store
    if getattr(store, "supports_attrs", False) is not True:
        return []
    try:
        return list(await store.list_by_attrs({"type": "project"}, limit=500))
    except Exception as exc:  # noqa: BLE001 - project metadata is optional
        ctx.diagnostics.append(f"grouping:projects: {exc}")
        return []


async def _match_page(hint: str, ctx: CollectContext, pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Match a hint to a project page by id, then by title slug."""
    try:
        page = await ctx.store.get_page(hint, include_body=False)
    except Exception as exc:  # noqa: BLE001 - lookup failure falls through the chain
        ctx.diagnostics.append(f"grouping:get_page: {exc}")
        page = None
    if page:
        attrs = page.get("attrs") or {}
        if attrs.get("type") == "project" or any(str(p.get("concept_id")) == hint for p in pages):
            return page
    hint_slug = _slug(hint)
    for stub in sorted(pages, key=lambda p: str(p.get("concept_id"))):
        if hint_slug and _slug(str(stub.get("title") or "")) == hint_slug:
            return stub
    return None


async def _resolve(item: BriefItem, ctx: CollectContext, pages: list[dict[str, Any]]) -> tuple[str, str | None]:
    """Return ``(project label, project status)`` for an item."""
    hint = (item.project_hint or "").strip()
    if not hint:
        return INTERNAL, None
    page = await _match_page(hint, ctx, pages)
    if page is not None:
        attrs = page.get("attrs") or {}
        return str(page.get("title") or hint), attrs.get("status")
    mapped = ctx.cfg.project_map.get(hint)
    if mapped:
        mapped_page = await _match_page(mapped, ctx, pages)
        if mapped_page is not None:
            return str(mapped_page.get("title") or mapped), (mapped_page.get("attrs") or {}).get("status")
        return mapped, None
    if item.source == "jira" or item.kind == "ticket":
        return hint, None
    if item.source in _SDD_SOURCES or item.kind == "task":
        return hint, None
    return INTERNAL, None


async def resolve_project(item: BriefItem, ctx: CollectContext) -> str:
    """Resolve a project label using the precedence fixed by M5.

    Precedence: project page id, project page title slug, configured
    ``project_map``, raw Jira project key, SDD feature slug, then ``Internal``.
    """
    label, _status = await _resolve(item, ctx, await _project_pages(ctx))
    return label


def _section_for(item: BriefItem, ctx: CollectContext) -> str:
    """Route an item to exactly one section key."""
    if item.status == "blocked":
        return "blocked"
    if item.source == "memory" or item.source == "memories":
        return "memories"
    if item.kind == "ticket":
        return "tickets"
    if item.kind == "task":
        return "tasks"
    if item.kind == "decision":
        return "decisions"
    if item.kind == "deliverable":
        return "drafts"
    if item.kind == "meeting" and item.date is not None:
        return "upcoming" if item.date >= ctx.window.anchor else "recent"
    return "recent"


def _sort_key(item: BriefItem) -> tuple[bool, date, str]:
    """Urgent first, then due/date ascending, then id."""
    return (not item.urgent, item.due or item.date or date.max, item.id)


def _build_sections(items: list[BriefItem], ctx: CollectContext) -> list[BriefSection]:
    """Bucket items into non-empty ordered sections."""
    buckets: dict[str, list[BriefItem]] = {}
    for item in items:
        buckets.setdefault(_section_for(item, ctx), []).append(item)
    return [BriefSection(key=key, items=sorted(buckets[key], key=_sort_key)) for key in SECTION_ORDER if buckets.get(key)]


async def group_items(items: list[BriefItem], ctx: CollectContext) -> tuple[list[ProjectSlice], list[BriefSection]]:
    """Return activity-sorted projects and Internal sections with stable item order."""
    pages = await _project_pages(ctx)
    by_project: dict[str, list[BriefItem]] = {}
    statuses: dict[str, str | None] = {}
    for item in sorted(items, key=lambda i: i.id):
        label, status = await _resolve(item, ctx, pages)
        by_project.setdefault(label, []).append(item)
        if status and not statuses.get(label):
            statuses[label] = status
    internal = _build_sections(by_project.pop(INTERNAL, []), ctx)
    projects = [
        ProjectSlice(
            project=label,
            status=statuses.get(label),
            sections=_build_sections(members, ctx),
            activity=len(members),
        )
        for label, members in by_project.items()
    ]
    projects.sort(key=lambda p: (-p.activity, p.project))
    return projects, internal
