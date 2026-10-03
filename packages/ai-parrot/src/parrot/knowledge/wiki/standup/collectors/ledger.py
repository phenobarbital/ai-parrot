"""Collect ledger items without making missing sources fatal."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.project import find_shared_root
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.models import BriefItem


def _in_progress_features(root: Path) -> list[str]:
    """Return feature ids whose task indexes are in progress."""
    result: set[str] = set()
    for path in sorted((root / "sdd" / "tasks" / "index").glob("*.json")):
        if path.name == "_orphans.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        feature_id = payload.get("feature_id")
        tasks = payload.get("tasks")
        if isinstance(feature_id, str) and isinstance(tasks, list) and any(
            isinstance(task, dict) and task.get("status") == "in-progress" for task in tasks
        ):
            result.add(feature_id)
    return sorted(result)


async def collect(ctx: CollectContext) -> list[BriefItem]:
    """Return normalized items and append source failures to ctx.diagnostics."""
    try:
        shared_root = find_shared_root(ctx.root)
        if shared_root is None:
            ctx.diagnostics.append("ledger: shared root unavailable")
            return []
        service = LedgerService.from_root(shared_root)
        rows = await service.list_issues(("open", "claimed"))
        blockers: set[str] = set()
        for feature_id in await asyncio.to_thread(_in_progress_features, shared_root):
            blockers.update(str(row.get("issue_id")) for row in await service.merge_blockers(feature_id))
        items = [
            BriefItem(
                id=str(row["issue_id"]),
                kind="ticket",
                title=str(row.get("title") or row["issue_id"]),
                status="blocked" if str(row.get("issue_id")) in blockers else str(row.get("status") or "open"),
                owner=str(row["claimed_by"]) if row.get("claimed_by") else None,
                urgent=str(row.get("issue_id")) in blockers,
                source="ledger",
            )
            for row in rows
            if ctx.team
            or not row.get("claimed_by")
            or str(row.get("claimed_by")) in {ctx.identity.wiki, *ctx.identity.aliases}
        ]
        return sorted(items, key=lambda item: (not item.urgent, item.id))
    except Exception as exc:  # noqa: BLE001 - ledger is an optional source
        ctx.diagnostics.append(f"ledger: {exc}")
        return []
