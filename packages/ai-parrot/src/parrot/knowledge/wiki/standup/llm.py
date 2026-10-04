"""Bounded optional synthesis with deterministic fallback bullets."""

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING

from parrot.knowledge.wiki.standup.models import BriefItem, BriefProjection, Period

if TYPE_CHECKING:
    from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter

logger = logging.getLogger(__name__)

MAX_ITEMS = 40
MAX_BULLETS = 3
_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•]+|\d+[.)])\s*")


def _ranked(items: list[BriefItem]) -> list[BriefItem]:
    """Return items ordered urgent-first, then newest date, then stable id."""

    def key(item: BriefItem) -> tuple[int, int, int, str]:
        date = item.date or item.due
        return (0 if item.urgent else 1, 1 if date is None else 0, -date.toordinal() if date else 0, item.id)

    return sorted(items, key=key)


def project_items(items: list[BriefItem], *, period: Period, language: str) -> BriefProjection:
    """Whitelist at most forty ranked items and truncate titles to 120 characters.

    Only kind/title/status/project/age_days/urgent are exposed; bodies, URLs,
    owners and identifiers never reach the model.
    """
    rows: list[dict[str, str | int | bool | None]] = [
        {
            "kind": str(item.kind),
            "title": item.title[:120],
            "status": item.status,
            "project": item.project_hint,
            "age_days": item.age_days,
            "urgent": item.urgent,
        }
        for item in _ranked(items)[:MAX_ITEMS]
    ]
    return BriefProjection(period=period, language=language, items=rows)


def fallback_bullets(items: list[BriefItem], *, language: str) -> list[str]:
    """Return at most three deterministic ranked facts without a model."""
    spanish = language.lower().startswith("es")
    urgent_label = "Urgente" if spanish else "Urgent"
    bullets: list[str] = []
    for item in _ranked(items)[:MAX_BULLETS]:
        parts = [f"{urgent_label}: " if item.urgent else "", item.title[:120]]
        meta = [str(item.kind)]
        if item.status:
            meta.append(item.status)
        if item.project_hint:
            meta.append(item.project_hint)
        bullets.append(f"{''.join(parts)} ({', '.join(meta)})")
    return bullets


def _build_prompt(projection: BriefProjection, language: str) -> str:
    """Build the synthesis prompt from the bounded projection only."""
    return (
        f"Summarize the following {projection.period} work items in language '{language}'. "
        f"Write at most {MAX_BULLETS} short bullet points, one per line, each starting with '- '. "
        "Use ONLY the facts given below; do NOT invent facts, names, dates or numbers.\n\n"
        f"Items (JSON):\n{json.dumps(projection.items, ensure_ascii=False)}"
    )


def _parse_bullets(raw: object) -> list[str] | None:
    """Validate model output: 1..3 non-empty bullet lines, else ``None``."""
    if not isinstance(raw, str):
        return None
    lines = [_BULLET_PREFIX.sub("", line).strip() for line in raw.splitlines() if line.strip()]
    if not lines or len(lines) > MAX_BULLETS or any(not line for line in lines):
        return None
    return lines


async def summarize(
    projection: BriefProjection,
    *,
    language: str,
    adapter: "PageIndexLLMAdapter",
    timeout_s: float = 20.0,
) -> list[str] | None:
    """Generate bounded factual bullets, returning None on failure or invalid output.

    The outer timeout covers adapter retries. Exceptions are logged by type only so
    credentials in provider errors cannot leak.
    """
    prompt = _build_prompt(projection, language)
    try:
        raw = await asyncio.wait_for(adapter.ask(prompt, temperature=0), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning("Brief synthesis timed out after %ss", timeout_s)
        return None
    except Exception as exc:  # noqa: BLE001 — fail safe to deterministic fallback
        logger.warning("Brief synthesis failed (%s)", type(exc).__name__)
        return None
    bullets = _parse_bullets(raw)
    if bullets is None:
        logger.warning("Brief synthesis returned invalid output")
    return bullets
