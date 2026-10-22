"""Collect jira items without making missing sources fatal."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from parrot.knowledge.wiki.context import qualify_id
from parrot.knowledge.wiki.entities import URGENT_STATUSES, canonical_ticket_status, normalize_frontmatter
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.collectors.entities import _body_frontmatter
from parrot.knowledge.wiki.standup.models import BriefItem
from parrot.knowledge.wiki.store import BaseWikiStore


def _parse_date(value: str | None) -> date | None:
    """Accept ISO calendar and Jira datetime values as calendar dates."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _attrs_from_row(row: Mapping[str, Any]) -> dict[str, str]:
    """Expose a row attrs mapping with string values only."""
    return {str(key): str(value) for key, value in dict(row.get("attrs") or {}).items() if value is not None}


def _personal(attrs: Mapping[str, str], ctx: CollectContext) -> bool:
    """Match account ID first and only use a display name if no ID is usable."""
    if ctx.team:
        return True
    assignee_id = attrs.get("x_assignee_id")
    if assignee_id:
        return bool(ctx.identity.jira_account_id) and assignee_id == ctx.identity.jira_account_id
    assignee = attrs.get("x_assignee")
    return bool(ctx.identity.jira_display_name) and assignee == ctx.identity.jira_display_name


def _in_period(status: str, attrs: Mapping[str, str], ctx: CollectContext) -> bool:
    """Retain open tickets always and closed tickets only for period roll-ups."""
    if status != "closed":
        return True
    if ctx.window.period == "day":
        return False
    ticket_date = _parse_date(attrs.get("date") or attrs.get("x_updated_at") or attrs.get("x_resolved_at"))
    return ticket_date is not None and ctx.window.start <= ticket_date <= ctx.window.end


def _age_days(row: Mapping[str, Any], ctx: CollectContext) -> int | None:
    """Compute age from a page update timestamp when it is ISO-parseable."""
    updated = str(row.get("updated_at") or "")
    try:
        updated_date = datetime.fromisoformat(updated.replace("Z", "+00:00")).date()
    except ValueError:
        return None
    return max(0, (ctx.window.anchor - updated_date).days)


async def _rows(store: BaseWikiStore) -> list[dict[str, Any]]:
    """Read tickets through attrs or parse legacy Jira markdown bodies."""
    if getattr(store, "supports_attrs", False) is True:
        return await store.list_by_attrs({"type": "ticket", "source": ["markdown", "jira"]}, limit=500)
    output: list[dict[str, Any]] = []
    for category in ("document", "entity", "ticket"):
        for stub in await store.list_pages(category=category, limit=500):
            page = await store.get_page(str(stub["concept_id"]), include_body=True)
            frontmatter = _body_frontmatter(page or {})
            if frontmatter is None:
                continue
            attrs = normalize_frontmatter(frontmatter, source="markdown").to_rows()
            if attrs.get("type") == "ticket":
                output.append({**(page or stub), "attrs": attrs})
    return output


async def collect(ctx: CollectContext) -> list[BriefItem]:
    """Return normalized items and append source failures to ctx.diagnostics."""
    try:
        store = ctx.store.scoped("issues") if hasattr(ctx.store, "scoped") else ctx.store
    except (KeyError, ValueError) as exc:
        ctx.diagnostics.append(f"jira:issues unavailable: {exc}")
        return []
    try:
        if getattr(store, "supports_attrs", False) is not True:
            ctx.diagnostics.append("jira:issues attrs unsupported; using body frontmatter fallback")
        items: dict[str, BriefItem] = {}
        for row in await _rows(store):
            attrs = _attrs_from_row(row)
            if attrs.get("source") == "brief" or not _personal(attrs, ctx):
                continue
            raw_status = attrs.get("status_raw") or attrs.get("status")
            status = canonical_ticket_status(raw_status, ctx.cfg.ticket_status_map)
            if status is None:
                status = "open"
                if raw_status:
                    ctx.unmapped_statuses[raw_status] = ctx.unmapped_statuses.get(raw_status, 0) + 1
            if not _in_period(status, attrs, ctx):
                continue
            page_id = str(row.get("concept_id") or "")
            if not page_id:
                continue
            qualified = qualify_id("issues", page_id)
            items.setdefault(
                qualified,
                BriefItem(
                    id=qualified,
                    kind="ticket",
                    title=str(row.get("title") or attrs.get("x_key") or page_id),
                    status=status,
                    status_raw=raw_status,
                    project_hint=attrs.get("project") or attrs.get("x_project"),
                    date=_parse_date(attrs.get("date") or attrs.get("x_updated_at")),
                    due=_parse_date(attrs.get("due")),
                    owner=attrs.get("x_assignee"),
                    urgent=status in URGENT_STATUSES,
                    namespace="issues",
                    url=attrs.get("x_url"),
                    source="jira",
                    age_days=_age_days(row, ctx),
                ),
            )
        return sorted(items.values(), key=lambda item: (not item.urgent, item.date or date.max, item.id))
    except Exception as exc:  # noqa: BLE001 - Jira is an optional source
        ctx.diagnostics.append(f"jira:issues: {exc}")
        return []
