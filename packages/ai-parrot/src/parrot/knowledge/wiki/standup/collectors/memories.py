"""Collect memories items without making missing sources fatal."""

from __future__ import annotations

from datetime import date, datetime

from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.models import BriefItem


def _updated_date(value: object) -> date | None:
    """Parse a page timestamp as an ISO calendar date."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


async def collect(ctx: CollectContext) -> list[BriefItem]:
    """Return normalized items and append source failures to ctx.diagnostics."""
    try:
        pages = await ctx.store.list_pages(origin=["memory", "authored"], limit=10_000)
        allowed = {ctx.identity.wiki, *ctx.identity.aliases}
        items: list[BriefItem] = []
        for page in pages:
            page_id = page.get("concept_id")
            category = str(page.get("category") or "")
            changed = _updated_date(page.get("updated_at"))
            owner = page.get("asserted_by")
            if (
                not isinstance(page_id, str)
                or category not in {"note", "concept", "lesson", "decision"}
                or changed is None
                or not (ctx.window.start <= changed <= ctx.window.end)
                or (not ctx.team and owner not in allowed)
            ):
                continue
            kind = "decision" if category == "decision" else "deliverable"
            items.append(
                BriefItem(
                    id=page_id,
                    kind=kind,
                    title=str(page.get("title") or page_id),
                    date=changed,
                    owner=str(owner) if owner else None,
                    source="memory",
                    age_days=max(0, (ctx.window.anchor - changed).days),
                )
            )
        return sorted(items, key=lambda item: (item.date or date.max, item.id))
    except Exception as exc:  # noqa: BLE001 - memories are an optional source
        ctx.diagnostics.append(f"memories: {exc}")
        return []
