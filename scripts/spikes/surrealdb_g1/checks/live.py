"""G1-07 live-query delivery and reconnect check."""

from __future__ import annotations

from checks._common import connect, execute, g1_check
from harness import CheckResult, SpikeContext


@g1_check("G1-07", "LIVE SELECT delivers changes after reconnect", blocking=True)
async def check_g1_07_live(ctx: SpikeContext) -> CheckResult:
    """Subscribe, create data, reconnect, and verify a second subscription receives data."""
    create_table = "DEFINE TABLE live_event SCHEMAFULL; DEFINE FIELD value ON live_event TYPE string;"
    async with connect(ctx, "g1", "g1_07") as db:
        await execute(db, create_table)
        subscription = await db.live("live_event")
        await execute(db, "CREATE live_event:first SET value = 'first';")
        first = await subscription.__anext__()
    async with connect(ctx, "g1", "g1_07") as db:
        subscription = await db.live("live_event")
        await execute(db, "CREATE live_event:second SET value = 'second';")
        second = await subscription.__anext__()
    assert first["result"]["value"] == "first" and second["result"]["value"] == "second"
    return CheckResult(
        "G1-07",
        check_g1_07_live.title,
        True,
        "pass",
        f"LIVE SELECT live_event; CREATE first/second; first={first!r}; reconnect={second!r}",
    )
