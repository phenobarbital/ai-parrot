"""Tests for pending staged Telegram login coordination (FEAT-776 M9)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from parrot.auth.oauth2.events import ConnectionEvent
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.principal import Principal
from parrot.integrations.telegram.connection_notifier import TelegramConnectionNotifier
from parrot.integrations.telegram.models import PostAuthAction
from parrot.integrations.telegram.post_auth_connection import PendingLoginCoordinator


class Clock:
    """Deterministic monotonic clock for attempt expiry tests."""

    def __init__(self, now: float = 10.0) -> None:
        self.now = now

    def __call__(self) -> float:
        """Return the current deterministic timestamp."""
        return self.now


class FailingBot:
    """Telegram double whose delivery always fails."""

    async def send_message(self, **kwargs: Any) -> None:
        """Simulate a Telegram delivery failure."""
        del kwargs
        raise RuntimeError("telegram unavailable")


def _fields(*, actions: list[PostAuthAction] | None = None, expires_at: float | None = None) -> dict[str, Any]:
    """Build the complete creation payload for a staged login attempt."""
    principal = Principal(user_id="1042", channel="telegram", channel_user_id="88123")
    return {
        "telegram_id": 88123,
        "chat_id": 88123,
        "bot_id": "7001",
        "principal": principal,
        "permission_context": PermissionContext(
            session=UserSession(user_id="1042", tenant_id="tenant-a", roles=frozenset()),
            channel="telegram",
            channel_user_id="88123",
        ),
        "candidate": object(),
        "actions": actions if actions is not None else [PostAuthAction(provider="jira", required=True)],
        "expires_at": time.monotonic() + 100.0 if expires_at is None else expires_at,
    }


def _event(*, provider: str = "jira", user_id: str = "1042", occurred_at: float = 1.0) -> ConnectionEvent:
    """Build a correlated connection completion event."""
    return ConnectionEvent(
        kind="connection.completed",
        user_id=user_id,
        provider=provider,
        channel="telegram",
        occurred_at=occurred_at,
    )


def _state(attempt_id: str, *, bot_id: str = "7001") -> dict[str, Any]:
    """Build trusted callback state for a combined login attempt."""
    return {"extra": {"attempt_id": attempt_id, "bot_id": bot_id, "combined": True}}


@pytest.mark.asyncio
async def test_connection_post_auth_build_and_handle() -> None:
    """Only a matching provider callback completes and finalizes an attempt once."""
    finalized: list[str] = []

    async def finalize(attempt: Any) -> None:
        finalized.append(attempt.attempt_id)

    coordinator = PendingLoginCoordinator(finalize=finalize)
    attempt = coordinator.create(**_fields())

    assert not await coordinator.on_provider_completed(_event(user_id="other"), _state(attempt.attempt_id))
    assert not await coordinator.on_provider_completed(_event(provider="o365"), _state(attempt.attempt_id))
    assert not await coordinator.on_provider_completed(_event(), _state(attempt.attempt_id, bot_id="other-bot"))
    assert await coordinator.on_provider_completed(_event(), _state(attempt.attempt_id))
    assert not await coordinator.on_provider_completed(_event(), _state(attempt.attempt_id))
    assert finalized == [attempt.attempt_id]
    assert attempt.finalized


@pytest.mark.asyncio
async def test_combined_login_callback_correlation() -> None:
    """Expired, cancelled, and missing attempts fail closed without finalization."""
    clock = Clock()
    finalized: list[str] = []

    async def finalize(attempt: Any) -> None:
        finalized.append(attempt.attempt_id)

    coordinator = PendingLoginCoordinator(finalize=finalize, clock=clock)
    expired = coordinator.create(**_fields(expires_at=11.0))
    coordinator.cap_expiry(expired.attempt_id, 1)
    clock.now = 11.0
    assert not await coordinator.on_provider_completed(_event(), _state(expired.attempt_id))

    cancelled = coordinator.create(**_fields())
    await coordinator.cancel(attempt_id=cancelled.attempt_id)
    assert not await coordinator.on_provider_completed(_event(), _state(cancelled.attempt_id))
    assert not await coordinator.on_provider_completed(_event(), _state("missing"))
    assert finalized == []


@pytest.mark.asyncio
async def test_optional_failure_advances_a_settled_login() -> None:
    """An optional action can be skipped after failure once required actions complete."""
    finalized: list[str] = []

    async def finalize(attempt: Any) -> None:
        finalized.append(attempt.attempt_id)

    coordinator = PendingLoginCoordinator(finalize=finalize)
    attempt = coordinator.create(
        **_fields(
            actions=[PostAuthAction(provider="jira", required=True), PostAuthAction(provider="o365")],
        )
    )
    await coordinator.on_provider_failed(attempt.attempt_id, "o365", "provider unavailable")

    assert await coordinator.on_provider_completed(_event(), _state(attempt.attempt_id))
    assert finalized == [attempt.attempt_id]


@pytest.mark.asyncio
async def test_required_failure_discards_the_candidate_and_reports_once() -> None:
    """A required failure cancels its attempt without compensating completed grants."""
    failed: list[tuple[str, str]] = []

    async def finalize(attempt: Any) -> None:
        pytest.fail(f"unexpected finalization for {attempt.attempt_id}")

    async def on_failed(attempt: Any, reason: str) -> None:
        failed.append((attempt.attempt_id, reason))

    coordinator = PendingLoginCoordinator(finalize=finalize, on_failed=on_failed)
    attempt = coordinator.create(**_fields())

    await coordinator.on_provider_failed(attempt.attempt_id, "jira", "denied")
    await coordinator.on_provider_failed(attempt.attempt_id, "jira", "denied")

    assert attempt.cancelled
    assert attempt.candidate is None
    assert failed == [(attempt.attempt_id, "denied")]


@pytest.mark.asyncio
async def test_cancel_race_prevents_a_late_completion_from_finalizing() -> None:
    """Cancellation and completion share a lock so cancellation wins when it starts first."""
    finalized: list[str] = []

    async def finalize(attempt: Any) -> None:
        finalized.append(attempt.attempt_id)

    coordinator = PendingLoginCoordinator(finalize=finalize)
    attempt = coordinator.create(**_fields())
    cancel = asyncio.create_task(coordinator.cancel(attempt_id=attempt.attempt_id))
    await asyncio.sleep(0)
    completed = asyncio.create_task(coordinator.on_provider_completed(_event(), _state(attempt.attempt_id)))
    await asyncio.gather(cancel, completed)

    assert completed.result() is False
    assert finalized == []


@pytest.mark.asyncio
async def test_combined_login_notifier_send_failure() -> None:
    """Lifecycle finalization is independent of a failed Telegram notification send."""
    finalized: list[str] = []

    async def finalize(attempt: Any) -> None:
        finalized.append(attempt.attempt_id)

    coordinator = PendingLoginCoordinator(finalize=finalize)
    attempt = coordinator.create(**_fields())
    notifier = TelegramConnectionNotifier()
    notifier.attach("7001", FailingBot())
    notifier.set_login_coordinator(coordinator)

    await notifier.notify(
        _event(),
        {
            "extra": {
                "attempt_id": attempt.attempt_id,
                "bot_id": "7001",
                "chat_id": 88123,
                "combined": True,
            }
        },
    )

    assert finalized == [attempt.attempt_id]


@pytest.mark.asyncio
async def test_finished_and_cancelled_attempts_release_their_locks() -> None:
    """Finalized, cancelled and superseded attempts leave no per-attempt state behind."""
    finalized: list[str] = []

    async def finalize(attempt: Any) -> None:
        finalized.append(attempt.attempt_id)

    coordinator = PendingLoginCoordinator(finalize=finalize)
    done = coordinator.create(**_fields())
    assert await coordinator.on_provider_completed(_event(), _state(done.attempt_id))
    cancelled = coordinator.create(**_fields())
    await coordinator.cancel(attempt_id=cancelled.attempt_id)
    superseded = coordinator.create(**_fields())
    coordinator.create(**_fields())  # supersedes the previous attempt for the same Telegram user

    assert finalized == [done.attempt_id]
    assert superseded.cancelled is True
    assert len(coordinator._locks) == len(coordinator._attempts) == 1


@pytest.mark.asyncio
async def test_cancel_and_supersede_do_not_race_an_in_flight_finalize() -> None:
    """cancel() waits for finalize; supersede() leaves a finalizing attempt alone; no state is left behind."""
    entered = asyncio.Event()
    release = asyncio.Event()
    order: list[str] = []

    async def finalize(attempt: Any) -> None:
        entered.set()
        await release.wait()
        order.append(f"finalized:{attempt.cancelled}")

    coordinator = PendingLoginCoordinator(finalize=finalize)
    attempt = coordinator.create(**_fields())
    completing = asyncio.create_task(coordinator.on_provider_completed(_event(), _state(attempt.attempt_id)))
    await entered.wait()

    coordinator.supersede(88123)  # a /login retry while finalizing must not mark it cancelled
    assert attempt.cancelled is False
    cancelling = asyncio.create_task(coordinator.cancel(telegram_id=88123))
    await asyncio.sleep(0)
    assert not cancelling.done()  # still waiting on the attempt lock

    release.set()
    await completing
    await cancelling
    assert order == ["finalized:False"]
    assert not coordinator._attempts and not coordinator._locks
    assert attempt.events["jira"].provider == "jira"
