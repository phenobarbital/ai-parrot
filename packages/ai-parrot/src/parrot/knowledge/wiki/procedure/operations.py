"""Transport-neutral procedure operations (FEAT-891)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from parrot.knowledge.wiki import project
from parrot.knowledge.wiki.operations import OperationResult
from parrot.knowledge.wiki.procedure.models import INDEX_FILE, PLANE_DIR

PROCEDURE_NEXT_DESCRIPTION = (
    "Deterministic next step in this repository's procedure graph: the procedures that apply to a feature or "
    "task, which step is valid next, which preconditions are unmet, and the mandatory rules ahead. "
    "Local checks only; no LLM call."
)


class ProcedureNextInput(BaseModel):
    """Arguments for ``wiki_procedure_next``."""

    feature: str | None = Field(default=None, description="Feature slug or FEAT id; default: from the current branch.")
    task: str | None = Field(default=None, description="Task id, e.g. TASK-123.")


def procedure_plane_available(root: Path | None) -> bool:
    """True when ``<shared-root>/.parrot/procedure/procedures.json`` exists for ``root``."""
    if root is None:
        return False
    shared = project.find_shared_root(Path(root))
    return shared is not None and (shared / PLANE_DIR / INDEX_FILE).is_file()


def _check_text(result: Any) -> str:
    """Render one unresolved precondition without exposing procedure internals."""
    check = result.check
    if result.value is None:
        state = result.detail or "unknown"
    else:
        state = f"got {result.value!r}, expected {check.expect!r}"
    return f"{check.probe}: {state}"


def _resolution_payload(resolution: Any) -> dict[str, Any]:
    """Return the stable, trimmed MCP payload for a procedure resolution."""
    next_steps = []
    for item in resolution.next:
        next_steps.append(
            {
                "id": item.spec.id,
                "title": item.spec.title,
                "mode": item.spec.mode,
                "command": item.spec.command,
                "advice": item.spec.advice,
                "unmet": [_check_text(check) for check in item.preconditions if check.value is not True],
            }
        )
    mandatory = [
        {"id": spec.id, "command": spec.command, "use_instead": spec.use_instead} for spec in resolution.mandatory
    ]
    return {"scope": resolution.scope, "stale": resolution.stale, "next": next_steps, "mandatory": mandatory}


def _resolution_text(data: dict[str, Any]) -> str:
    """Render a compact plain-text summary of the trimmed resolution payload."""
    scope = data["scope"]
    scope_text = ", ".join(f"{key}={value}" for key, value in scope.items()) or "none"
    lines = [f"scope: {scope_text}", f"stale: {data['stale']}", "next:"]
    next_steps = data["next"]
    if next_steps:
        lines.extend(
            f"- {item['id']} ({item['mode']}): {item['title']} — {item['command'] or item['advice'] or 'no command'}"
            for item in next_steps[:6]
        )
        if len(next_steps) > 6:
            lines.append(f"- ... and {len(next_steps) - 6} more")
    else:
        lines.append("- none")
    mandatory = data["mandatory"]
    mandatory_text = "; ".join(
        f"{item['id']}: {item['command'] or item['use_instead'] or 'no command'}" for item in mandatory
    )
    lines.append(f"mandatory: {mandatory_text or 'none'}")
    return "\n".join(lines[:10])


async def op_procedure_next(store: Any, params: ProcedureNextInput, **context: Any) -> OperationResult:
    """Resolve the next valid procedure step(s) for ``context['root']`` with local probes only."""
    del store
    root = context.get("root")
    if not procedure_plane_available(root):
        return OperationResult(text="No procedure plane. Run: parrot sdd procedure build")

    try:
        from parrot.knowledge.wiki.procedure.index import is_stale, read_index
        from parrot.knowledge.wiki.procedure.plane import ProcedurePlane
        from parrot.knowledge.wiki.procedure.resolver import resolve
        from parrot.sdd.scripts.procedure_advice import checkout_root
        from parrot.sdd.scripts.procedure_probes import SddProbeRunner, scope_for

        shared = project.find_shared_root(Path(root))
        if shared is None:
            return OperationResult(text="No procedure plane. Run: parrot sdd procedure build")
        plane = ProcedurePlane(shared / PLANE_DIR)
        specs = await plane.specs()
        stale = is_stale(read_index(plane.plane_dir), root=shared)
        checkout = checkout_root(Path(root)) or Path(root)

        def resolve_local() -> Any:
            """Resolve scope and procedure state without blocking the event loop."""
            scope = scope_for(checkout, feature=params.feature, task=params.task)
            return resolve(specs, scope, SddProbeRunner(checkout), allow_remote=False, stale=stale)

        resolution = await asyncio.to_thread(resolve_local)
    except (ValueError, OSError) as exc:
        return OperationResult(text=str(exc), is_error=True)

    data = _resolution_payload(resolution)
    return OperationResult(text=_resolution_text(data), data=data)
