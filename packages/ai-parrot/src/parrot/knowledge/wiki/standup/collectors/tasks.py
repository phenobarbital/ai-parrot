"""Collect tasks items without making missing sources fatal."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.models import BriefItem


def _read_indexes(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Read task indexes synchronously for execution in a worker thread."""
    items: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    directory = root / "sdd" / "tasks" / "index"
    if not directory.exists():
        return items, ["tasks: index root unavailable"]
    for path in sorted(directory.glob("*.json")):
        if path.name == "_orphans.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            tasks = payload["tasks"]
            if not isinstance(tasks, list):
                raise TypeError("tasks is not a list")
        except (OSError, KeyError, json.JSONDecodeError, TypeError) as exc:
            diagnostics.append(f"tasks:{path.name}: {exc}")
            continue
        for task in tasks:
            if isinstance(task, dict):
                items.append(task)
    return items, diagnostics


async def collect(ctx: CollectContext) -> list[BriefItem]:
    """Return normalized items and append source failures to ctx.diagnostics."""
    try:
        rows, diagnostics = await asyncio.to_thread(_read_indexes, ctx.root)
        ctx.diagnostics.extend(diagnostics)
        statuses = {str(row.get("id")): str(row.get("status")) for row in rows if row.get("id")}
        allowed = {ctx.identity.wiki, *ctx.identity.aliases}
        items: list[BriefItem] = []
        for row in rows:
            task_id = row.get("id")
            status = row.get("status")
            assigned_to = row.get("assigned_to")
            if not isinstance(task_id, str) or status not in ("in-progress", "pending"):
                continue
            if not ctx.team and assigned_to not in allowed:
                continue
            ready = status == "pending" and all(statuses.get(str(dep)) == "done" for dep in row.get("depends_on", []))
            if status == "pending" and not ready:
                continue
            items.append(
                BriefItem(
                    id=task_id,
                    kind="task",
                    title=str(row.get("title") or task_id),
                    status=status,
                    status_raw="ready" if ready else None,
                    project_hint=str(row["feature"]) if row.get("feature") else None,
                    owner=str(assigned_to) if assigned_to else None,
                    source="task-index",
                )
            )
        return sorted(items, key=lambda item: item.id)
    except Exception as exc:  # noqa: BLE001 - task indexes are an optional source
        ctx.diagnostics.append(f"tasks: {exc}")
        return []
