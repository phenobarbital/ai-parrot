"""The runner: what turns a stored review into an answered one.

Four properties are tested here more carefully than the rest, because each
fails silently rather than loudly:

* **``_save_result`` is called with ``tenant=``.** ``AgentsFlow`` inherits
  ``PersistenceMixin`` and never calls it, and the mixin does
  ``data.setdefault("tenant", "global")`` — so omitting the keyword files every
  tenant's execution rows under one shared bucket with no error anywhere.
* **The runtime is leased for the whole run.** Nodes hold their agents by
  reference; an eviction mid-run would close a live client.
* **A failed run is still a recorded run.** A worker that dies must leave
  evidence.
* **Nothing propagates.** A run starts from a background job, so an exception
  escaping here would be logged by the job manager and lost.
"""
from __future__ import annotations

import asyncio

import pytest
from parrot.bots.flows.core.storage.backends.base import ResultStorage

from parrot_saas.flows.community_manager.runner import (
    CommunityManagerRunner,
    review_to_intake,
)
from parrot_saas.reviews.models import Review
from parrot_saas.runs.models import RunStatus
from parrot_saas.tenancy.context import TenantContext
from parrot_saas.tenancy.runtime import TenantRuntime


@pytest.fixture
def tenant() -> TenantContext:
    """The tenant every run in this module serves."""
    return TenantContext(tenant_id="bar-pepe", name="Bar Pepe", timezone="Europe/Madrid")


def _review(**overrides) -> Review:
    """A stored review, as ingest hands it over."""
    payload = {
        "review_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "bar-pepe",
        "source": "mock",
        "external_id": "ext-1",
        "rating": 1,
        "text": "Cold food and a long wait.",
        "raw": {"everything": "the platform sent"},
    }
    payload.update(overrides)
    return Review(**payload)


class _Runtimes:
    """Stand-in for ``TenantRuntimeCache``, counting leases."""

    def __init__(self, runtime=None) -> None:
        self.runtime = runtime
        self.leases = 0
        self.max_concurrent = 0

    async def get(self, tenant):
        if self.runtime is None:
            self.runtime = TenantRuntime(tenant=tenant)
        return self.runtime


class _Runs:
    """Recording stand-in for ``RunRepository``."""

    def __init__(self, *, fail_start=None) -> None:
        self.started: list = []
        self.finished: list = []
        self.fail_start = fail_start

    async def start(self, tenant_id, run_id, *, review_id="", flow=""):
        if self.fail_start is not None:
            raise self.fail_start
        self.started.append((tenant_id, run_id, review_id, flow))

    async def finish(self, tenant_id, run_id, **fields):
        self.finished.append((tenant_id, run_id, fields))


class _Source:
    """A review source that accepts the reply."""

    def __init__(self) -> None:
        self.published: list = []

    async def reply(self, tenant_id, external_id, text):
        self.published.append((tenant_id, external_id, text))
        return type("_R", (), {"external_reply_id": "ext-reply-1"})()


class _Storage(ResultStorage):
    """Captures what ``PersistenceMixin`` writes.

    A real ``ResultStorage`` subclass rather than a duck: ``get_result_storage``
    resolves anything that is not an instance of it by *name*, so a plain
    stand-in would be silently replaced by the default backend.
    """

    def __init__(self) -> None:
        self.saved: list = []

    async def save(self, collection, document):
        self.saved.append((collection, document))

    async def fetch(self, collection, execution_id):
        return [d for c, d in self.saved if c == collection]

    async def close(self):
        return None


def _runner(**kw) -> CommunityManagerRunner:
    kw.setdefault("runtimes", _Runtimes())
    return CommunityManagerRunner(**kw)


# ---------------------------------------------------------------------------
# The run itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_review_is_answered_and_the_run_recorded(tenant):
    """The whole path, with only the review platform wired in."""
    runs, source = _Runs(), _Source()
    runner = _runner(runs=runs, review_sources={"mock": source})

    outcome = await runner.run(tenant, _review(), "aaaaaaaa-0000-0000-0000-000000000001")

    assert outcome["status"] == RunStatus.COMPLETED.value
    assert outcome["outcome"] == "replied_no_contact"
    assert len(source.published) == 1

    assert runs.started[0][:2] == ("bar-pepe", "aaaaaaaa-0000-0000-0000-000000000001")
    _, _, fields = runs.finished[0]
    assert fields["status"] is RunStatus.COMPLETED
    assert fields["replied"] is True
    assert fields["outcome"] == "replied_no_contact"
    assert fields["duration_ms"] >= 0
    assert [n["node_id"] for n in fields["nodes"]]


@pytest.mark.asyncio
async def test_the_tenant_reaches_the_execution_row(tenant):
    """Forgetting ``tenant=`` files the row under 'global' with no error.

    ``PersistenceMixin._save_result`` does ``data.setdefault("tenant",
    "global")``, so this is a silent cross-tenant mix-up rather than a crash —
    which is exactly why it is asserted rather than assumed.
    """
    runs, store = _Runs(), _Storage()
    runner = _runner(
        runs=runs, review_sources={"mock": _Source()}, result_storage=store
    )

    await runner.run(tenant, _review(), "aaaaaaaa-0000-0000-0000-000000000002")

    collection, document = store.saved[0]
    assert collection == "saas_cm_executions"
    assert document["tenant"] == "bar-pepe"
    assert document["execution_id"] == "aaaaaaaa-0000-0000-0000-000000000002"
    assert document["session_id"] == "11111111-1111-1111-1111-111111111111"
    assert document["method"] == "run_flow"


@pytest.mark.asyncio
async def test_the_runtime_is_leased_for_the_whole_run(tenant):
    """An eviction mid-run would close the agents the nodes are holding."""
    runtime = TenantRuntime(tenant=tenant)
    seen: list[bool] = []

    class _Source2(_Source):
        async def reply(self, tenant_id, external_id, text):
            seen.append(runtime.in_use)
            return await super().reply(tenant_id, external_id, text)

    runner = _runner(
        runtimes=_Runtimes(runtime), review_sources={"mock": _Source2()}
    )

    await runner.run(tenant, _review(), "aaaaaaaa-0000-0000-0000-000000000003")

    assert seen == [True]
    assert runtime.in_use is False


@pytest.mark.asyncio
async def test_the_tenant_concurrency_semaphore_is_honoured(tenant):
    """The scheduler caps nothing, so the runtime's semaphore has to."""
    runtime = TenantRuntime(tenant=tenant, semaphore=asyncio.Semaphore(1))
    live, peak = [0], [0]

    class _Slow(_Source):
        async def reply(self, tenant_id, external_id, text):
            live[0] += 1
            peak[0] = max(peak[0], live[0])
            await asyncio.sleep(0.02)
            live[0] -= 1
            return await super().reply(tenant_id, external_id, text)

    runner = _runner(runtimes=_Runtimes(runtime), review_sources={"mock": _Slow()})

    await asyncio.gather(
        *(
            runner.run(
                tenant,
                _review(external_id=f"ext-{i}"),
                f"aaaaaaaa-0000-0000-0000-00000000001{i}",
            )
            for i in range(3)
        )
    )

    assert peak[0] == 1


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failing_flow_is_recorded_as_failed(tenant):
    """The failure handler's summary becomes the run's failure."""
    class _Refuses:
        """A platform that rejects the reply — a run that genuinely failed."""

        async def reply(self, tenant_id, external_id, text):
            raise RuntimeError("403 from the review platform")

    runs = _Runs()
    runner = _runner(runs=runs, review_sources={"mock": _Refuses()})

    outcome = await runner.run(
        tenant, _review(), "aaaaaaaa-0000-0000-0000-000000000004"
    )

    assert outcome["status"] == RunStatus.FAILED.value
    _, _, fields = runs.finished[0]
    assert fields["status"] is RunStatus.FAILED
    assert fields["failed_node"] == "publish_reply"
    assert "403 from the review platform" in fields["error"]
    assert fields["replied"] is False


@pytest.mark.asyncio
async def test_a_runtime_that_cannot_be_built_is_recorded_not_raised(tenant):
    """A run starts from a background job; an exception here would be lost."""

    class _Broken:
        async def get(self, tenant):
            raise RuntimeError("secret store unreachable")

    runs = _Runs()
    runner = _runner(runtimes=_Broken(), runs=runs)

    outcome = await runner.run(
        tenant, _review(), "aaaaaaaa-0000-0000-0000-000000000005"
    )

    assert outcome["status"] == RunStatus.FAILED.value
    _, _, fields = runs.finished[0]
    assert "secret store unreachable" in fields["error"]


@pytest.mark.asyncio
async def test_the_run_happens_even_if_its_record_cannot_be_opened(tenant):
    """An unanswered guest is worse than a missing bookkeeping row."""
    runs = _Runs(fail_start=RuntimeError("db down"))
    source = _Source()
    runner = _runner(runs=runs, review_sources={"mock": source})

    outcome = await runner.run(
        tenant, _review(), "aaaaaaaa-0000-0000-0000-000000000006"
    )

    assert outcome["status"] == RunStatus.COMPLETED.value
    assert len(source.published) == 1


@pytest.mark.asyncio
async def test_a_malformed_run_id_does_not_stop_the_run(tenant):
    """The id comes from ingest, but a replay or a test may hand over junk."""
    runner = _runner(runs=_Runs(), review_sources={"mock": _Source()})

    outcome = await runner.run(tenant, _review(), "not-a-uuid")

    assert outcome["status"] == RunStatus.COMPLETED.value


# ---------------------------------------------------------------------------
# What crosses into the flow
# ---------------------------------------------------------------------------


def test_the_platforms_raw_payload_does_not_enter_the_flow():
    """``raw`` is the platform's whole original body.

    A ``model_dump`` round trip would carry it into shared state and from
    there into every checkpoint and execution row, for no benefit — the
    stored review already holds it.
    """
    intake = review_to_intake(_review())

    assert intake.rating == 1
    assert intake.text == "Cold food and a long wait."
    assert not hasattr(intake, "raw")


@pytest.mark.asyncio
async def test_the_tenant_timezone_reaches_the_rules(tenant):
    """In UTC, Saturday night in Madrid is not the weekend."""
    captured: dict = {}

    class _Rules:
        def evaluate_sync(self, ctx, env):
            captured["env"] = env
            return type("_R", (), {"matched": False, "value": None})()

    runtime = TenantRuntime(tenant=tenant, ruleset=_Rules())

    class _Guests:
        async def get(self, tenant_id, guest_id):
            from parrot_saas.reviews.models import Guest

            return Guest(
                guest_id=guest_id,
                tenant_id=tenant_id,
                email="g@example.com",
                consent_marketing=True,
            )

    runner = _runner(
        runtimes=_Runtimes(runtime),
        review_sources={"mock": _Source()},
        guests=_Guests(),
    )

    await runner.run(
        tenant,
        _review(guest_id="22222222-2222-2222-2222-222222222222"),
        "aaaaaaaa-0000-0000-0000-000000000007",
    )

    assert "env" in captured, "the eligibility node never evaluated the ruleset"
    assert captured["env"].timezone_name == "Europe/Madrid"


@pytest.mark.asyncio
async def test_usage_recorded_by_the_llm_nodes_reaches_the_run_row(tenant):
    """Two model calls per review, paid with the tenant's key."""

    class _Agent:
        async def invoke(self, task, **kwargs):
            text = (
                "We are very sorry about the wait and the cold food, and we "
                "have raised it with the team who were on that evening."
            )
            usage = type(
                "_U",
                (),
                {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            )()
            return type(
                "_M",
                (),
                {
                    "output": text,
                    "structured_output": text,
                    "usage": usage,
                    "model": "m",
                    "provider": "p",
                },
            )()

    runtime = TenantRuntime(tenant=tenant, agents={"reply_draft": _Agent()})
    runs = _Runs()
    runner = _runner(
        runtimes=_Runtimes(runtime), runs=runs, review_sources={"mock": _Source()}
    )

    await runner.run(tenant, _review(), "aaaaaaaa-0000-0000-0000-000000000008")

    _, _, fields = runs.finished[0]
    assert fields["usage"]["reply_draft"]["total_tokens"] == 120
