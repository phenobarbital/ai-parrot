"""Regression coverage for queued command declarations and shared messages."""

from datetime import datetime, timezone

import pytest

from parrot.integrations.core.queued import (
    JobNotice,
    JobView,
    Requester,
    SubmitOutcome,
    discover_queued_commands,
    queued_command,
    queued_spec_of,
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
