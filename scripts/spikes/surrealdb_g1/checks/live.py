"""G1-07 live-query delivery and reconnect check."""

from __future__ import annotations

import asyncio
from typing import Any

from checks._common import connect, execute, g1_check
from harness import CheckResult, SpikeContext

_TIMEOUT_S = 10.0


async def _next_notification(subscription: Any) -> Any:
    """Return the next notification of an SDK live subscription (async-iterable) within a timeout."""
    iterator = subscription.__aiter__()
    return await asyncio.wait_for(iterator.__anext__(), timeout=_TIMEOUT_S)


def _value(notification: Any) -> Any:
    """Extract the ``value`` field from a notification (dict with ``result`` or an object with ``result``)."""
    result = notification["result"] if isinstance(notification, dict) else getattr(notification, "result", notification)
    return result["value"] if isinstance(result, dict) else getattr(result, "value", None)


@g1_check("G1-07", "LIVE SELECT delivers changes after reconnect", blocking=True)
async def check_g1_07_live(ctx: SpikeContext) -> CheckResult:
    """Subscribe, create data, reconnect, and verify a second subscription receives data."""
    create_table = "DEFINE TABLE live_event SCHEMAFULL; DEFINE FIELD value ON live_event TYPE string;"
    async with connect(ctx, "g1", "g1_07") as db:
        await execute(db, create_table)
        subscription = await db.live("live_event")
        await execute(db, "CREATE live_event:first SET value = 'first';")
        first = await _next_notification(subscription)
    async with connect(ctx, "g1", "g1_07") as db:
        subscription = await db.live("live_event")
        await execute(db, "CREATE live_event:second SET value = 'second';")
        second = await _next_notification(subscription)
    assert _value(first) == "first" and _value(second) == "second", (first, second)
    return CheckResult(
        check_id="G1-07",
        title=check_g1_07_live.title,
        blocking=True,
        status="pass",
        evidence=f"LIVE SELECT live_event; CREATE first/second; first={first!r}; reconnect={second!r}",
    )
