"""Collect decisions items without making missing sources fatal."""

from __future__ import annotations

from datetime import date, datetime

from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.models import BriefItem


def _page_date(value: object) -> date | None:
    """Parse a page timestamp as a calendar date."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


async def collect(ctx: CollectContext) -> list[BriefItem]:
    """Return normalized items and append source failures to ctx.diagnostics."""
    try:
        repository = DecisionRepository(ctx.store)
        records = await repository.inventory()
        pages = {str(row.get("concept_id")): row for row in await ctx.store.list_pages(category="adr", limit=10_000)}
        items: list[BriefItem] = []
        for record in records:
            if not (
                record.source_status == "proposed"
                or (record.origin == "inferred" and record.review_status == "unreviewed")
                or (ctx.window.period != "day" and record.source_status == "accepted")
            ):
                continue
            page = pages.get(record.decision_id, {})
            owner = page.get("asserted_by")
            if not ctx.team and owner not in {ctx.identity.wiki, *ctx.identity.aliases}:
                continue
            changed = _page_date(page.get("updated_at"))
            items.append(
                BriefItem(
                    id=record.decision_id,
                    kind="decision",
                    title=record.title or record.decision_id,
                    status=record.source_status if record.origin == "documented" else record.review_status,
                    date=changed,
                    owner=str(owner) if owner else None,
                    source="decision",
                    age_days=max(0, (ctx.window.anchor - changed).days) if changed else None,
                )
            )
        return sorted(items, key=lambda item: (item.date or date.max, item.id))
    except Exception as exc:  # noqa: BLE001 - decisions are an optional source
        ctx.diagnostics.append(f"decisions: {exc}")
        return []
