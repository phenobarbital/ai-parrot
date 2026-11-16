"""Resumable, batched backfill driver for legacy conversation turns (FEAT-886 M11).

Run as ``python -m parrot.storage.backfill``. This module is an operator tool: it is
never imported from a request path, because a full scan is exactly what the chronological
index exists to avoid at serve time.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from navconfig.logging import logging

from parrot.storage.backends import build_conversation_backend
from parrot.storage.backends.base import BackfillBatch, ConversationBackend

logger = logging.getLogger("parrot.storage.backfill")

_STATE_VERSION = 1
_DEFAULT_CURSOR_FILE = Path.home() / ".parrot" / "conversation-backfill-cursor.json"


@dataclass(frozen=True)
class BackfillReport:
    """Outcome of one :func:`run_backfill` invocation.

    Attributes:
        processed: Turns indexed by this invocation (not by earlier resumed segments).
        complete: ``True`` when the backend reported ``next_cursor is None``.
        invalid_sessions: Sessions left ``invalid`` (missing / unparseable timestamp),
            cumulative for the current pass.
    """

    processed: int
    complete: bool
    invalid_sessions: Tuple[str, ...]


def _fresh_state() -> Dict[str, Any]:
    return {"version": _STATE_VERSION, "cursor": None, "complete": False, "invalid_sessions": []}


def _load_state(path: Optional[Path]) -> Dict[str, Any]:
    """Return the persisted state, or a fresh one when absent, damaged or marked complete."""
    if path is None or not path.exists():
        return _fresh_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Backfill state %s is unreadable; starting a fresh pass", path)
        return _fresh_state()
    if not isinstance(state, dict) or state.get("version") != _STATE_VERSION or state.get("complete"):
        return _fresh_state()
    return {**_fresh_state(), "cursor": state.get("cursor"),
            "invalid_sessions": list(state.get("invalid_sessions", []))}


def _save_state(path: Optional[Path], state: Dict[str, Any]) -> None:
    """Atomically replace the state file (no-op without a path)."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


async def run_backfill(
    backend: ConversationBackend,
    *,
    batch_size: int = 500,
    max_batches: Optional[int] = None,
    cursor_path: Optional[Path] = None,
) -> BackfillReport:
    """Drive ``backend.backfill_batch`` until complete or ``max_batches`` is reached.

    Resumes from ``cursor_path`` when it holds an unfinished pass; a file marked complete
    starts a new pass (operators re-run after repairing bad timestamps; a pass is cheap and
    idempotent). The cursor is persisted after every batch.

    Args:
        backend: An initialised backend.
        batch_size: Legacy turns examined per batch (>= 1).
        max_batches: Stop after this many batches; ``None`` runs to completion.
        cursor_path: State file for resumption; ``None`` keeps state in memory only.

    Returns:
        The :class:`BackfillReport` for this invocation.

    Raises:
        ValueError: ``batch_size`` or ``max_batches`` below 1.
        RuntimeError: The backend returned the cursor it was given (no progress).
        StorageError: Propagated from the backend; the last good cursor is already persisted.
    """
    if batch_size < 1 or (max_batches is not None and max_batches < 1):
        raise ValueError("batch_size and max_batches must be >= 1")
    state = await asyncio.to_thread(_load_state, cursor_path)
    cursor: Optional[str] = state["cursor"]
    invalid: Dict[str, None] = dict.fromkeys(state["invalid_sessions"])
    processed = batches = 0
    complete = False
    while not complete and (max_batches is None or batches < max_batches):
        batch: BackfillBatch = await backend.backfill_batch(cursor, batch_size)
        if batch.next_cursor is not None and batch.next_cursor == cursor:
            raise RuntimeError(f"backfill made no progress: backend returned the same cursor {cursor!r}")
        processed += batch.processed
        invalid.update(dict.fromkeys(batch.invalid_sessions))
        cursor, batches, complete = batch.next_cursor, batches + 1, batch.next_cursor is None
        await asyncio.to_thread(
            _save_state,
            cursor_path,
            {"version": _STATE_VERSION, "cursor": cursor, "complete": complete,
             "invalid_sessions": list(invalid)},
        )
    return BackfillReport(processed=processed, complete=complete, invalid_sessions=tuple(invalid))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m parrot.storage.backfill", description=__doc__)
    parser.add_argument("--backend", default=None, help="Override PARROT_STORAGE_BACKEND for this run.")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--cursor-file", type=Path, default=_DEFAULT_CURSOR_FILE)
    return parser


async def _run_cli(args: argparse.Namespace) -> int:
    backend = await build_conversation_backend(args.backend)
    await backend.initialize()
    try:
        report = await run_backfill(
            backend, batch_size=args.batch_size, max_batches=args.max_batches, cursor_path=args.cursor_file
        )
    finally:
        await backend.close()
    sys.stdout.write(json.dumps({"processed": report.processed, "complete": report.complete,
                                 "invalid_sessions": list(report.invalid_sessions)}) + "\n")
    if not report.complete:
        return 3
    return 2 if report.invalid_sessions else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point (``python -m parrot.storage.backfill``). Returns the process exit code."""
    args = _build_parser().parse_args(argv)
    return asyncio.run(_run_cli(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
