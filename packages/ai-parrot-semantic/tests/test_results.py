"""Regression contract: Scoped result handles and exact retained provenance (M9b)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from parrot.auth import PermissionContext, UserSession
from parrot.semantic.context import SemanticRequestIdentity
from parrot.semantic.errors import SemanticResultError
from parrot.semantic.results import ResultHandle, ResultHandleStore


def _identity(
    *, user_id: str = "user-1", tenant_id: str = "tenant-1", agent_id: str = "agent-1", session_id: str = "session-1"
) -> SemanticRequestIdentity:
    """Build a trusted, isolated semantic identity for a claim test."""
    context = PermissionContext(session=UserSession(user_id, tenant_id, frozenset({"analyst"}), {"region": "EU"}))
    return SemanticRequestIdentity(ctx=context, channel="agent", agent_id=agent_id, session_id=session_id)


def _handle() -> ResultHandle:
    """Build a governed result with exact semantic and physical provenance."""
    return ResultHandle(
        result_id="pending",
        agent_id="agent-1",
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        subject_digest="subject-v1",
        model="sales",
        model_digest="model-v1",
        policy_digest="policy-v1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        members=("revenue", "region"),
        physical_columns=("public.sales.amount", "public.sales.region"),
        physical_tables=("public.sales",),
        columns=["Revenue", "Region"],
        rows=[{"Revenue": 10, "Region": "EU"}],
        audit_id="audit-1",
        governed_sql="SELECT amount, region FROM public.sales",
    )


def _claim(store: ResultHandleStore, result_id: str, identity: SemanticRequestIdentity) -> ResultHandle:
    """Claim with the current, matching governance digests."""
    return store.claim(
        result_id,
        identity=identity,
        subject_digest="subject-v1",
        model_digest="model-v1",
        policy_digest="policy-v1",
    )


def test_same_user_distinct_sessions_and_agents(tmp_path: Path) -> None:
    """Deny retained results to other sessions or agents for the same user."""
    del tmp_path
    store = ResultHandleStore()
    result_id = store.put(_handle())

    assert _claim(store, result_id, _identity()).rows == [{"Revenue": 10, "Region": "EU"}]
    for identity in (_identity(session_id="session-2"), _identity(agent_id="agent-2"), _identity(user_id="user-2")):
        with pytest.raises(SemanticResultError) as error:
            _claim(store, result_id, identity)
        assert error.value.code == "result_unavailable"


def test_expiry_context_policy_and_provenance(tmp_path: Path) -> None:
    """Deny expired, foreign-tenant, and stale-context/version claims."""
    del tmp_path
    store = ResultHandleStore()
    result_id = store.put(_handle())
    identity = _identity()

    for kwargs in (
        {"identity": _identity(tenant_id="tenant-2")},
        {"subject_digest": "roles-or-metadata-changed"},
        {"model_digest": "model-v2"},
        {"policy_digest": "policy-v2"},
    ):
        args = {
            "identity": identity,
            "subject_digest": "subject-v1",
            "model_digest": "model-v1",
            "policy_digest": "policy-v1",
        }
        args.update(kwargs)
        with pytest.raises(SemanticResultError) as error:
            store.claim(result_id, **args)
        assert error.value.code == "result_unavailable"

    expired = ResultHandleStore(ttl_s=0)
    expired_id = expired.put(_handle())
    with pytest.raises(SemanticResultError) as error:
        _claim(expired, expired_id, identity)
    assert error.value.code == "result_unavailable"


def test_defensive_copy_and_bounded_store(tmp_path: Path) -> None:
    """Return detached rows and evict entries according to bounded retention."""
    del tmp_path
    source = _handle()
    store = ResultHandleStore(max_entries=1)
    first_id = store.put(source)
    source.rows[0]["Revenue"] = 99
    claimed = _claim(store, first_id, _identity())
    claimed.rows[0]["Revenue"] = 42
    assert _claim(store, first_id, _identity()).rows == [{"Revenue": 10, "Region": "EU"}]

    second_id = store.put(_handle())
    with pytest.raises(SemanticResultError) as error:
        _claim(store, first_id, _identity())
    assert error.value.code == "result_unavailable"
    assert _claim(store, second_id, _identity()).result_id == second_id
