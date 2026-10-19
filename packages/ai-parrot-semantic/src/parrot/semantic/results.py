"""Opaque, bounded, expiring, owner-bound result handles (spec §3 Module 9, AC10)."""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from parrot.auth import PermissionContext

from .errors import SemanticResultError


class ResultHandle(BaseModel):
    """Retained governed-query result and its authorization bindings."""

    result_id: str = ""
    agent_id: str | None
    user_id: str
    tenant_id: str
    session_id: str | None
    subject_digest: str
    model: str
    model_digest: str
    policy_digest: str
    expires_at: datetime
    columns: list[str]
    rows: list[dict]
    audit_id: str
    governed_sql: str


class ResultHandleStore:
    """Thread-safe in-memory store for bounded, short-lived result handles."""

    def __init__(self, *, ttl_s: int = 900, max_entries: int = 256) -> None:
        """Initialize the store's lifetime and capacity bounds."""
        self.ttl = timedelta(seconds=ttl_s)
        self.max_entries = max_entries
        self._data: OrderedDict[str, ResultHandle] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, handle: ResultHandle) -> str:
        """Store with a fresh opaque id (secrets.token_urlsafe) and expires_at = now + ttl."""
        now = datetime.now(timezone.utc)
        with self._lock:
            self._purge_expired(now)
            result_id = secrets.token_urlsafe(24)
            while result_id in self._data:
                result_id = secrets.token_urlsafe(24)
            self._data[result_id] = handle.model_copy(
                update={"result_id": result_id, "expires_at": now + self.ttl}
            )
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)
        return result_id

    def claim(
        self,
        result_id: str,
        *,
        ctx: PermissionContext,
        subject_digest: str,
        model_digest: str,
        policy_digest: str,
    ) -> ResultHandle:
        """Return a handle only when all owner, context, and version bindings match."""
        now = datetime.now(timezone.utc)
        with self._lock:
            self._purge_expired(now)
            handle = self._data.get(result_id)
            if handle is None or (
                handle.agent_id != ctx.extra.get("agent_id")
                or handle.user_id != ctx.user_id
                or handle.tenant_id != ctx.tenant_id
                or handle.session_id != ctx.extra.get("session_id")
                or handle.subject_digest != subject_digest
                or handle.model_digest != model_digest
                or handle.policy_digest != policy_digest
            ):
                raise SemanticResultError("result_unavailable")
            return handle

    def _purge_expired(self, now: datetime) -> None:
        """Remove every handle whose expiry is not later than ``now``."""
        expired = [result_id for result_id, handle in self._data.items() if handle.expires_at <= now]
        for result_id in expired:
            del self._data[result_id]
