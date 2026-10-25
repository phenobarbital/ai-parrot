"""Reusable contract cases for trusted host adapters; flags alone are insufficient."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from parrot.semantic.context import SemanticRequestIdentity
from parrot.semantic.errors import SemanticResultError
from parrot.semantic.handoff import GovernedDatasetSink, ReadAuthorizer, handle_owner
from parrot.semantic.results import ResultHandle

EXPOSURES = ("list", "describe", "sample", "cache", "query", "export", "derive")


class PrivateManagerAdapter:
    """Representative test adapter: a private store whose every route calls the authorizer."""

    guarded_reads = True

    def __init__(self, scope_id: str, owner: tuple[str, str, str, str]) -> None:
        """Create an adapter bound to one scope and owner."""
        self.scope_id = scope_id
        self.owner = owner
        self._items: dict[str, ResultHandle] = {}
        self._authorize: ReadAuthorizer | None = None

    async def publish(self, name: str, handle: ResultHandle, authorize_read: ReadAuthorizer) -> dict[str, Any]:
        """Keep a private copy and the authorizer; return metadata only."""
        self._items[name] = handle.model_copy(deep=True)
        self._authorize = authorize_read
        return {"name": name, "scope_id": self.scope_id, "rows": len(handle.rows)}

    async def route(self, exposure: str, name: str, identity: SemanticRequestIdentity) -> dict[str, Any]:
        """Serve one exposure after invoking the read callback for the current caller."""
        if self._authorize is None or name not in self._items:
            raise SemanticResultError("result_unavailable", "Result is unavailable")
        await self._authorize(identity)
        item = self._items[name]
        if exposure == "list":
            return {"names": sorted(self._items)}
        if exposure == "describe":
            return {"columns": list(item.columns), "model": item.model}
        if exposure == "derive":
            return {
                "rows": [dict(row) for row in item.rows],
                "provenance": (item.model, item.model_digest, item.policy_digest),
                "expires_at": item.expires_at,
            }
        if exposure == "sample":
            return {"rows": [dict(row) for row in item.rows[:1]]}
        return {"rows": [dict(row) for row in item.rows]}


def make_handle(owner: SemanticRequestIdentity, *, ttl: timedelta = timedelta(hours=1)) -> ResultHandle:
    """Build a retained handle owned by ``owner`` for conformance probes."""
    return ResultHandle(
        result_id="probe",
        agent_id=owner.agent_id,
        user_id=owner.ctx.user_id,
        tenant_id=owner.ctx.tenant_id,
        session_id=owner.session_id,
        subject_digest="subject-probe",
        model="sales",
        model_digest="model-v1",
        policy_digest="policy-v1",
        expires_at=datetime.now(timezone.utc) + ttl,
        members=("revenue",),
        physical_columns=("public.sales.amount",),
        physical_tables=("public.sales",),
        columns=["Revenue"],
        rows=[{"Revenue": 10}, {"Revenue": 20}],
        audit_id="audit-probe",
        governed_sql="SELECT amount FROM public.sales",
    )


async def assert_sink_conformance(
    factory: Callable[..., Awaitable[GovernedDatasetSink]],
    identities: tuple[SemanticRequestIdentity, ...],
) -> None:
    """Exercise every adapter exposure with authorization revocation and expiry.

    Args:
        factory: Awaitable building a sink with ``scope_id``/``owner`` of ``identities[0]``.
        identities: ``(owner, other)`` trusted identities; the second must be a different subject.
    """
    owner, other = identities[0], identities[1]
    sink = await factory()
    assert sink.guarded_reads is True
    assert sink.owner == (owner.agent_id, owner.ctx.user_id, owner.ctx.tenant_id, owner.session_id)
    handle = make_handle(owner)
    assert handle_owner(handle) == sink.owner

    seen: list[SemanticRequestIdentity] = []
    state = {"revoked": False}

    async def authorize_read(identity: SemanticRequestIdentity) -> None:
        seen.append(identity)
        if state["revoked"] or identity is not owner:
            raise SemanticResultError("result_unavailable", "Result is unavailable")

    published = await sink.publish("probe", handle, authorize_read)
    assert isinstance(published, dict)
    assert not any(type(value).__name__ in {"DatasetManager", "DataFrame"} for value in published.values())
    route = sink.route

    for exposure in EXPOSURES:
        before = len(seen)
        result = await route(exposure, "probe", owner)
        assert len(seen) == before + 1 and seen[-1] is owner, f"{exposure} did not call the authorizer"
        assert result
        if exposure == "derive":
            assert result["expires_at"] <= handle.expires_at
            assert result["provenance"] == (handle.model, handle.model_digest, handle.policy_digest)
        with pytest.raises(SemanticResultError):
            await route(exposure, "probe", other)
        assert seen[-1] is other, f"{exposure} used a captured identity instead of the current caller"

    state["revoked"] = True
    for exposure in EXPOSURES:
        with pytest.raises(SemanticResultError):
            await route(exposure, "probe", owner)
