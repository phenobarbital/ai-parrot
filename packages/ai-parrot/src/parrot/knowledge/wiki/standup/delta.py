"""Stable new/absent item IDs against the previous same-period brief."""

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from parrot.knowledge.wiki.standup.models import PeriodWindow
from parrot.knowledge.wiki.store import BaseWikiStore

logger = logging.getLogger(__name__)

_BRIEF_PREFIXES = {"day": "daily", "week": "weekly", "month": "monthly"}


async def previous_brief(store: BaseWikiStore, window: PeriodWindow) -> dict[str, Any] | None:
    """Select the most recent strictly earlier brief of the same period.

    Args:
        store: Store that supplies attribute-filtered page stubs.
        window: Current period and stable brief identity.

    Returns:
        The latest earlier same-cadence brief stub, or ``None`` on a first run.
    """
    prefix = f"brief:{_BRIEF_PREFIXES[window.period]}:"
    pages = await store.list_by_attrs({"period": window.period}, limit=200)
    candidates = [
        page
        for page in pages
        if isinstance(page.get("concept_id"), str)
        and page["concept_id"].startswith(prefix)
        and page["concept_id"] < window.brief_id
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda page: (str(page.get("attrs", {}).get("date", "")), str(page["concept_id"])))
    return candidates[-1]


def diff(current_ids: Sequence[str], previous_page: Mapping[str, Any] | None) -> tuple[list[str], list[str]]:
    """Return sorted new and absent IDs using the persisted items JSON attribute.

    Args:
        current_ids: IDs selected for the current brief.
        previous_page: Previous brief page stub, if one exists.

    Returns:
        A ``(new_ids, absent_ids)`` tuple. An absent prior page has no delta.
    """
    if previous_page is None:
        return [], []

    attrs = previous_page.get("attrs")
    raw_items = attrs.get("items") if isinstance(attrs, Mapping) else None
    try:
        decoded = json.loads(raw_items) if isinstance(raw_items, str) else None
    except json.JSONDecodeError:
        logger.warning("Previous brief %s has malformed attrs.items", previous_page.get("concept_id", "<unknown>"))
        decoded = None
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        logger.warning("Previous brief %s has invalid attrs.items", previous_page.get("concept_id", "<unknown>"))
        return sorted(set(current_ids)), []

    current = set(current_ids)
    previous = set(decoded)
    return sorted(current - previous), sorted(previous - current)
