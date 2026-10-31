"""SpecUsageRecorder — durable per-feature usage sink (FEAT-783 M5).

A SINK, not an EventProvider: the existing UsageRecordingSubscriber owns the subscription
(run_ledger.py:1-14 pattern). Root resolution reuses FEAT-554's rule (main checkout via
git-common-dir; refused inside the worktree base) so rows outlive ``git worktree remove``.
``cumulative_cost_usd`` is process-cumulative: readers must never sum it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from parrot.observability.recorders.base import AbstractLogger
from parrot.observability.recorders.models import UsageRecord

logger = logging.getLogger(__name__)


class SpecUsageRecorder(AbstractLogger):
    """Append one JSONL row per attributed UsageRecord to ``<root>/<feat_id>.jsonl``."""

    name: str = "spec_usage"

    def __init__(self, root: Optional[Path] = None, *, worktree_base_path: str) -> None:
        """Initialize the sink with a validated out-of-worktree root.

        Args:
            root: Explicit absolute durable root, or ``None`` to derive the main checkout.
            worktree_base_path: Parent directory containing disposable worktrees.

        Raises:
            ValueError: The root is relative, unresolvable, or inside the worktree base.
        """
        from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root  # noqa: PLC0415

        if root is not None:
            resolved = resolve_durable_root(str(root), worktree_base_path=worktree_base_path)
        else:
            resolved = resolve_durable_root(None, worktree_base_path=worktree_base_path).parent / "sdd-spec-usage"
            resolved = resolve_durable_root(str(resolved), worktree_base_path=worktree_base_path)
        self._root = resolved
        self._pending: set[asyncio.Task[None]] = set()
        # asyncio.Lock grants waiters FIFO, so appends land in record() order (one thread write at a time).
        self._write_lock = asyncio.Lock()
        self._warned = False

    @property
    def root(self) -> Path:
        """The validated durable root."""
        return self._root

    async def record(self, record: UsageRecord) -> None:
        """Append one row keyed by feat_id. Fail-open: never raises, warns once.

        Args:
            record: Normalized usage record to persist.
        """
        if not record.feat_id:
            return

        try:
            from parrot.flows.dev_loop.sdd_coder.telemetry import (  # noqa: PLC0415
                MAX_LINE_BYTES,
                feature_file_name,
            )

            payload = (record.model_dump_json() + "\n").encode("utf-8")
            if len(payload) > MAX_LINE_BYTES:
                raise ValueError(f"usage row is {len(payload)} bytes; maximum is {MAX_LINE_BYTES}")

            file_path = self._root / feature_file_name(record.feat_id)

            def _write() -> None:
                self._root.mkdir(parents=True, exist_ok=True)
                fd = os.open(file_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
                try:
                    os.write(fd, payload)
                finally:
                    os.close(fd)

            async def _ordered_write() -> None:
                async with self._write_lock:
                    await asyncio.to_thread(_write)

            task = asyncio.create_task(_ordered_write())
            self._pending.add(task)
            task.add_done_callback(self._write_done)
        except Exception as exc:  # noqa: BLE001 - usage persistence is deliberately fail-open
            self._warn_once(exc)

    async def aclose(self) -> None:
        """Await in-flight writes. Unlike RunLedgerRecorder.aclose this is not a no-op."""
        while self._pending:
            pending = tuple(self._pending)
            await asyncio.gather(*pending, return_exceptions=True)
            self._pending.difference_update(pending)

    def _write_done(self, task: asyncio.Task[None]) -> None:
        """Remove a completed write and report its failure at most once.

        Args:
            task: Completed background write task.
        """
        self._pending.discard(task)
        if task.cancelled():
            self._warn_once(asyncio.CancelledError("spec usage write was cancelled"))
            return
        error = task.exception()
        if error is not None:
            self._warn_once(error)

    def _warn_once(self, error: BaseException) -> None:
        """Log the first persistence failure and suppress subsequent warnings.

        Args:
            error: Persistence failure to report.
        """
        if not self._warned:
            logger.warning("Spec usage write failed (suppressing future warnings): %s", error)
            self._warned = True


def read_spec_usage(root: Path, feat_id: str) -> list[UsageRecord]:
    """Read every row for *feat_id*; malformed lines are skipped.

    Args:
        root: Directory containing per-feature JSONL files.
        feat_id: Feature identifier used to select the guarded filename.

    Returns:
        Valid usage records in file order, or an empty list when the file is absent.
    """
    from parrot.flows.dev_loop.sdd_coder.telemetry import feature_file_name  # noqa: PLC0415

    path = root / feature_file_name(feat_id)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []

    records: list[UsageRecord] = []
    for line in lines:
        try:
            records.append(UsageRecord.model_validate_json(line))
        except (TypeError, ValueError):
            continue
    return records
