"""Regression coverage for queued command declarations, execution and messages."""

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from parrot.jobs import JobManager, JobStatus
from parrot.integrations.core.queued import (
    CommandUsageError,
    JobNotice,
    JobView,
    PreparedCommand,
    QueuedCommand,
    QueuedCommandService,
    QueuedCommandSpec,
    Requester,
    SubmitOutcome,
    current_job_id,
    discover_queued_commands,
    queued_command,
    queued_spec_of,
    report_command_progress,
)
from parrot.integrations.core.queued.messages import (
    format_ack,
    format_cancel,
    format_job_list,
    format_job_view,
    format_notice_header,
)


@pytest.mark.parametrize("name", ["pr-review", "PR_REVIEW", "a" * 33, ""])
def test_queued_command_rejects_bad_name(name: str) -> None:
    """Reject non-canonical command names at decoration time."""

    with pytest.raises(ValueError, match="command must match"):
        queued_command(name)


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("max_runtime", 0),
        ("max_runtime", float("inf")),
        ("max_queue_wait", -1),
        ("max_queue_wait", float("nan")),
        ("max_concurrent", 0),
        ("max_concurrent", 1.5),
    ],
)
def test_queued_command_rejects_invalid_limits(argument: str, value: float) -> None:
    """Reject non-positive, non-finite, and non-integral limits."""

    with pytest.raises(ValueError):
        queued_command("review", **{argument: value})


def test_queued_command_returns_original_and_attaches_spec() -> None:
    """Keep direct calls inline while attaching the complete declaration."""

    async def review() -> str:
        return "done"

    decorated = queued_command(
        "pr_review",
        "Review a PR",
        aliases=("pr-review",),
        prepare="prepare_review",
        max_runtime=12,
        max_queue_wait=34,
        max_concurrent=3,
        concurrency_group="reviews",
    )(review)

    assert decorated is review
    spec = queued_spec_of(review)
    assert spec is not None
    assert spec.command == "pr_review"
    assert spec.aliases == ("pr-review",)
    assert spec.max_runtime == 12
    assert spec.max_queue_wait == 34
    assert spec.max_concurrent == 3
    assert spec.concurrency_group == "reviews"


def test_discover_skips_missing_prepare(caplog: pytest.LogCaptureFixture) -> None:
    """Skip invalid prepare hooks while discovering other queued methods."""

    class Agent:
        @queued_command("bad", prepare="_nope")
        async def bad(self) -> None:
            return None

        @queued_command("good")
        async def good(self) -> None:
            return None

    with caplog.at_level("ERROR"):
        commands = discover_queued_commands(Agent())

    assert [command.spec.command for command in commands] == ["good"]
    assert "prepare hook _nope is missing or not callable" in caplog.text


def test_discovery_resolves_bound_prepare_and_skips_private() -> None:
    """Return bound methods and ignore private decorated attributes."""

    class Agent:
        async def prepare_review(self, raw: str) -> str:
            return raw

        @queued_command("review", prepare="prepare_review")
        async def review(self) -> str:
            return "done"

        @queued_command("hidden")
        async def _hidden(self) -> None:
            return None

    agent = Agent()
    commands = discover_queued_commands(agent)

    assert len(commands) == 1
    assert commands[0].method == agent.review
    assert commands[0].prepare == agent.prepare_review
    assert queued_spec_of(agent.review) is queued_spec_of(Agent.review)


def test_requester_actor_is_platform_scoped() -> None:
    """Scope job ownership by platform and user identifier."""

    requester = Requester(platform="telegram", user_id="42", chat_id="100")
    assert requester.actor == "telegram:42"


def test_shared_message_formatters_cover_job_states() -> None:
    """Keep fixed user-facing job text in the shared messages module."""

    accepted = SubmitOutcome(status="accepted", job_id="abc123", label="review PR", message="ignored")
    duplicate = SubmitOutcome(status="duplicate", job_id="abc123", label="review PR", message="ignored")
    rejected = SubmitOutcome(status="rejected", message="Usage: /review <PR>")
    assert format_ack(accepted).startswith("⏳ Accepted — job `abc123`: review PR.")
    assert "Already running — job `abc123`" in format_ack(duplicate)
    assert format_ack(rejected) == "Usage: /review <PR>"

    notice = JobNotice(job_id="abc123", command="review", label="review PR", status="completed", elapsed_s=72)
    assert format_notice_header(notice) == "✅ Job `abc123` finished in 1m12s — review PR"
    timeout = notice.model_copy(update={"status": "timed_out"})
    assert "timed out after 1m12s" in format_notice_header(timeout)
    queue_timeout = timeout.model_copy(update={"error": "timed out waiting for a slot after 30s"})
    assert "timed out waiting for a slot after 30s" in format_notice_header(queue_timeout)
    interrupted = notice.model_copy(
        update={"status": "cancelled", "error": "interrupted — the bot is shutting down; run the command again"}
    )
    assert format_notice_header(interrupted).endswith("— the bot is shutting down; run the command again")


def test_job_views_lists_and_cancellation_hide_unknown_ownership() -> None:
    """Differentiate queue state and use identical unknown/foreign wording."""

    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    queued = JobView(job_id="one", command="review", label="first", status="queued", created_at=created_at)
    running = queued.model_copy(update={"job_id": "two", "status": "running", "progress": "Reading files"})

    assert "queued (waiting for a slot)" in format_job_view(queued)
    assert "running" in format_job_view(running)
    assert "Progress: Reading files" in format_job_view(running)
    assert format_job_list([]) == "You have no recent jobs."
    assert format_job_list([queued, running]).splitlines()[0] == "Your recent jobs:"
    assert format_cancel("not_found", "secret") == format_cancel("foreign", "secret")
    assert format_cancel("not_found", "secret") == "No job `secret` found for you."


class _Recorder:
    """Capture terminal notices and expose deterministic synchronization."""

    def __init__(self) -> None:
        self.notices: list[JobNotice] = []
        self.received = asyncio.Event()

    async def __call__(self, notice: JobNotice) -> None:
        self.notices.append(notice)
        self.received.set()


def _requester(user_id: str = "42") -> Requester:
    """Build a stable Telegram requester for service tests."""

    return Requester(platform="telegram", user_id=user_id, chat_id="chat", thread_id="topic")


def _command(
    method: Any,
    *,
    name: str = "review",
    prepare: Any = None,
    max_runtime: float = 1.0,
    max_queue_wait: float = 1.0,
    max_concurrent: int = 2,
    concurrency_group: str | None = None,
) -> QueuedCommand:
    """Build a discovered-command equivalent with explicit execution limits."""

    return QueuedCommand(
        spec=QueuedCommandSpec(
            command=name,
            description="review request",
            max_runtime=max_runtime,
            max_queue_wait=max_queue_wait,
            max_concurrent=max_concurrent,
            concurrency_group=concurrency_group,
        ),
        method_name=name,
        method=method,
        prepare=prepare,
    )


def _service(**kwargs: Any) -> QueuedCommandService:
    """Build a service with an injected in-memory manager."""

    return QueuedCommandService(
        owner="test:bot",
        job_manager=kwargs.pop("job_manager", JobManager(id="test")),
        use_redis=False,
        **kwargs,
    )


async def _wait_for_terminal(service: QueuedCommandService, job_id: str) -> None:
    """Yield until JobManager records a terminal transition."""

    deadline = asyncio.get_running_loop().time() + 1.0
    while asyncio.get_running_loop().time() < deadline:
        if service.manager.jobs[job_id].status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return
        await asyncio.sleep(0.001)
    raise AssertionError(f"job {job_id} did not become terminal")


@pytest.mark.asyncio
async def test_submit_accepts_and_delivers_result() -> None:
    """Accept a local job, deliver its result, and store bounded JSON-safe text."""

    async def method() -> str:
        return "done"

    service = _service()
    recorder = _Recorder()
    outcome = await service.submit(_command(method), "", _requester(), recorder)

    assert outcome.status == "accepted"
    assert outcome.job_id is not None
    assert len(outcome.job_id) == 12
    assert all(character in "0123456789abcdef" for character in outcome.job_id)
    await recorder.received.wait()
    await _wait_for_terminal(service, outcome.job_id)
    assert recorder.notices[0].status == "completed"
    assert recorder.notices[0].result == "done"
    assert service.manager.jobs[outcome.job_id].result == {"text": "done"}
    await service.stop()


@pytest.mark.asyncio
async def test_submit_usage_error_creates_no_job() -> None:
    """Reject preparation usage errors verbatim without reserving or creating."""

    async def method() -> str:
        return "unreachable"

    async def prepare(raw: str) -> PreparedCommand:
        raise CommandUsageError(f"Usage: /review {raw}".rstrip())

    service = _service()
    outcome = await service.submit(_command(method, prepare=prepare), "<PR>", _requester(), _Recorder())

    assert outcome.status == "rejected"
    assert outcome.message == "Usage: /review <PR>"
    assert service.manager.jobs == {}
    await service.stop()


@pytest.mark.asyncio
async def test_submit_duplicate_returns_existing_job() -> None:
    """Return the active local reservation and release it after completion."""

    release = asyncio.Event()
    started = asyncio.Event()

    async def method() -> str:
        started.set()
        await release.wait()
        return "done"

    async def prepare(_: str) -> PreparedCommand:
        return PreparedCommand(label="same PR", dedup_key="review:1")

    service = _service()
    command = _command(method, prepare=prepare)
    first = await service.submit(command, "", _requester(), _Recorder())
    await started.wait()
    duplicate = await service.submit(command, "", _requester(), _Recorder())

    assert duplicate.status == "duplicate"
    assert duplicate.job_id == first.job_id
    assert len(service.manager.jobs) == 1

    release.set()
    await _wait_for_terminal(service, first.job_id)
    again = await service.submit(command, "", _requester(), _Recorder())
    assert again.status == "accepted"
    assert again.job_id != first.job_id
    await _wait_for_terminal(service, again.job_id)
    await service.stop()


@pytest.mark.asyncio
async def test_concurrency_group_caps_parallel_runs() -> None:
    """Share the first declared concurrency cap across commands in a group."""

    release = asyncio.Event()
    first_started = asyncio.Event()
    second_started = asyncio.Event()

    async def first_method() -> str:
        first_started.set()
        await release.wait()
        return "first"

    async def second_method() -> str:
        second_started.set()
        return "second"

    service = _service()
    first = await service.submit(
        _command(first_method, name="first", max_concurrent=1, concurrency_group="reviews"),
        "",
        _requester(),
        _Recorder(),
    )
    await first_started.wait()
    second = await service.submit(
        _command(second_method, name="second", max_concurrent=5, concurrency_group="reviews"),
        "",
        _requester(),
        _Recorder(),
    )
    await asyncio.sleep(0)

    second_view = await service.get(second.job_id, _requester())
    assert second_view is not None
    assert second_view.status == "queued"
    assert not second_started.is_set()

    release.set()
    await _wait_for_terminal(service, first.job_id)
    await _wait_for_terminal(service, second.job_id)
    assert second_started.is_set()
    await service.stop()


@pytest.mark.asyncio
async def test_max_runtime_times_out() -> None:
    """Map execution deadline exhaustion to FAILED and one timed-out notice."""

    never = asyncio.Event()

    async def method() -> None:
        await never.wait()

    service = _service()
    recorder = _Recorder()
    outcome = await service.submit(_command(method, max_runtime=0.01), "", _requester(), recorder)
    await recorder.received.wait()
    await _wait_for_terminal(service, outcome.job_id)

    job = service.manager.jobs[outcome.job_id]
    assert [notice.status for notice in recorder.notices] == ["timed_out"]
    assert job.status == JobStatus.FAILED
    assert job.error.startswith("timed out after")
    await service.stop()


@pytest.mark.asyncio
async def test_failure_notice_and_status() -> None:
    """Deliver a bounded failure notice and let JobManager record FAILED."""

    error = "x" * 400

    async def method() -> None:
        raise RuntimeError(error)

    service = _service()
    recorder = _Recorder()
    outcome = await service.submit(_command(method), "", _requester(), recorder)
    await recorder.received.wait()
    await _wait_for_terminal(service, outcome.job_id)

    assert recorder.notices[0].status == "failed"
    assert len(recorder.notices[0].error) == 300
    assert service.manager.jobs[outcome.job_id].status == JobStatus.FAILED
    await service.stop()


@pytest.mark.asyncio
async def test_stop_interrupts_and_notifies() -> None:
    """Notify before shutdown completes and retain the interruption reason."""

    started = asyncio.Event()
    never = asyncio.Event()

    async def method() -> None:
        started.set()
        await never.wait()

    service = _service()
    recorder = _Recorder()
    outcome = await service.submit(_command(method), "", _requester(), recorder)
    await started.wait()
    await service.stop()

    job = service.manager.jobs[outcome.job_id]
    assert job.status == JobStatus.CANCELLED
    assert job.error == "interrupted — the bot is shutting down; run the command again"
    assert recorder.notices[0].status == "cancelled"
    assert recorder.notices[0].error == job.error
    await service.stop()


@pytest.mark.asyncio
async def test_stop_waits_for_in_flight_admission_before_cancelling() -> None:
    """Prevent prepare-to-scheduler races from leaving a job after shutdown."""

    preparing = asyncio.Event()
    release_prepare = asyncio.Event()
    recorder = _Recorder()

    async def prepare(_: str) -> PreparedCommand:
        preparing.set()
        await release_prepare.wait()
        return PreparedCommand()

    async def method() -> None:
        await asyncio.Event().wait()

    service = _service()
    submit_task = asyncio.create_task(service.submit(_command(method, prepare=prepare), "", _requester(), recorder))
    await preparing.wait()
    stop_task = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    release_prepare.set()

    outcome = await submit_task
    await stop_task
    assert outcome.status == "accepted"
    assert service.manager.jobs[outcome.job_id].status == JobStatus.CANCELLED
    assert recorder.notices[0].status == "cancelled"
    assert service.manager.tasks == {}


@pytest.mark.asyncio
async def test_get_and_cancel_are_owner_scoped() -> None:
    """Hide a live job from another actor and cancel it for its requester."""

    started = asyncio.Event()
    never = asyncio.Event()

    async def method() -> None:
        started.set()
        await never.wait()

    service = _service()
    recorder = _Recorder()
    owner = _requester("owner")
    foreign = _requester("foreign")
    outcome = await service.submit(_command(method), "", owner, recorder)
    await started.wait()

    assert await service.get(outcome.job_id, foreign) is None
    assert await service.cancel(outcome.job_id, foreign) == "not_found"
    assert await service.cancel(outcome.job_id, owner) == "cancelling"
    await _wait_for_terminal(service, outcome.job_id)
    assert service.manager.jobs[outcome.job_id].error == "cancelled by the requester"
    await service.stop()


@pytest.mark.asyncio
async def test_expired_view_for_orphan() -> None:
    """Expire only foreign non-terminal records with an elapsed immutable deadline."""

    manager = JobManager(id="test")
    service = _service(job_manager=manager)
    await service.start()
    requester = _requester()
    past = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
    common = {"command": "review", "label": "PR", "phase": "queued"}
    expired = manager.create_job(
        "expired", "owner:review", {}, user_id=requester.actor, metadata={**common, "expires_at": past}
    )
    unknown = manager.create_job("unknown", "owner:review", {}, user_id=requester.actor, metadata=common)
    terminal = manager.create_job(
        "terminal", "owner:review", {}, user_id=requester.actor, metadata={**common, "expires_at": past}
    )
    terminal.status = JobStatus.COMPLETED

    assert (await service.get(expired.job_id, requester)).status == "expired"
    assert (await service.get(unknown.job_id, requester)).status == "queued"
    assert (await service.get(terminal.job_id, requester)).status == "completed"
    await service.stop()


@pytest.mark.asyncio
async def test_report_command_progress_visible_in_view() -> None:
    """Expose ContextVar progress in views and reset context after execution."""

    observed_job_id: list[str | None] = []

    async def method() -> str:
        observed_job_id.append(current_job_id())
        await report_command_progress("reading files")
        return "done"

    await report_command_progress("outside")
    service = _service()
    outcome = await service.submit(_command(method), "", _requester(), _Recorder())
    await _wait_for_terminal(service, outcome.job_id)
    view = await service.get(outcome.job_id, _requester())

    assert observed_job_id == [outcome.job_id]
    assert view.progress == "reading files"
    assert current_job_id() is None
    await service.stop()


@pytest.mark.asyncio
async def test_deliver_failure_does_not_change_status() -> None:
    """Isolate platform delivery errors from the JobManager state machine."""

    async def method() -> str:
        return "done"

    async def deliver(_: JobNotice) -> None:
        raise RuntimeError("chat unavailable")

    service = _service()
    outcome = await service.submit(_command(method), "", _requester(), deliver)
    await _wait_for_terminal(service, outcome.job_id)
    assert service.manager.jobs[outcome.job_id].status == JobStatus.COMPLETED
    await service.stop()


@pytest.mark.asyncio
async def test_slack_ack_with_slow_or_unavailable_redis() -> None:
    """Keep first/subsequent admissions local when persistence stalls."""

    class SlowStore:
        async def connect(self) -> None:
            await asyncio.Event().wait()

        async def save(self, job: Any) -> None:
            del job
            await asyncio.Event().wait()

        async def close(self) -> None:
            return None

    async def method() -> str:
        return "done"

    manager = JobManager(id="slow", store=SlowStore(), persistence_timeout=0.01)
    service = _service(job_manager=manager, admission_timeout=0.1)
    first = await service.submit(_command(method), "", _requester(), _Recorder())
    second = await service.submit(_command(method), "", _requester(), _Recorder())

    assert first.status == second.status == "accepted"
    await _wait_for_terminal(service, first.job_id)
    await _wait_for_terminal(service, second.job_id)
    await service.stop()

    async def slow_prepare(_: str) -> PreparedCommand:
        await asyncio.Event().wait()

    timeout_service = _service(prepare_timeout=0.01, admission_timeout=0.05)
    rejected = await timeout_service.submit(
        _command(method, prepare=slow_prepare),
        "",
        _requester(),
        _Recorder(),
    )
    assert rejected.status == "rejected"
    assert timeout_service.manager.jobs == {}
    assert timeout_service._reservations == {}
    await timeout_service.stop()


@pytest.mark.asyncio
async def test_remote_live_queue_does_not_expire_early() -> None:
    """Use total-lifetime expiry and post-semaphore phase for foreign views."""

    requester = _requester()
    owner_manager = JobManager(id="owner")
    job = owner_manager.create_job(
        "remote",
        "owner:review",
        {},
        user_id=requester.actor,
        metadata={
            "command": "review",
            "label": "PR",
            "phase": "queued",
            "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat(),
        },
    )
    job.started_at = datetime(2020, 1, 1, tzinfo=timezone.utc)

    class ForeignManager(JobManager):
        async def get_job_async(self, job_id: str) -> Any:
            return job if job_id == job.job_id else None

    foreign_manager = ForeignManager(id="foreign")
    service = _service(job_manager=foreign_manager)
    assert (await service.get(job.job_id, requester)).status == "queued"
    assert foreign_manager.jobs == {}

    job.metadata["phase"] = "running"
    job.metadata["execution_started_at"] = datetime.now(timezone.utc).isoformat()
    job.status = JobStatus.RUNNING
    assert (await service.get(job.job_id, requester)).status == "running"
    job.status = JobStatus.COMPLETED
    job.result = {"text": "done"}
    assert (await service.get(job.job_id, requester)).status == "completed"
    assert foreign_manager.jobs == {}


@pytest.mark.asyncio
async def test_queue_deadline_never_invokes_method() -> None:
    """Count scheduling and semaphore wait in the queue budget, then release dedup."""

    release = asyncio.Event()
    first_started = asyncio.Event()
    second_called = False

    async def first_method() -> str:
        first_started.set()
        await release.wait()
        return "first"

    async def second_method() -> str:
        nonlocal second_called
        second_called = True
        return "second"

    async def prepare(_: str) -> PreparedCommand:
        return PreparedCommand(dedup_key="second:1")

    service = _service()
    first = await service.submit(
        _command(first_method, name="first", max_concurrent=1, concurrency_group="group"),
        "",
        _requester(),
        _Recorder(),
    )
    await first_started.wait()
    recorder = _Recorder()
    second_command = _command(
        second_method,
        name="second",
        prepare=prepare,
        max_queue_wait=0.01,
        max_concurrent=1,
        concurrency_group="group",
    )
    second = await service.submit(second_command, "", _requester(), recorder)
    await recorder.received.wait()
    await _wait_for_terminal(service, second.job_id)

    assert second_called is False
    assert recorder.notices[0].status == "timed_out"
    assert service.manager.jobs[second.job_id].status == JobStatus.FAILED
    retry = await service.submit(second_command, "", _requester(), _Recorder())
    assert retry.status == "accepted"
    assert retry.job_id != second.job_id

    release.set()
    await _wait_for_terminal(service, first.job_id)
    await _wait_for_terminal(service, retry.job_id)
    await service.stop()
