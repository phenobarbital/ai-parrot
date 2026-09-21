"""Concrete receipt-reading compaction driver for the main Claude Code loop.

The Claude Code hook owns ``$.session.compact()``.  Python has no invocation
surface for it, so this driver only records its intent and reports an observed
receipt when one is available.  No observable receipt channel is currently
homologated for this process, therefore it fails explicitly rather than
mistaking silence for a completed compaction.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import CompactionReceipt, ReviewCheckpoint, WorkflowEvent
from parrot.knowledge.wiki.claude_code.compaction import compaction_status


class ClaudeMainLoopCompactionDriver:
    """PhaseBoundaryDriver for the main loop that reads receipts but never invokes compaction."""

    def __init__(self, *, worktree_root: Path, store: ExecutionEvidenceStore) -> None:
        """Bind the worktree-local installation diagnostic and durable event store.

        Args:
            worktree_root: Worktree whose plugin installation is evaluated.
            store: Durable store used for the request and outcome events.
        """
        self._worktree_root = Path(worktree_root)
        self._store = store

    async def supports(self, context_id: str) -> bool:
        """Return whether the main context has all required local installation wiring."""
        if context_id != "main":
            return False
        status = await asyncio.to_thread(compaction_status, self._worktree_root)
        required = ("compaction_plugin", "compaction_function_hooks", "compaction_api_key")
        return all(status.get(key, False) for key in required)

    async def compact(self, checkpoint: ReviewCheckpoint) -> CompactionReceipt:
        """Record an honest compaction observation result for a main-loop checkpoint.

        The host offers no Python-side receipt stream, environment variable, or
        documented transcript/log endpoint that can be correlated to this
        checkpoint.  Returning an explicit failure preserves the checkpoint
        handoff while ensuring no success is manufactured from that absence.

        Args:
            checkpoint: Checkpoint identifying the main conversation context.

        Returns:
            Durable-event-backed receipt with an explicit unsupported or failed
            result.

        Raises:
            ValueError: The checkpoint does not identify the main context.
        """
        if checkpoint.context_id != "main":
            raise ValueError("ClaudeMainLoopCompactionDriver only supports context_id='main'")

        started = time.perf_counter()
        await self._append_event(checkpoint, "compaction.requested", {"context_id": checkpoint.context_id})

        reason = (
            "No observable Claude Code plugin receipt surface is available to this Python process; "
            "current-process environment and documented Claude transcript/log locations cannot provide a "
            "checkpoint-correlated Jev receipt."
        )
        receipt = CompactionReceipt(
            checkpoint_id=checkpoint.checkpoint_id,
            context_id=checkpoint.context_id,
            status="failed",
            reason=reason,
            backend="unknown",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        await self._append_event(
            checkpoint,
            "compaction.finished",
            {
                "context_id": checkpoint.context_id,
                "status": receipt.status,
                "backend": receipt.backend,
                "reason": receipt.reason,
                "elapsed_ms": receipt.elapsed_ms,
            },
        )
        return receipt

    async def _append_event(self, checkpoint: ReviewCheckpoint, kind: str, payload: dict[str, object]) -> None:
        """Append a uniquely identified, UTC-timestamped compaction event."""
        event = WorkflowEvent(
            event_id=f"{kind}-{checkpoint.checkpoint_id}-{uuid.uuid4().hex}",
            kind=kind,
            execution_id=checkpoint.execution_id,
            timestamp=datetime.now(timezone.utc),
            source="engine",
            payload=payload,
        )
        await self._store.append_event(event)
