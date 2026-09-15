"""Per-seat roll-up of ``sdd-coder`` jobs — the "who did what, for how long,
at what token cost" table of a feature run.

The engine records every attempt as an :class:`AttemptRecord` under
``CoderJob.tasks[*].attempts[*]`` and journals each job to
``<worktree>/.sdd-coder/jobs/<job_id>.json``. Nothing aggregated those
records: the ``sdd-worker`` prompt asked the LLM to compute a per-seat
table by hand from the raw JSON, and the dev-flow never saw it at all.
:func:`summarize_job_seats` is that aggregation, done once, in code, so
``coder_status``/``coder_wait`` can return it and ``DevelopmentNode`` can
read it post-hoc from the journals.

Pure — no I/O except :func:`load_jobs`, which only reads files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord, CoderJob
from parrot.flows.dev_loop.session_state import SeatUsageSummary

logger = logging.getLogger(__name__)

JOURNAL_DIR = Path(".sdd-coder") / "jobs"


def load_jobs(worktree_path: str) -> List[CoderJob]:
    """Read every ``CoderJob`` journal under ``<worktree>/.sdd-coder/jobs/``.

    Sorted by file name (job ids are minted monotonically, so this is also
    creation order). A journal that fails to parse is skipped with a DEBUG
    log rather than failing the summary — a half-written snapshot from a
    crashed engine must not hide the seats that did finish.

    Args:
        worktree_path: The feature worktree the engine journaled into.

    Returns:
        The parsed jobs; empty when the directory does not exist.
    """
    directory = Path(worktree_path) / JOURNAL_DIR
    if not directory.is_dir():
        return []
    jobs: List[CoderJob] = []
    for path in sorted(directory.glob("*.json")):
        try:
            jobs.append(CoderJob.model_validate(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:  # noqa: BLE001 - one bad journal must not sink the summary
            logger.debug("Skipping unreadable sdd-coder journal %s", path, exc_info=True)
    return jobs


def _int_or_none(value: object) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _add(previous: Optional[int], incoming: Optional[int]) -> Optional[int]:
    if incoming is None:
        return previous
    return incoming if previous is None else previous + incoming


def summarize_job_seats(jobs: Iterable[CoderJob]) -> List[SeatUsageSummary]:
    """Group every attempt in *jobs* by seat label.

    Per seat: the distinct task ids attempted, how many of those tasks
    ended ``merged`` (the latest ``TaskResult.outcome`` wins when a task
    appears in several jobs), attempt/retry/failure counts, summed
    ``duration_s``, and summed provider tokens — ``None`` with
    ``usage_known=False`` when no attempt on the seat reported any
    (``codex`` CLI seats never do; native ``haiku`` seats produce no
    ``AttemptRecord`` at all and therefore no row).

    Args:
        jobs: The jobs to fold — typically :func:`load_jobs`'s result, or
            the single job a ``coder_status`` call is reporting on.

    Returns:
        One :class:`SeatUsageSummary` per seat, ordered by seat label.
    """
    seats: Dict[str, dict] = {}
    latest_outcome: Dict[str, str] = {}  # task_id -> outcome from the LAST job that carried it
    task_seat: Dict[str, str] = {}  # task_id -> seat of its last attempt

    for job in jobs:
        for task in job.tasks:
            latest_outcome[task.task_id] = task.outcome
            for attempt in task.attempts:
                seat = attempt.seat_label or "(unlabelled)"
                acc = seats.setdefault(
                    seat,
                    {
                        "backend": "",
                        "model": "",
                        "tasks": [],
                        "attempts": 0,
                        "retries": 0,
                        "failures": 0,
                        "duration_s": 0.0,
                        "input_tokens": None,
                        "output_tokens": None,
                        "cost_usd": None,
                    },
                )
                _fold_attempt(acc, attempt, task.task_id)
                task_seat[task.task_id] = seat

    out: List[SeatUsageSummary] = []
    for seat in sorted(seats):
        acc = seats[seat]
        merged = sum(1 for t in acc["tasks"] if latest_outcome.get(t) == "merged" and task_seat.get(t) == seat)
        out.append(
            SeatUsageSummary(
                seat=seat,
                backend=acc["backend"],
                model=acc["model"],
                tasks_handled=list(acc["tasks"]),
                tasks_merged=merged,
                attempts=acc["attempts"],
                retries=acc["retries"],
                failures=acc["failures"],
                duration_s=round(acc["duration_s"], 3),
                input_tokens=acc["input_tokens"],
                output_tokens=acc["output_tokens"],
                cost_usd=acc["cost_usd"],
                usage_known=acc["input_tokens"] is not None or acc["output_tokens"] is not None,
            )
        )
    return out


def _fold_attempt(acc: dict, attempt: AttemptRecord, task_id: str) -> None:
    """Fold one attempt into a seat accumulator (in place)."""
    if attempt.backend and not acc["backend"]:
        acc["backend"] = attempt.backend
    model = attempt.resolved_model or attempt.model
    if model and not acc["model"]:
        acc["model"] = model
    if task_id not in acc["tasks"]:
        acc["tasks"].append(task_id)
    acc["attempts"] += 1
    if attempt.attempt > 1:
        acc["retries"] += 1
    if attempt.terminal == "failed":
        acc["failures"] += 1
    acc["duration_s"] += float(attempt.duration_s or 0.0)
    usage = attempt.usage or {}
    acc["input_tokens"] = _add(acc["input_tokens"], _int_or_none(usage.get("input_tokens")))
    acc["output_tokens"] = _add(acc["output_tokens"], _int_or_none(usage.get("output_tokens")))
    cost = usage.get("total_cost_usd")
    if cost is not None:
        try:
            acc["cost_usd"] = (acc["cost_usd"] or 0.0) + float(cost)
        except (TypeError, ValueError):
            pass


__all__ = ["JOURNAL_DIR", "load_jobs", "summarize_job_seats"]
