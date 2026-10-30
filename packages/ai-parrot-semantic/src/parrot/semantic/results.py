"""Bounded expiring handles with immutable ownership and authorization provenance."""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from pydantic import BaseModel

from .context import SemanticRequestIdentity
from .errors import SemanticResultError


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


class ResultHandle(BaseModel):
    """A defensive retained result, never a grant by itself."""

    result_id: str
    agent_id: str
    user_id: str
    tenant_id: str
    session_id: str
    subject_digest: str
    model: str
    model_digest: str
    policy_digest: str
    expires_at: datetime
    members: tuple[str, ...]
    physical_columns: tuple[str, ...]
    physical_tables: tuple[str, ...]
    columns: list[str]
    rows: list[dict[str, Any]]
    audit_id: str
    governed_sql: str

    def model_post_init(self, __context: Any) -> None:
        """Validate immutable provenance and defensively copy mutable result data."""
        required_fields = {
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "subject_digest": self.subject_digest,
            "model": self.model,
            "model_digest": self.model_digest,
            "policy_digest": self.policy_digest,
            "audit_id": self.audit_id,
            "governed_sql": self.governed_sql,
        }
        for name, value in required_fields.items():
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        if self.result_id and not self.result_id.strip():
            raise ValueError("result_id must not be blank")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        self._validate_members()
        self._validate_physical_provenance()
        if any(not column.strip() for column in self.columns):
            raise ValueError("columns must not contain blank values")
        self.columns = deepcopy(self.columns)
        self.rows = deepcopy(self.rows)

    def _validate_members(self) -> None:
        """Reject blank semantic members while preserving their exact order."""
        if any(not member.strip() for member in self.members):
            raise ValueError("members must not contain blank values")

    def _validate_physical_provenance(self) -> None:
        """Require qualified physical columns and tables, never output aliases."""
        for table in self.physical_tables:
            if len(table.split(".")) < 2 or any(not part.strip() for part in table.split(".")):
                raise ValueError("physical_tables must be qualified")
        for column in self.physical_columns:
            if len(column.split(".")) < 2 or any(not part.strip() for part in column.split(".")):
                raise ValueError("physical_columns must be qualified")


class ResultHandleStore:
    """Opaque TTL store with complete owner and version checks."""

    def __init__(self, *, ttl_s: int = 900, max_entries: int = 256) -> None:
        """Create a bounded store with a replaceable UTC clock for tests.

        Args:
            ttl_s: Lifetime assigned to every retained handle in seconds.
            max_entries: Maximum handles retained after each mutation.
        """
        self._ttl = timedelta(seconds=max(ttl_s, 0))
        self._max_entries = max(max_entries, 0)
        self._data: OrderedDict[str, ResultHandle] = OrderedDict()
        self._clock: Callable[[], datetime] = _utc_now
        self._lock = threading.Lock()

    def put(self, handle: ResultHandle) -> str:
        """Store a defensive snapshot under a random opaque id.

        Args:
            handle: Result and immutable governance provenance to retain.

        Returns:
            Newly minted opaque result identifier.
        """
        now = self._clock()
        result_id = secrets.token_urlsafe(24)
        snapshot = handle.model_copy(
            update={"result_id": result_id, "expires_at": now + self._ttl},
            deep=True,
        )
        with self._lock:
            self._purge_expired(now)
            self._data[result_id] = snapshot
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)
        return result_id

    def claim(
        self,
        result_id: str,
        *,
        identity: SemanticRequestIdentity,
        subject_digest: str,
        model_digest: str,
        policy_digest: str,
    ) -> ResultHandle:
        """Return a snapshot only for exact current owner, context, and versions.

        Args:
            result_id: Opaque identifier returned by :meth:`put`.
            identity: Trusted request identity to compare against the retained owner.
            subject_digest: Current digest of the complete policy-relevant subject.
            model_digest: Current semantic-model version digest.
            policy_digest: Current policy version digest.

        Returns:
            A deep-copied retained result.

        Raises:
            SemanticResultError: If the handle is unknown, expired, foreign, or stale.
        """
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            handle = self._data.get(result_id)
            if handle is None or not self._matches(handle, identity, subject_digest, model_digest, policy_digest):
                raise SemanticResultError("result_unavailable", "Result is unavailable")
            self._data.move_to_end(result_id)
            return handle.model_copy(deep=True)

    def _purge_expired(self, now: datetime) -> None:
        """Remove expired entries while holding ``_lock``."""
        for result_id in [key for key, handle in self._data.items() if handle.expires_at <= now]:
            del self._data[result_id]

    @staticmethod
    def _matches(
        handle: ResultHandle,
        identity: SemanticRequestIdentity,
        subject_digest: str,
        model_digest: str,
        policy_digest: str,
    ) -> bool:
        """Compare every owner and version component without wildcard defaults."""
        return (
            handle.agent_id == identity.agent_id
            and handle.user_id == identity.ctx.user_id
            and handle.tenant_id == identity.ctx.tenant_id
            and handle.session_id == identity.session_id
            and handle.subject_digest == subject_digest
            and handle.model_digest == model_digest
            and handle.policy_digest == policy_digest
        )
