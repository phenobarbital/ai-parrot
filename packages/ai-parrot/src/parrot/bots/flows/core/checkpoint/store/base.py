"""CheckpointStore abstract base class (FEAT-399, TASK-2048).

The contract every checkpoint backend implements — ephemeral (Redis) or
durable (sqlite/postgres/mongodb). Pattern mirrors `ResultStorage`
(`core/storage/backends/base.py`, FEAT-147) but is a deliberately
separate family: checkpoints are recoverable *state* (latest-pointer +
bounded history + TTL + lease), not append-only audit *results*.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from parrot.bots.flows.core.checkpoint.model import FlowCheckpoint


class CheckpointStore(ABC):
    """Abstract pluggable backend for AgentsFlow checkpoint persistence.

    Implementations must be async-safe and idempotent on ``close()``.
    Lease methods (``acquire_lease``/``renew_lease``/``release_lease``)
    implement the concurrent-resume protection described in spec §2/§7:
    a second ``acquire_lease`` for a flow_id already held fails (returns
    ``False``); ``renew_lease``/``release_lease`` are holder-checked —
    releasing/renewing someone else's lease is a no-op.
    """

    @abstractmethod
    async def put(self, checkpoint: FlowCheckpoint) -> None:
        """Persist a checkpoint, updating the flow's latest pointer.

        Args:
            checkpoint: The `FlowCheckpoint` to store.
        """

    @abstractmethod
    async def latest(self, flow_id: str) -> FlowCheckpoint | None:
        """Return the most recent checkpoint for a flow, if any.

        Args:
            flow_id: Unique identifier of the flow run.

        Returns:
            The latest `FlowCheckpoint`, or ``None`` if none exists.
        """

    @abstractmethod
    async def get(self, flow_id: str, checkpoint_id: int) -> FlowCheckpoint | None:
        """Return a specific checkpoint by id (for re-fork/time-travel).

        Args:
            flow_id: Unique identifier of the flow run.
            checkpoint_id: Monotonic checkpoint id within the flow.

        Returns:
            The matching `FlowCheckpoint`, or ``None`` if not found.
        """

    @abstractmethod
    async def history(self, flow_id: str, limit: int = 10) -> list[FlowCheckpoint]:
        """Return the retained checkpoint history for a flow, newest first.

        Args:
            flow_id: Unique identifier of the flow run.
            limit: Maximum number of checkpoints to return.

        Returns:
            List of `FlowCheckpoint` instances, newest first.
        """

    @abstractmethod
    async def list_flows(self, status: str | None = None) -> list[dict[str, Any]]:
        """List known flows, optionally filtered by status.

        Args:
            status: Optional status filter (``"running"``, ``"suspended"``,
                ``"completed"``, ``"failed"``).

        Returns:
            List of plain dicts describing each flow (at least
            ``flow_id``, ``flow_name``, ``status``, ``checkpoint_id``).
        """

    @abstractmethod
    async def delete_flow(self, flow_id: str) -> None:
        """Delete all checkpoints and metadata for a flow.

        Args:
            flow_id: Unique identifier of the flow run.
        """

    @abstractmethod
    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        """Acquire the resume lease for a flow_id.

        Args:
            flow_id: Unique identifier of the flow run.
            holder: Opaque identifier of the lease holder (e.g. process id).
            ttl: Lease time-to-live in seconds.

        Returns:
            ``True`` if the lease was acquired, ``False`` if another
            holder already holds an active lease.
        """

    @abstractmethod
    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        """Renew the resume lease for a flow_id (heartbeat).

        Args:
            flow_id: Unique identifier of the flow run.
            holder: Opaque identifier of the lease holder; renewal only
                succeeds if this holder currently owns the lease.
            ttl: New lease time-to-live in seconds.

        Returns:
            ``True`` if renewed, ``False`` if this holder does not own
            the lease (expired or held by someone else).
        """

    @abstractmethod
    async def release_lease(self, flow_id: str, holder: str) -> None:
        """Release the resume lease for a flow_id.

        Releasing a lease not owned by ``holder`` is a no-op (logged as
        a warning by implementations), never an error.

        Args:
            flow_id: Unique identifier of the flow run.
            holder: Opaque identifier of the lease holder.
        """

    @abstractmethod
    async def close(self) -> None:
        """Release any underlying connection/pool. Safe to call multiple times."""
