"""Tests for owner-bound semantic result handles."""

from datetime import datetime, timezone
from typing import Callable

import pytest

from parrot.auth import PermissionContext
from parrot.semantic.errors import SemanticResultError
from parrot.semantic.results import ResultHandle, ResultHandleStore


def _context(
    pctx_factory: Callable[..., PermissionContext],
    *,
    user_id: str = "user-a",
    tenant_id: str = "t1",
    agent_id: str = "agent-a",
    session_id: str = "session-a",
) -> PermissionContext:
    """Build a permission context with the request-scoped handle bindings."""
    ctx = pctx_factory(user_id=user_id, tenant_id=tenant_id)
    ctx.extra.update({"agent_id": agent_id, "session_id": session_id})
    return ctx


def _handle() -> ResultHandle:
    """Build a result handle before the store replaces its id and expiry."""
    return ResultHandle(
        agent_id="agent-a",
        user_id="user-a",
        tenant_id="t1",
        session_id="session-a",
        subject_digest="subject-v1",
        model="orders",
        model_digest="model-v1",
        policy_digest="policy-v1",
        expires_at=datetime.now(timezone.utc),
        columns=["revenue"],
        rows=[{"revenue": 42}],
        audit_id="audit-1",
        governed_sql="SELECT 42 AS revenue",
    )


def test_result_handle_ownership(pctx_factory: Callable[..., PermissionContext]) -> None:
    """Reject unknown, foreign, expired, and stale handles without revealing why."""
    store = ResultHandleStore()
    result_id = store.put(_handle())
    owner = _context(pctx_factory)

    claimed = store.claim(
        result_id,
        ctx=owner,
        subject_digest="subject-v1",
        model_digest="model-v1",
        policy_digest="policy-v1",
    )
    assert claimed.result_id == result_id
    assert claimed.rows == [{"revenue": 42}]

    mismatches = [
        ("unknown", owner, "subject-v1", "model-v1", "policy-v1"),
        (result_id, _context(pctx_factory, user_id="user-b"), "subject-v1", "model-v1", "policy-v1"),
        (result_id, _context(pctx_factory, tenant_id="t2"), "subject-v1", "model-v1", "policy-v1"),
        (result_id, _context(pctx_factory, agent_id="agent-b"), "subject-v1", "model-v1", "policy-v1"),
        (result_id, _context(pctx_factory, session_id="session-b"), "subject-v1", "model-v1", "policy-v1"),
        (result_id, owner, "subject-v2", "model-v1", "policy-v1"),
        (result_id, owner, "subject-v1", "model-v2", "policy-v1"),
        (result_id, owner, "subject-v1", "model-v1", "policy-v2"),
    ]
    for candidate_id, ctx, subject_digest, model_digest, policy_digest in mismatches:
        with pytest.raises(SemanticResultError) as exc_info:
            store.claim(
                candidate_id,
                ctx=ctx,
                subject_digest=subject_digest,
                model_digest=model_digest,
                policy_digest=policy_digest,
            )
        assert exc_info.value.code == "result_unavailable"

    expired_store = ResultHandleStore(ttl_s=0)
    expired_id = expired_store.put(_handle())
    with pytest.raises(SemanticResultError) as exc_info:
        expired_store.claim(
            expired_id,
            ctx=owner,
            subject_digest="subject-v1",
            model_digest="model-v1",
            policy_digest="policy-v1",
        )
    assert exc_info.value.code == "result_unavailable"

    bounded_store = ResultHandleStore(max_entries=1)
    evicted_id = bounded_store.put(_handle())
    retained_id = bounded_store.put(_handle())
    with pytest.raises(SemanticResultError) as exc_info:
        bounded_store.claim(
            evicted_id,
            ctx=owner,
            subject_digest="subject-v1",
            model_digest="model-v1",
            policy_digest="policy-v1",
        )
    assert exc_info.value.code == "result_unavailable"
    assert (
        bounded_store.claim(
            retained_id,
            ctx=owner,
            subject_digest="subject-v1",
            model_digest="model-v1",
            policy_digest="policy-v1",
        ).result_id
        == retained_id
    )
