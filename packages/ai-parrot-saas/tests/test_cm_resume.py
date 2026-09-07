"""Resuming a Community Manager run.

The interesting case is the realistic one: a run that published nothing
because the review platform refused, checkpointed along the way, and is
restarted once the platform recovers. What must *not* happen is the reply
going out twice — so the assertions are as much about what is skipped as
about what runs.

An in-memory checkpoint store stands in for Redis; no external service is
involved.
"""
from __future__ import annotations


import pytest
from parrot.bots.flows.core.checkpoint import CheckpointNotFoundError, CheckpointStore

from parrot_saas.flows.community_manager import definition as topo
from parrot_saas.flows.community_manager.runner import (
    CommunityManagerRunner,
    RunNotResumable,
)
from parrot_saas.reviews.models import Review
from parrot_saas.runs.models import Run, RunStatus
from parrot_saas.tenancy.context import TenantContext
from parrot_saas.tenancy.runtime import TenantRuntime

class FakeCheckpointStore(CheckpointStore):
    """In-memory ``CheckpointStore`` — the full contract, no Redis.

    A real subclass, not a duck: ``get_checkpoint_store`` resolves anything
    that is not an instance of the ABC by *name*, so a plain stand-in would be
    silently replaced by the Redis backend.
    """

    def __init__(self) -> None:
        self._by_flow: dict[str, list] = {}
        self._leases: dict[str, str] = {}

    async def put(self, checkpoint) -> None:
        history = self._by_flow.setdefault(checkpoint.flow_id, [])
        history[:] = [
            c for c in history if c.checkpoint_id != checkpoint.checkpoint_id
        ]
        history.append(checkpoint)
        history.sort(key=lambda c: c.checkpoint_id)

    async def latest(self, flow_id: str):
        history = self._by_flow.get(flow_id, [])
        return history[-1] if history else None

    async def get(self, flow_id: str, checkpoint_id: int):
        for cp in self._by_flow.get(flow_id, []):
            if cp.checkpoint_id == checkpoint_id:
                return cp
        return None

    async def history(self, flow_id: str, limit: int = 10) -> list:
        return list(reversed(self._by_flow.get(flow_id, [])))[:limit]

    async def list_flows(self, status: str | None = None) -> list:
        return [{"flow_id": fid} for fid in self._by_flow]

    async def delete_flow(self, flow_id: str) -> None:
        self._by_flow.pop(flow_id, None)

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        if flow_id in self._leases:
            return False
        self._leases[flow_id] = holder
        return True

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        return self._leases.get(flow_id) == holder

    async def release_lease(self, flow_id: str, holder: str) -> None:
        if self._leases.get(flow_id) == holder:
            del self._leases[flow_id]

    async def close(self) -> None:
        return None


RUN_ID = "aaaaaaaa-0000-0000-0000-0000000000ff"


@pytest.fixture
def tenant() -> TenantContext:
    """The tenant whose run is being resumed."""
    return TenantContext(tenant_id="bar-pepe", name="Bar Pepe")


def _review(**overrides) -> Review:
    """The stored review a run is about."""
    payload = {
        "review_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "bar-pepe",
        "source": "mock",
        "external_id": "ext-1",
        "rating": 1,
        "text": "Cold food and a long wait.",
    }
    payload.update(overrides)
    return Review(**payload)


class _Runtimes:
    """Stand-in for ``TenantRuntimeCache``."""

    def __init__(self, runtime=None) -> None:
        self.runtime = runtime

    async def get(self, tenant):
        if self.runtime is None:
            self.runtime = TenantRuntime(tenant=tenant)
        return self.runtime


class _Reviews:
    """Only what the runner reads back."""

    def __init__(self, review: Review) -> None:
        self.review = review
        self.statuses: list = []
        self.replies: list = []

    async def get(self, tenant_id, review_id):
        return self.review

    async def set_status(self, tenant_id, review_id, status):
        self.statuses.append(status)
        return self.review

    async def record_reply(self, tenant_id, review_id, **kw):
        self.replies.append(kw)


class _Runs:
    """Recording stand-in for ``RunRepository``."""

    def __init__(self, record: Run | None = None) -> None:
        self.record = record
        self.started: list = []
        self.finished: list = []

    async def get(self, tenant_id, run_id):
        return self.record

    async def start(self, tenant_id, run_id, *, review_id="", flow=""):
        self.started.append((tenant_id, run_id, review_id))

    async def finish(self, tenant_id, run_id, **fields):
        self.finished.append(fields)


class _Refusing:
    """A platform that rejects the first reply and accepts the next."""

    def __init__(self) -> None:
        self.published: list = []
        self.refuse = True

    async def reply(self, tenant_id, external_id, text):
        if self.refuse:
            raise RuntimeError("503 from the review platform")
        self.published.append((tenant_id, external_id, text))
        return type("_R", (), {"external_reply_id": "ext-reply-1"})()


def _runner(store, source, reviews, runs, **kw) -> CommunityManagerRunner:
    return CommunityManagerRunner(
        runtimes=_Runtimes(),
        runs=runs,
        reviews=reviews,
        review_sources={"mock": source},
        checkpoint=True,
        checkpoint_store=store,
        **kw,
    )


# ---------------------------------------------------------------------------
# The real case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_run_resumes_and_publishes(tenant):
    """A platform outage should cost a retry, not a whole re-run."""
    store, source = FakeCheckpointStore(), _Refusing()
    reviews, runs = _Reviews(_review()), _Runs()
    runner = _runner(store, source, reviews, runs)

    first = await runner.run(tenant, _review(), RUN_ID)
    assert first["status"] == RunStatus.FAILED.value
    assert source.published == []

    # The platform recovers.
    source.refuse = False
    runs.record = Run(
        run_id=RUN_ID,
        tenant_id="bar-pepe",
        review_id=reviews.review.review_id,
        status=RunStatus.FAILED,
    )

    resumed = await runner.resume_run(tenant, RUN_ID)

    assert resumed["status"] == RunStatus.COMPLETED.value
    assert len(source.published) == 1
    assert runs.finished[-1]["status"] is RunStatus.COMPLETED
    assert runs.finished[-1]["replied"] is True


@pytest.mark.asyncio
async def test_a_resume_does_not_call_the_model_again(tenant):
    """Completed nodes are seeded, not re-executed.

    This is the property a resume exists for, and it is money: without it a
    restart re-runs triage and drafting, two model calls on the tenant's own
    key for work that was already done and whose result is sitting in the
    checkpoint.

    Asserted on the agent rather than on ``result.nodes``, which reports the
    whole graph's final state — seeded nodes included — and so cannot tell a
    re-execution from a restored one.
    """

    class _CountingAgent:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke(self, task, **kwargs):
            self.calls += 1
            text = (
                "We are sorry about the wait and the cold food, and we have "
                "raised it with the team who were on that evening."
            )
            return type(
                "_M",
                (),
                {"output": text, "structured_output": text, "usage": None},
            )()

    agent = _CountingAgent()
    store, source = FakeCheckpointStore(), _Refusing()
    reviews, runs = _Reviews(_review()), _Runs()
    runner = _runner(store, source, reviews, runs)
    runner._runtimes = _Runtimes(
        TenantRuntime(tenant=tenant, agents={"reply_draft": agent})
    )

    await runner.run(tenant, _review(), RUN_ID)
    assert agent.calls == 1

    source.refuse = False
    runs.record = Run(
        run_id=RUN_ID, tenant_id="bar-pepe", review_id=reviews.review.review_id
    )
    await runner.resume_run(tenant, RUN_ID)

    assert agent.calls == 1, "the resume re-drafted a reply it already had"
    assert len(source.published) == 1


@pytest.mark.asyncio
async def test_the_resumed_graph_keeps_its_live_dependencies(tenant):
    """The regression the core change exists for.

    Rebuilt from the checkpoint's definition instead, ``publish_reply`` would
    come back with ``review_source=None`` — no exception, no publication, and
    a run that closes reporting success.
    """
    store, source = FakeCheckpointStore(), _Refusing()
    reviews, runs = _Reviews(_review()), _Runs()
    runner = _runner(store, source, reviews, runs)

    await runner.run(tenant, _review(), RUN_ID)
    source.refuse = False
    runs.record = Run(
        run_id=RUN_ID, tenant_id="bar-pepe", review_id=reviews.review.review_id
    )

    await runner.resume_run(tenant, RUN_ID)

    # It published, which it could only do holding the real adapter.
    assert source.published[0][1] == "ext-1"


@pytest.mark.asyncio
async def test_the_resumed_graph_keeps_the_or_join(tenant):
    """``close`` has six predecessors; under AND-join it never fires.

    A definition-rebuilt flow loses the explicit-edge scheduler, so this
    assertion fails there even when the dependencies survive.
    """
    store, source = FakeCheckpointStore(), _Refusing()
    reviews, runs = _Reviews(_review()), _Runs()
    runner = _runner(store, source, reviews, runs)

    await runner.run(tenant, _review(), RUN_ID)
    source.refuse = False
    runs.record = Run(
        run_id=RUN_ID, tenant_id="bar-pepe", review_id=reviews.review.review_id
    )

    outcome = await runner.resume_run(tenant, RUN_ID)

    executed = [n["node_id"] for n in runs.finished[-1]["nodes"]]
    assert topo.CLOSE in executed
    assert outcome["outcome"] == "replied_no_contact"


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_run_with_no_checkpoint_says_so(tenant):
    """The normal answer when the deployment is not checkpointing."""
    runs = _Runs(Run(run_id=RUN_ID, tenant_id="bar-pepe"))
    runner = _runner(FakeCheckpointStore(), _Refusing(), _Reviews(_review()), runs)

    with pytest.raises(CheckpointNotFoundError):
        await runner.resume_run(tenant, RUN_ID)


@pytest.mark.asyncio
async def test_a_completed_run_is_not_resumable(tenant):
    """Re-entering a finished flow could publish a second reply."""
    runs = _Runs(
        Run(run_id=RUN_ID, tenant_id="bar-pepe", status=RunStatus.COMPLETED)
    )
    runner = _runner(FakeCheckpointStore(), _Refusing(), _Reviews(_review()), runs)

    with pytest.raises(RunNotResumable, match="already completed"):
        await runner.resume_run(tenant, RUN_ID)


@pytest.mark.asyncio
async def test_the_run_record_is_reopened_on_a_resume(tenant):
    """A resumed run must not stay 'failed' while it is running again."""
    store, source = FakeCheckpointStore(), _Refusing()
    reviews, runs = _Reviews(_review()), _Runs()
    runner = _runner(store, source, reviews, runs)

    await runner.run(tenant, _review(), RUN_ID)
    source.refuse = False
    runs.record = Run(
        run_id=RUN_ID, tenant_id="bar-pepe", review_id=reviews.review.review_id
    )
    runs.started.clear()

    await runner.resume_run(tenant, RUN_ID)

    assert runs.started == [("bar-pepe", RUN_ID, reviews.review.review_id)]
