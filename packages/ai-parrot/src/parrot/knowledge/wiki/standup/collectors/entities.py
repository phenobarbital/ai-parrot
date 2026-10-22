"""Collect entity items without making missing sources fatal."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import PurePosixPath
import re
from typing import Any

from parrot.knowledge.wiki.context import qualify_id
from parrot.knowledge.wiki.entities import OPEN_STATUSES, URGENT_STATUSES, normalize_frontmatter, parse_leading_yaml
from parrot.knowledge.wiki.federation import FederatedWikiStore
from parrot.knowledge.wiki.file_suffixes import DOC_SUFFIXES
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.models import BriefItem
from parrot.knowledge.wiki.store import BaseWikiStore

_WRAPPER_RE = re.compile(r"\A# [^\n]*\n\n## Content(?: \(truncated\))?\n(?P<content>.*)\Z", re.DOTALL)
_ENTITY_TYPES = ("meeting", "decision", "deliverable")
_FALLBACK_CATEGORIES = ("document", "entity", "meeting", "decision", "deliverable")


def _planes(store: BaseWikiStore) -> Iterable[tuple[str | None, str, BaseWikiStore]]:
    """Yield every concrete plane rather than using a composed capability flag."""
    if isinstance(store, FederatedWikiStore):
        yield store._local_prefix, store.local_name, store.local
        for name, handle in store.namespaces.items():
            yield name, name, handle.store
        return
    yield None, "local", store


def _body_frontmatter(page: Mapping[str, Any]) -> dict[str, Any] | None:
    """Parse stored frontmatter, including the verified repo-scan wrapper."""
    body = str(page.get("body") or "")
    concept_id = str(page.get("concept_id") or "")
    if concept_id.startswith("file:") and PurePosixPath(concept_id[5:]).suffix.lower() in DOC_SUFFIXES:
        match = _WRAPPER_RE.match(body)
        if match:
            body = match.group("content")
    return parse_leading_yaml(body.lstrip("\n"))


def _parse_date(value: str | None) -> date | None:
    """Return an ISO calendar date when a source attribute supplies one."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _matches_window(attrs: Mapping[str, str], ctx: CollectContext) -> bool:
    """Apply the entity vocabulary's meeting, decision, and draft rules."""
    kind = attrs.get("type")
    status = attrs.get("status")
    if kind == "meeting":
        value = _parse_date(attrs.get("date"))
        return value is not None and ctx.window.recent_start <= value <= ctx.window.upcoming_end
    return kind in ("decision", "deliverable") and status in OPEN_STATUSES[kind]


def _is_personal(attrs: Mapping[str, str], ctx: CollectContext) -> bool:
    """Keep unowned entities, and filter explicitly-owned items in personal mode."""
    if ctx.team:
        return True
    owner = attrs.get("owner")
    return owner is None or owner in {ctx.identity.wiki, *ctx.identity.aliases}


def _item(row: Mapping[str, Any], attrs: Mapping[str, str], namespace: str | None) -> BriefItem | None:
    """Adapt one normalized entity row to a brief item."""
    kind = attrs.get("type")
    if kind not in _ENTITY_TYPES:
        return None
    page_id = str(row.get("concept_id") or "")
    if not page_id or attrs.get("source") == "brief" or str(row.get("category") or "") == "brief":
        return None
    status = attrs.get("status")
    return BriefItem(
        id=qualify_id(namespace, page_id),
        kind=kind,
        title=str(row.get("title") or page_id),
        status=status,
        status_raw=attrs.get("status_raw"),
        project_hint=attrs.get("project"),
        date=_parse_date(attrs.get("date")),
        due=_parse_date(attrs.get("due")),
        owner=attrs.get("owner"),
        urgent=attrs.get("urgent", "").casefold() == "true" or status in URGENT_STATUSES,
        namespace=namespace,
        url=attrs.get("x_url"),
        source=attrs.get("source") or "entity",
    )


async def _attr_rows(store: BaseWikiStore) -> list[dict[str, Any]]:
    """Read attrs rows without applying a date filter that would hide open entities."""
    return await store.list_by_attrs({"type": list(_ENTITY_TYPES)}, limit=500)


async def _fallback_rows(store: BaseWikiStore) -> list[dict[str, Any]]:
    """Read the supported legacy document/entity categories once per plane."""
    rows: dict[str, dict[str, Any]] = {}
    for category in _FALLBACK_CATEGORIES:
        for row in await store.list_pages(category=category, limit=500):
            page_id = str(row.get("concept_id") or "")
            if page_id:
                rows.setdefault(page_id, row)
    return list(rows.values())


async def collect(ctx: CollectContext) -> list[BriefItem]:
    """Return normalized items and append source failures to ctx.diagnostics."""
    items: dict[str, BriefItem] = {}
    for namespace, name, store in _planes(ctx.store):
        try:
            if getattr(store, "supports_attrs", False) is True:
                rows = await _attr_rows(store)
                normalized = ((row, dict(row.get("attrs") or {})) for row in rows)
            else:
                ctx.diagnostics.append(f"entities:{name}: attrs unsupported; using body frontmatter fallback")
                rows = await _fallback_rows(store)
                normalized_rows: list[tuple[dict[str, Any], dict[str, str]]] = []
                for row in rows:
                    page = await store.get_page(str(row["concept_id"]), include_body=True)
                    frontmatter = _body_frontmatter(page or {})
                    if frontmatter is None:
                        continue
                    attrs = normalize_frontmatter(frontmatter, source="markdown").to_rows()
                    if attrs:
                        normalized_rows.append((page or row, attrs))
                normalized = iter(normalized_rows)
            for row, attrs in normalized:
                if not _matches_window(attrs, ctx) or not _is_personal(attrs, ctx):
                    continue
                item = _item(row, attrs, namespace)
                if item is not None:
                    items.setdefault(item.id, item)
        except Exception as exc:  # noqa: BLE001 - a source must not make a brief fail
            ctx.diagnostics.append(f"entities:{name}: {exc}")
    return sorted(items.values(), key=lambda item: (item.date or date.max, item.id))
