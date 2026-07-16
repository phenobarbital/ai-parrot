"""Unit tests for NotificationSubscriber (FEAT-310, TASK-1787)."""
import asyncio
import time

import pytest

from parrot.core.events.bus import BusCore, EventEnvelope, Severity
from parrot.core.events.bus.subscribers import (
    AlertRule,
    AlertsConfig,
    NotificationSubscriber,
)


def make_envelope(
    topic: str = "app.error",
    severity: Severity = Severity.ERROR,
) -> EventEnvelope:
    return EventEnvelope(topic=topic, payload={}, severity=severity)


async def wait_until(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.01)
    pytest.fail("condition not met within timeout")


class MockSender:
    """Records send_notification calls (async-notify stand-in)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_notification(
        self, message, recipients, provider="email", subject=None, **kwargs
    ):
        self.calls.append(
            {
                "message": message,
                "recipients": recipients,
                "provider": provider,
                "subject": subject,
            }
        )
        return {"status": "sent"}


@pytest.fixture
def mock_notify():
    return MockSender()


def threshold_rule(**overrides) -> AlertRule:
    defaults = dict(
        rule_id="errors",
        pattern="app.*",
        min_severity=Severity.ERROR,
        provider="slack",
        recipients=["#alerts"],
    )
    defaults.update(overrides)
    return AlertRule(**defaults)


async def test_defaults_match_spec():
    cfg = AlertsConfig()
    assert cfg.dedup_window_seconds == 300.0
    assert cfg.channel_throttle_max == 10
    assert cfg.channel_throttle_window_seconds == 60.0
    assert cfg.storm_threshold_events == 25
    assert cfg.storm_window_seconds == 30.0
    assert cfg.include_bus_internal is False


async def test_notification_threshold_rule(mock_notify):
    sub = NotificationSubscriber(mock_notify, rules=[threshold_rule()])
    await sub._on_envelope(make_envelope("app.error", Severity.ERROR))
    await wait_until(lambda: len(mock_notify.calls) == 1)
    call = mock_notify.calls[0]
    assert call["provider"] == "slack"
    assert call["recipients"] == ["#alerts"]
    assert "app.error" in call["message"]

    # Below threshold: never delivered.
    await sub._on_envelope(make_envelope("app.info", Severity.INFO))
    await asyncio.sleep(0.05)
    assert len(mock_notify.calls) == 1


async def test_notification_rate_window_rule(mock_notify):
    rule = threshold_rule(
        rule_id="err-burst",
        window_seconds=1.0,
        count_threshold=3,
    )
    sub = NotificationSubscriber(mock_notify, rules=[rule])

    await sub._on_envelope(make_envelope())
    await sub._on_envelope(make_envelope())
    await asyncio.sleep(0.05)
    assert len(mock_notify.calls) == 0  # below N

    await sub._on_envelope(make_envelope())  # crosses N=3 → fires once
    await wait_until(lambda: len(mock_notify.calls) == 1)
    assert "3+" in mock_notify.calls[0]["message"]

    await sub._on_envelope(make_envelope())  # new window — no fire
    await asyncio.sleep(0.05)
    assert len(mock_notify.calls) == 1


async def test_notification_dedup_and_repeat_count(mock_notify):
    cfg = AlertsConfig(dedup_window_seconds=0.2)
    sub = NotificationSubscriber(
        mock_notify, rules=[threshold_rule()], config=cfg
    )

    await sub._on_envelope(make_envelope("app.error"))
    await sub._on_envelope(make_envelope("app.error"))  # suppressed
    await sub._on_envelope(make_envelope("app.other"))  # same topic class → suppressed
    await wait_until(lambda: len(mock_notify.calls) == 1)

    await asyncio.sleep(0.25)  # dedup window closes
    await sub._on_envelope(make_envelope("app.error"))
    await wait_until(lambda: len(mock_notify.calls) == 2)
    assert "2 identical alert(s) suppressed" in mock_notify.calls[1]["message"]


async def test_notification_storm_collapse(mock_notify):
    cfg = AlertsConfig(
        storm_threshold_events=5,
        storm_window_seconds=0.5,
        dedup_window_seconds=0.01,  # keep dedup out of the way
    )
    sub = NotificationSubscriber(
        mock_notify, rules=[threshold_rule()], config=cfg
    )

    for i in range(12):
        await sub._on_envelope(make_envelope(f"app.err{i}", Severity.ERROR))
        await asyncio.sleep(0.005)

    await asyncio.sleep(0.1)
    storm_msgs = [
        c for c in mock_notify.calls if "Event storm" in c["message"]
    ]
    assert len(storm_msgs) == 1  # ONE CRITICAL storm alert
    # Everything after the storm activated was suppressed.
    post_storm = [
        c
        for c in mock_notify.calls
        if "err6" in c["message"]
        or "err7" in c["message"]
        or "err8" in c["message"]
    ]
    assert post_storm == []

    # Rate drops → alerting resumes.
    await asyncio.sleep(0.6)
    before = len(mock_notify.calls)
    await sub._on_envelope(make_envelope("app.recovered", Severity.ERROR))
    await wait_until(lambda: len(mock_notify.calls) == before + 1)


async def test_channel_throttle_digest(mock_notify):
    cfg = AlertsConfig(
        channel_throttle_max=3,
        channel_throttle_window_seconds=0.3,
        dedup_window_seconds=1000.0,
        storm_threshold_events=1000,
    )
    # Distinct topic classes so dedup does not interfere.
    rule = threshold_rule(pattern="*")
    sub = NotificationSubscriber(mock_notify, rules=[rule], config=cfg)

    for i in range(5):
        await sub._on_envelope(make_envelope(f"class{i}.error"))
    await wait_until(lambda: len(mock_notify.calls) == 3)  # throttled at 3

    # Overflow folded into ONE digest after the window.
    await wait_until(lambda: len(mock_notify.calls) == 4, timeout=3.0)
    digest = mock_notify.calls[3]
    assert "DIGEST" in digest["message"]
    assert "2 alert(s) throttled" in digest["message"]
    await asyncio.sleep(0.1)
    assert len(mock_notify.calls) == 4


async def test_bus_internal_topics_never_alert(mock_notify):
    sub = NotificationSubscriber(
        mock_notify, rules=[threshold_rule(pattern="*")]
    )
    await sub._on_envelope(
        make_envelope("bus.subscriber_error", Severity.CRITICAL)
    )
    await sub._on_envelope(make_envelope("bus.dlq", Severity.ERROR))
    await asyncio.sleep(0.05)
    assert mock_notify.calls == []


async def test_sender_failure_is_isolated(mock_notify):
    class FailingSender:
        async def send_notification(self, **kwargs):
            raise RuntimeError("provider down")

    sub = NotificationSubscriber(FailingSender(), rules=[threshold_rule()])
    # Must not raise into the dispatch path.
    await sub._on_envelope(make_envelope("app.error"))
    await asyncio.sleep(0.05)


async def test_attach_through_bus_core(mock_notify):
    core = BusCore(workers=2, queue_size=16)
    await core.start()
    sub = NotificationSubscriber(mock_notify, rules=[threshold_rule()])
    sid = sub.attach(core)
    assert isinstance(sid, str)

    await core.publish(make_envelope("app.error", Severity.ERROR))
    await wait_until(lambda: len(mock_notify.calls) == 1)

    assert sub.detach(core) is True
    await core.publish(make_envelope("app.error2", Severity.ERROR))
    await asyncio.sleep(0.05)
    assert len(mock_notify.calls) == 1
    await core.close()


async def test_config_from_dict_with_rules():
    cfg = AlertsConfig.from_dict(
        {
            "dedup_window_seconds": 60,
            "rules": [
                {
                    "rule_id": "toml-rule",
                    "pattern": "orders.*",
                    "min_severity": Severity.WARNING,
                    "provider": "telegram",
                    "recipients": "ops-chat",
                }
            ],
        }
    )
    assert cfg.dedup_window_seconds == 60
    assert cfg.rules[0].rule_id == "toml-rule"
    sub = NotificationSubscriber(MockSender(), config=cfg)
    assert len(sub._rules) == 1
