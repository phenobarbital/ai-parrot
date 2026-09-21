"""Compatible full responses and bounded, recoverable compact projections.

Spec `sdd/specs/sdd-execution-optimization.spec.md` (FEAT-584), module M3
("Vistas compactas compatibles", R2). `full` is the unmodified prior wire
contract. `compact` first persists the WHOLE payload as one immutable,
execution-scoped evidence artifact -- a reference is never handed out before
the snapshot it points to is durable (spec: "artefactos inmutables antes de
exponer refs") -- then returns a bounded (<=16 KiB) projection that never
drops a decision, an outcome, a reason or a blocker/pending id: oversized id
lists are paginated into their own recoverable artifact instead of being
silently truncated. The projector is purely structural (keyed off the dumped
field names), so it works for both `CoderPlan` and `CoderJobView` payloads
without importing either model.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore

#: Spec AC4: "16 KiB de vista" -- the compact projection's own serialized budget.
COMPACT_VIEW_BUDGET_BYTES = 16384

#: Headroom reserved for `evidence_ref`/`required_pages_remaining`/`projection`,
#: which are only known once the pageable content has already been fitted.
_METADATA_RESERVE_BYTES = 1024

#: `CoderPlan`/`CoderJobView` fields preserved verbatim: identity, generation,
#: state and every decision/reason list small enough to never need paging.
_VERBATIM_FIELDS: Tuple[str, ...] = (
    "feature_id",
    "feature",
    "feature_branch",
    "index_path",
    "execution_id",
    "pool_generation",
    "job_id",
    "state",
    "status",
    "started_at",
    "ended_at",
    "error",
    "roster",
    "orphan_branches",
    "routing_blocks",
    "seats",
)

#: `CoderPlan` id lists that grow with feature size -- the only fields this
#: projector paginates (into a durable artifact) rather than ever truncating
#: silently.
_PAGEABLE_ID_FIELDS: Tuple[str, ...] = ("pending", "blocked")


class _PagePayload(BaseModel):
    """Durable artifact holding one paginated field's full (untruncated) id list."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(..., min_length=1)
    ids: List[str] = Field(default_factory=list)


def _canonical_bytes(data: Dict[str, Any]) -> int:
    """Byte length of *data* as canonical JSON (never confuse characters with bytes/tokens)."""
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return len(encoded.encode("utf-8"))


def _compact_planned_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only the routing decision a dispatcher needs: seat, model and assessment id."""
    return {
        "task_id": task.get("task_id"),
        "seat_label": task.get("seat_label"),
        "native": task.get("native"),
        "backend": task.get("backend"),
        "model": task.get("model"),
        "assessment_id": task.get("assessment_id"),
    }


def _compact_chunk(chunk: Dict[str, Any]) -> Dict[str, Any]:
    """Project one `PlanChunk`: index plus its tasks' routing decisions."""
    return {"index": chunk.get("index"), "tasks": [_compact_planned_task(t) for t in chunk.get("tasks", [])]}


def _compact_attempt(attempt: Dict[str, Any]) -> Dict[str, Any]:
    """Drop heavy per-turn telemetry (`turn_series`/`usage`/`budget_report`).

    Recoverable in full from the durable snapshot artifact this same call
    already published -- never dropped, only moved.
    """
    return {
        "attempt": attempt.get("attempt"),
        "attempt_uid": attempt.get("attempt_uid"),
        "seat_label": attempt.get("seat_label"),
        "backend": attempt.get("backend"),
        "model": attempt.get("model"),
        "resolved_model": attempt.get("resolved_model"),
        "started_at": attempt.get("started_at"),
        "ended_at": attempt.get("ended_at"),
        "duration_s": attempt.get("duration_s"),
        "error": attempt.get("error"),
        "error_class": attempt.get("error_class"),
        "terminal": attempt.get("terminal"),
        "turns": attempt.get("turns"),
    }


def _compact_lint(lint: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Keep correctness `errors` (never blocks the merge, but never hidden either); drop style `residual`."""
    if lint is None:
        return None
    return {
        "formatter": lint.get("formatter"),
        "commit": lint.get("commit"),
        "errors": lint.get("errors", []),
        "residual_count": lint.get("residual_count", 0),
        "tool_error": lint.get("tool_error", ""),
    }


def _compact_task_result(task: Dict[str, Any]) -> Dict[str, Any]:
    """Never drop `outcome`/`unexpected_files`/`diagnostics` -- those ARE the decision."""
    return {
        "task_id": task.get("task_id"),
        "outcome": task.get("outcome"),
        "branch": task.get("branch"),
        "worktree_path": task.get("worktree_path"),
        "conflict_files": task.get("conflict_files", []),
        "unexpected_files": task.get("unexpected_files", []),
        "diagnostics": task.get("diagnostics"),
        "attempts": [_compact_attempt(a) for a in task.get("attempts", [])],
        "lint": _compact_lint(task.get("lint")),
    }


def _project_compact_fields(full_dump: Dict[str, Any]) -> Dict[str, Any]:
    """Structural (not type-based) projection: works for both `CoderPlan` and `CoderJobView` dumps."""
    compact: Dict[str, Any] = {k: full_dump[k] for k in _VERBATIM_FIELDS if k in full_dump}
    for field in _PAGEABLE_ID_FIELDS:
        if field in full_dump:
            compact[field] = list(full_dump[field])
    if "chunks" in full_dump:
        chunks = full_dump.get("chunks") or []
        compact["next_chunk"] = _compact_chunk(chunks[0]) if chunks else None
        compact["remaining_chunks"] = max(len(chunks) - 1, 0)
    if "tasks" in full_dump:
        compact["tasks"] = [_compact_task_result(t) for t in full_dump["tasks"]]
    return compact


async def _paginate_oversized_ids(
    compact: Dict[str, Any], *, execution_id: str, store: ExecutionEvidenceStore, budget_bytes: int
) -> List[Dict[str, Any]]:
    """Halve any `_PAGEABLE_ID_FIELDS` list still inline until `compact` fits `budget_bytes`.

    The FULL (untruncated) list is published as one durable artifact BEFORE
    the inline copy is ever shortened, so every blocked/pending id stays
    fully recoverable via `coder_read_artifact` -- this projector pages, it
    never drops an id.
    """
    required_pages: List[Dict[str, Any]] = []
    for field in _PAGEABLE_ID_FIELDS:
        ids = compact.get(field)
        if not isinstance(ids, list) or not ids:
            continue
        published = False
        while _canonical_bytes(compact) > budget_bytes and len(compact[field]) > 1:
            if not published:
                ref = await store.put_artifact(execution_id, _PagePayload(field=field, ids=list(ids)))
                required_pages.append({"field": field, **ref.model_dump(mode="json")})
                published = True
            compact[field] = compact[field][: max(len(compact[field]) // 2, 1)]
    return required_pages


async def project_response(
    payload: BaseModel,
    *,
    mode: Literal["full", "compact"],
    execution_id: str,
    store: ExecutionEvidenceStore,
) -> Dict[str, object]:
    """Preserve full data or publish detail before returning a compact snapshot.

    Args:
        payload: The tool result model to project (`CoderPlan`/`CoderJobView`).
        mode: `'full'` returns the existing `model_dump()` contract unmodified.
            `'compact'` projects it into a bounded, recoverable view.
        execution_id: The execution `payload` belongs to; every artifact this
            call publishes in `compact` mode is scoped underneath it.
        store: The durable evidence store `compact` mode persists into.

    Returns:
        A JSON-safe dict: the untouched full dump for `'full'`, or a compact,
        <=16 KiB one for `'compact'` -- always including `evidence_ref`
        (the full snapshot, recoverable via `coder_read_artifact`) and
        `required_pages_remaining` (any paginated id lists, empty when none).
    """
    full_dump = payload.model_dump(mode="json")
    if mode == "full":
        return full_dump

    full_bytes = _canonical_bytes(full_dump)
    full_ref = await store.put_artifact(execution_id, payload)
    compact = _project_compact_fields(full_dump)
    content_budget = COMPACT_VIEW_BUDGET_BYTES - _METADATA_RESERVE_BYTES
    required_pages = await _paginate_oversized_ids(
        compact, execution_id=execution_id, store=store, budget_bytes=content_budget
    )
    compact["evidence_ref"] = full_ref.model_dump(mode="json")
    compact["required_pages_remaining"] = required_pages
    compact["projection"] = {"full_bytes": full_bytes, "compact_bytes": _canonical_bytes(compact)}
    return compact
